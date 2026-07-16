"""Per-Requirement Evaluation — Relevance's stage 4.

Document 2 §5.4 and §7.1, stage 4. Renders a verdict for each requirement
against the AI Output.

**The vocabulary here is not frozen.** Document 2 §6.3 specifies Relevance's
ledger as "Per-requirement evaluation (Hard / Soft classified)" but fixes no
verdict set, unlike Accuracy's or Coverage's. :class:`RequirementVerdict` —
Satisfied / Partially Satisfied / Violated — is this implementation's choice and
is documented as an assumption in :mod:`app.shared.vocabularies`.

**Why the middle value earns its place.** A requirement can be addressed but
incompletely: asked for five examples, given three. With only Satisfied and
Violated, that has to be called *Violated* — and if the requirement was
classified **Hard**, Relevance would raise a Critical Finding and gate the whole
audit to *Untrusted* over content that merely under-delivered. The middle value
is what stops a shortfall from being reported as a breach.

**Deterministic first.** Requirements that stage 3 rendered into a machine-
checkable constraint ("max_words: 200") are answered by the validators at
stage 7, not here — a word count is a fact and no judge improves on it
(Document 4, §11). This judge takes the requirements that genuinely need reading
comprehension.
"""

from __future__ import annotations

from typing import Any

from app.shared.extraction.models import Requirement
from app.shared.verification.base import LLMJudge
from app.shared.vocabularies import RequirementVerdict

__all__ = ["RequirementEvaluationJudge"]


class RequirementEvaluationJudge(LLMJudge[Requirement, RequirementVerdict]):
    """Stage 4 — evaluates each requirement against the AI Output.

    Note:
        The requirement's Hard/Soft type is deliberately **not** shown to the
        judge. Whether an instruction was followed is a question about the text;
        telling the model the answer is trust-blocking invites it to soften a
        genuine violation to avoid the consequence. Stage 3 decides the stakes,
        this stage decides the facts, and keeping them apart is what stops the
        stakes from bending the facts.
    """

    engine = "relevance"
    stage = "requirement_evaluation"
    version = "v1"
    verdict_enum = RequirementVerdict
    id_attr = "requirement_id"
    unit_name = "requirement"
    collection_key = "verdicts"

    def _render_unit(self, unit: Requirement) -> dict[str, Any]:
        """Render one requirement for the prompt, without its Hard/Soft type."""
        return {"id": unit.requirement_id, "requirement": unit.text}

    def _prompt_variables(
        self, units_json: str, evidence_block: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Supply the prompt template's variables.

        Args:
            units_json: The rendered requirements.
            evidence_block: Unused — the output is passed whole, since a
                requirement can be satisfied across the document rather than in
                one retrievable passage.
            **kwargs: Must carry ``ai_output``.
        """
        return {"requirements": units_json, "ai_output": kwargs["ai_output"]}
