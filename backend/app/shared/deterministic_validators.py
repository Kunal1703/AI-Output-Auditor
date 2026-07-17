"""Deterministic Validators — rule-based, non-model verification.

Document 2 §5.6 defines four instantiations, one per consuming engine:

* **Relevance** — Deterministic Constraint Checks: format, language, length
  (§7.1, stage 7). **Implemented.**
* **Credibility** — URL / DOI Verification (§7.4, stage 4). **Implemented.**
* **Readability** — Deterministic Analysis (§7.6, stage 2). **Implemented.**
* **Engagement** — Manipulation Pattern Detection (§7.7, stage 5). **Implemented.**

**These checks matter disproportionately to their simplicity.** They are the
parts of an audit that carry no model variability at all: whether a URL
resolves, or whether the output is 470 words when 200 were requested, is a fact.
Document 4 §11 requires results stable across re-runs, and every judgment made
here is stable by construction. Where a deterministic check can answer a
question, it should — an LLM judge should never be asked what a regex already
knows.

**They detect; they do not decide.** ``verify_url`` reports that a link returned
404. Concluding that the citation was *fabricated* is Credibility's stage 9
(Document 2, §7.4). The distinction is not pedantic: a 404 can mean link rot on
a real paper, and only the engine — which also has the grounding verification
and the source classification — is positioned to weigh that.
"""

from __future__ import annotations

import abc
import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import httpx

from app.core.config import Settings
from app.core.logging import bind, get_logger
from app.shared.schemas import Severity

__all__ = [
    "ValidationOutcome",
    "DeterministicValidators",
    "DefaultDeterministicValidators",
    "URL_PATTERN",
    "DOI_PATTERN",
]

logger = get_logger(__name__)

#: Bare and markdown-embedded URLs.
URL_PATTERN = re.compile(r"https?://[^\s<>()\[\]\"'`]+", re.IGNORECASE)

#: DOI identifiers, with or without a ``doi:`` or resolver prefix.
DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[-._;()/:a-z0-9]+\b", re.IGNORECASE)

_WORD = re.compile(r"\b[\w'’-]+\b", re.UNICODE)

#: Trailing punctuation a URL regex tends to swallow from prose.
_URL_TRAILING = ".,;:!?)]}'\"›»"

#: Blank-line paragraph boundary, for the structure heuristics.
_PARAGRAPH_SPLIT = re.compile(r"\n[ \t]*\n+")

#: An accidentally doubled word ("the the"). Bounded to genuine repeats: the
#: backreference requires the same word twice, and legitimate doubling in
#: English ("had had", "that that") is rare enough that a low-severity note is
#: the right response rather than suppression.
_REPEATED_WORD = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE)

#: Terminal punctuation a well-formed sentence ends with. Includes closing
#: quotes and brackets, which legitimately follow the terminator.
_TERMINATORS = (".", "!", "?", ":", '"', "'", ")", "]", "”", "’", "`")

#: A line that is structure rather than prose — a markdown heading, a list item,
#: a table row, a code fence, or a setext underline.
#:
#: None of these is required to end in punctuation, and a termination check that
#: does not know that will flag every well-structured document it sees. Measured
#: during verification: without this screen, ``# How rate limiting works`` was
#: reported as an unterminated sentence and became a recommendation to fix
#: perfectly good prose.
_STRUCTURAL_LINE = re.compile(
    r"^(?:"
    r"[ \t]{0,3}#{1,6}[ \t]+"          # ATX heading
    r"|[ \t]{0,3}(?:[-*+]|\d+[.)])[ \t]+"  # list item
    r"|[ \t]{0,3}\|"                    # table row
    r"|[ \t]{0,3}```"                   # code fence
    r"|[ \t]{0,3}[=-]{2,}[ \t]*$"       # setext underline
    r")"
)


def _is_structural_line(text: str) -> bool:
    """Whether a segment is markdown structure rather than a prose sentence."""
    return bool(_STRUCTURAL_LINE.match(text.strip()))

