"""LLM Extraction — the shared decomposition component (Document 2, §5.1).

    *LLM-based decomposition of an input into atomic units of evaluation.*

Four instantiations are catalogued by the specification: Requirement Extraction
(Relevance), Claim Extraction (Accuracy), Key Point Extraction (Coverage), and
Citation Extraction (Credibility). Milestone 2 implements the first two; the
other two slot in behind this same base class in Milestone 3 by supplying a
prompt, a schema, and a unit constructor.

**What lives here.** Everything the four instantiations share and would
otherwise each reimplement — which is exactly what Document 4 §15 means by
"engines never duplicate logic":

* drop empties, merge near-duplicates, locate each unit in its source;
* report diagnostics the engine can use when setting its own confidence.

Prompt rendering, the LLM call, and response-shape tolerance are one level
further down in :class:`~app.shared.llm_stage.LLMStage`, shared with
Classification (§5.2) and Verification (§5.4) — all three components do those
same four things before they do anything specific.

**What does not live here.** Any judgment about the units. No classification
(that is §5.2 and a later engine stage), no verification, no scoring, no
confidence. The base class is a decomposition machine: text in, structured units
out, with no opinion about them.

The seam is enforced by shape, not just by convention: :meth:`_build_unit`
receives one parsed record and returns one unit, and the models it can construct
have their classification fields defaulted to ``None``. There is nowhere to put
a verdict even if you wanted to.
"""

from __future__ import annotations

import abc
import itertools
from typing import Any, Generic, Sequence, TypeVar

from app.core.logging import bind, get_logger
from app.shared.extraction.models import ExtractionResult
from app.shared.llm_service import LLMService
from app.shared.llm_stage import LLMStage, LLMStageError
from app.shared.prompt_manager import PromptManager
from app.shared.text_segmentation import TextSpan, locate_span, normalize_whitespace

__all__ = ["LLMExtractionService", "ExtractionError"]

logger = get_logger(__name__)

UnitT = TypeVar("UnitT")

#: Characters of source text handed to the model in one call. Generous enough
#: for a long article, bounded so a pathological input cannot blow the context
#: window. When it bites, ``ExtractionResult.truncated`` says so rather than the
#: service silently auditing a prefix.
DEFAULT_MAX_SOURCE_CHARS = 24_000


class ExtractionError(LLMStageError):
    """Extraction could not produce usable units.

    Inherits the ``ProviderError`` lineage of :class:`LLMStageError`, so an
    engine's existing provider-failure handling covers it: the engine catches,
    degrades, and the Decision Engine reads the gap (Document 4, §12).
    Extraction never decides what its own failure means.
    """

    code = "extraction_failed"


