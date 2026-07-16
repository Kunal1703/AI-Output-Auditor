"""Readability Audit Engine (``ENG-READABILITY``) — Document 2, §7.6.

**Governing question.** Is the content easy for its intended audience to
understand (clarity, coherence, structure)?

**Inputs.** AI Output.

**Classification.** Quality Dimension · Critical Finding Capability: No ·
Does Not Support N/A.

**Frozen pipeline (Document 2, §7.6).**

1. Input (AI Output)
2. Deterministic Analysis (Grammar, sentence complexity, structure heuristics)
3. LLM Readability Review (Clarity, Coherence, Structure)
4. Issue Classification
5. Severity Assignment
6. Evidence Collection
7. Readability Score
8. Confidence
9. Recommendations

**Outputs.** Score · Confidence · Readability Ledger · Evidence ·
Recommendations.

**Note the ordering.** Deterministic analysis runs *before* the LLM review, not
after. The cheap, reproducible signals are gathered first and give the judge
something concrete to reason about — and Document 4 §11 wants as much of the
verdict as possible resting on checks that do not vary between runs.

This engine is also the clearest case for the two-axis separation: polished
prose scores well here while Credibility is simultaneously gating the content to
*Untrusted* over a fabricated citation. Readability lowers or raises the Quality
band and touches trust never (Document 3, §7).
"""

from __future__ import annotations

from typing import Mapping

from app.audit_engines.base import AuditEngine
from app.audit_engines.registry import register_engine
from app.shared.context import SharedContext
from app.shared.schemas import AuditResult

__all__ = ["ReadabilityAuditEngine"]


@register_engine
class ReadabilityAuditEngine(AuditEngine):
    """Measures clarity, coherence, and document structure.

    Shared Components used (Document 2, §7.6): Deterministic Validators, LLM
    Service, Evidence Store, Confidence Estimator, Recommendation Generator,
    Prompt Templates, JSON Models.
    """

    dimension = "Readability"

    async def _execute(
        self, context: SharedContext, prior_results: Mapping[str, AuditResult]
    ) -> AuditResult:
        """Run the frozen Readability pipeline.

        Raises:
            NotImplementedError: Until Milestone 4.
        """
        raise NotImplementedError(
            "The Readability pipeline is implemented in Milestone 4 (Document 2, "
            "§7.6)."
        )
