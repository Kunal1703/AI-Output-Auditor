"""Diversity Audit Engine (``ENG-DIVERSITY``) — Document 2, §7.8.

**Governing question.** Where appropriate, does the content fairly represent
legitimate perspectives while avoiding false balance?

**Inputs.** Prompt + AI Output.

**Classification.** Quality Dimension (applicability-gated) · Critical Finding
Capability: No · **Supports N/A** — the only engine that does.

**Frozen pipeline with its applicability branch (Document 2, §7.8).**

1. Input (Prompt + AI Output)
2. Applicability Classification
3. Applicability branch:
   * **No →** Return N/A (terminate; no score produced).
   * **Yes →** continue.
4. Stance Contract Detection
5. Retrieval of Credible Perspectives
6. Viewpoint Extraction
7. Balance Evaluation
8. Bias & Loaded Language Detection
9. Evidence Collection
10. Diversity Score
11. Confidence
12. Recommendations

**Outputs.** Applicable (Yes/No) · Applicability Reason · Score (or N/A) ·
Confidence · Diversity Ledger · Evidence · Recommendations.

**Contract mapping (Document 2, §6.5).** The frozen *Applicable* and
*Applicability Reason* outputs are carried in ``metadata.applicable`` and
``metadata.applicability_reason``; ``score`` is ``"N/A"`` when applicable is
False, and the ledger is empty. Use :meth:`AuditEngine.build_metadata`, which
enforces those pairings.

**Why the branch terminates rather than scoring low.** "Avoiding false balance"
is the whole point. Demanding perspective balance from a factual or technical
output would reward manufacturing a controversy that does not exist. So when the
dimension does not apply, the engine returns N/A and the Decision Engine excludes
it from the Quality Verdict entirely — removed from numerator *and* denominator,
never scored as zero (Document 3, §9). An inapplicable dimension must neither
help nor harm.

Returning N/A is also invisible to trust: Diversity is a Quality dimension with
no critical-finding capability, so it cannot affect the Trust Verdict either way.
"""

from __future__ import annotations

from typing import Mapping

from app.audit_engines.base import AuditEngine
from app.audit_engines.registry import register_engine
from app.shared.context import SharedContext
from app.shared.schemas import AuditResult

__all__ = ["DiversityAuditEngine"]


@register_engine
class DiversityAuditEngine(AuditEngine):
    """Measures perspective balance, where the dimension applies.

    Shared Components used (Document 2, §7.8): LLM Service, Retrieval Service,
    Evidence Store, Confidence Estimator, Recommendation Generator, Prompt
    Templates, JSON Models.
    """

    dimension = "Diversity"

    async def _execute(
        self, context: SharedContext, prior_results: Mapping[str, AuditResult]
    ) -> AuditResult:
        """Run the frozen Diversity pipeline, including the applicability branch.

        Raises:
            NotImplementedError: Until Milestone 4.
        """
        raise NotImplementedError(
            "The Diversity pipeline is implemented in Milestone 4 (Document 2, "
            "§7.8), including the applicability branch that returns N/A."
        )
