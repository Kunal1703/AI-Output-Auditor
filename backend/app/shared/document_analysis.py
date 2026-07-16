"""Document statistics and metadata — measured facts, not judgments.

Shared infrastructure surfaced through
:class:`~app.shared.context.SharedContext`. Every value here is a *measurement*:
how many words, what language, whether a heading exists. Nothing here decides
whether any of it is good.

**The line this module walks, and why it holds.** Relevance's stage 7 is
"Deterministic Constraint Checks (format, language, length, etc.)" and
Readability's stage 2 is "Deterministic Analysis (grammar, sentence complexity,
structure heuristics)" — both frozen engine stages (Document 2, §7.1 and §7.6).
So why is counting words here rather than there?

Because *detecting* and *checking* are different acts:

* "This document is 470 words and reads as English" is a **fact**. It is true
  regardless of what was asked for, and it is identical for every engine.
* "The prompt demanded 200 words in French, so this violates a hard
  requirement" is a **judgment**. It needs the prompt, it produces a finding,
  and it belongs to Relevance.

This module does only the first. The engines consume it and do the second at
their frozen stage. That keeps two engines from disagreeing about the word count
of the same document — which would be a genuinely baffling report — while
leaving every verdict where the specification put it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import bind, get_logger
from app.shared.text_segmentation import TextSpan

__all__ = [
    "DocumentStatistics",
    "DocumentMetadata",
    "analyze_statistics",
    "analyze_metadata",
    "warm_language_detection",
]

logger = get_logger(__name__)

_WORD = re.compile(r"\b[\w'’-]+\b", re.UNICODE)

#: A markdown ATX heading (``# Title``) or a setext underline (``Title\n===``).
_ATX_HEADING = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_SETEXT_HEADING = re.compile(r"^[ \t]{0,3}(\S.*)\n[ \t]{0,3}([=-]{2,})[ \t]*$", re.MULTILINE)

_LIST_ITEM = re.compile(r"^[ \t]{0,3}([-*+]|\d+[.)])[ \t]+\S", re.MULTILINE)
_CODE_FENCE = re.compile(r"^[ \t]{0,3}```", re.MULTILINE)
_TABLE_ROW = re.compile(r"^[ \t]{0,3}\|.*\|[ \t]*$", re.MULTILINE)

#: Bare URLs and markdown links. Counted, never judged — whether a link is a
#: *trustworthy citation* is Credibility's question (Document 2, §7.4).
_URL = re.compile(r"https?://[^\s<>()\[\]\"']+", re.IGNORECASE)
_DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:a-z0-9]+\b", re.IGNORECASE)


@dataclass(frozen=True)
class DocumentStatistics:
    """Size and shape measurements of one document.

    Attributes:
        character_count: Total characters, including whitespace.
        word_count: Word-like tokens.
        sentence_count: Sentences found by the segmenter.
        paragraph_count: Blank-line-delimited blocks.
        line_count: Physical lines.
        mean_sentence_words: Mean words per sentence. ``0.0`` when there are no
            sentences. An *input* to Readability's complexity heuristics
            (Document 2, §7.6 stage 2) — never a readability score.
        max_sentence_words: Longest sentence in words.
        unique_word_ratio: Distinct lowercase tokens over total tokens, in
            [0, 1]. An *input* to Novelty's redundancy detection — never a
            novelty score, which the frozen pipeline derives from embeddings and
            a functional-repetition review (Document 2, §7.5).
    """

    character_count: int
    word_count: int
    sentence_count: int
    paragraph_count: int
    line_count: int
    mean_sentence_words: float
    max_sentence_words: int
    unique_word_ratio: float

    @property
    def is_empty(self) -> bool:
        """Whether the document has no words at all."""
        return self.word_count == 0


@dataclass(frozen=True)
class DocumentMetadata:
    """Descriptive facts about one document.

    Attributes:
        title: The first heading, when the document has one. ``None`` for
            untitled prose.
        language: ISO 639-1 code detected from the text, e.g. ``"en"``.
            ``None`` when detection is unavailable or the text is too short to
            call. This is the *detected* language — comparing it against a
            requested language is Relevance's stage 7.
        language_confidence: Detector confidence in [0, 1], or ``None``.
        format: ``"markdown"`` or ``"plain"``, inferred from structural markers.
        has_headings: Whether any heading was found.
        has_lists: Whether any list item was found.
        has_code_blocks: Whether any fenced code block was found.
        has_tables: Whether any table row was found.
        url_count: Bare and markdown URLs present.
        doi_count: DOI identifiers present.
        extra: Provenance passed through from extraction (extractor used,
            source title from HTML, and so on).
    """

    title: str | None
    language: str | None
    language_confidence: float | None
    format: str
    has_headings: bool
    has_lists: bool
    has_code_blocks: bool
    has_tables: bool
    url_count: int
    doi_count: int
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def has_citations_present(self) -> bool:
        """Whether any URL or DOI appears in the text.

        Named ``_present`` deliberately. It reports that citation-shaped strings
        *exist*; it says nothing about whether they resolve, support their
        claims, or were fabricated. Those are Credibility's stages 4–6
        (Document 2, §7.4), and this flag must never be mistaken for them.
        """
        return self.url_count > 0 or self.doi_count > 0


def analyze_statistics(
    text: str,
    sentences: tuple[TextSpan, ...],
    paragraphs: tuple[TextSpan, ...],
) -> DocumentStatistics:
    """Measure a document.

    Takes the spans rather than re-segmenting: the caller
    (:class:`~app.shared.context.SharedContext`) has already computed and cached
    them, and re-splitting would risk two components reporting different
    sentence counts for the same text.

    Args:
        text: The source document.
        sentences: Sentence spans from the segmenter.
        paragraphs: Paragraph spans from the segmenter.

    Returns:
        The measurements.
    """
    words = _WORD.findall(text)
    word_count = len(words)

    per_sentence = [len(_WORD.findall(span.text)) for span in sentences]
    mean_words = (sum(per_sentence) / len(per_sentence)) if per_sentence else 0.0

    unique = {word.lower() for word in words}
    unique_ratio = (len(unique) / word_count) if word_count else 0.0

    return DocumentStatistics(
        character_count=len(text),
        word_count=word_count,
        sentence_count=len(sentences),
        paragraph_count=len(paragraphs),
        line_count=text.count("\n") + 1 if text else 0,
        mean_sentence_words=round(mean_words, 2),
        max_sentence_words=max(per_sentence, default=0),
        unique_word_ratio=round(unique_ratio, 4),
    )


def _detect_title(text: str) -> str | None:
    """Return the document's first heading, if it has one."""
    atx = _ATX_HEADING.search(text)
    setext = _SETEXT_HEADING.search(text)

    candidates: list[tuple[int, str]] = []
    if atx:
        candidates.append((atx.start(), atx.group(2).strip()))
    if setext:
        candidates.append((setext.start(), setext.group(1).strip()))
    if not candidates:
        return None

    candidates.sort(key=lambda pair: pair[0])
    title = candidates[0][1]
    return title or None


