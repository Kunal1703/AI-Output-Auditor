"""Classification & Weighting — the shared labelling component (Document 2, §5.2).

    *Assignment of type and/or importance labels to extracted units.*

Six instantiations are catalogued by the specification:

* **Relevance** — Hard / Soft Requirement Classification (§7.1, stage 3)
* **Accuracy** — Claim Classification (§7.2, stage 3) and Claim Centrality &
  Severity Assignment (stage 4)
* **Coverage** — Salience Assignment (§7.3, stage 3) and Category & Severity
  Assignment (stage 4)
* **Credibility** — Source Classification (§7.4, stage 7)
* **Readability** — Issue Classification and Severity Assignment (§7.6) —
  Milestone 4
* **Diversity** — Applicability Classification and Stance Contract Detection
  (§7.8) — Milestone 4

**Classification is a stage, not an afterthought.** Document 2 keeps it separate
from extraction (§5.1) precisely because the labels carry consequences that
extraction has no business deciding: a *Hard* requirement's violation is a
Critical Finding that gates trust; an *Opinion* claim is excluded from Accuracy's
verification entirely. Getting the label wrong changes the verdict, so it gets
its own stage, its own prompt, and its own place in the frozen pipeline.

**Batched by design.** One call labels every unit, because twenty sequential
calls would dominate the audit's latency budget (Document 4, §12) and because a
model labelling a claim can see its siblings — which is what makes centrality
("is this load-bearing *relative to the rest*?") answerable at all.

**Unmatched units stay unlabelled.** :func:`~app.shared.llm_stage.index_by`
matches the model's answers to units by id, never by position. A unit the model
skipped comes back with its label still ``None``, and the engine decides what
that means. Guessing a default here would put an invented label — and therefore
an invented verdict — into the ledger with no trace.
"""

from __future__ import annotations

import abc
import json
from typing import Any, Generic, Sequence, TypeVar

from app.core.logging import bind, get_logger
from app.shared.llm_service import LLMService
from app.shared.llm_stage import LLMStage, LLMStageError, index_by
from app.shared.prompt_manager import PromptManager

__all__ = ["LLMClassifier", "ClassificationError", "render_units"]

logger = get_logger(__name__)

UnitT = TypeVar("UnitT")


class ClassificationError(LLMStageError):
    """A classification stage could not label its units."""

    code = "classification_failed"


def render_units(
    units: Sequence[Any], id_attr: str, text_attr: str = "text", limit: int = 400
) -> str:
    """Render units as a JSON array for a classification prompt.

    JSON rather than prose numbering: the ids must survive round-tripping
    exactly, and a model reading ``{"id": "clm_3", ...}`` echoes ``clm_3`` far
    more reliably than one reading ``3. The tower...`` echoes ``3``. Since
    mismatched ids silently attach verdicts to the wrong units, cheap insurance
    is worth taking.

    Args:
        units: The units to render.
        id_attr: Attribute holding each unit's id.
        text_attr: Attribute holding each unit's text.
        limit: Per-unit character bound, so one long unit cannot crowd the
            context window.

    Returns:
        A JSON array string.
    """
    payload = []
    for unit in units:
        text = str(getattr(unit, text_attr, ""))
        payload.append(
            {
                "id": getattr(unit, id_attr),
                "text": text if len(text) <= limit else text[: limit - 1] + "…",
            }
        )
    return json.dumps(payload, ensure_ascii=False, indent=2)


