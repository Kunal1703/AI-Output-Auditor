"""Claim Verification — Accuracy's stage 6.

Document 2 §5.4 and §7.2, stage 6. Renders the frozen three-value verdict (§6.4)
for each factual claim against retrieved evidence:
**Supported / Contradicted / Unverifiable**.

**The three-way split is the whole point of this stage.** A two-way
true/false judge would be a different, worse system:

* **Supported** — the evidence backs the claim.
* **Contradicted** — the evidence says otherwise. A confident negative. Drives a
  Critical Finding and, through it, *Untrusted* (Document 3, §5).
* **Unverifiable** — the evidence does not settle it. **Not a failure.** It
  lowers confidence and heads for *Unable to Verify* (Document 3, §8).

Collapsing Unverifiable into Contradicted would turn "we could not check this"
into "this is false" — manufacturing accusations out of gaps in the evidence,
which is precisely the failure this auditor exists to prevent. Collapsing it into
Supported would be worse still: unverified content would pass as trustworthy.
The prompt is emphatic about this because the model's instinct — answering from
its own knowledge — produces exactly that error.
"""

from __future__ import annotations

from typing import Any

from app.shared.extraction.models import Claim
from app.shared.verification.base import LLMJudge
from app.shared.vocabularies import ClaimVerdict

__all__ = ["ClaimVerificationJudge"]


class ClaimVerificationJudge(LLMJudge[Claim, ClaimVerdict]):
    """Stage 6 — verifies each factual claim against retrieved evidence.

    Note:
        Judges **only against the evidence shown**, never against the model's
        own knowledge. That constraint is what makes Accuracy an auditor rather
        than a second opinion: a claim the evidence does not cover is
        *Unverifiable* even if the model happens to know it is true. The prompt
        states this repeatedly because it is the instruction models are most
        prone to ignore.
    """

    engine = "accuracy"
    stage = "claim_verification"
    version = "v1"
    verdict_enum = ClaimVerdict
    id_attr = "claim_id"
    unit_name = "claim"
    collection_key = "verdicts"

    def _render_unit(self, unit: Claim) -> dict[str, Any]:
        """Render one claim for the prompt."""
        return {"id": unit.claim_id, "claim": unit.text}

    def _prompt_variables(
        self, units_json: str, evidence_block: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Supply the prompt template's variables."""
        return {"claims": units_json, "evidence": evidence_block}
