"""Diversity's balance and bias stages — §7.8 stages 7 and 8.

Document 2 §5.4 catalogues both as LLM Verification / Judge instantiations:
*"Balance Evaluation and Bias & Loaded Language Detection (Diversity)"*.

**They measure the two ways content can be unbalanced.**
:class:`BalanceEvaluationJudge` asks whether each legitimate viewpoint is fairly
represented — a question about what the content *includes*.
:class:`BiasDetectionStage` asks whether the framing is loaded — a question about
*how* it says what it says. An output can name every viewpoint and still bury one
under a sneer, and only the second stage catches it.

**Both are judged against the stance contract**, which stage 4 established. A
declared argument that gives its opponents two sentences is doing what arguments
do; a piece claiming neutrality that does the same is misleading its reader. The
stance is passed to both stages rather than applied afterward, because it changes
what the right answer *is* rather than how the answer is scored.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import replace
from typing import Any, Sequence

from app.core.logging import bind, get_logger
from app.shared.extraction.models import Viewpoint
from app.shared.llm_stage import LLMStage, LLMStageError
from app.shared.quality_units import BiasItem
from app.shared.schemas import Severity
from app.shared.text_segmentation import locate_span
from app.shared.verification.base import Judgment, LLMJudge, VerificationError
from app.shared.vocabularies import BalanceVerdict

__all__ = ["BalanceEvaluationJudge", "BiasDetectionStage"]

logger = get_logger(__name__)


class BalanceEvaluationJudge(LLMJudge[Viewpoint, BalanceVerdict]):
    """Stage 7 — evaluates how fairly each viewpoint is represented.

    Note:
        The judge returns a ``legitimacy`` alongside each verdict, and the engine
        reads it back onto the viewpoint. That is the §5.2-shaped half of this
        stage: extraction named the viewpoints and deliberately left legitimacy
        unset, because deciding a viewpoint is fringe is both how false balance
        is avoided and how a real objection gets buried — it needs to be made
        with the balance question in view, not in passing.

        Weighting by legitimacy is what lets the score distinguish "the output
        ignored a serious objection" from "the output declined to platform a
        fringe claim". Without it, Diversity would reward giving equal room to
        anything anyone has ever said, which is false balance by construction and
        the failure §7.8 exists to avoid.
    """

    engine = "diversity"
    stage = "balance_evaluation"
    version = "v1"
    verdict_enum = BalanceVerdict
    id_attr = "viewpoint_id"
    unit_name = "viewpoint"
    collection_key = "verdicts"

    def _render_unit(self, unit: Viewpoint) -> dict[str, Any]:
        """Render one viewpoint for the prompt."""
        return {
            "id": unit.viewpoint_id,
            "viewpoint": unit.text,
            "appears_in_output": unit.in_output,
        }

    def _prompt_variables(
        self, units_json: str, evidence_block: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Supply the prompt template's variables.

        Args:
            units_json: The rendered viewpoints.
            evidence_block: Unused — the output is supplied whole, since fair
                representation is a property of the document rather than of a
                retrieved fragment.
            **kwargs: Must carry ``ai_output``, ``stance``, and ``topic``.
        """
        return {
            "viewpoints": units_json,
            "ai_output": kwargs["ai_output"],
            "stance": kwargs["stance"],
            "topic": kwargs["topic"],
        }

    def _response_schema(self) -> dict[str, Any]:
        """Extend the shared judge schema with the legitimacy weighting."""
        schema = super()._response_schema()
        item = schema["properties"][self.collection_key]["items"]
        item["properties"]["legitimacy"] = {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": (
                "How well-founded this viewpoint is among informed people. A "
                "mainstream expert position is near 1.0; a fringe claim with no "
                "serious support is near 0.1. Omitting a fringe viewpoint is not "
                "a failure."
            ),
        }
        item["required"] = [*item["required"], "legitimacy"]
        return schema

    async def evaluate(
        self, viewpoints: Sequence[Viewpoint], ai_output: str, stance: str, topic: str
    ) -> tuple[Judgment[Viewpoint, BalanceVerdict], ...]:
        """Evaluate every viewpoint and attach the legitimacy it was rated at.

        The base :meth:`~app.shared.verification.base.LLMJudge.judge` reads only
        the verdict, rationale, and certainty from each record — the shape every
        judge shares. This stage's frozen output carries one field more, so it
        reuses :meth:`~app.shared.verification.base.LLMJudge.build_judgments` for
        the matching and vocabulary enforcement and reads the extra field itself.

        Args:
            viewpoints: The viewpoints to evaluate.
            ai_output: The content under audit, whole.
            stance: The rendered stance contract from §7.8 stage 4.
            topic: The question the content addresses.

        Returns:
            One judgment per viewpoint, each carrying the judge's legitimacy
            rating. A viewpoint the judge did not rate keeps ``legitimacy=None``
            — never a default, because an unrated viewpoint is one nothing is
            known about, and a default would let a fringe claim weigh on the
            score exactly as a mainstream position does.

        Raises:
            VerificationError: The prompt could not be rendered, the provider
                failed, or the response could not be parsed.
        """
        if not viewpoints:
            return ()

        units_json = json.dumps(
            [self._render_unit(v) for v in viewpoints], ensure_ascii=False, indent=2
        )
        records = await self._run_records(
            self._prompt_variables(
                units_json,
                evidence_block="",
                ai_output=ai_output,
                stance=stance,
                topic=topic,
            ),
            self._response_schema(),
        )

        judgments = self.build_judgments(viewpoints, records)
        legitimacy = self._legitimacy_by_id(records)

        rated: list[Judgment[Viewpoint, BalanceVerdict]] = []
        for judgment in judgments:
            value = legitimacy.get(judgment.unit.viewpoint_id)
            if value is None:
                rated.append(judgment)
                continue
            rated.append(
                Judgment(
                    unit=replace(judgment.unit, legitimacy=value),
                    verdict=judgment.verdict,
                    rationale=judgment.rationale,
                    evidence_refs=judgment.evidence_refs,
                    confidence_hint=judgment.confidence_hint,
                )
            )

        logger.info(
            "balance evaluation complete",
            extra=bind(
                stage=self.identifier,
                evaluated=sum(1 for j in rated if j.is_judged),
                rated=len(legitimacy),
                total=len(viewpoints),
            ),
        )
        return tuple(rated)

    @staticmethod
    def _legitimacy_by_id(records: Sequence[dict[str, Any]]) -> dict[str, float]:
        """Recover the legitimacy rating from each record, by viewpoint id."""
        ratings: dict[str, float] = {}
        for record in records:
            identifier = record.get("id")
            value = record.get("legitimacy")
            if not isinstance(identifier, str) or not identifier.strip():
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            ratings[identifier.strip()] = min(1.0, max(0.0, float(value)))
        return ratings


