"""Functional Repetition Review — Novelty's stage 6.

Document 2 §5.4 catalogues this as an LLM Verification / Judge instantiation:
*"Functional Repetition Review (Novelty)"*. §7.5 places it at stage 6, after the
embedding stages have found candidates and before the Coverage Cross-check.

**The stage exists because similarity is not redundancy.** Stages 3–5 measure how
alike two segments are; that is arithmetic, and arithmetic cannot tell a padded
restatement from a summary line that closes an argument. Both score 0.9 against
the sentence they echo. Only a reader-like judgment can say which one the
document needs, and this is that judgment.

**The vocabulary is frozen** (Document 2, §6.3): *Redundant candidate* or
*Functional repetition*. The second value is the one that matters — Novelty's
purpose is efficiency *"while preserving important content"* (§7.5), and an
engine that could only say "duplicate" would tell every writer to delete their
conclusions.

**Two values, and the question they answer is "should this be cut?"** That
framing matters at the margin. The candidate threshold is set where measurement
shows real restatement begins (~0.60 raw cosine), which necessarily admits some
pairs that merely share a topic and restate nothing. The frozen vocabulary has no
third value for "not repetition at all", so those resolve to *Functional
repetition*: nothing should be cut, and that is precisely what the verdict means
for the score. The prompt says so explicitly rather than leaving the judge to
force a non-repetition into the redundant bucket.
"""

from __future__ import annotations

from typing import Any

from app.shared.quality_units import RedundancyCandidate
from app.shared.verification.base import LLMJudge
from app.shared.vocabularies import RedundancyVerdict

__all__ = ["FunctionalRepetitionJudge"]


class FunctionalRepetitionJudge(LLMJudge[RedundancyCandidate, RedundancyVerdict]):
    """Stage 6 — decides whether each repetition serves the reader.

    Note:
        Each candidate is rendered with *both* segments and their measured
        similarity. The judge cannot answer from the later segment alone: the
        question is whether this text adds anything over the earlier text, and
        that is not a property of either one by itself.

        The similarity score is shown as context, not as a verdict. A pair at
        0.95 that a reader needs twice is Functional repetition, and the judge is
        told so plainly — otherwise a high number reads as an instruction.
    """

    engine = "novelty"
    stage = "functional_repetition"
    version = "v1"
    verdict_enum = RedundancyVerdict
    id_attr = "candidate_id"
    unit_name = "candidate"
    collection_key = "verdicts"

    def _render_unit(self, unit: RedundancyCandidate) -> dict[str, Any]:
        """Render one candidate pair for the prompt."""
        return {
            "id": unit.candidate_id,
            "earlier_text": unit.earlier.text,
            "later_text": unit.segment.text,
            "similarity": round(unit.similarity, 3),
            "literal_duplicate": unit.is_literal,
        }

    def _prompt_variables(
        self, units_json: str, evidence_block: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Supply the prompt template's variables.

        Args:
            units_json: The rendered candidate pairs.
            evidence_block: Unused — the candidates carry their own text, and
                the document as a whole is supplied separately so the judge can
                see where each pair sits in the argument.
            **kwargs: Must carry ``ai_output``.
        """
        return {"candidates": units_json, "ai_output": kwargs["ai_output"]}