#: Heuristic bounds for :meth:`DefaultDeterministicValidators.analyze_readability`.
#:
#: Fallbacks only — ``engines.readability`` in ``config/settings.yaml`` is the
#: real source, and the engine always passes them in. They live here so the
#: validator is usable standalone in a unit test, not so behavior can be tuned
#: in code (Document 4, §15).
_READABILITY_DEFAULTS: Mapping[str, float] = {
    "max_mean_sentence_words": 25.0,
    "max_sentence_words": 45.0,
    "min_reading_ease": 30.0,
    "max_grade_level": 14.0,
    "max_paragraph_words": 150.0,
    "structure_required_above_words": 400.0,
}

def _phrase(pattern: str) -> re.Pattern[str]:
    """Compile a multi-word manipulation pattern, tolerating wrapped lines.

    Every literal space becomes ``\\s+``. This is not cosmetic: prose wraps, and
    a pattern written with literal spaces silently misses any phrase that
    straddles a line break. Measured during verification — ``"act now"`` split
    across a newline went undetected, so an engine that looked like it was
    checking for false urgency was checking only the phrases that happened not
    to wrap.
    """
    return re.compile(pattern.replace(" ", r"\s+"), re.IGNORECASE)


#: Manipulative phrasing families, as ``(family, pattern, severity)``.
#:
#: **Every one of these is a candidate, not a finding.** Document 2 §7.7 puts an
#: LLM verification stage after this one, and these patterns are exactly why: a
#: news article about a fraud case will match ``overclaiming`` while quoting the
#: fraudster, and an honest deadline reminder will match ``false_urgency``. The
#: regex finds phrases worth *asking about*. The severities are the impact *if
#: stage 6 confirms them*, not an assertion that it will.
_MANIPULATION_PATTERNS: tuple[tuple[str, re.Pattern[str], Severity], ...] = (
    (
        "clickbait",
        _phrase(
            r"\b(you won'?t believe|what happened next|this one (weird )?trick|"
            r"doctors hate|shocking truth|will blow your mind|"
            r"the secret (that )?(they|nobody) (don'?t want you to know|wants you to know))\b"
        ),
        Severity.HIGH,
    ),
    (
        "false_urgency",
        _phrase(
            r"\b(act (now|fast|immediately)|limited time only|before it'?s too late|"
            r"don'?t miss out|hurry[,!]|last chance|only \d+ (left|remaining|spots?))\b"
        ),
        Severity.MEDIUM,
    ),
    (
        "overclaiming",
        _phrase(
            r"\b(guaranteed to|100% (effective|safe|accurate|guaranteed)|"
            r"never fails|always works|the only way to|"
            r"scientifically proven to (cure|eliminate)|miracle (cure|solution))\b"
        ),
        Severity.HIGH,
    ),
    (
        "manufactured_consensus",
        _phrase(
            r"\b(everyone knows( that)?|nobody (seriously )?disputes|"
            r"any reasonable person (would|knows)|it'?s obvious to anyone|"
            r"no one can deny)\b"
        ),
        Severity.MEDIUM,
    ),
    (
        "fear_appeal",
        _phrase(
            r"\b(you'?ll regret|dangerous mistake|putting (your|yourself|your family) at risk|"
            r"could cost you everything|devastating consequences)\b"
        ),
        Severity.MEDIUM,
    ),
    (
        "emphasis_inflation",
        # Three or more terminal marks, or a shouted word of four-plus letters.
        # Both are style signals rather than deception on their own, which is why
        # this family carries the lowest severity here and leans hardest on stage
        # 6 to clear it. Case-sensitive by necessity — the whole signal is the
        # capitals — so it is compiled directly rather than through _phrase.
        re.compile(r"([!?]{3,}|\b[A-Z]{4,}\b(?!\s*[.:]))"),
        Severity.LOW,
    ),
)


@dataclass(frozen=True)
class ValidationOutcome:
    """The result of one deterministic check.

    Attributes:
        check: What was checked, e.g. ``"length_constraint"``, ``"url_resolves"``.
        passed: Whether the content satisfied the check.
        detail: Human-readable explanation, suitable for evidence content.
        severity: Impact when the check fails. ``None`` when it passed.
        observed: What the validator actually measured — the resolved status
            code, the word count, the detected language. Retained because
            "expected 200 words, found 470" is far more actionable in a report
            than "length check failed".
    """

    check: str
    passed: bool
    detail: str
    severity: Severity | None = None
    observed: dict[str, Any] = field(default_factory=dict)


