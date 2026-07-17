"""Stage 6 — Quality Evaluation (Document 3, §7).

Consumes the Quality dimensions (Novelty, Readability, Engagement, and Diversity
when applicable) plus the *quality contribution* of the Hybrid dimensions —
Relevance and Coverage's scored assessment of intent fulfillment and
completeness, which is distinct from their trust-gating critical findings.

**Quality is compensatory — and that is the deliberate opposite of Trust.**
Strengths in one area can reasonably offset weaknesses in another, because these
dimensions describe how well-made the content is. Quality never gates trust and
never, by itself, produces *Untrusted*.

**Contribution model.**

* Each participating dimension contributes its ``score``, weighted by its
  ``confidence`` and by a configurable dimension weight
  (``decision.quality_weights``).
* **N/A dimensions are excluded entirely** — removed from numerator *and*
  denominator (Document 3, §9). Their absence neither helps nor harms.
* The result is banded into High / Adequate / Low.

**Separation guarantee.** The Quality Verdict is always reported independently
of the Trust Verdict, never fused into it. Content can be high-quality yet
Untrusted — a polished text containing a fabricated citation — and trustworthy
yet low-quality. Preserving both axes rather than collapsing them into one
number is a guarantee of Document 3 §7, and it is the whole reason the auditor
returns two verdicts instead of a score.
"""

from __future__ import annotations

from typing import Mapping

from app.core.config import DecisionSettings
from app.core.constants import QUALITY_CONTRIBUTING_DIMENSIONS
from app.core.logging import bind, get_logger
from app.decision_engine.applicability import ApplicabilityPartition
from app.shared.schemas import AuditResult, QualityBand, QualityVerdict
from app.shared.scoring import weighted_mean

__all__ = ["evaluate"]

logger = get_logger(__name__)


def _band(aggregate: float, settings: DecisionSettings) -> QualityBand:
    """Band the aggregate. Thresholds are configuration; the banding is fixed."""
    if aggregate >= settings.quality_bands["high"]:
        return QualityBand.HIGH
    if aggregate >= settings.quality_bands["adequate"]:
        return QualityBand.ADEQUATE
    return QualityBand.LOW


def evaluate(
    scored: Mapping[str, AuditResult],
    partition: ApplicabilityPartition,
    settings: DecisionSettings,
) -> QualityVerdict:
    """Produce the Quality Verdict.

    **The weight is ``dimension_weight × confidence``**, and that product does
    two of Document 3's jobs at once:

    * §7's contribution model — each dimension contributes its score weighted by
      its confidence and its configured weight.
    * §8's "high score + low confidence" rule — a dimension the auditor could not
      measure well cannot push the band up on unverified strength, because its
      weight shrinks with its confidence. A *failed* dimension (confidence 0.0)
      weighs exactly nothing, so an engine outage neither raises nor lowers the
      band. It is not excluded by rule the way N/A is — it simply cannot vote,
      which is the arithmetic saying the same thing the confidence does.

    **N/A dimensions never reach this function.** Stage 3 removed them from
    ``scored`` entirely, so they are absent from the numerator *and* the
    denominator (§9). They are reported in ``excluded_dimensions`` so the
    exclusion is visible rather than silent.

    **Trust never enters.** No critical finding, no trust verdict, and no Trust
    dimension's score is read here. Content gated to *Untrusted* over a
    fabricated citation still scores its real Quality band, because §7's
    separation guarantee is what lets the report say "polished, and do not rely
    on it".

    Args:
        scored: The applicable results from Stage 3, keyed by dimension. Only
            the Quality and Hybrid entries contribute; Trust dimensions do not.
        partition: Stage 3's outcome, supplying the excluded dimensions that the
            verdict must report as N/A rather than silently omit.
        settings: Supplies ``quality_weights`` and ``quality_bands``.

    Returns:
        The Quality Verdict — band, aggregate, drivers, and the dimensions
        excluded as N/A.
    """
    contributions: list[tuple[float, float]] = []
    detail: list[tuple[str, float, float, float]] = []  # dim, score, conf, weight

    for dimension in QUALITY_CONTRIBUTING_DIMENSIONS:
        result = scored.get(dimension)
        if result is None or not isinstance(result.score, float):
            continue
        weight = settings.quality_weights.get(dimension, 1.0) * result.confidence
        contributions.append((float(result.score), weight))
        detail.append((dimension, float(result.score), result.confidence, weight))

    voting = [d for d in detail if d[3] > 0.0]

    if not voting:
        # Every quality-contributing dimension was excluded, absent, or measured
        # with zero confidence. There is no aggregate to report.
        #
        # score=None is the honest machine-readable signal ("no quality
        # dimension could be scored" — QualityVerdict.score's own contract), and
        # the band is the cautious end of a three-value enum with no "Unknown"
        # member. The pairing matters: a Low band with a null score says "not
        # measured", where a Low band with a 0.12 score says "measured, and
        # poor". A consumer that reads the band alone gets the fail-safe answer;
        # one that reads both gets the truth.
        logger.info(
            "quality could not be scored: no dimension carried voting weight",
            extra=bind(excluded=partition.excluded_dimensions),
        )
        return QualityVerdict(
            band=QualityBand.LOW,
            score=None,
            drivers=[
                "No quality dimension could be scored: "
                + (
                    ", ".join(
                        f"{d} reported zero confidence" for d, _, _, _ in detail
                    )
                    or "no quality-contributing dimension produced a result"
                )
                + ". The band is not a measurement — see the confidence report."
            ],
            excluded_dimensions=list(partition.excluded_dimensions),
        )

    aggregate = weighted_mean(contributions, default=0.0)
    band = _band(aggregate, settings)

    # The two strongest and the weakest — what a reader wants from "drivers":
    # what carried the band, and what held it back.
    ranked = sorted(voting, key=lambda item: item[1], reverse=True)
    highlighted = [*ranked[:2], ranked[-1]]
    drivers = [
        f"{dimension} {score:.2f} (confidence {confidence:.2f}"
        + (", down-weighted as low-confidence" if confidence < 0.5 else "")
        + ")"
        for dimension, score, confidence, _ in highlighted
    ]
    # Dedupe, preserving order: with fewer than three voters the strongest and
    # the weakest are the same entry, and naming a dimension twice would read as
    # two separate findings about it.
    drivers = list(dict.fromkeys(drivers))

    # Name the dimensions that could not vote. Without this the band is
    # arithmetically correct and rhetorically misleading: "Quality: High" over
    # two voters reads exactly like "Quality: High" over six, and the reader
    # cannot tell which they are looking at. The band does not change — only
    # what the report admits about it.
    silent = [d for d, _, _, w in detail if w == 0.0]
    if silent:
        drivers.append(
            f"{', '.join(sorted(silent))} could not be measured and carried no "
            f"weight — the band rests on {len(voting)} of "
            f"{len(voting) + len(silent)} quality-contributing dimension(s)"
        )

    for dimension in partition.excluded_dimensions:
        drivers.append(
            f"{dimension} excluded as not applicable — neither helping nor "
            "harming the band"
        )

    logger.info(
        "quality evaluated",
        extra=bind(
            band=band.value,
            aggregate=round(aggregate, 3),
            voting=[d for d, _, _, _ in voting],
            zero_weight=[d for d, _, _, w in detail if w == 0.0],
            excluded=partition.excluded_dimensions,
        ),
    )
    return QualityVerdict(
        band=band,
        score=aggregate,
        drivers=drivers,
        excluded_dimensions=list(partition.excluded_dimensions),
    )
