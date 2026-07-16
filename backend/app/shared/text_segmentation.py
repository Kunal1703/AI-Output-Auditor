"""Text segmentation — sentences, paragraphs, and locatable spans.

Shared infrastructure consumed through :class:`~app.shared.context.SharedContext`.
It is mechanical and evaluation-neutral: it decides *where a sentence ends*,
never *whether the sentence is any good*.

**Why every span carries offsets.** Document 4 §8 requires the Evidence Viewer
to drill from a finding through to "the evidence span/source that backs it", and
Document 3 §12 makes traceability a report guarantee. A detached snippet cannot
be highlighted in the original; a ``(start, end)`` into the source can. So
segmentation returns :class:`TextSpan`, not ``list[str]`` — losing the offsets
here would quietly cost the UI its ability to point at anything.

**Relationship to the frozen pipelines.** Novelty's stage 2 is "Text
Segmentation" (Document 2, §7.5). That stage stays Novelty's: the engine still
performs it at its frozen position. It simply *calls* this segmenter instead of
carrying its own copy, which is what Document 2 §5 means by a shared component
and what Document 4 §15 means by "engines never duplicate logic". Reuse of a
mechanism is not relocation of a stage.

Regex-based by choice. Document 4 §2 lists ``regex``/``langdetect``/``textstat``
as the deterministic toolkit and names no parser. A regex splitter is
deterministic, has no model download, and never varies between runs — which
Document 4 §11 asks of everything that can manage it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

__all__ = [
    "TextSpan",
    "SegmentKind",
    "TextSegmenter",
    "locate_span",
    "normalize_whitespace",
]


@dataclass(frozen=True)
class TextSpan:
    """A located run of text within a source document.

    Attributes:
        text: The span's text, exactly as it appears in the source.
        start: Character offset of the first character, inclusive.
        end: Character offset one past the last character, exclusive.
        index: Ordinal position among spans of the same kind, zero-based.
        kind: What this span is — a sentence, a paragraph, or a claim's source.
    """

    text: str
    start: int
    end: int
    index: int = 0
    kind: str = "sentence"

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError(
                f"invalid span offsets: start={self.start}, end={self.end}"
            )

    @property
    def length(self) -> int:
        """Character length of the span."""
        return self.end - self.start

    def locator(self) -> str:
        """Render the offsets as an ``EvidenceItem.locator`` string.

        The format ``"kind[index]@start:end"`` is stable and machine-parseable,
        so the frontend can turn a locator back into a highlight range.
        """
        return f"{self.kind}[{self.index}]@{self.start}:{self.end}"

    def snippet(self, limit: int = 160) -> str:
        """Return the text, truncated for logs and prompts.

        Args:
            limit: Maximum characters before truncation.
        """
        collapsed = normalize_whitespace(self.text)
        if len(collapsed) <= limit:
            return collapsed
        return collapsed[: limit - 1] + "…"


class SegmentKind:
    """Span kind labels. Constants rather than an enum — they are free-form,
    since an engine may introduce a kind of its own (e.g. a citation span)."""

    SENTENCE = "sentence"
    PARAGRAPH = "paragraph"
    CLAIM = "claim"
    REQUIREMENT = "requirement"


_WHITESPACE = re.compile(r"\s+")

#: Blank-line paragraph boundary: a newline, optional spaces, another newline.
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n+")

#: A candidate sentence terminator: ``.!?`` plus optional closing quotes or
#: brackets, followed by whitespace. Each hit is then screened by
#: :func:`_is_false_boundary`, which rejects the ones that are not real.
_SENTENCE_BOUNDARY = re.compile(r'([.!?]+["\'’”)\]]*)(\s+)')

#: Tokens that end in a period without ending a sentence. Screening these is the
#: single biggest correctness win for a regex splitter: without it, "approx. 40
#: million visitors" becomes two sentences and every downstream span is wrong.
_ABBREVIATIONS = frozenset(
    """
    dr mr mrs ms mx prof sr jr st rev hon gen col lt sgt capt
    vs etc al inc ltd co corp dept est approx cf ca fig figs eq eqs
    no nos vol vols pp ed eds trans repr rev ch chap sec secs
    min max avg std dev repr eg ie viz
    jan feb mar apr jun jul aug sept sep oct nov dec
    mon tue tues wed thu thurs fri sat sun
    """.split()
)

#: Multi-part abbreviations whose internal periods must not split. Matched on
#: the raw tail of the preceding text rather than on a single token.
_DOTTED_ABBREVIATIONS = (
    "e.g.",
    "i.e.",
    "u.s.",
    "u.k.",
    "u.n.",
    "a.m.",
    "p.m.",
    "et al.",
    "ph.d.",
    "m.d.",
    "b.c.",
    "a.d.",
)

#: A single capital letter used as an initial, e.g. the "J." of "J. Smith".
_INITIAL = re.compile(r"\b[A-Z]\.$")

#: A digit immediately before the period, e.g. "3.14" or "Section 2.1".
_DECIMAL = re.compile(r"\d$")


def normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace to single spaces and strip the ends.

    Used for comparison and display only. **Never** for the text handed to the
    engines: Document 4 §5 forbids preprocessing from altering content, and a
    normalized copy would desynchronize every offset from the original.
    """
    return _WHITESPACE.sub(" ", text).strip()