class DeterministicValidators(abc.ABC):
    """The interface for rule-based checks.

    Consumed by Relevance, Credibility, Readability, and Engagement.
    """

    @abc.abstractmethod
    def check_constraints(
        self, text: str, constraints: dict[str, Any]
    ) -> list[ValidationOutcome]:
        """Check format, language, and length constraints (Relevance, §7.1).

        Args:
            text: The AI Output under audit.
            constraints: Constraints extracted from the prompt — expected
                language, word or character bounds, required format.

        Returns:
            One outcome per constraint checked.
        """

    @abc.abstractmethod
    async def verify_url(self, url: str) -> ValidationOutcome:
        """Verify that a URL resolves (Credibility, §7.4, stage 4).

        Must not raise on an unreachable URL: a citation pointing nowhere is a
        finding Credibility needs to record, not an error that aborts the audit.

        Args:
            url: The URL to verify.

        Returns:
            The outcome, with ``passed=False`` when unreachable.
        """

    @abc.abstractmethod
    async def verify_doi(self, doi: str) -> ValidationOutcome:
        """Verify that a DOI resolves (Credibility, §7.4, stage 4).

        Args:
            doi: The DOI to verify.

        Returns:
            The outcome, with ``passed=False`` when unresolvable.
        """

    @abc.abstractmethod
    def analyze_readability(
        self,
        text: str,
        sentences: Sequence[str] = (),
        thresholds: Mapping[str, Any] | None = None,
    ) -> list[ValidationOutcome]:
        """Run grammar, complexity, and structure heuristics (Readability, §7.6).

        Args:
            text: The AI Output under audit.
            sentences: The run's already-computed sentence texts. Supplied by the
                engine from ``context.sentences`` so that the auditor reports one
                sentence count for one document — two components disagreeing
                about how many sentences a text has is a report nobody can
                defend. Falls back to the library's own segmentation when empty.
            thresholds: Heuristic bounds from ``engines.readability``. Thresholds
                are configuration, not code (Document 4, §15), so this method
                holds none of its own.

        Returns:
            One outcome per heuristic checked. Measurements, not verdicts — see
            the module docstring.
        """

    @abc.abstractmethod
    def detect_manipulation_patterns(self, text: str) -> list[ValidationOutcome]:
        """Detect manipulative or clickbait phrasing (Engagement, §7.7, stage 5).

        Args:
            text: The AI Output under audit.

        Returns:
            One outcome per matched pattern, each carrying the matched span in
            ``observed`` so the engine can locate it. A single passing outcome
            when nothing matched — the absence of manipulation is a real
            measurement and Engagement's confidence depends on knowing the check
            actually ran.

        Note:
            A match is a **candidate**, never a finding. Document 2 §7.7 puts an
            LLM Manipulation Verification stage (6) after this one precisely
            because a rhetorical question or an emphatic headline matches these
            patterns without being manipulative.
        """

    async def aclose(self) -> None:
        """Release HTTP resources on shutdown."""
        return None


