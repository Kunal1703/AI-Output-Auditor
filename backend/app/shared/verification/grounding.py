"""Grounding Verification — Credibility's stage 6.

Document 2 §5.4 and §7.4, stage 6. Renders the frozen four-value verdict (§6.4)
for each citation against the source it points at:
**Supports / Partial / Contradicts / Unrelated**.

**This stage answers a different question from stage 4.** Stage 4 asked whether
the citation *resolves* — a deterministic URL probe. This asks whether the thing
it resolves to actually *backs the claim attached to it*. The two failures look
nothing alike and must not be confused:

* A dead URL → fabrication signal. The source does not exist.
* A live URL whose content is **Unrelated** to the claim → *misattribution*. The
  source exists and says nothing of the kind. This is the more insidious
  failure: it survives every link check and looks authoritative to a reader who
  does not follow the reference.

**Contradicts is the sharpest signal here.** A citation offered in support of a
claim that the source actually refutes is worse than no citation at all — the
reader is being pointed at evidence *against* the thing they are being told.

Verdicts are rendered against the fetched source text only. A source that could
not be fetched is not judged here at all; the engine records the fetch failure
from stage 5 and does not ask a judge to guess at absent content.
"""

from __future__ import annotations

from typing import Any

from app.shared.extraction.models import Citation
from app.shared.verification.base import LLMJudge
from app.shared.vocabularies import GroundingVerdict

__all__ = ["GroundingVerificationJudge"]


class GroundingVerificationJudge(LLMJudge[Citation, GroundingVerdict]):
    """Stage 6 — checks whether each cited source supports its mapped claims.

    Note:
        Only citations whose sources were successfully fetched reach this judge.
        Credibility filters first: judging an unfetched citation would mean
        asking the model to reason about content nobody has seen, and it would
        answer — which is how a fabricated citation could come back *Supports*.
    """

    engine = "credibility"
    stage = "grounding_verification"
    version = "v1"
    verdict_enum = GroundingVerdict
    id_attr = "citation_id"
    unit_name = "citation"
    collection_key = "verdicts"

    def _render_unit(self, unit: Citation) -> dict[str, Any]:
        """Render one citation with the claims mapped to it by stage 3.

        The mapped claims are the point of comparison: "does this source support
        *this claim*" is unanswerable without knowing which claim.
        """
        return {
            "id": unit.citation_id,
            "citation": unit.text,
            "url": unit.url,
            "supported_claims": unit.attributes.get("mapped_claim_texts", []),
        }

    def _prompt_variables(
        self, units_json: str, evidence_block: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Supply the prompt template's variables.

        ``evidence_block`` carries the fetched source content, tagged with its
        evidence ids so the judge can cite the passage it relied on — which is
        what makes a misattribution finding traceable to the sentence that
        proves it.
        """
        return {"citations": units_json, "sources": evidence_block}
