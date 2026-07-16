"""Deterministic Validators — rule-based, non-model verification.

Document 2 §5.6 defines four instantiations, one per consuming engine:

* **Relevance** — Deterministic Constraint Checks: format, language, length
  (§7.1, stage 7). **Implemented.**
* **Credibility** — URL / DOI Verification (§7.4, stage 4). **Implemented.**
* **Readability** — Deterministic Analysis (§7.6, stage 2). Milestone 4.
* **Engagement** — Manipulation Pattern Detection (§7.7, stage 5). Milestone 4.

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
from typing import Any

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
    def analyze_readability(self, text: str) -> list[ValidationOutcome]:
        """Run grammar, complexity, and structure heuristics (Readability, §7.6)."""

    @abc.abstractmethod
    def detect_manipulation_patterns(self, text: str) -> list[ValidationOutcome]:
        """Detect manipulative or clickbait phrasing (Engagement, §7.7, stage 5)."""

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

    # -- Milestone 4 ------------------------------------------------------- #

    def analyze_readability(self, text: str) -> list[ValidationOutcome]:
        """Run readability heuristics.

        Raises:
            NotImplementedError: Until Milestone 4, with the Readability engine.
        """
        raise NotImplementedError(
            "analyze_readability is implemented in Milestone 4, with the "
            "Readability engine's Deterministic Analysis stage (Document 2, §7.6)."
        )

    def detect_manipulation_patterns(self, text: str) -> list[ValidationOutcome]:
        """Detect manipulative phrasing patterns.

        Raises:
            NotImplementedError: Until Milestone 4, with the Engagement engine.
        """
        raise NotImplementedError(
            "detect_manipulation_patterns is implemented in Milestone 4, with "
            "the Engagement engine's Manipulation Pattern Detection stage "
            "(Document 2, §7.7)."
        )

    async def aclose(self) -> None:
        """Close the HTTP client, if this service created it."""
        if self._owns_client:
            await self._client.aclose()