def _detect_language(text: str) -> tuple[str | None, float | None]:
    """Detect the document's language.

    Imported lazily and failure-tolerant on purpose. Language is a descriptive
    field, not a gate: if detection is unavailable or the sample is too short,
    the honest answer is ``None`` — and ``None`` lets Relevance report "could not
    determine language" rather than assert a wrong one. An exception here would
    take down preprocessing over a nice-to-have.

    Returns:
        ``(iso_code, confidence)``, or ``(None, None)``.
    """
    sample = text.strip()
    if len(sample) < 20:
        return None, None

    try:
        from langdetect import DetectorFactory, detect_langs  # type: ignore

        # Without a fixed seed langdetect is non-deterministic, which would put
        # run-to-run variance into a value that has no business varying
        # (Document 4, §11).
        DetectorFactory.seed = 0
        ranked = detect_langs(sample[:4000])
    except ImportError:
        logger.debug("langdetect not installed; language will be reported as unknown")
        return None, None
    except Exception as exc:
        logger.debug("language detection failed", extra=bind(error=type(exc).__name__))
        return None, None

    if not ranked:
        return None, None
    best = ranked[0]
    return best.lang, round(float(best.prob), 4)


def warm_language_detection() -> bool:
    """Load langdetect's language profiles ahead of the first audit.

    Measured: the first ``detect_langs`` call costs ~575ms while langdetect
    reads its profile set, and every call after is ~1ms. Left cold, that half
    second lands **on the event loop, inside the first audit** — blocking every
    engine in wave 1 for a derivation only Relevance actually asked for.

    Paying it once at startup moves it off the request path entirely, which is
    what Document 4 §12 means by production readiness. Failure-tolerant, like
    the detection itself: a warm-up that cannot warm is not a reason to fail a
    boot.

    Returns:
        True if the profiles loaded.
    """
    _, confidence = _detect_language(
        "This sentence exists only to load the language detection profiles."
    )
    return confidence is not None


def analyze_metadata(text: str, extra: dict[str, Any] | None = None) -> DocumentMetadata:
    """Describe a document's structure, language, and citation markers.

    Args:
        text: The source document.
        extra: Provenance from extraction, passed through unchanged.

    Returns:
        The metadata.
    """
    has_headings = bool(_ATX_HEADING.search(text) or _SETEXT_HEADING.search(text))
    has_lists = bool(_LIST_ITEM.search(text))
    has_code = bool(_CODE_FENCE.search(text))
    has_tables = bool(_TABLE_ROW.search(text))

    language, confidence = _detect_language(text)

    return DocumentMetadata(
        title=_detect_title(text),
        language=language,
        language_confidence=confidence,
        format="markdown" if (has_headings or has_lists or has_code or has_tables) else "plain",
        has_headings=has_headings,
        has_lists=has_lists,
        has_code_blocks=has_code,
        has_tables=has_tables,
        url_count=len(_URL.findall(text)),
        doi_count=len(_DOI.findall(text)),
        extra=dict(extra or {}),
    )