class LLMExtractionService(LLMStage, Generic[UnitT]):
    """Base for the four LLM Extraction instantiations of Document 2 §5.1.

    Subclasses declare where their prompt lives and how to turn one parsed
    record into one unit. Everything else is inherited.

    Args:
        llm: The Shared LLM Service. Injected — an engine never reaches a
            provider directly (Document 4, §4), and neither does this.
        prompts: The Prompt Manager. Prompts are configuration, not code
            (Document 4, §15), so nothing here contains prompt text.
        max_source_chars: Truncation bound for the source text.

    Attributes:
        engine: Prompt directory, e.g. ``"accuracy"``.
        stage: Prompt template name, e.g. ``"claim_extraction"``.
        version: Prompt version. Pinned per service so a prompt revision is a
            deliberate act — extraction output changes when the prompt changes,
            and that must not happen silently.
        unit_name: Human-readable unit name, for logs and errors.
        id_prefix: Prefix for minted unit ids, e.g. ``"clm"``.
    """

    engine: str = ""
    stage: str = ""
    version: str = "v1"
    unit_name: str = "unit"
    id_prefix: str = "unit"
    error_class: type[LLMStageError] = ExtractionError

    def __init__(
        self,
        llm: LLMService,
        prompts: PromptManager,
        max_source_chars: int = DEFAULT_MAX_SOURCE_CHARS,
    ) -> None:
        super().__init__(llm, prompts)
        self._max_source_chars = max_source_chars
        self._counter = itertools.count(1)

    # -- Subclass contract -------------------------------------------------- #

    @abc.abstractmethod
    def _response_schema(self) -> dict[str, Any]:
        """Return the JSON Schema the model's response must conform to.

        Passed to the LLM Service, which hands it to the provider where
        supported and leaves the prompt to carry it otherwise (Groq accepts
        ``json_object`` but not ``json_schema`` on most models).
        """

    @abc.abstractmethod
    def _prompt_variables(self, source: str, **kwargs: Any) -> dict[str, Any]:
        """Return the variables for the prompt template.

        Args:
            source: The (possibly truncated) source text.
            **kwargs: Extra context the caller supplied.
        """

    @abc.abstractmethod
    def _build_unit(self, record: dict[str, Any], unit_id: str, span: TextSpan | None) -> UnitT:
        """Turn one validated record into one unit.

        Args:
            record: A validated record from the model's response.
            unit_id: The minted id.
            span: Where the unit was located in its source, or ``None``.

        Returns:
            The constructed unit, with every classification field left unset.
        """

    def _unit_text(self, record: dict[str, Any]) -> str:
        """Extract the unit's text from a record. Override for a different key."""
        value = record.get("text", "")
        return value.strip() if isinstance(value, str) else ""

    def _locate_text(self, record: dict[str, Any]) -> str:
        """Return the text to search for when locating this unit in its source.

        Defaults to the unit's own text, which is right when the unit *is* a
        substring of the source — a claim is usually close to the sentence it
        came from.

        It is wrong for units that are restatements. A requirement extracted
        from "Please keep it under 200 words" reads "The response must not
        exceed 200 words", which appears nowhere in the prompt. Those services
        override this to return the model's verbatim quote instead, so the span
        points at the words that actually imposed the requirement rather than at
        nothing.
        """
        return self._unit_text(record)

    # -- Shared machinery --------------------------------------------------- #

    def _next_id(self) -> str:
        return f"{self.id_prefix}_{next(self._counter)}"

    @property
    def collection_key(self) -> str:  # type: ignore[override]
        """The key the prompt asks the model to wrap its list in."""
        return f"{self.unit_name.lower().replace(' ', '_')}s"

    @staticmethod
    def _dedupe_key(text: str) -> str:
        """Normalize a unit's text for near-duplicate detection.

        Case- and whitespace-insensitive, with trailing punctuation dropped.
        Models restate the same claim with different punctuation surprisingly
        often; letting both through would double-count it in a ledger and skew
        every rate computed from it.
        """
        return normalize_whitespace(text).lower().rstrip(".!?;:,")

    async def extract(self, source: str, **kwargs: Any) -> ExtractionResult[UnitT]:
        """Decompose ``source`` into atomic units.

        The template method every instantiation shares. Returns units and
        diagnostics; interprets neither.

        Args:
            source: The text to decompose — the Prompt for requirements, the AI
                Output for claims, the Reference Source for key points.
            **kwargs: Extra context forwarded to :meth:`_prompt_variables`.

        Returns:
            The extracted units and the diagnostics of how extraction went. An
            empty or whitespace-only source yields an empty result rather than a
            model call.

        Raises:
            ExtractionError: The prompt could not be rendered, the provider
                failed, or the response could not be parsed. The calling engine
                catches this and degrades (Document 4, §12); extraction does not
                decide what its own failure means.
        """
        if not source or not source.strip():
            return ExtractionResult.empty()

        truncated = len(source) > self._max_source_chars
        text = source[: self._max_source_chars] if truncated else source
        if truncated:
            logger.warning(
                "source truncated for extraction",
                extra=bind(
                    unit=self.unit_name,
                    original_chars=len(source),
                    kept_chars=len(text),
                ),
            )

        records = await self._run_records(
            self._prompt_variables(text, **kwargs), self._response_schema()
        )

        units: list[UnitT] = []
        seen: set[str] = set()
        duplicates = 0
        located = 0

        for record in records:
            unit_text = self._unit_text(record)
            if not unit_text:
                continue

            key = self._dedupe_key(unit_text)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)

            span = locate_span(
                source,
                self._locate_text(record),
                kind=self._span_kind(),
                index=len(units),
            )
            if span is not None:
                located += 1

            units.append(self._build_unit(record, self._next_id(), span))

        result = ExtractionResult(
            units=tuple(units),
            source_characters=len(source),
            located_count=located,
            duplicate_count=duplicates,
            truncated=truncated,
            raw_unit_count=len(records),
        )
        logger.info(
            "extraction complete",
            extra=bind(
                unit=self.unit_name,
                extracted=len(units),
                raw=len(records),
                duplicates=duplicates,
                location_rate=round(result.location_rate, 3),
                truncated=truncated,
            ),
        )
        return result

    def _span_kind(self) -> str:
        """The ``TextSpan.kind`` recorded for located units."""
        return self.unit_name.lower().replace(" ", "_")

    @staticmethod
    def _order_by_span(units: Sequence[Any]) -> tuple[Any, ...]:
        """Sort units by source position, keeping unlocated ones at the end.

        Source order makes a ledger readable — a reviewer works through the
        document top to bottom, and a ledger that jumps around fights them.
        """
        located = [u for u in units if getattr(u, "source_span", None) is not None]
        unlocated = [u for u in units if getattr(u, "source_span", None) is None]
        located.sort(key=lambda u: u.source_span.start)
        return tuple([*located, *unlocated])
