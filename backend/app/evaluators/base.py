"""Shared helpers for the metric evaluators (AI Output Auditor, MB2+).

Small, dependency-light utilities the evaluators share: projecting a located
:class:`~app.shared.text_segmentation.TextSpan` into a contract
:class:`~app.shared.schemas.Span`, minting run-unique finding ids, and projecting
an internal 0–1 score onto the 1–5 presentation band. Deliberately not a heavy
base class — the evaluators have different inputs (Faithfulness reads the
attribution map; Numeric Accuracy reads the numeric ledgers), so they share
functions, not a lifecycle.
"""

from __future__ import annotations

import itertools
from typing import Iterator, Literal

from app.shared.schemas import Span
from app.shared.text_segmentation import TextSpan

__all__ = ["to_span", "band_from_score", "finding_ids"]


def to_span(text_span: TextSpan, ref: Literal["source", "output"]) -> Span:
    """Project a :class:`TextSpan` into a contract :class:`Span`.

    Args:
        text_span: The located span.
        ref: Which document the offsets index into.

    Returns:
        The contract span, carrying the locator for UI highlighting.
    """
    return Span(
        text=text_span.text,
        start=text_span.start,
        end=text_span.end,
        ref=ref,
        locator=text_span.locator(),
    )


def band_from_score(score: float | None) -> int | None:
    """Project an internal 0–1 score onto a 1–5 presentation band.

    A monotonic, report-layer projection only — the internal float remains the
    authority for aggregation and gating.

    Args:
        score: A score in [0, 1], or None.

    Returns:
        A band in [1, 5], or None when ``score`` is None.
    """
    if score is None:
        return None
    if score >= 0.90:
        return 5
    if score >= 0.75:
        return 4
    if score >= 0.50:
        return 3
    if score >= 0.25:
        return 2
    return 1


def finding_ids(prefix: str) -> Iterator[str]:
    """Yield ``fnd_<prefix>_1``, ``fnd_<prefix>_2``, … for one evaluate pass.

    The per-metric prefix keeps ids distinct when an ``OutputAudit`` later
    aggregates findings across evaluators (MB4).
    """
    for n in itertools.count(1):
        yield f"fnd_{prefix}_{n}"