class LLMClassifier(LLMStage, Generic[UnitT]):
    """Base for the Classification & Weighting instantiations of Document 2 §5.2.

    Subclasses declare their prompt, their schema, and how to apply one record's
    labels to one unit. Everything else — batching, id matching, unmatched-unit
    handling, logging — is inherited.

    Args:
        llm: The Shared LLM Service.
        prompts: The Prompt Manager.

    Attributes:
        id_attr: The unit attribute holding its id, e.g. ``"claim_id"``.
        unit_name: Human-readable unit name, for logs.
    """

    id_attr: str = "id"
    unit_name: str = "unit"
    collection_key: str = "items"
    error_class: type[LLMStageError] = ClassificationError

    def __init__(self, llm: LLMService, prompts: PromptManager) -> None:
        super().__init__(llm, prompts)

    @abc.abstractmethod
    def _response_schema(self) -> dict[str, Any]:
        """Return the JSON Schema the model's response must conform to."""

    @abc.abstractmethod
    def _prompt_variables(self, units: Sequence[UnitT], **kwargs: Any) -> dict[str, Any]:
        """Return the variables for the prompt template."""

    @abc.abstractmethod
    def _apply(self, unit: UnitT, record: dict[str, Any]) -> UnitT:
        """Return a copy of ``unit`` carrying the labels from ``record``.

        Units are frozen dataclasses, so this returns a new instance rather than
        mutating. That is deliberate: an extracted unit and a classified unit
        are different things, and a stage that mutated its input in place would
        make the pipeline's stage boundaries unverifiable after the fact.

        Args:
            unit: The unlabelled unit.
            record: The model's record for it, matched by id.

        Returns:
            The labelled unit.
        """

    async def classify(self, units: Sequence[UnitT], **kwargs: Any) -> tuple[UnitT, ...]:
        """Label every unit in one batched call.

        Args:
            units: The units to label.
            **kwargs: Extra context forwarded to :meth:`_prompt_variables`.

        Returns:
            The units in their original order. Any unit the model did not
            return a record for is passed through **unlabelled** — never
            defaulted.

        Raises:
            ClassificationError: The prompt could not be rendered, the provider
                failed, or the response could not be parsed. The calling engine
                catches this and decides what it means for its dimension.
        """
        if not units:
            return ()

        records = await self._run_records(
            self._prompt_variables(units, **kwargs), self._response_schema()
        )
        indexed = index_by(records, "id")

        labelled: list[UnitT] = []
        matched = 0
        for unit in units:
            record = indexed.get(str(getattr(unit, self.id_attr)))
            if record is None:
                labelled.append(unit)
                continue
            try:
                labelled.append(self._apply(unit, record))
                matched += 1
            except (ValueError, KeyError, TypeError) as exc:
                # A malformed label for one unit must not lose the other
                # nineteen. The unit stays unlabelled and the engine sees it.
                logger.warning(
                    "could not apply classification; unit left unlabelled",
                    extra=bind(
                        stage=self.identifier,
                        unit_id=str(getattr(unit, self.id_attr)),
                        error=type(exc).__name__,
                    ),
                )
                labelled.append(unit)

        if matched < len(units):
            logger.warning(
                "classification did not cover every unit",
                extra=bind(
                    stage=self.identifier, matched=matched, total=len(units)
                ),
            )
        logger.info(
            "classification complete",
            extra=bind(stage=self.identifier, matched=matched, total=len(units)),
        )
        return tuple(labelled)


def coerce_enum(value: Any, enum_cls: type, field: str) -> Any:
    """Parse a model-supplied string into a frozen vocabulary member.

    Case-insensitive, because a model asked for ``"Factual"`` will occasionally
    answer ``"factual"``, and rejecting a correct answer over capitalization
    would cost a claim its verification for no reason.

    Args:
        value: The model's string.
        enum_cls: The target enum.
        field: Field name, for the error message.

    Returns:
        The enum member.

    Raises:
        ValueError: The value is not in the vocabulary. The caller leaves the
            unit unlabelled — an out-of-vocabulary label is a model error, and
            silently mapping it to the nearest member would invent a judgment.
    """
    if isinstance(value, enum_cls):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field}: expected a string, got {type(value).__name__}")

    wanted = value.strip().lower()
    for member in enum_cls:
        if member.value.lower() == wanted:
            return member
    raise ValueError(
        f"{field}: {value!r} is not one of "
        f"{[m.value for m in enum_cls]}"
    )


def coerce_unit_float(value: Any, field: str) -> float:
    """Parse a model-supplied number into [0, 1].

    Clamps rather than rejects: a model asked for a 0–1 score occasionally
    answers ``1.2``, and its *intent* — "maximally central" — is unambiguous.
    Clamping preserves that; rejecting would drop a usable signal.

    Raises:
        ValueError: The value is not a number at all, which is not a
            near-miss but a category error.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field}: expected a number, got {value!r}")
    return min(1.0, max(0.0, float(value)))
