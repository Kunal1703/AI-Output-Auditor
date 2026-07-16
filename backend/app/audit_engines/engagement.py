"""Engagement Audit Engine (``ENG-ENGAGEMENT``) — Document 2, §7.7.

**Alternate title.** Usefulness & Communicative Integrity.

**Governing question.** Does the content help the user achieve their goal
without manipulative or misleading communication?

**Inputs.** Prompt + AI Output. *Cross-engine input:* consumes prior audit
results from Relevance, Coverage, Readability, and Novelty (Document 2, §8) —
which is why the orchestrator runs it last, in wave 3.

**Classification.** Quality Dimension · Critical Finding Capability: No ·
Does Not Support N/A.

**Frozen pipeline (Document 2, §7.7).**

1. Input (Prompt + AI Output)
2. Context & Task Identification
3. Reuse Previous Audit Results (Relevance, Coverage, Readability, Novelty)
4. LLM-based Task Fitness Evaluation
5. Manipulation Pattern Detection
6. LLM Manipulation Verification
7. Evidence Collection
8. Engagement Score
9. Confidence
10. Recommendations

**Outputs.** Score · Confidence · Engagement Ledger · Evidence ·
Recommendations.

**Stage 3 is a reuse stage, not a re-measurement stage.** Document 2 §4 is
explicit that Engagement "reuses the results of other engines rather than
recomputing overlapping signals". Whether the output was on-instruction, was
complete, was clear, was efficient — those are already measured. This engine
reads those four results and asks the one question none of them answers: does
the content actually serve the user's goal, honestly?

**Detection then verification.** Stage 5 pattern-matches; stage 6 judges. A
rhetorical question or a strong headline is a *pattern*, not automatically
manipulation. Flagging on the regex alone would make this engine cry wolf.
"""

from __future__ import annotations

from typing import Mapping

from app.audit_engines.base import AuditEngine
from app.audit_engines.registry import register_engine
from app.shared.context import SharedContext
from app.shared.schemas import AuditResult

__all__ = ["EngagementAuditEngine"]


@register_engine
class EngagementAuditEngine(AuditEngine):
    """Measures task fitness and communicative integrity.

    Shared Components used (Document 2, §7.7): LLM Service, Deterministic
    Validators, Evidence Store, Confidence Estimator, Recommendation Generator,
    Prompt Templates, JSON Models. Cross-engine inputs: Relevance, Coverage,
    Readability, Novelty.
    """

    dimension = "Engagement"

    async def _execute(
        self, context: SharedContext, prior_results: Mapping[str, AuditResult]
    ) -> AuditResult:
        """Run the frozen Engagement pipeline.

        Args:
            context: The run's normalized content and shared derivation store.
            prior_results: Carries the Relevance, Coverage, Readability, and
                Novelty results for the stage 3 reuse.

        Raises:
            NotImplementedError: Until Milestone 4.
        """
        raise NotImplementedError(
            "The Engagement pipeline is implemented in Milestone 4 (Document 2, "
            "§7.7)."
        )