def _is_false_boundary(text: str, terminator_end: int) -> bool:
    """Decide whether a candidate terminator is a real sentence end.

    Args:
        text: The full source text.
        terminator_end: Offset one past the terminator's last character.

    Returns:
        True if this is *not* a sentence boundary and the split must be
        suppressed.
    """
    head = text[:terminator_end]

    # "3.14", "Section 2.1" — a period between digits is never a boundary.
    if head.endswith(".") and _DECIMAL.search(head[:-1] or ""):
        after = text[terminator_end : terminator_end + 2].lstrip()
        if after and after[0].isdigit():
            return True

    lowered = head.lower()
    for abbreviation in _DOTTED_ABBREVIATIONS:
        if lowered.endswith(abbreviation):
            return True

    if _INITIAL.search(head):
        return True

    # Single-token abbreviations: take the last word before the period.
    if head.endswith("."):
        token = re.split(r"[\s(\[\"']", head[:-1])[-1].lower().strip(".")
        if token in _ABBREVIATIONS:
            return True

    return False


def _looks_like_sentence_start(text: str, offset: int) -> bool:
    """Whether the text at ``offset`` plausibly begins a new sentence.

    A terminator followed by a lowercase word is usually an abbreviation this
    module has not catalogued, so requiring an opener is a cheap second line of
    defense behind :func:`_is_false_boundary`.
    """
    rest = text[offset:].lstrip()
    if not rest:
        return False
    first = rest[0]
    return first.isupper() or first.isdigit() or first in "\"'“‘([-—*#>"


