"""Claim Extraction — the AI Output decomposed into checkable claims.

Document 2 §5.1: *"Claim Extraction (Accuracy) — extracts factual claims from
the AI Output."* Consumed by Accuracy at its stage 2, "LLM-based Claim
Extraction" (§7.2).

**It extracts candidates. It does not classify, verify, or weigh them.** The
frozen Accuracy pipeline keeps those apart deliberately:

* stage 2 — **Claim Extraction** ← this service
* stage 3 — Claim Classification (Factual / Opinion / Non-verifiable) ← §5.2
* stage 4 — Claim Centrality & Severity Assignment ← §5.2
* stages 5–7 — Evidence Retrieval and Verification → Supported / Contradicted /
  Unverifiable

So every :class:`Claim` returned here has ``claim_type=None`` and
``centrality=None``. The docstring calls them *candidate* claims for that
reason: whether a sentence is even a factual assertion is stage 3's answer, and
this service must surface anything that might be rather than pre-filter on a
judgment it is not authorized to make.

**Why the caller must not read an empty result as "no claims".** An empty result
is genuinely ambiguous — the text may assert nothing, or extraction may have
missed. Accuracy is a Trust dimension, so treating "found nothing" as "nothing
to check" would silently manufacture a pass. :class:`ExtractionResult` therefore
reports diagnostics and refuses to interpret them; Document 3 §8 gives the
engine the honest path (low confidence → *Unable to Verify*).
"""

from __future__ import annotations

from typing import Any

from app.shared.extraction.base import LLMExtractionService
from app.shared.extraction.models import Claim, ExtractionResult
from app.shared.text_segmentation import SegmentKind, TextSpan

__all__ = ["ClaimExtractionService"]


class ClaimExtractionService(LLMExtractionService[Claim]):
    """Decomposes an AI Output into atomic, independently checkable claims.

    Args:
        llm: The Shared LLM Service.
        prompts: The Prompt Manager.
        max_source_chars: Truncation bound for the output text.

    Example:
        Accuracy's stage 2, in Milestone 3::

            result = await claim_extraction.extract(context.ai_output)
            # result.units -> Claim objects; claim_type and centrality still None
            # stage 3 classifies, stage 4 weighs, stages 5-7 verify
    """

    engine = "accuracy"
    stage = "claim_extraction"
    version = "v1"
    unit_name = "claim"
    id_prefix = "clm"

    def _response_schema(self) -> dict[str, Any]:
        """The JSON Schema the model's response must conform to."""
        return {
            "type": "object",
            "properties": {
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "One atomic claim, self-contained "
                                "enough to check on its own.",
                            },
                            "quote": {
                                "type": "string",
                                "description": "The sentence of the output the "
                                "claim came from, verbatim.",
                            },
                        },
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["claims"],
            "additionalProperties": False,
        }

    def _prompt_variables(self, source: str, **kwargs: Any) -> dict[str, Any]:
        """Supply the prompt template's variables."""
        return {"ai_output": source}

    def _locate_text(self, record: dict[str, Any]) -> str:
        """Locate a claim by its source sentence, falling back to its own text.

        A claim is often lightly rewritten to stand alone — "It attracts 40
        million visitors" becomes "The Eiffel Tower attracts 40 million visitors
        annually" — so the rewritten text may not appear verbatim. The ``quote``
        field carries the sentence it came from, which does.

        Getting this right is what lets a Critical Finding about a hallucinated
        claim point the Evidence Viewer at the exact sentence that contains it
        (Document 4, §8).
        """
        quote = record.get("quote")
        if isinstance(quote, str) and quote.strip():
            return quote.strip()
        return self._unit_text(record)

    def _build_unit(
        self, record: dict[str, Any], unit_id: str, span: TextSpan | None
    ) -> Claim:
        """Construct one candidate claim, leaving classification to stage 3."""
        return Claim(
            claim_id=unit_id,
            text=self._unit_text(record),
            source_span=span,
            claim_type=None,  # Accuracy stage 3 assigns this.
            centrality=None,  # Accuracy stage 4 assigns this.
        )

    def _span_kind(self) -> str:
        return SegmentKind.CLAIM

    async def extract(self, source: str, **kwargs: Any) -> ExtractionResult[Claim]:
        """Decompose an AI Output into candidate claims.

        Args:
            source: The AI-generated content under audit.
            **kwargs: Unused; accepted for interface symmetry.

        Returns:
            The candidate claims and extraction diagnostics, in source order
            where locatable. Every ``claim_type`` and ``centrality`` is ``None``
            — later stages fill them.

        Raises:
            ExtractionError: The prompt could not be rendered, or the provider
                failed.
        """
        result = await super().extract(source, **kwargs)
        # Source order makes the Claim Verification Ledger readable: a reviewer
        # works through the output top to bottom, and a ledger that jumps around
        # fights them.
        return ExtractionResult(
            units=self._order_by_span(result.units),  # type: ignore[arg-type]
            source_characters=result.source_characters,
            located_count=result.located_count,
            duplicate_count=result.duplicate_count,
            truncated=result.truncated,
            raw_unit_count=result.raw_unit_count,
        )
