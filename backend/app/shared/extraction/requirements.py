"""Requirement Extraction — the Prompt decomposed into atomic requirements.

Document 2 §5.1: *"Requirement Extraction (Relevance) — extracts requirements
from the Prompt."* Consumed by Relevance at its stage 2, "LLM-based Requirement
Extraction" (§7.1).

**It extracts. It does not classify.** Relevance's stage 3 — "Hard / Soft
Requirement Classification" — is a separate frozen stage backed by a separate
shared component (§5.2). So every :class:`Requirement` this service returns has
``requirement_type=None``.

That restraint matters more than it looks. A violated **hard** requirement is a
Critical Finding that gates trust non-compensatorily (Document 3, §5); a missed
**soft** one is a quality signal that cannot. Deciding which is which during
extraction would move a trust gate into a stage the specification never gave one
— and would do it invisibly, inside a prompt.
"""

from __future__ import annotations

from typing import Any

from app.shared.extraction.base import LLMExtractionService
from app.shared.extraction.models import ExtractionResult, Requirement
from app.shared.text_segmentation import SegmentKind, TextSpan

__all__ = ["RequirementExtractionService"]


class RequirementExtractionService(LLMExtractionService[Requirement]):
    """Decomposes a Prompt into atomic, independently checkable requirements.

    Args:
        llm: The Shared LLM Service.
        prompts: The Prompt Manager.
        max_source_chars: Truncation bound for the prompt text.

    Example:
        Relevance's stage 2, in Milestone 3::

            result = await requirement_extraction.extract(context.prompt)
            # result.units -> Requirement objects, requirement_type still None
            # stage 3 then classifies each one Hard or Soft
    """

    engine = "relevance"
    stage = "requirement_extraction"
    version = "v1"
    unit_name = "requirement"
    id_prefix = "req"

    def _response_schema(self) -> dict[str, Any]:
        """The JSON Schema the model's response must conform to."""
        return {
            "type": "object",
            "properties": {
                "requirements": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "One atomic requirement, stated "
                                "as an instruction.",
                            },
                            "quote": {
                                "type": "string",
                                "description": "The exact words of the prompt "
                                "that impose it, verbatim.",
                            },
                        },
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["requirements"],
            "additionalProperties": False,
        }

    def _prompt_variables(self, source: str, **kwargs: Any) -> dict[str, Any]:
        """Supply the prompt template's variables."""
        return {"prompt_text": source}

    def _locate_text(self, record: dict[str, Any]) -> str:
        """Locate a requirement by the model's verbatim quote, not its text.

        A requirement is a *restatement* of an instruction — "The response must
        not exceed 200 words" appears nowhere in a prompt that said "keep it
        short". Searching for the restatement would find nothing and every
        requirement would come back unlocated. The ``quote`` field carries the
        words that actually imposed it, so that is what gets located.

        Falls back to the requirement text when the model omitted a quote, which
        at least succeeds for requirements stated verbatim.
        """
        quote = record.get("quote")
        if isinstance(quote, str) and quote.strip():
            return quote.strip()
        return self._unit_text(record)

    def _build_unit(
        self, record: dict[str, Any], unit_id: str, span: TextSpan | None
    ) -> Requirement:
        """Construct one requirement, leaving classification to stage 3."""
        return Requirement(
            requirement_id=unit_id,
            text=self._unit_text(record),
            source_span=span,
            requirement_type=None,  # Relevance stage 3 assigns this.
        )

    def _span_kind(self) -> str:
        return SegmentKind.REQUIREMENT

    async def extract(self, source: str, **kwargs: Any) -> ExtractionResult[Requirement]:
        """Decompose a Prompt into requirements.

        Args:
            source: The user's original instruction.
            **kwargs: Unused; accepted for interface symmetry.

        Returns:
            The requirements and extraction diagnostics. An absent or empty
            prompt yields an empty result — Relevance decides what having no
            stated intent means for its own dimension.

        Raises:
            ExtractionError: The prompt could not be rendered, or the provider
                failed.
        """
        return await super().extract(source, **kwargs)
