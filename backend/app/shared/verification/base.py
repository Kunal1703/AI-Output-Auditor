"""LLM Verification / Judge — the shared per-unit verdict component (§5.4).

    *LLM-based rendering of a per-unit verdict against evidence or criteria.*

Eight instantiations are catalogued (Document 2, §5.4). Milestone 3 implements
the four belonging to the Trust and Hybrid engines:

* **Relevance** — Per-Requirement Evaluation (§7.1, stage 4)
* **Accuracy** — Claim Verification → Supported / Contradicted / Unverifiable
  (§7.2, stage 6)
* **Coverage** — Coverage Verification → Present / Partial / Absent (§7.3,
  stage 5)
* **Credibility** — Grounding Verification → Supports / Partial / Contradicts /
  Unrelated (§7.4, stage 6)

**This is where the auditor's judgment actually happens**, and three properties
of this base class exist to keep it honest.

*A verdict must come with a rationale.* Document 3 §13 requires every decision to
be reconstructable, and for an LLM judgment the rationale **is** the support.
A verdict with no stated reason cannot be reviewed, argued with, or trusted — so
the schema demands one and the engine records it as evidence.

*A judge may only return its own vocabulary.* Verdict sets are frozen (§6.4) and
each value has downstream consequences: *Contradicted* drives a Critical Finding
toward *Untrusted*, *Unverifiable* drives confidence down toward *Unable to
Verify*. An out-of-vocabulary answer is rejected rather than mapped to the
nearest member — guessing what the model meant would be inventing a verdict.

*An unjudged unit stays unjudged.* Verdicts are matched to units by id, never by
position, and a unit the model skipped comes back without one. The engine decides
what that means. This matters more here than anywhere else in the pipeline:
positional matching against a model that dropped one entry would shift every
subsequent verdict by one, labelling an innocuous claim *Contradicted* and a
hallucinated one *Supported*, with nothing in the output to reveal it.
"""

from __future__ import annotations

import abc
import json
from dataclasses import dataclass, field
from typing import Any, Generic, Sequence, TypeVar

from app.core.logging import bind, get_logger
from app.shared.llm_service import LLMService
from app.shared.llm_stage import LLMStage, LLMStageError, index_by
from app.shared.prompt_manager import PromptManager
from app.shared.schemas import EvidenceItem
from app.shared.evidence_pipeline import format_for_prompt

__all__ = ["LLMJudge", "VerificationError", "Judgment"]

logger = get_logger(__name__)

UnitT = TypeVar("UnitT")
VerdictT = TypeVar("VerdictT")


class VerificationError(LLMStageError):
    """A verification stage could not render its verdicts."""

    code = "verification_failed"


@dataclass(frozen=True)
class Judgment(Generic[UnitT, VerdictT]):
    """One unit's verdict, with the reasoning behind it.

    Attributes:
        unit: The unit judged.
        verdict: The verdict, from the stage's frozen vocabulary. ``None`` when
            the model returned nothing for this unit, or returned something
            outside the vocabulary — the engine must treat that as *unjudged*,
            not as any particular outcome.
        rationale: Why. Recorded as evidence so the verdict is reconstructable
            (Document 3, §13).
        evidence_refs: Ids of the evidence the judge was shown and cited.
        confidence_hint: The judge's own stated certainty in [0, 1], when it
            gave one. A *hint*, not the dimension's confidence — Document 2
            §5.10 makes confidence estimation its own component, and this is one
            input among several the engine weighs there.
    """

    unit: UnitT
    verdict: VerdictT | None
    rationale: str = ""
    evidence_refs: tuple[str, ...] = ()
    confidence_hint: float | None = None

    @property
    def is_judged(self) -> bool:
        """Whether a verdict was actually rendered for this unit."""
        return self.verdict is not None


