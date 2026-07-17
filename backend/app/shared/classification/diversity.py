"""Diversity's applicability and stance stages — §7.8 stages 2 and 4.

Document 2 §5.2 catalogues both as Classification & Weighting instantiations:
*"Applicability Classification and Stance Contract Detection (Diversity)"*.

**Their unit is the document itself**, not a list of extracted units, so they
extend :class:`~app.shared.llm_stage.LLMStage` directly rather than
:class:`~app.shared.classification.base.LLMClassifier` — that base answers "one
record per unit", and these answer one question about one text. The catalogue
entry describes what the stage *does* (assign a label), not the shape of the call.

**They stay two stages because the frozen pipeline branches between them.**
Applicability is stage 2; the branch is stage 3; stance detection is stage 4, on
the Yes path only. Merging them into one call would run stance detection on
content the engine is about to decline to score — wasted, and it would blur the
one branch in the pipeline that decides whether anything else happens at all.

**Applicability is the most consequential judgment in this engine**, and it is
consequential in a direction that is easy to get backwards. Answering *No* on
content that genuinely needed balance hides a real failure. Answering *Yes* on
settled factual content demands the output manufacture a controversy that does
not exist — and then marks it down for declining. §7.8 names avoiding false
balance as the engine's purpose, so the second error is the one the prompt works
hardest against.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import bind, get_logger
from app.shared.classification.base import coerce_enum
from app.shared.llm_stage import LLMStage, LLMStageError
from app.shared.vocabularies import StanceContract

__all__ = [
    "ApplicabilityClassifier",
    "StanceContractDetector",
    "ApplicabilityDecision",
    "StanceDecision",
    "DiversityClassificationError",
]

logger = get_logger(__name__)


class DiversityClassificationError(LLMStageError):
    """An applicability or stance stage could not reach a decision."""

    code = "diversity_classification_failed"


class ApplicabilityDecision:
    """Stage 2's answer: does perspective balance apply to this content?

    Attributes:
        applicable: Whether the dimension applies.
        reason: Why. Required either way — Document 3 §9 surfaces this verbatim
            in the report so that every exclusion is auditable, and an
            unexplained N/A is indistinguishable from an engine that gave up.
        topic: What question the content addresses, for the later stages.
    """

    def __init__(self, applicable: bool, reason: str, topic: str = "") -> None:
        self.applicable = applicable
        self.reason = reason
        self.topic = topic


class StanceDecision:
    """Stage 4's answer: does the output present itself as neutral or as advocacy?

    Document 2 §3 defines the Stance Contract as *"whether the AI Output presents
    itself as neutral/objective or as declared advocacy"* — a binary, and this
    carries exactly that plus its reason.

    **There is deliberately no separate "does it disclose?" field.** *Declared*
    Advocacy means the advocacy is declared; the disclosure is what the label
    says. An earlier draft carried a `discloses` flag alongside the stance and it
    was incoherent in both directions: paired with `Declared Advocacy` it was a
    contradiction that could never fire, and paired with `Neutral` it would have
    penalized every encyclopedia article that fails to announce its own
    neutrality — which is all of them.

    The failure it was meant to catch — content that argues a position while
    posing as a neutral survey — is caught properly by the stance label alone.
    Such content presents itself as neutral, so it is *Neutral* here, so the
    balance evaluation holds it to the strict standard and the imbalance it was
    hiding is exactly what shows up. See ``_BALANCE_CREDIT`` in the engine.

    Attributes:
        stance: The detected contract.
        reason: What in the output establishes it. Surfaced in the ledger, so a
            reader can check which standard was applied and why.
    """

    def __init__(self, stance: StanceContract, reason: str) -> None:
        self.stance = stance
        self.reason = reason


class ApplicabilityClassifier(LLMStage):
    """Stage 2 — decides whether perspective balance applies at all.

    The gate on the whole engine. A *No* terminates the pipeline and returns
    ``N/A`` (§7.8 stage 3), which the Decision Engine then excludes from the
    Quality Verdict entirely — removed from numerator and denominator, never
    scored zero (Document 3, §9).
    """

    engine = "diversity"
    stage = "applicability_classification"
    version = "v1"
    error_class: type[LLMStageError] = DiversityClassificationError

    def _response_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "applicable": {
                    "type": "boolean",
                    "description": "True only when the content addresses a "
                    "question on which informed people legitimately differ.",
                },
                "reason": {
                    "type": "string",
                    "description": "Why the dimension does or does not apply, in "
                    "one or two sentences.",
                },
                "topic": {
                    "type": "string",
                    "description": "The question the content addresses.",
                },
            },
            "required": ["applicable", "reason"],
            "additionalProperties": False,
        }

    async def classify_applicability(
        self, prompt: str, ai_output: str
    ) -> ApplicabilityDecision:
        """Decide whether Diversity applies to this content.

        Args:
            prompt: The user's instruction. May be empty.
            ai_output: The content under audit.

        Returns:
            The decision, always carrying a reason.

        Raises:
            DiversityClassificationError: The prompt could not be rendered, the
                provider failed, or the response could not be parsed.
        """
        payload = await self._invoke(
            {"prompt": prompt or "(no prompt was supplied)", "ai_output": ai_output},
            self._response_schema(),
        )
        if not isinstance(payload, dict) or "applicable" not in payload:
            raise self.error_class(
                f"{self.identifier} returned no applicability decision."
            )

        reason = str(payload.get("reason") or "").strip()
        if not reason:
            raise self.error_class(
                f"{self.identifier} returned an applicability decision with no "
                "reason. Document 3 §9 requires every exclusion to be auditable."
            )

        decision = ApplicabilityDecision(
            applicable=bool(payload["applicable"]),
            reason=reason,
            topic=str(payload.get("topic") or "").strip(),
        )
        logger.info(
            "diversity applicability decided",
            extra=bind(stage=self.identifier, applicable=decision.applicable),
        )
        return decision


class StanceContractDetector(LLMStage):
    """Stage 4 — detects whether the output claims neutrality or declares advocacy.

    Runs only on the Applicable=Yes branch. It sets the standard the balance
    evaluation judges against: a declared argument is not required to give equal
    room to the other side, but it must not misrepresent it and must not pose as
    a neutral survey.
    """

    engine = "diversity"
    stage = "stance_contract"
    version = "v1"
    error_class: type[LLMStageError] = DiversityClassificationError

    def _response_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "stance": {
                    "type": "string",
                    "enum": [s.value for s in StanceContract],
                    "description": "How the output presents itself.",
                },
                "reason": {
                    "type": "string",
                    "description": "What in the output establishes the stance.",
                },
            },
            "required": ["stance", "reason"],
            "additionalProperties": False,
        }

    async def detect(self, prompt: str, ai_output: str) -> StanceDecision:
        """Detect the output's stance contract.

        Args:
            prompt: The user's instruction. May be empty.
            ai_output: The content under audit.

        Returns:
            The detected stance. Falls back to ``NEUTRAL`` when the model answers
            outside the vocabulary — the stricter standard, so an unparseable
            answer cannot buy an output the latitude an argument earns by
            declaring itself.

        Raises:
            DiversityClassificationError: The prompt could not be rendered, the
                provider failed, or the response could not be parsed.
        """
        payload = await self._invoke(
            {"prompt": prompt or "(no prompt was supplied)", "ai_output": ai_output},
            self._response_schema(),
        )
        if not isinstance(payload, dict):
            raise self.error_class(
                f"{self.identifier} returned {type(payload).__name__}, expected an "
                "object describing the stance."
            )

        try:
            stance = coerce_enum(payload.get("stance"), StanceContract, "stance")
        except ValueError:
            logger.warning(
                "stance detector returned an out-of-vocabulary value; "
                "defaulting to Neutral, the stricter standard",
                extra=bind(stage=self.identifier, returned=str(payload.get("stance"))[:40]),
            )
            stance = StanceContract.NEUTRAL

        decision = StanceDecision(
            stance=stance, reason=str(payload.get("reason") or "").strip()
        )
        logger.info(
            "diversity stance detected",
            extra=bind(stage=self.identifier, stance=stance.value),
        )
        return decision
