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
from app.decision_engine.applicability import ApplicabilityPartition
from app.shared.schemas import AuditResult, QualityVerdict

__all__ = ["evaluate"]


def evaluate(
    scored: Mapping[str, AuditResult],
    partition: ApplicabilityPartition,
    settings: DecisionSettings,
) -> QualityVerdict:
    """Produce the Quality Verdict.

    Args:
        scored: The applicable results from Stage 3, keyed by dimension. Only
            the Quality and Hybrid entries contribute; Trust dimensions do not.
        partition: Stage 3's outcome, supplying the excluded dimensions that the
            verdict must report as N/A rather than silently omit.
        settings: Supplies ``quality_weights`` and ``quality_bands``.

    Returns:
        The Quality Verdict — band, aggregate, drivers, and the dimensions
        excluded as N/A.

    Raises:
        NotImplementedError: Until Milestone 2.
    """
    raise NotImplementedError(
        "Quality Evaluation is implemented in Milestone 2 (Document 3, §7)."
    )
