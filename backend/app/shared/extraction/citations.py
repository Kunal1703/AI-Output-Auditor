"""Citation Extraction — the AI Output decomposed into citations.

Document 2 §5.1: *"Citation Extraction (Credibility) — extracts
citations/references from the AI Output."* Consumed by Credibility at its
stage 2, "LLM Citation Extraction" (§7.4).

**It extracts. It does not verify or classify.** Whether the URL resolves is
stage 4 (deterministic). Whether the source supports the claim is stage 6. What
kind of source it is, is stage 7. Whether the whole thing was fabricated is
stage 9. So every :class:`Citation` here has ``source_class=None`` and no
verification outcome.

**Why URL and DOI are pulled out deterministically.** The model identifies *what
is a citation* — a genuinely linguistic judgment ("Smith et al. (2023)" is a
citation; "as shown above" is not). But once identified, finding the URL inside
it is a regex's job, and a regex cannot hallucinate a URL that was never there.
Letting the model retype the link would risk exactly that: a fabricated-citation
finding raised against a URL the author never wrote. So the model finds the
citation and the regex reads the link out of it.

This is the engine whose findings carry the system's headline scenario
(Document 1, §9): a fabricated citation gating trust to *Untrusted* regardless
of how well the content scores elsewhere. Everything downstream of this
extraction inherits that weight.
"""

from __future__ import annotations

from typing import Any

from app.shared.deterministic_validators import DOI_PATTERN, URL_PATTERN
from app.shared.extraction.base import LLMExtractionService
from app.shared.extraction.models import Citation, ExtractionResult
from app.shared.text_segmentation import TextSpan

__all__ = ["CitationExtractionService"]

#: Trailing punctuation a URL regex tends to swallow from prose.
_URL_TRAILING = ".,;:!?)]}'\"›»"


class CitationExtractionService(LLMExtractionService[Citation]):
    """Decomposes an AI Output into the citations it contains.

    Args:
        llm: The Shared LLM Service.
        prompts: The Prompt Manager.
        max_source_chars: Truncation bound for the output text.
    """

    engine = "credibility"
    stage = "citation_extraction"
    version = "v1"
    unit_name = "citation"
    id_prefix = "cit"

    def _response_schema(self) -> dict[str, Any]:
        """The JSON Schema the model's response must conform to."""
        return {
            "type": "object",
            "properties": {
                "citations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "The citation exactly as it "
                                "appears in the text.",
                            },
                            "quote": {
                                "type": "string",
                                "description": "The sentence containing it, "
                                "verbatim.",
                            },
                        },
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["citations"],
            "additionalProperties": False,
        }

    def _prompt_variables(self, source: str, **kwargs: Any) -> dict[str, Any]:
        """Supply the prompt template's variables."""
        return {"ai_output": source}

    def _locate_text(self, record: dict[str, Any]) -> str:
        """Locate a citation by its own text.

        Unlike claims and requirements, a citation *is* a verbatim substring —
        that is what makes it a citation. So the default (locate by unit text)
        is right here, and the ``quote`` is only a fallback for a model that
        normalized the spacing.
        """
        text = self._unit_text(record)
        if text:
            return text
        quote = record.get("quote")
        return quote.strip() if isinstance(quote, str) else ""

    @property
    def collection_key(self) -> str:
        """The model wraps its list under ``citations``."""
        return "citations"

    def _build_unit(
        self, record: dict[str, Any], unit_id: str, span: TextSpan | None
    ) -> Citation:
        """Construct one citation, reading any URL or DOI out of it directly.

        The link is extracted from the citation's *own text* by regex — never
        taken from a field the model filled in. A model that retyped a URL could
        introduce a typo, and Credibility would then report a fabricated
        citation against a link the author wrote correctly. Reading it from the
        source text makes that failure impossible.
        """
        text = self._unit_text(record)
        quote = record.get("quote")
        searchable = f"{text} {quote if isinstance(quote, str) else ''}"

        url_match = URL_PATTERN.search(searchable)
        doi_match = DOI_PATTERN.search(searchable)

        return Citation(
            citation_id=unit_id,
            text=text,
            url=url_match.group(0).rstrip(_URL_TRAILING) if url_match else None,
            doi=doi_match.group(0) if doi_match else None,
            source_span=span,
            source_class=None,  # Credibility stage 7 assigns this.
        )

    def _span_kind(self) -> str:
        return "citation"

    async def extract(self, source: str, **kwargs: Any) -> ExtractionResult[Citation]:
        """Decompose an AI Output into its citations.

        Args:
            source: The AI-generated content under audit.
            **kwargs: Unused; accepted for interface symmetry.

        Returns:
            The citations and extraction diagnostics, in source order where
            locatable.

            An empty result is genuinely ambiguous and is left that way: content
            with no citations may be uncited prose (no credibility problem — it
            claims no sources) or content whose citations extraction missed.
            Credibility decides, because only it knows whether the content makes
            factual claims that *needed* sourcing.

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