class TextSegmenter:
    """Splits text into paragraphs and sentences, preserving source offsets.

    Stateless and deterministic: the same input always yields the same spans,
    which is what lets Document 4 §11's stability criterion hold for everything
    built on top of it.

    Note:
        Tuned for prose — the content this auditor exists to evaluate. Markdown
        structure (headings, list items) is treated as paragraph-level blocks
        rather than parsed, because no frozen pipeline asks for a document tree.
    """

    def paragraphs(self, text: str) -> tuple[TextSpan, ...]:
        """Split ``text`` into paragraph spans on blank lines.

        Args:
            text: The source document.

        Returns:
            Paragraph spans in document order. Empty for blank input.
        """
        if not text or not text.strip():
            return ()

        spans: list[TextSpan] = []
        cursor = 0
        index = 0

        for match in _PARAGRAPH_BREAK.finditer(text):
            block = text[cursor : match.start()]
            if block.strip():
                spans.append(self._trimmed(block, cursor, index, SegmentKind.PARAGRAPH))
                index += 1
            cursor = match.end()

        tail = text[cursor:]
        if tail.strip():
            spans.append(self._trimmed(tail, cursor, index, SegmentKind.PARAGRAPH))

        return tuple(spans)

    def sentences(self, text: str, offset: int = 0) -> tuple[TextSpan, ...]:
        """Split ``text`` into sentence spans.

        Args:
            text: The text to split.
            offset: Added to every span offset. Lets a caller segment a
                paragraph while keeping offsets relative to the whole document.

        Returns:
            Sentence spans in document order. Empty for blank input.
        """
        if not text or not text.strip():
            return ()

        cut_points: list[int] = []
        for match in _SENTENCE_BOUNDARY.finditer(text):
            terminator_end = match.end(1)
            if _is_false_boundary(text, terminator_end):
                continue
            if not _looks_like_sentence_start(text, match.end(2)):
                continue
            cut_points.append(terminator_end)

        spans: list[TextSpan] = []
        cursor = 0
        index = 0
        for cut in [*cut_points, len(text)]:
            raw = text[cursor:cut]
            if raw.strip():
                spans.append(
                    self._trimmed(raw, cursor + offset, index, SegmentKind.SENTENCE)
                )
                index += 1
            cursor = cut

        return tuple(spans)

    def sentences_by_paragraph(self, text: str) -> tuple[tuple[TextSpan, ...], ...]:
        """Split into sentences, grouped by their paragraph.

        Segmenting per paragraph rather than over the whole document prevents a
        sentence span from straddling a blank line — which would otherwise let a
        heading and the first line of its section merge into one "sentence".

        Args:
            text: The source document.

        Returns:
            One tuple of sentence spans per paragraph, in document order. Every
            offset refers to the original document.
        """
        return tuple(
            self.sentences(p.text, offset=p.start) for p in self.paragraphs(text)
        )

    def segment(self, text: str) -> tuple[TextSpan, ...]:
        """Split into sentence spans across the whole document.

        The flat view Novelty's stage 2 wants: every sentence of the AI Output,
        in order, each locatable in the original.

        Args:
            text: The source document.

        Returns:
            Sentence spans in document order, re-indexed document-wide.
        """
        flat: list[TextSpan] = []
        for group in self.sentences_by_paragraph(text):
            for span in group:
                flat.append(
                    TextSpan(
                        text=span.text,
                        start=span.start,
                        end=span.end,
                        index=len(flat),
                        kind=SegmentKind.SENTENCE,
                    )
                )
        return tuple(flat)

    @staticmethod
    def _trimmed(raw: str, start: int, index: int, kind: str) -> TextSpan:
        """Build a span with surrounding whitespace excluded from the offsets.

        Trimming the *offsets* rather than only the text keeps ``span.text`` and
        ``source[span.start:span.end]`` identical — an invariant the Evidence
        Viewer relies on, and one that is easy to break by trimming the string
        alone.
        """
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw) - len(raw.rstrip())
        return TextSpan(
            text=raw[leading : len(raw) - trailing],
            start=start + leading,
            end=start + len(raw) - trailing,
            index=index,
            kind=kind,
        )


def locate_span(
    haystack: str, needle: str, kind: str = SegmentKind.CLAIM, index: int = 0
) -> TextSpan | None:
    """Find ``needle`` in ``haystack`` and return it as a located span.

    Exists because an LLM extraction service returns *text*, not offsets, and
    often paraphrases or re-punctuates as it goes. Evidence needs a location, so
    this recovers one where it honestly can.

    Two passes: exact match, then whitespace-normalized match (which recovers
    the common case where a model reflowed a line break into a space). It does
    **not** attempt fuzzy or semantic matching — a span that only approximately
    matches would point the Evidence Viewer at text the model did not actually
    quote, and a wrong highlight is worse than no highlight.

    Args:
        haystack: The source document.
        needle: The text to locate.
        kind: Span kind for the result.
        index: Ordinal to record on the span.

    Returns:
        The located span, or ``None`` if the text cannot be found exactly. The
        caller decides what an unlocatable unit means — Document 4 §12 says
        degrade, never guess.
    """
    if not needle or not needle.strip():
        return None

    start = haystack.find(needle)
    if start != -1:
        return TextSpan(
            text=needle, start=start, end=start + len(needle), index=index, kind=kind
        )

    # Second pass: the model reflowed whitespace. Walk the normalized haystack
    # while keeping a map back to the original offsets.
    target = normalize_whitespace(needle)
    if not target:
        return None

    normalized_chars: list[str] = []
    origins: list[int] = []
    previous_was_space = False
    for position, char in enumerate(haystack):
        if char.isspace():
            if previous_was_space or not normalized_chars:
                continue
            normalized_chars.append(" ")
            origins.append(position)
            previous_was_space = True
        else:
            normalized_chars.append(char)
            origins.append(position)
            previous_was_space = False

    normalized = "".join(normalized_chars)
    found = normalized.find(target)
    if found == -1:
        return None

    origin_start = origins[found]
    origin_end = origins[found + len(target) - 1] + 1
    return TextSpan(
        text=haystack[origin_start:origin_end],
        start=origin_start,
        end=origin_end,
        index=index,
        kind=kind,
    )


def spans_to_text(spans: Sequence[TextSpan]) -> tuple[str, ...]:
    """Project spans to their texts, for callers that need no offsets."""
    return tuple(span.text for span in spans)