class BiasDetectionStage(LLMStage):
    """Stage 8 — detects biased framing and loaded language.

    Returns items rather than per-unit verdicts: there is no pre-existing list of
    phrases to rule on, and the stage's product *is* the list. It therefore
    extends :class:`~app.shared.llm_stage.LLMStage` directly, like the other
    stages in this system whose output is not one-record-per-unit.
    """

    engine = "diversity"
    stage = "bias_detection"
    version = "v1"
    collection_key = "bias_items"
    error_class: type[LLMStageError] = VerificationError

    def _response_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "bias_items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "quote": {
                                "type": "string",
                                "description": "The loaded phrasing, copied "
                                "verbatim from the output.",
                            },
                            "bias_type": {
                                "type": "string",
                                "description": "e.g. loaded language, strawman, "
                                "false balance, unattributed assertion, "
                                "asymmetric framing.",
                            },
                            "explanation": {
                                "type": "string",
                                "description": "Why this framing is loaded, and "
                                "what neutral phrasing would look like.",
                            },
                            "severity": {
                                "type": "string",
                                "enum": [s.value for s in Severity],
                            },
                        },
                        "required": ["quote", "bias_type", "explanation", "severity"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["bias_items"],
            "additionalProperties": False,
        }

    async def detect(
        self, ai_output: str, stance: str, topic: str
    ) -> tuple[BiasItem, ...]:
        """Detect biased framing in the output.

        Args:
            ai_output: The content under audit.
            stance: The stance contract stage 4 detected, rendered for the prompt.
            topic: The question the content addresses.

        Returns:
            The detected items, each located in the output where its quote could
            be found.

        Raises:
            VerificationError: The prompt could not be rendered, the provider
                failed, or the response could not be parsed.
        """
        records = await self._run_records(
            {"ai_output": ai_output, "stance": stance, "topic": topic},
            self._response_schema(),
        )

        ids = itertools.count(1)
        items: list[BiasItem] = []
        for record in records:
            quote = record.get("quote")
            explanation = record.get("explanation")
            if not isinstance(quote, str) or not quote.strip():
                continue
            if not isinstance(explanation, str) or not explanation.strip():
                # An accusation of bias with no argument behind it is not
                # something a reader can check or contest, and Document 3 §12
                # requires every conclusion to be inspectable.
                logger.warning(
                    "bias item has no explanation; dropped",
                    extra=bind(stage=self.identifier),
                )
                continue

            severity = Severity.LOW
            raw = record.get("severity")
            if isinstance(raw, str):
                try:
                    severity = Severity(raw.strip().lower())
                except ValueError:
                    severity = Severity.LOW

            items.append(
                BiasItem(
                    bias_id=f"bia_{next(ids)}",
                    text=quote.strip(),
                    bias_type=str(record.get("bias_type") or "loaded language").strip(),
                    explanation=explanation.strip(),
                    severity=severity,
                    source_span=locate_span(ai_output, quote.strip(), kind="bias"),
                )
            )

        logger.info(
            "bias detection complete",
            extra=bind(stage=self.identifier, items=len(items)),
        )
        return tuple(items)


def render_viewpoints_for_prompt(viewpoints: Sequence[Viewpoint]) -> str:
    """Render viewpoints as a readable block, for prompts that need context."""
    if not viewpoints:
        return "(none identified)"
    return "\n".join(f"- {viewpoint.text}" for viewpoint in viewpoints)
