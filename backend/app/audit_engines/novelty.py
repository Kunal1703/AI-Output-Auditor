"""Novelty Audit Engine (``ENG-NOVELTY``) — Document 2, §7.5.

**Governing question.** Does the output communicate efficiently, minimizing
unnecessary repetition while preserving important content?

**Inputs.** AI Output. *Cross-engine input:* consumes Coverage results for the
Coverage Cross-check (Document 2, §8) — which is why the orchestrator runs
Novelty in wave 2, after Coverage.

**Classification.** Quality Dimension · Critical Finding Capability: No ·
Does Not Support N/A.

Capability No is not an oversight. A repetitive text is badly made, not
untrustworthy, so Novelty can lower the Quality band but can never gate trust
(Document 3, §5).

**Frozen pipeline (Document 2, §7.5).**

1. Input (AI Output)
2. Text Segmentation
3. Sentence Embedding Generation
4. Semantic & Literal Duplicate Detection
5. Candidate Redundancy Identification
6. LLM-based Functional Repetition Review
7. Coverage Cross-check
8. Novelty Score
9. Confidence
10. Recommendations

**Outputs.** Score · Confidence · Redundancy Ledger · Evidence ·
Recommendations.

**Why stages 6 and 7 both exist.** Stage 4 finds text that *looks* duplicated;
stages 6 and 7 decide whether it is actually redundant. A recap that restates a
high-salience key point is functional repetition serving the reader, not padding
— the Coverage Cross-check is what tells the two apart. Penalizing it would put
this engine in direct conflict with Coverage.
"""

from __future__ import annotations

from typing import Mapping

from app.audit_engines.base import AuditEngine
from app.audit_engines.registry import register_engine
from app.shared.context import SharedContext
from app.shared.schemas import AuditResult

__all__ = ["NoveltyAuditEngine"]


@register_engine
class NoveltyAuditEngine(AuditEngine):
    """Measures communication efficiency and redundancy.

    Shared Components used (Document 2, §7.5): Embedding Service, LLM Service,
    Evidence Store, Confidence Estimator, Recommendation Generator, Prompt
    Templates, JSON Models. Cross-engine input: Coverage.
    """

    dimension = "Novelty"

    async def _execute(
        self, context: SharedContext, prior_results: Mapping[str, AuditResult]
    ) -> AuditResult:
        """Run the frozen Novelty pipeline.

        Args:
            context: The run's normalized content and shared derivation store.
            prior_results: Carries the Coverage ``AuditResult`` under
                ``"Coverage"``, for the stage 7 cross-check.

        Raises:
            NotImplementedError: Until Milestone 4.
        """
        raise NotImplementedError(
            "The Novelty pipeline is implemented in Milestone 4 (Document 2, "
            "§7.5)."
        )
