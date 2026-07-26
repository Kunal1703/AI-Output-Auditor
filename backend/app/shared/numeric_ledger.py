"""Numeric ledger — deterministic extraction and comparison of quantities.

The Factual & Numeric Accuracy metric is the one dimension where a rule beats a
model outright (Metric Research §3): numbers, dates, percentages, and quantities
are *deterministically checkable*, and a fluent LLM judge will happily read
"5.7%" as "6.0%". This module extracts those mentions from a document and
normalizes them so an output value can be compared against the source value by
arithmetic, never by an LLM's arithmetic mood.

It follows the **Proof-Carrying Numbers** idea: every mention keeps the verbatim
substring it came from and the sentence around it, so a comparison can attach the
source quote that grounds (or refutes) it as evidence.

Shared by both :class:`~app.shared.source_context.SourceContext` and
:class:`~app.shared.output_context.OutputContext` (each exposes its own ledger)
and consumed by the Numeric Accuracy evaluator. It is pure, regex-based, and
model-free — deterministic and identical on every run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from app.shared.text_segmentation import TextSpan

__all__ = [
    "NumericKind",
    "NumericMention",
    "extract_numeric_mentions",
    "content_tokens",
    "token_overlap",
    "values_equal",
    "mentions_equal",
    "relative_difference",
]


class NumericKind(str, Enum):
    """The kind of numeric mention, which decides what it is comparable to."""

    PERCENT = "percent"
    CURRENCY = "currency"
    DATE = "date"
    QUANTITY = "quantity"
    NUMBER = "number"


#: Multiplicative scales that can follow a number ("5.2 billion").
_SCALES: dict[str, float] = {
    "trillion": 1e12, "tn": 1e12,
    "billion": 1e9, "bn": 1e9,
    "million": 1e6, "mn": 1e6, "m": 1e6,
    "thousand": 1e3, "k": 1e3,
}

_CURRENCY_SYMBOLS: dict[str, str] = {"$": "USD", "£": "GBP", "€": "EUR"}
_CURRENCY_WORDS: dict[str, str] = {
    "dollars": "USD", "dollar": "USD", "usd": "USD",
    "pounds": "GBP", "gbp": "GBP",
    "euros": "EUR", "euro": "EUR", "eur": "EUR",
}

_MONTHS: dict[str, int] = {
    m: i
    for i, m in enumerate(
        [
            "january", "february", "march", "april", "may", "june", "july",
            "august", "september", "october", "november", "december",
        ],
        start=1,
    )
}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})

_NUM = r"\d[\d,]*(?:\.\d+)?"
_SCALE_WORDS = "|".join(sorted(_SCALES, key=len, reverse=True))

# Ordered by priority: earlier patterns claim their characters first so a year
# inside a currency amount is not also matched as a bare date, etc.
_PERCENT_RE = re.compile(rf"({_NUM})\s*(?:%|percent\b)", re.IGNORECASE)
_CURRENCY_SYMBOL_RE = re.compile(
    rf"([$£€])\s*({_NUM})\s*({_SCALE_WORDS})?", re.IGNORECASE
)
_CURRENCY_WORD_RE = re.compile(
    rf"({_NUM})\s*({_SCALE_WORDS})?\s*({'|'.join(_CURRENCY_WORDS)})\b", re.IGNORECASE
)
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MONTH_YEAR_RE = re.compile(
    r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?\s+(\d{4})\b",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b(1[6-9]\d\d|20\d\d)\b")
_QUANTITY_RE = re.compile(
    rf"({_NUM})\s*({_SCALE_WORDS})?\s*([A-Za-z][A-Za-z-]+)", re.IGNORECASE
)
_NUMBER_RE = re.compile(rf"({_NUM})\s*({_SCALE_WORDS})?")

_STOPWORDS = frozenset(
    """a an the of to in on at for and or but with without from by as is are was
    were be been being this that these those it its their his her our your my we
    they he she you i than then over under about into out up down more most less
    least very just only also not no nor so such per each which who whom whose""".split()
)
_TOKEN_RE = re.compile(r"[A-Za-z]+")


@dataclass(frozen=True)
class NumericMention:
    """One located, normalized numeric value found in a document.

    Attributes:
        kind: What sort of value it is (percent / currency / date / quantity /
            number), which determines comparability.
        raw: The verbatim substring, e.g. ``"$5.2 billion"`` — the proof-carrying
            quote.
        value: The normalized magnitude. Currency and scaled numbers are folded
            to base units ($5.2 billion → 5.2e9); a year is the integer year.
        unit: A comparability key — ``"%"``, an ISO currency code, ``"year"``, or
            a lower-cased unit noun for a quantity; ``None`` for a bare number.
        span: Where the value sits in the document, for evidence highlighting.
        sentence: The sentence containing it, used for context alignment.
        sentence_index: Index of that sentence in the document.
    """

    kind: NumericKind
    raw: str
    value: float
    unit: str | None
    span: TextSpan
    sentence: str = ""
    sentence_index: int = -1

    @property
    def comparable_unit(self) -> str:
        """A normalized unit key two mentions must share to be comparable."""
        if self.unit is None:
            return ""
        return self.unit.lower()


def _to_number(raw: str) -> float | None:
    """Parse a numeric token that may carry thousands separators."""
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def _scale(word: str | None) -> float:
    return _SCALES.get(word.lower(), 1.0) if word else 1.0


def extract_numeric_mentions(
    text: str, sentences: tuple[TextSpan, ...]
) -> tuple[NumericMention, ...]:
    """Extract every numeric mention from ``text``, normalized and located.

    Patterns are applied in priority order (percent → currency → date →
    quantity → bare number), and each match claims its character range so a
    value is never counted twice under two kinds — a currency amount's digits are
    not re-matched as a bare number, a year is not also a quantity, and so on.

    Args:
        text: The document text.
        sentences: The document's sentence spans (from the context), used to
            attach each mention's containing sentence for context alignment.

    Returns:
        Mentions in document order.
    """
    claimed: list[tuple[int, int]] = []
    mentions: list[NumericMention] = []

    def is_free(start: int, end: int) -> bool:
        return all(end <= s or start >= e for s, e in claimed)

    def sentence_for(pos: int) -> tuple[str, int]:
        for span in sentences:
            if span.start <= pos < span.end:
                return span.text, span.index
        return "", -1

    def add(match: re.Match, kind: NumericKind, value: float, unit: str | None) -> None:
        start, end = match.start(), match.end()
        if not is_free(start, end):
            return
        claimed.append((start, end))
        sent, sent_idx = sentence_for(start)
        mentions.append(
            NumericMention(
                kind=kind,
                raw=match.group(0).strip(),
                value=value,
                unit=unit,
                span=TextSpan(
                    text=match.group(0).strip(),
                    start=start,
                    end=end,
                    index=len(mentions),
                    kind="numeric",
                ),
                sentence=sent,
                sentence_index=sent_idx,
            )
        )

    for m in _PERCENT_RE.finditer(text):
        value = _to_number(m.group(1))
        if value is not None:
            add(m, NumericKind.PERCENT, value, "%")

    for m in _CURRENCY_SYMBOL_RE.finditer(text):
        value = _to_number(m.group(2))
        if value is not None:
            add(m, NumericKind.CURRENCY, value * _scale(m.group(3)),
                _CURRENCY_SYMBOLS.get(m.group(1), m.group(1)))

    for m in _CURRENCY_WORD_RE.finditer(text):
        value = _to_number(m.group(1))
        if value is not None:
            add(m, NumericKind.CURRENCY, value * _scale(m.group(2)),
                _CURRENCY_WORDS.get(m.group(3).lower(), m.group(3)))

    for m in _ISO_DATE_RE.finditer(text):
        year = _to_number(m.group(1))
        month = _to_number(m.group(2))
        if year is not None:
            # Encode month as the fractional part (2021-03 → 2021.03) so date
            # comparison can read year and month back without a relative
            # tolerance treating adjacent years as equal.
            add(m, NumericKind.DATE, year + (month or 0) / 100.0, "year-month")

    for m in _MONTH_YEAR_RE.finditer(text):
        year = _to_number(m.group(2))
        if year is not None:
            month = _MONTHS.get(m.group(1).lower(), 0)
            add(m, NumericKind.DATE, year + month / 100.0, "year-month")

    for m in _YEAR_RE.finditer(text):
        year = _to_number(m.group(1))
        if year is not None:
            add(m, NumericKind.DATE, year, "year")

    for m in _QUANTITY_RE.finditer(text):
        unit_word = m.group(3).lower()
        # A trailing scale word with no noun ("5 million") is a scaled number,
        # not a quantity; and a unit that is actually a currency word was already
        # claimed above. Skip scale words captured as the "noun".
        if unit_word in _SCALES or unit_word in _CURRENCY_WORDS:
            continue
        value = _to_number(m.group(1))
        if value is not None:
            add(m, NumericKind.QUANTITY, value * _scale(m.group(2)), unit_word)

    for m in _NUMBER_RE.finditer(text):
        value = _to_number(m.group(1))
        if value is not None:
            add(m, NumericKind.NUMBER, value * _scale(m.group(2)), None)

    mentions.sort(key=lambda mention: mention.span.start)
    return tuple(mentions)


def content_tokens(text: str) -> set[str]:
    """Lower-cased content words of ``text`` (letters only, stopwords dropped)."""
    return {
        tok for tok in (t.lower() for t in _TOKEN_RE.findall(text))
        if tok not in _STOPWORDS and len(tok) > 1
    }


def token_overlap(left: str, right: str) -> float:
    """Jaccard overlap of the content tokens of two sentences, in [0, 1]."""
    a, b = content_tokens(left), content_tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def relative_difference(a: float, b: float) -> float:
    """Relative difference between two values, in [0, ∞).

    Symmetric and scale-free: ``|a - b| / max(|a|, |b|)``. Zero when both are
    zero.
    """
    scale = max(abs(a), abs(b))
    if scale == 0.0:
        return 0.0
    return abs(a - b) / scale


def values_equal(a: float, b: float, tolerance: float) -> bool:
    """Whether two values match within a relative ``tolerance``."""
    return relative_difference(a, b) <= tolerance


def _split_date(value: float) -> tuple[int, int]:
    """Recover ``(year, month)`` from an encoded date value (2021.03 → (2021, 3))."""
    year = int(value)
    month = int(round((value - year) * 100))
    return year, month


def mentions_equal(
    a: "NumericMention", b: "NumericMention", tolerance: float
) -> bool:
    """Whether two mentions state the same value.

    Dates are compared by year (and month when both carry one) rather than by
    relative tolerance — on the year scale a two-year error is a ~0.1% relative
    difference, which a numeric tolerance would wrongly treat as equal. All other
    kinds use the relative rounding tolerance.
    """
    if a.kind is NumericKind.DATE and b.kind is NumericKind.DATE:
        ya, ma = _split_date(a.value)
        yb, mb = _split_date(b.value)
        if ya != yb:
            return False
        if ma and mb:
            return ma == mb
        return True  # one is year-only — a matching year is sufficient
    return values_equal(a.value, b.value, tolerance)
