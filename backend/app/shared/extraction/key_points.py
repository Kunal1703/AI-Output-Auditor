"""Key Point Extraction — the Reference Source decomposed into key points.

Document 2 §5.1: *"Key Point Extraction (Coverage) — extracts important
information units from the Reference Source."* Consumed by Coverage at its
stage 2, "LLM Key Point Extraction" (§7.3).

**It extracts. It does not weigh.** Coverage's stage 3 (Salience Assignment) and
stage 4 (Category & Severity Assignment) are separate frozen stages backed by
the separate §5.2 component. So every :class:`KeyPoint` returned here has
``salience=None``, ``category=None``, and ``severity=None``.

That restraint is what protects Coverage's central promise — completeness
*"without over-penalizing summarization"* (§7.3). Salience is precisely the
signal that separates "this summary legitimately left out a detail" from "this
summary dropped the finding the whole document was about". Deciding it during
extraction — where the AI Output is not even in view — would be guessing at the
one judgment the engine most needs to get right.

**Note the direction.** This reads the *Reference Source*, not the AI Output.
Every other extraction service decomposes what the AI wrote; this decomposes what
it should have covered. Coverage then checks the output against these points.
"""

from __future__ import annotations

from typing import Any

from app.shared.extraction.base import LLMExtractionService
from app.shared.extraction.models import ExtractionResult, KeyPoint
from app.shared.text_segmentation import TextSpan

__all__ = ["KeyPointExtractionService"]


class KeyPointExtractionService(LLMExtractionService[KeyPoint]):
    """Decomposes a Reference Source into atomic key points.

    Args:
        llm: The Shared LLM Service.
        prompts: The Prompt Manager.
        max_source_chars: Truncation bound for the reference text.

    Example:
        Coverage's stage 2, called with the reference source::

            result = await key_point_extraction.extract(context.reference_source)
            # result.units -> KeyPoint objects; salience/category/severity None
            # stages 3-4 then weigh them; stage 5 checks the output against them
    """

    engine = "coverage"
    stage = "key_point_extraction"
    version = "v1"
    unit_name = "key point"
    id_prefix = "kpt"

    def _response_schema(self) -> dict[str, Any]:
        """The JSON Schema the model's response must conform to."""
        return {
            "type": "object",
            "properties": {
                "key_points": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "One atomic unit of important "
                                "information, self-contained.",
                            },
                            "quote": {
                                "type": "string",
                                "description": "The sentence of the source it "
                                "came from, verbatim.",
                            },
                        },
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["key_points"],
            "additionalProperties": False,
        }

    def _prompt_variables(self, source: str, **kwargs: Any) -> dict[str, Any]:
        """Supply the prompt template's variables."""
        return {"reference_source": source}

    def _locate_text(self, record: dict[str, Any]) -> str:
        """Locate a key point by its source sentence, falling back to its text.

        Key points are restated to stand alone, so the restatement rarely appears
        verbatim in the reference. The ``quote`` does — and it is what lets a
        Critical Omission point the reader at the passage of the source that was
        dropped.
        """
        quote = record.get("quote")
        if isinstance(quote, str) and quote.strip():
            return quote.strip()
        return self._unit_text(record)

    @property
    def collection_key(self) -> str:
        """The model wraps its list under ``key_points``."""
        return "key_points"

    def _build_unit(
        self, record: dict[str, Any], unit_id: str, span: TextSpan | None
    ) -> KeyPoint:
        """Construct one key point, leaving weighting to stages 3–4."""
        return KeyPoint(
            key_point_id=unit_id,
            text=self._unit_text(record),
            source_span=span,
            salience=None,  # Coverage stage 3 assigns this.
            category=None,  # Coverage stage 4 assigns this.
            severity=None,  # Coverage stage 4 assigns this.
        )

    def _span_kind(self) -> str:
        return "key_point"

    async def extract(self, source: str, **kwargs: Any) -> ExtractionResult[KeyPoint]:
        """Decompose a Reference Source into key points.

        Args:
            source: The ground-truth document.
            **kwargs: Unused; accepted for interface symmetry.

        Returns:
            The key points and extraction diagnostics, in source order where
            locatable. An absent reference yields an empty result — Coverage
            decides what having no ground truth means for its dimension
            (Document 2, §6.1 requires a reference for Coverage to score).

        Raises:
            ExtractionError: The prompt could not be rendered, or the provider
                failed.
        """
        result = await super().extract(source, **kwargs)
        return ExtractionResult(
            units=self._order_by_span(result.units),  # type: ignore[arg-type]
            source_characters=result.source_characters,
            located_count=result.located_count,
            duplicate_count=result.duplicate_count,
            truncated=result.truncated,
            raw_unit_count=result.raw_unit_count,
        )