class DefaultDeterministicValidators(DeterministicValidators):
    """The standard validator suite.

    Args:
        settings: Supplies fetch timeouts for URL and DOI verification.
        client: Inject an HTTP client to test without network access.
    """

    def __init__(
        self, settings: Settings, client: httpx.AsyncClient | None = None
    ) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.retrieval.fetch_timeout_seconds),
            follow_redirects=True,
            headers={"User-Agent": settings.retrieval.user_agent},
        )
        self._owns_client = client is None

    # -- Relevance: constraint checks (§7.1, stage 7) ----------------------- #

    def check_constraints(
        self, text: str, constraints: dict[str, Any]
    ) -> list[ValidationOutcome]:
        """Check format, language, and length constraints.

        Only checks constraints the caller actually supplied. Relevance derives
        them from the prompt's requirements, so an absent key means the user
        never asked — and inventing a default ("responses should be under 500
        words") would fabricate a requirement and then fault the content for
        missing it.

        Recognized keys: ``max_words``, ``min_words``, ``max_characters``,
        ``min_characters``, ``language`` (ISO 639-1), ``format``
        (``markdown`` / ``plain`` / ``json``), ``must_contain`` (list of
        strings), ``must_not_contain`` (list of strings).

        Args:
            text: The AI Output under audit.
            constraints: Constraints extracted from the prompt.

        Returns:
            One outcome per constraint actually checked.
        """
        outcomes: list[ValidationOutcome] = []
        words = len(_WORD.findall(text))
        characters = len(text)

        max_words = constraints.get("max_words")
        if isinstance(max_words, (int, float)) and max_words > 0:
            passed = words <= max_words
            outcomes.append(
                ValidationOutcome(
                    check="max_words",
                    passed=passed,
                    detail=(
                        f"Requested at most {int(max_words)} words; found {words}."
                    ),
                    severity=None if passed else Severity.MEDIUM,
                    observed={"limit": int(max_words), "actual": words},
                )
            )

        min_words = constraints.get("min_words")
        if isinstance(min_words, (int, float)) and min_words > 0:
            passed = words >= min_words
            outcomes.append(
                ValidationOutcome(
                    check="min_words",
                    passed=passed,
                    detail=f"Requested at least {int(min_words)} words; found {words}.",
                    severity=None if passed else Severity.MEDIUM,
                    observed={"limit": int(min_words), "actual": words},
                )
            )

        max_characters = constraints.get("max_characters")
        if isinstance(max_characters, (int, float)) and max_characters > 0:
            passed = characters <= max_characters
            outcomes.append(
                ValidationOutcome(
                    check="max_characters",
                    passed=passed,
                    detail=(
                        f"Requested at most {int(max_characters)} characters; "
                        f"found {characters}."
                    ),
                    severity=None if passed else Severity.MEDIUM,
                    observed={"limit": int(max_characters), "actual": characters},
                )
            )

        min_characters = constraints.get("min_characters")
        if isinstance(min_characters, (int, float)) and min_characters > 0:
            passed = characters >= min_characters
            outcomes.append(
                ValidationOutcome(
                    check="min_characters",
                    passed=passed,
                    detail=(
                        f"Requested at least {int(min_characters)} characters; "
                        f"found {characters}."
                    ),
                    severity=None if passed else Severity.MEDIUM,
                    observed={"limit": int(min_characters), "actual": characters},
                )
            )

        expected_language = constraints.get("language")
        if isinstance(expected_language, str) and expected_language.strip():
            outcomes.append(self._check_language(text, expected_language.strip()))

        expected_format = constraints.get("format")
        if isinstance(expected_format, str) and expected_format.strip():
            outcomes.append(self._check_format(text, expected_format.strip().lower()))

        for phrase in constraints.get("must_contain") or []:
            if not isinstance(phrase, str) or not phrase.strip():
                continue
            passed = phrase.lower() in text.lower()
            outcomes.append(
                ValidationOutcome(
                    check="must_contain",
                    passed=passed,
                    detail=f"Required content {phrase!r} is "
                    f"{'present' if passed else 'absent'}.",
                    severity=None if passed else Severity.HIGH,
                    observed={"phrase": phrase},
                )
            )

        for phrase in constraints.get("must_not_contain") or []:
            if not isinstance(phrase, str) or not phrase.strip():
                continue
            passed = phrase.lower() not in text.lower()
            outcomes.append(
                ValidationOutcome(
                    check="must_not_contain",
                    passed=passed,
                    detail=f"Excluded content {phrase!r} is "
                    f"{'absent' if passed else 'present'}.",
                    severity=None if passed else Severity.HIGH,
                    observed={"phrase": phrase},
                )
            )

        return outcomes

    @staticmethod
    def _check_language(text: str, expected: str) -> ValidationOutcome:
        """Compare the detected language against the requested one.

        Undetectable language yields ``passed=True`` with a stated caveat rather
        than a violation. A 15-word answer is too short for any detector to call,
        and reporting "wrong language" because the detector shrugged would be a
        finding about the tooling, not about the content.
        """
        from app.shared.document_analysis import analyze_metadata  # noqa: PLC0415

        detected = analyze_metadata(text).language
        normalized = expected.lower()[:2]

        if detected is None:
            return ValidationOutcome(
                check="language",
                passed=True,
                detail=(
                    f"Requested {expected!r}; the text is too short to detect a "
                    "language, so this constraint could not be checked."
                ),
                observed={"expected": expected, "detected": None},
            )

        passed = detected.lower()[:2] == normalized
        return ValidationOutcome(
            check="language",
            passed=passed,
            detail=f"Requested {expected!r}; detected {detected!r}.",
            severity=None if passed else Severity.HIGH,
            observed={"expected": expected, "detected": detected},
        )

    @staticmethod
    def _check_format(text: str, expected: str) -> ValidationOutcome:
        """Check the output's format against the requested one."""
        from app.shared.document_analysis import analyze_metadata  # noqa: PLC0415

        if expected == "json":
            import json  # noqa: PLC0415

            stripped = text.strip()
            fenced = stripped.removeprefix("```json").removeprefix("```").removesuffix("```")
            try:
                json.loads(fenced.strip())
                passed = True
                detail = "Requested JSON; the output parses as JSON."
            except ValueError as exc:
                passed = False
                detail = f"Requested JSON; the output does not parse: {exc}"
            return ValidationOutcome(
                check="format",
                passed=passed,
                detail=detail,
                severity=None if passed else Severity.HIGH,
                observed={"expected": "json"},
            )

        detected = analyze_metadata(text).format
        passed = detected == expected
        return ValidationOutcome(
            check="format",
            passed=passed,
            detail=f"Requested {expected!r} format; detected {detected!r}.",
            severity=None if passed else Severity.MEDIUM,
            observed={"expected": expected, "detected": detected},
        )

    # -- Credibility: URL / DOI verification (§7.4, stage 4) ---------------- #

    async def verify_url(self, url: str) -> ValidationOutcome:
        """Verify that a URL resolves.

        HEAD first, GET on fallback: many servers reject or mishandle HEAD, and
        reporting a real page as unreachable would push Credibility toward a
        *fabricated citation* finding on a citation that is perfectly fine. A
        false accusation of fabrication is the worst error this validator can
        make, so it works to avoid it.

        Never raises — every failure is an outcome.

        Args:
            url: The URL to verify.

        Returns:
            The outcome, with the status code in ``observed``.
        """
        cleaned = url.strip().rstrip(_URL_TRAILING)
        if not URL_PATTERN.fullmatch(cleaned):
            return ValidationOutcome(
                check="url_resolves",
                passed=False,
                detail=f"{cleaned!r} is not a well-formed http(s) URL.",
                severity=Severity.MEDIUM,
                observed={"url": cleaned, "malformed": True},
            )

        for method in ("HEAD", "GET"):
            try:
                response = await self._client.request(method, cleaned)
            except httpx.TimeoutException:
                return ValidationOutcome(
                    check="url_resolves",
                    passed=False,
                    detail=f"{cleaned} did not respond before the timeout.",
                    severity=Severity.MEDIUM,
                    observed={"url": cleaned, "error": "timeout"},
                )
            except httpx.HTTPError as exc:
                return ValidationOutcome(
                    check="url_resolves",
                    passed=False,
                    detail=f"{cleaned} could not be reached: {type(exc).__name__}.",
                    severity=Severity.HIGH,
                    observed={"url": cleaned, "error": type(exc).__name__},
                )

            if response.status_code < 400:
                return ValidationOutcome(
                    check="url_resolves",
                    passed=True,
                    detail=f"{cleaned} resolved with HTTP {response.status_code}.",
                    observed={"url": cleaned, "status_code": response.status_code},
                )
            if method == "HEAD" and response.status_code in (403, 405, 501):
                continue  # Server dislikes HEAD; try GET before judging.
            return ValidationOutcome(
                check="url_resolves",
                passed=False,
                detail=f"{cleaned} returned HTTP {response.status_code}.",
                severity=Severity.HIGH,
                observed={"url": cleaned, "status_code": response.status_code},
            )

        return ValidationOutcome(
            check="url_resolves",
            passed=False,
            detail=f"{cleaned} could not be verified.",
            severity=Severity.MEDIUM,
            observed={"url": cleaned},
        )

    async def verify_doi(self, doi: str) -> ValidationOutcome:
        """Verify that a DOI resolves through doi.org.

        Args:
            doi: The DOI, with or without a ``doi:`` or resolver prefix.

        Returns:
            The outcome. A DOI that does not resolve is strong evidence of
            fabrication — DOIs are registered, so an unregistered one was
            invented rather than merely moved — but the finding is still
            Credibility's to make.
        """
        match = DOI_PATTERN.search(doi)
        if match is None:
            return ValidationOutcome(
                check="doi_resolves",
                passed=False,
                detail=f"{doi!r} is not a well-formed DOI.",
                severity=Severity.MEDIUM,
                observed={"doi": doi, "malformed": True},
            )

        identifier = match.group(0)
        outcome = await self.verify_url(f"https://doi.org/{identifier}")
        return ValidationOutcome(
            check="doi_resolves",
            passed=outcome.passed,
            detail=outcome.detail.replace(
                f"https://doi.org/{identifier}", f"DOI {identifier}"
            ),
            severity=outcome.severity,
            observed={**outcome.observed, "doi": identifier},
        )

    # -- Readability: deterministic analysis (§7.6, stage 2) ---------------- #

    def analyze_readability(
        self,
        text: str,
        sentences: Sequence[str] = (),
        thresholds: Mapping[str, Any] | None = None,
    ) -> list[ValidationOutcome]:
        """Run grammar, complexity, and structure heuristics.

        Three families, matching the three the frozen stage names (Document 2,
        §7.6, stage 2): **grammar** (repeated words, unterminated sentences),
        **sentence complexity** (length, reading ease, grade level), and
        **structure heuristics** (paragraph length, navigational aids).

        Every outcome is a measurement. "Mean sentence length is 34 words,
        above the 25-word heuristic" is a fact about the text; whether that makes
        the content *hard to read* is the engine's stage 3–5 judgment, informed
        by an LLM that can see whether those long sentences are actually clear.
        This is why ``passed=False`` here does not mean "bad writing" — it means
        a heuristic bound was exceeded, which is a different and much narrower
        claim.

        See :meth:`DeterministicValidators.analyze_readability`.
        """
        bounds = dict(_READABILITY_DEFAULTS)
        bounds.update({k: v for k, v in (thresholds or {}).items() if v is not None})

        outcomes: list[ValidationOutcome] = []
        if not text or not text.strip():
            return outcomes

        units = [s for s in (sentences or ()) if s.strip()]
        outcomes.extend(self._sentence_complexity(text, units, bounds))
        outcomes.extend(self._reading_indices(text, bounds))
        outcomes.extend(self._grammar_checks(text, units))
        outcomes.extend(self._structure_checks(text, bounds))
        return outcomes

    @staticmethod
    def _sentence_complexity(
        text: str, sentences: Sequence[str], bounds: Mapping[str, Any]
    ) -> list[ValidationOutcome]:
        """Measure sentence length against the configured heuristics."""
        if not sentences:
            return []

        lengths = [len(_WORD.findall(s)) for s in sentences]
        mean_words = sum(lengths) / len(lengths)
        longest = max(lengths)
        longest_index = lengths.index(longest)

        max_mean = float(bounds["max_mean_sentence_words"])
        max_single = float(bounds["max_sentence_words"])

        outcomes = [
            ValidationOutcome(
                check="mean_sentence_length",
                passed=mean_words <= max_mean,
                detail=(
                    f"Mean sentence length is {mean_words:.1f} words across "
                    f"{len(sentences)} sentences; the heuristic bound is "
                    f"{max_mean:.0f}."
                ),
                severity=None if mean_words <= max_mean else Severity.MEDIUM,
                observed={
                    "mean_sentence_words": round(mean_words, 2),
                    "sentence_count": len(sentences),
                    "limit": max_mean,
                },
            ),
            ValidationOutcome(
                check="longest_sentence",
                passed=longest <= max_single,
                detail=(
                    f"The longest sentence runs {longest} words; the heuristic "
                    f"bound is {max_single:.0f}."
                ),
                severity=None if longest <= max_single else Severity.MEDIUM,
                observed={
                    "max_sentence_words": longest,
                    "sentence_index": longest_index,
                    "sentence": sentences[longest_index],
                    "limit": max_single,
                },
            ),
        ]
        return outcomes

    @staticmethod
    def _reading_indices(
        text: str, bounds: Mapping[str, Any]
    ) -> list[ValidationOutcome]:
        """Compute reading-ease and grade-level indices with ``textstat``.

        Import is local and failure-tolerant on purpose: these indices enrich the
        analysis but nothing depends on them. A missing or misbehaving library
        should cost the run two heuristics, not the Readability dimension —
        Document 4 §12 wants degradation, and this is the smallest possible unit
        of it.
        """
        try:
            import textstat  # noqa: PLC0415
        except ImportError:
            logger.debug("textstat not installed; reading indices skipped")
            return []

        try:
            ease = float(textstat.flesch_reading_ease(text))
            grade = float(textstat.flesch_kincaid_grade(text))
        except Exception as exc:
            logger.debug(
                "reading indices unavailable", extra=bind(error=type(exc).__name__)
            )
            return []

        min_ease = float(bounds["min_reading_ease"])
        max_grade = float(bounds["max_grade_level"])

        return [
            ValidationOutcome(
                check="reading_ease",
                passed=ease >= min_ease,
                detail=(
                    f"Flesch reading ease is {ease:.1f}; the heuristic floor is "
                    f"{min_ease:.0f}. Lower scores indicate denser prose."
                ),
                severity=None if ease >= min_ease else Severity.MEDIUM,
                observed={"flesch_reading_ease": round(ease, 2), "floor": min_ease},
            ),
            ValidationOutcome(
                check="grade_level",
                passed=grade <= max_grade,
                detail=(
                    f"Flesch-Kincaid grade level is {grade:.1f}; the heuristic "
                    f"bound is {max_grade:.0f}."
                ),
                severity=None if grade <= max_grade else Severity.LOW,
                observed={"flesch_kincaid_grade": round(grade, 2), "limit": max_grade},
            ),
        ]

    @staticmethod
    def _grammar_checks(
        text: str, sentences: Sequence[str]
    ) -> list[ValidationOutcome]:
        """Run the grammar heuristics that carry no false-positive risk.

        Deliberately narrow. A full grammar checker would be a model, and a model
        is what stage 3 already is — the value of a deterministic stage is that
        it cannot vary between runs, and that is only worth having for checks
        which are unambiguously right. "The the" is a typo in every dialect;
        whether a sentence fragment is a stylistic choice is not something a
        regex gets to rule on.
        """
        outcomes: list[ValidationOutcome] = []

        repeats = [m.group(0) for m in _REPEATED_WORD.finditer(text)]
        outcomes.append(
            ValidationOutcome(
                check="repeated_words",
                passed=not repeats,
                detail=(
                    "No accidentally repeated words were found."
                    if not repeats
                    else f"Found {len(repeats)} repeated word(s): "
                    f"{', '.join(repr(r) for r in repeats[:5])}."
                ),
                severity=None if not repeats else Severity.LOW,
                observed={"matches": repeats[:10], "count": len(repeats)},
            )
        )

        # Prose only. A heading, a list item, and a table row all legitimately
        # end without punctuation, and flagging them would fault a well-structured
        # document for being well-structured — the check would fire on almost
        # every markdown output ever written.
        prose = [s for s in sentences if not _is_structural_line(s)]
        if prose:
            unterminated = [s for s in prose if not s.rstrip().endswith(_TERMINATORS)]
            outcomes.append(
                ValidationOutcome(
                    check="sentence_termination",
                    passed=not unterminated,
                    detail=(
                        "Every prose sentence ends with terminal punctuation."
                        if not unterminated
                        else f"{len(unterminated)} of {len(prose)} prose sentences "
                        "do not end with terminal punctuation, which usually "
                        "means the text was cut off: "
                        f"{unterminated[0].strip()[-60:]!r}"
                    ),
                    severity=None if not unterminated else Severity.MEDIUM,
                    observed={
                        "unterminated_count": len(unterminated),
                        "prose_sentence_count": len(prose),
                        "sentence": unterminated[0] if unterminated else None,
                    },
                )
            )

        return outcomes

    @staticmethod
    def _structure_checks(
        text: str, bounds: Mapping[str, Any]
    ) -> list[ValidationOutcome]:
        """Measure document structure against the configured heuristics.

        Structure is judged *relative to length*. A three-paragraph answer needs
        no headings, and faulting it for having none would be faulting it for
        being short. Only past the configured word count does the absence of any
        navigational aid become worth reporting.
        """
        from app.shared.document_analysis import analyze_metadata  # noqa: PLC0415

        outcomes: list[ValidationOutcome] = []
        words = len(_WORD.findall(text))
        blocks = [b for b in _PARAGRAPH_SPLIT.split(text) if b.strip()]

        if blocks:
            per_block = [len(_WORD.findall(b)) for b in blocks]
            longest = max(per_block)
            limit = float(bounds["max_paragraph_words"])
            outcomes.append(
                ValidationOutcome(
                    check="paragraph_length",
                    passed=longest <= limit,
                    detail=(
                        f"The longest paragraph runs {longest} words across "
                        f"{len(blocks)} paragraph(s); the heuristic bound is "
                        f"{limit:.0f}."
                    ),
                    severity=None if longest <= limit else Severity.LOW,
                    observed={
                        "max_paragraph_words": longest,
                        "paragraph_count": len(blocks),
                        "limit": limit,
                    },
                )
            )

        threshold = float(bounds["structure_required_above_words"])
        if words > threshold:
            meta = analyze_metadata(text)
            has_aids = meta.has_headings or meta.has_lists or meta.has_tables
            outcomes.append(
                ValidationOutcome(
                    check="structural_aids",
                    passed=has_aids,
                    detail=(
                        f"The output runs {words} words and "
                        + (
                            "uses headings, lists, or tables to organize it."
                            if has_aids
                            else "uses no headings, lists, or tables."
                        )
                    ),
                    severity=None if has_aids else Severity.MEDIUM,
                    observed={
                        "word_count": words,
                        "has_headings": meta.has_headings,
                        "has_lists": meta.has_lists,
                        "has_tables": meta.has_tables,
                        "threshold": threshold,
                    },
                )
            )

        return outcomes

    # -- Engagement: manipulation pattern detection (§7.7, stage 5) --------- #

    def detect_manipulation_patterns(self, text: str) -> list[ValidationOutcome]:
        """Match known manipulative phrasing patterns.

        See :meth:`DeterministicValidators.detect_manipulation_patterns`. Every
        outcome carries the matched span's offsets in ``observed`` so Engagement
        can turn a match into a locatable evidence item, and so the verification
        judge at stage 6 can be shown the phrase in context rather than asked
        about a category in the abstract.
        """
        outcomes: list[ValidationOutcome] = []
        if not text or not text.strip():
            return outcomes

        for family, pattern, severity in _MANIPULATION_PATTERNS:
            for match in pattern.finditer(text):
                outcomes.append(
                    ValidationOutcome(
                        check=f"manipulation:{family}",
                        passed=False,
                        detail=(
                            f"Matched the {family.replace('_', ' ')} pattern: "
                            f"{match.group(0).strip()!r}."
                        ),
                        severity=severity,
                        observed={
                            "family": family,
                            "match": match.group(0).strip(),
                            "start": match.start(),
                            "end": match.end(),
                        },
                    )
                )

        if not outcomes:
            # A positive result, and Engagement needs it. Without this the engine
            # cannot distinguish "no manipulation was found" from "the check
            # never ran", and Document 3 §8 turns on exactly that difference.
            return [
                ValidationOutcome(
                    check="manipulation:none",
                    passed=True,
                    detail=(
                        "No clickbait, false-urgency, overclaiming, or "
                        "pressure-phrasing patterns were matched."
                    ),
                    observed={"patterns_checked": len(_MANIPULATION_PATTERNS)},
                )
            ]
        return outcomes

    async def aclose(self) -> None:
        """Close the HTTP client, if this service created it."""
        if self._owns_client:
            await self._client.aclose()
