"""Engagement's two judges — stages 4 and 6.

Document 2 §5.4 catalogues both as LLM Verification / Judge instantiations:
*"Task Fitness Evaluation and Manipulation Verification (Engagement)"*. §7.7
places them at stages 4 and 6, with the deterministic pattern detection between
them.

**The two answer the engine's two halves.** Engagement asks whether content
*"effectively helps the user achieve their goal while avoiding manipulative,
sensational, or misleading communication"* (§7.7) — usefulness and integrity.
:class:`TaskFitnessJudge` measures the first against the criteria stage 2
identified; :class:`ManipulationVerificationJudge` measures the second against
the candidates stage 5 matched. Neither can substitute for the other: content can
serve the user's goal perfectly and manipulate them while doing it, and the
report has to be able to say so.
"""

from __future__ import annotations

from typing import Any

from app.shared.quality_units import ManipulationCandidate, TaskCriterion
from app.shared.verification.base import LLMJudge
from app.shared.vocabularies import ManipulationVerdict, TaskFitnessVerdict

__all__ = ["TaskFitnessJudge", "ManipulationVerificationJudge"]


class TaskFitnessJudge(LLMJudge[TaskCriterion, TaskFitnessVerdict]):
    """Stage 4 — evaluates the output against each success criterion.

    Note:
        The judge is shown the prior audit results (stage 3's reuse) as context.
        This is *reuse*, not re-measurement, and the distinction is the whole
        point of Document 2 §4's note that Engagement "reuses the results of
        other engines rather than recomputing overlapping signals". Whether the
        output was on-instruction, complete, clear, and efficient has already
        been measured by four engines. This judge is told what they found and
        asked the one question none of them answers: does the content actually
        serve the user's goal?

        It is told plainly not to re-litigate those four verdicts. A fitness
        judge that decided for itself whether the content was clear would be a
        fifth opinion on Readability's question, reached with less evidence.
    """

    engine = "engagement"
    stage = "task_fitness"
    version = "v1"
    verdict_enum = TaskFitnessVerdict
    id_attr = "criterion_id"
    unit_name = "criterion"
    collection_key = "verdicts"

    def _render_unit(self, unit: TaskCriterion) -> dict[str, Any]:
        """Render one criterion for the prompt."""
        return {
            "id": unit.criterion_id,
            "criterion": unit.text,
            "importance": round(unit.importance, 2),
        }

    def _prompt_variables(
        self, units_json: str, evidence_block: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Supply the prompt template's variables.

        Args:
            units_json: The rendered criteria.
            evidence_block: Unused — the output and the prior findings are the
                material here, and both are supplied whole.
            **kwargs: Must carry ``ai_output``, ``prompt``, ``task``, and
                ``prior_findings``.
        """
        return {
            "criteria": units_json,
            "ai_output": kwargs["ai_output"],
            "prompt": kwargs["prompt"],
            "task": kwargs["task"],
            "prior_findings": kwargs["prior_findings"],
        }


class ManipulationVerificationJudge(
    LLMJudge[ManipulationCandidate, ManipulationVerdict]
):
    """Stage 6 — decides which matched patterns actually manipulate the reader.

    Note:
        Every candidate reaching this judge matched a regex, and the judge is
        told so. Document 2 §7.7 separates detection from verification because
        the patterns are unavoidably over-inclusive: an article *about* a scam
        quotes the scam's language, a legitimate deadline is urgent, and a
        warranty that genuinely is guaranteed says "guaranteed". Each of those
        matches; none is manipulation.

        *Legitimate* is therefore the verdict that clears a false positive, and
        the prompt makes clear that reaching for it is expected rather than
        lenient. A verification stage that confirmed every candidate would be an
        expensive way to trust the regex.
    """

    engine = "engagement"
    stage = "manipulation_verification"
    version = "v1"
    verdict_enum = ManipulationVerdict
    id_attr = "candidate_id"
    unit_name = "candidate"
    collection_key = "verdicts"

    def _render_unit(self, unit: ManipulationCandidate) -> dict[str, Any]:
        """Render one matched pattern, with the surrounding text as context."""
        return {
            "id": unit.candidate_id,
            "matched_phrase": unit.text,
            "pattern_family": unit.family,
            "surrounding_text": unit.attributes.get("context", ""),
        }

    def _prompt_variables(
        self, units_json: str, evidence_block: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Supply the prompt template's variables.

        Args:
            units_json: The rendered candidates.
            evidence_block: Unused — see the class note.
            **kwargs: Must carry ``ai_output``.
        """
        return {"candidates": units_json, "ai_output": kwargs["ai_output"]}
