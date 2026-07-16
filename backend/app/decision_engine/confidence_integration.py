"""Stage 7 — Confidence Integration (Document 3, §8).

Overlays per-dimension confidence on the Trust and Quality outcomes to decide
whether each verdict is assertable, or whether the run must be marked *Unable to
Verify*.

Confidence is a **first-class gate on assertability**, separate from the score,
exactly as the engines report it. This stage does not recompute engine
confidence — it interprets it to decide whether a verdict can honestly be
stated.

**Interpretation rules (Document 3, §8).**

| Situation | Behavior |
|---|---|
| **High score + low confidence** | The favorable score cannot be asserted. Trust-relevant → routes toward *Unable to Verify*; quality → contribution down-weighted and flagged low-confidence. **Never upgraded to Trusted on unverified strength.** |
| **Low score + high confidence** | A confident negative. Asserted firmly — drives *Untrusted* (if trust-relevant and gating) or *Needs Revision* / lower Quality. |
| **Conflicting confidence across dimensions** | Weight each contribution by its own confidence; a low-confidence dimension cannot outweigh a high-confidence one. If the conflict sits on a trust-relevant dimension and cannot be resolved, escalate that dimension to *Unable to Verify*. |
| **Low overall confidence** | If trust-relevant dimensions collectively fail to reach the minimum needed to assert a Trust Verdict, the Overall Verdict becomes *Unable to Verify*. |

**When *Unable to Verify* applies.** No qualifying Critical Finding is present
(so it is not *Untrusted*), **but** one or more trust-relevant dimensions cannot
be asserted with sufficient confidence — evidence could not be retrieved, a
Trust or Hybrid result is missing or invalid, or confidence on a gating
dimension falls below the minimum.

*Unable to Verify* is an **honest-uncertainty verdict, not a failure verdict.*
It says trust is *undetermined*, not that the content failed, and it routes to
human review. Thresholds are configuration; the principle — *insufficient
confidence on a trust dimension blocks a Trusted verdict* — is fixed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from app.core.config import DecisionSettings
from app.shared.schemas import AuditResult, ConfidenceReport, QualityVerdict, TrustVerdict

__all__ = ["IntegratedConfidence", "integrate"]


@dataclass(frozen=True)
class IntegratedConfidence:
    """The result of Stage 7.

    Attributes:
        report: Per-dimension and overall confidence for the Final Audit Report.
        trust_assertable: Whether the Trust Verdict may be stated as-is. False
            escalates the run to *Unable to Verify* — unless trust is already
            gated to *Untrusted*, which a confidence gap never overturns. An
            established critical failure does not become uncertain just because
            another dimension was hard to measure.
        trust_verdict: The Trust Verdict after confidence overlay, possibly
            escalated to *Unable to Verify*.
    """

    report: ConfidenceReport
    trust_assertable: bool
    trust_verdict: TrustVerdict


def integrate(
    results: Mapping[str, AuditResult],
    trust_verdict: TrustVerdict,
    quality_verdict: QualityVerdict,
    settings: DecisionSettings,
) -> IntegratedConfidence:
    """Overlay confidence on the trust and quality outcomes.

    Args:
        results: All eight results, keyed by dimension. Includes the excluded
            ones — an N/A dimension still reports confidence, and the report
            shows it.
        trust_verdict: Stage 5's output.
        quality_verdict: Stage 6's output.
        settings: Supplies ``min_trust_confidence``.

    Returns:
        The confidence report and the possibly-escalated Trust Verdict.

    Raises:
        NotImplementedError: Until Milestone 2.
    """
    raise NotImplementedError(
        "Confidence Integration is implemented in Milestone 2 (Document 3, §8)."
    )
