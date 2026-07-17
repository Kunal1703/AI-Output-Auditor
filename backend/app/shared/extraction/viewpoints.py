"""Viewpoint Extraction — Diversity's stage 6.

Document 2 §7.8 places this at stage 6, after the credible perspectives have been
retrieved and before the balance evaluation. It is an LLM Extraction
instantiation in the sense of §5.1 — text in, atomic units out, no judgment —
and it extends the same base class as the four §5.1 catalogues.

**It extracts from the question, not from the output.** The other four extraction
services decompose a document that is in front of them. This one has to name the
viewpoints that *exist on the question the output addresses*, including the ones
the output never mentions — because "which legitimate perspective is missing" is
exactly what stage 7 needs to answer, and a viewpoint that was never extracted
can never be found missing.

That is why the retrieved perspectives matter. Where the audit could retrieve
material, the viewpoints are grounded in what other sources actually say. Where it
could not, the model is working from its own knowledge of the question, and
Diversity's confidence says so rather than the engine pretending otherwise.

**Legitimacy is left unset**, per the extraction/classification split (§5.1 vs
§5.2). Extraction names the viewpoints; the balance evaluation weighs them. That
split matters more here than anywhere: deciding a viewpoint is illegitimate is
how false balance gets avoided *and* how a real objection gets buried, and it is
not a call extraction should make in passing.
"""

from __future__ import annotations

from typing import Any

from app.shared.extraction.base import LLMExtractionService
from app.shared.extraction.models import Viewpoint
from app.shared.text_segmentation import TextSpan

__all__ = ["ViewpointExtractionService"]


class ViewpointExtractionService(LLMExtractionService[Viewpoint]):
    """Stage 6 — extracts the legitimate viewpoints on the output's question."""

    engine = "diversity"
    stage = "viewpoint_extraction"
    version = "v1"
    unit_name = "viewpoint"
    id_prefix = "vwp"

    def _response_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "viewpoints": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "The position, stated as someone "
                                "who holds it would state it.",
                            },
                            "in_output": {
                                "type": "boolean",
                                "description": "Whether the output states this "
                                "viewpoint at all.",
                            },
                            "quote": {
                                "type": "string",
                                "description": "Where the output states it, "
                                "copied verbatim. Empty when it does not.",
                            },
                        },
                        "required": ["text", "in_output"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["viewpoints"],
            "additionalProperties": False,
        }

    def _prompt_variables(self, source: str, **kwargs: Any) -> dict[str, Any]:
        """Supply the prompt template's variables.

        Args:
            source: The AI Output.
            **kwargs: Must carry ``prompt`` and ``perspectives``.
        """
        return {
            "ai_output": source,
            "prompt": kwargs["prompt"],
            "perspectives": kwargs["perspectives"],
        }

    def _locate_text(self, record: dict[str, Any]) -> str:
        """Locate a viewpoint by the model's quote, never by its own text.

        A viewpoint is a *restatement* of a position — "critics argue the cost
        estimates are optimistic" appears nowhere in the output verbatim, so
        searching for it would find nothing and every viewpoint would come back
        unlocated. The quote is the output's own words, which is what the
        Evidence Viewer needs to highlight. The same reasoning as Relevance's
        requirement extraction.
        """
        quote = record.get("quote")
        return quote.strip() if isinstance(quote, str) else ""

    def _build_unit(
        self, record: dict[str, Any], unit_id: str, span: TextSpan | None
    ) -> Viewpoint:
        """Build one viewpoint, with legitimacy left for the balance evaluation."""
        return Viewpoint(
            viewpoint_id=unit_id,
            text=self._unit_text(record),
            source_span=span,
            in_output=bool(record.get("in_output")),
            attributes={"quote": (record.get("quote") or "").strip()},
        )