class LLMJudge(LLMStage, Generic[UnitT, VerdictT]):
    """Base for the LLM Verification instantiations of Document 2 §5.4.

    Subclasses declare their vocabulary, their prompt, and how to render a unit.
    Batching, id matching, vocabulary enforcement, and unjudged-unit handling are
    inherited.

    Args:
        llm: The Shared LLM Service.
        prompts: The Prompt Manager.

    Attributes:
        verdict_enum: The frozen vocabulary this judge may return.
        id_attr: The unit attribute holding its id.
        unit_name: Human-readable unit name, for logs.
    """

    verdict_enum: type[Any] = object
    id_attr: str = "id"
    unit_name: str = "unit"
    collection_key: str = "verdicts"
    error_class: type[LLMStageError] = VerificationError

    def __init__(self, llm: LLMService, prompts: PromptManager) -> None:
        super().__init__(llm, prompts)

    @abc.abstractmethod
    def _render_unit(self, unit: UnitT) -> dict[str, Any]:
        """Render one unit as a JSON-ready record for the prompt.

        Must include an ``id`` key matching the unit's id attribute.
        """

    @abc.abstractmethod
    def _prompt_variables(
        self, units_json: str, evidence_block: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Return the variables for the prompt template.

        Args:
            units_json: The rendered units.
            evidence_block: The rendered evidence, from
                :func:`~app.shared.evidence_pipeline.format_for_prompt`.
            **kwargs: Extra context the caller supplied.
        """

    def _response_schema(self) -> dict[str, Any]:
        """The JSON Schema every judge's response shares.

        Uniform across the four instantiations: only the ``verdict`` enum
        differs, and it is read from :attr:`verdict_enum`. That is what makes
        adding Coverage's judge a prompt rather than another schema.
        """
        return {
            "type": "object",
            "properties": {
                self.collection_key: {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "verdict": {
                                "type": "string",
                                "enum": [v.value for v in self.verdict_enum],
                            },
                            "rationale": {
                                "type": "string",
                                "description": "Why this verdict, citing the "
                                "evidence ids you relied on.",
                            },
                            "evidence_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Evidence ids that support the "
                                "verdict.",
                            },
                            "confidence": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                            },
                        },
                        "required": ["id", "verdict", "rationale"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": [self.collection_key],
            "additionalProperties": False,
        }

    def _coerce_verdict(self, value: Any) -> VerdictT | None:
        """Parse a verdict string into the frozen vocabulary.

        Returns ``None`` for anything outside it. Case-insensitive, because a
        model asked for ``"Supported"`` will occasionally answer ``"supported"``
        and rejecting that would cost a claim its verification for nothing.
        But a genuinely unrecognized value is **not** mapped to the nearest
        member — the unit is left unjudged instead, because inventing a verdict
        the model did not render is exactly how a hallucination gets marked
        *Supported*.
        """
        if not isinstance(value, str):
            return None
        wanted = value.strip().lower()
        for member in self.verdict_enum:
            if member.value.lower() == wanted:
                return member  # type: ignore[return-value]
        return None

    async def judge(
        self,
        units: Sequence[UnitT],
        evidence: Sequence[EvidenceItem] = (),
        **kwargs: Any,
    ) -> tuple[Judgment[UnitT, VerdictT], ...]:
        """Render a verdict for every unit in one batched call.

        Args:
            units: The units to judge.
            evidence: Evidence to judge against, rendered into the prompt with
                its ids so the model can cite what it relied on.
            **kwargs: Extra context forwarded to :meth:`_prompt_variables`.

        Returns:
            One :class:`Judgment` per unit, in the original order. A unit the
            model skipped, or answered outside the vocabulary, comes back with
            ``verdict=None`` — never a default.

        Raises:
            VerificationError: The prompt could not be rendered, the provider
                failed, or the response could not be parsed. The engine catches
                and decides what it means for its dimension.
        """
        if not units:
            return ()

        units_json = json.dumps(
            [self._render_unit(unit) for unit in units], ensure_ascii=False, indent=2
        )
        evidence_block = format_for_prompt(evidence)

        records = await self._run_records(
            self._prompt_variables(units_json, evidence_block, **kwargs),
            self._response_schema(),
        )
        # A judge may cite only evidence it was actually shown. Passing the shown
        # ids lets build_judgments drop anything the model invented — a model
        # handed no evidence (Relevance's requirement eval) will otherwise return
        # quote text in evidence_ids, which then rides into a finding's
        # evidence_refs and fails the AuditResult contract, degrading the whole
        # dimension. An empty set here means "cite nothing", which is correct.
        return self.build_judgments(
            units, records, valid_evidence_ids={e.evidence_id for e in evidence}
        )

    def build_judgments(
        self,
        units: Sequence[UnitT],
        records: Sequence[dict[str, Any]],
        valid_evidence_ids: set[str] | None = None,
    ) -> tuple[Judgment[UnitT, VerdictT], ...]:
        """Match the model's records to units by id and build the judgments.

        Split out of :meth:`judge` so a stage whose frozen output is *more than*
        a verdict per unit can reuse the matching, vocabulary enforcement, and
        unjudged-unit handling rather than reimplement them. Readability's stage
        3 is the case: Document 2 §7.6 has it review Clarity, Coherence, and
        Structure *and* surface the issues behind those verdicts, in one pass.

        Args:
            units: The units judged, in their original order.
            records: The model's records, each keyed by an ``id``.
            valid_evidence_ids: The ids the judge was shown. When provided,
                model-cited evidence ids outside this set are dropped, so a
                hallucinated id never reaches a finding's ``evidence_refs``.
                ``None`` disables the check for callers that supply no evidence.

        Returns:
            One :class:`Judgment` per unit, in the original order.
        """
        indexed = index_by(records, "id")

        judgments: list[Judgment[UnitT, VerdictT]] = []
        judged = 0
        for unit in units:
            record = indexed.get(str(getattr(unit, self.id_attr)))
            if record is None:
                judgments.append(Judgment(unit=unit, verdict=None))
                continue

            verdict = self._coerce_verdict(record.get("verdict"))
            if verdict is None:
                logger.warning(
                    "judge returned an out-of-vocabulary verdict; unit left unjudged",
                    extra=bind(
                        stage=self.identifier,
                        unit_id=str(getattr(unit, self.id_attr)),
                        returned=str(record.get("verdict"))[:40],
                    ),
                )
                judgments.append(Judgment(unit=unit, verdict=None))
                continue

            rationale = record.get("rationale")
            refs = record.get("evidence_ids")
            hint = record.get("confidence")

            # Keep only ids the judge was actually shown. ``None`` disables the
            # check for direct callers that pass no evidence set (Readability,
            # Diversity), preserving their existing behavior; the four verdict
            # judges always pass one, so a model-invented id — an id absent from
            # the evidence, or worse, a raw quote — never reaches a finding's
            # evidence_refs and never fails the AuditResult contract.
            clean_refs = tuple(
                r
                for r in (refs or [])
                if isinstance(r, str)
                and r.strip()
                and (valid_evidence_ids is None or r in valid_evidence_ids)
            )

            judgments.append(
                Judgment(
                    unit=unit,
                    verdict=verdict,
                    rationale=rationale.strip() if isinstance(rationale, str) else "",
                    evidence_refs=clean_refs,
                    confidence_hint=(
                        min(1.0, max(0.0, float(hint)))
                        if isinstance(hint, (int, float)) and not isinstance(hint, bool)
                        else None
                    ),
                )
            )
            judged += 1

        if judged < len(units):
            logger.warning(
                "verification did not cover every unit",
                extra=bind(stage=self.identifier, judged=judged, total=len(units)),
            )
        logger.info(
            "verification complete",
            extra=bind(stage=self.identifier, judged=judged, total=len(units)),
        )
        return tuple(judgments)
