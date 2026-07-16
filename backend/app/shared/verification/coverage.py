"""Coverage Verification — Coverage's stage 5.

Document 2 §5.4 and §7.3, stage 5. Renders the frozen three-value verdict (§6.4)
for each key point against the AI Output:
**Present / Partial / Absent**.

**Partial is what keeps Coverage fair.** The engine's purpose is completeness
*"without over-penalizing summarization"* (§7.3), and a summary compresses by
design. A key point stated briefly, or folded into a broader sentence, is
*Partial* — covered, if not in full. Forcing that into Present or Absent would
make the engine either blind to real compression loss or hostile to summarizing
at all.

**Semantically, not literally.** A key point is *Present* when the output
conveys it, whatever words it uses. Coverage asks whether the information
survived, not whether the phrasing was copied — a paraphrase is a good summary,
not a gap.
"""

from __future__ import annotations

from typing import Any

from app.shared.extraction.models import KeyPoint
from app.shared.verification.base import LLMJudge
from app.shared.vocabularies import CoverageVerdict

__all__ = ["CoverageVerificationJudge"]


class CoverageVerificationJudge(LLMJudge[KeyPoint, CoverageVerdict]):
    """Stage 5 — checks each key point's presence in the AI Output.

    Note:
        The AI Output is passed as the ``ai_output`` prompt variable rather than
        as evidence items. It is the *thing being checked against*, not support
        for a conclusion — and the judge needs it whole, because a key point can
        be conveyed across several sentences that no single retrieved passage
        would contain.
    """

    engine = "coverage"
    stage = "coverage_verification"
    version = "v1"
    verdict_enum = CoverageVerdict
    id_attr = "key_point_id"
    unit_name = "key point"
    collection_key = "verdicts"

    def _render_unit(self, unit: KeyPoint) -> dict[str, Any]:
        """Render one key point for the prompt."""
        return {"id": unit.key_point_id, "key_point": unit.text}

    def _prompt_variables(
        self, units_json: str, evidence_block: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Supply the prompt template's variables.

        Args:
            units_json: The rendered key points.
            evidence_block: Unused here — see the class note.
            **kwargs: Must carry ``ai_output``.
        """
        return {"key_points": units_json, "ai_output": kwargs["ai_output"]}
