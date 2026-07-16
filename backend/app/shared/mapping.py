"""Claim-to-Citation Mapping — Credibility's stage 3.

Document 2 §7.4, stage 3. Establishes which claims each citation is offered in
support of.

**Why this is its own stage.** Grounding verification (stage 6) asks "does this
source support the claim attached to it" — a question that is meaningless
without knowing *which claim*. A citation floating free of any claim cannot be
grounded, and a claim with no citation cannot be mis-cited. The mapping is what
makes both questions answerable.

**Its second output is the more interesting one.** The stage also reveals which
factual claims carry **no citation at all**. That is the transparency signal:
content asserting checkable facts without attributing any of them is not
*miscited*, it is *unsourced* — a different and often more consequential
credibility observation. Credibility decides what to do with it; this stage just
surfaces it honestly.

**A mapping is not a judgment.** This says "the author offered source X for
claim Y". It says nothing about whether X supports Y — that is stage 6 — nor
whether X exists — that is stage 4. Keeping those apart is what lets the engine
distinguish a fabricated source from a real source cited for the wrong thing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Sequence

from app.core.logging import bind, get_logger
from app.shared.extraction.models import Citation, Claim
from app.shared.llm_stage import LLMStage, LLMStageError

__all__ = ["ClaimCitationMapper", "CitationMapping"]

logger = get_logger(__name__)


@dataclass(frozen=True)
class CitationMapping:
    """Which claims each citation supports, and which claims have no citation.

    Attributes:
        claims_by_citation: Claim ids keyed by citation id.
        uncited_claim_ids: Factual claims no citation was offered for. The
            transparency signal — content that asserts checkable facts while
            attributing none of them.
        citations_without_claims: Citations mapped to no claim. Usually a
            general reference ("for background, see X") rather than a defect;
            they are excluded from grounding verification because there is
            nothing to ground them against.
    """

    claims_by_citation: dict[str, tuple[str, ...]]
    uncited_claim_ids: tuple[str, ...]
    citations_without_claims: tuple[str, ...]

    @property
    def citation_coverage(self) -> float:
        """Fraction of claims that carry a citation, in [0, 1].

        A *transparency* measure, not a quality one. Low coverage means the
        content sources little of what it asserts; whether that matters depends
        on what it asserts, which is the engine's call.
        """
        cited = sum(len(ids) for ids in self.claims_by_citation.values())
        total = cited + len(self.uncited_claim_ids)
        return cited / total if total else 0.0


class ClaimCitationMapper(LLMStage):
    """Stage 3 — maps claims to the citations offered in support of them.

    Args:
        llm: The Shared LLM Service.
        prompts: The Prompt Manager.
    """

    engine = "credibility"
    stage = "claim_citation_mapping"
    version = "v1"
    collection_key = "mappings"

    def _response_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "mappings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "citation_id": {"type": "string"},
                            "claim_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Claims this citation is offered "
                                "in support of. Empty if it supports none.",
                            },
                        },
                        "required": ["citation_id", "claim_ids"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["mappings"],
            "additionalProperties": False,
        }

    async def map(
        self, claims: Sequence[Claim], citations: Sequence[Citation]
    ) -> CitationMapping:
        """Map claims to citations.

        Args:
            claims: The factual claims from Accuracy-style extraction. Pass only
                factual ones — an opinion needs no source, and counting it as
                uncited would report a transparency problem that does not exist.
            citations: The citations extracted from the output.

        Returns:
            The mapping, including the uncited claims.

        Raises:
            LLMStageError: The prompt could not be rendered, the provider
                failed, or the response could not be parsed.
        """
        if not claims or not citations:
            # Nothing to map. Every claim is uncited if there are no citations;
            # every citation is unattached if there are no claims. Both are
            # honest outcomes, and neither needs a model call.
            return CitationMapping(
                claims_by_citation={},
                uncited_claim_ids=tuple(c.claim_id for c in claims),
                citations_without_claims=tuple(c.citation_id for c in citations),
            )

        records = await self._run_records(
            {
                "claims": json.dumps(
                    [{"id": c.claim_id, "text": c.text} for c in claims],
                    ensure_ascii=False,
                    indent=2,
                ),
                "citations": json.dumps(
                    [{"id": c.citation_id, "text": c.text} for c in citations],
                    ensure_ascii=False,
                    indent=2,
                ),
            },
            self._response_schema(),
        )

        known_claims = {c.claim_id for c in claims}
        known_citations = {c.citation_id for c in citations}

        claims_by_citation: dict[str, tuple[str, ...]] = {}
        cited: set[str] = set()

        for record in records:
            citation_id = record.get("citation_id")
            if not isinstance(citation_id, str) or citation_id not in known_citations:
                continue
            raw_ids = record.get("claim_ids") or []
            # Filter to ids that actually exist. A model that invents "clm_99"
            # would otherwise put a phantom claim into the Citation Ledger.
            mapped = tuple(
                cid
                for cid in raw_ids
                if isinstance(cid, str) and cid in known_claims
            )
            if mapped:
                claims_by_citation[citation_id] = mapped
                cited.update(mapped)

        mapping = CitationMapping(
            claims_by_citation=claims_by_citation,
            uncited_claim_ids=tuple(
                c.claim_id for c in claims if c.claim_id not in cited
            ),
            citations_without_claims=tuple(
                c.citation_id
                for c in citations
                if c.citation_id not in claims_by_citation
            ),
        )
        logger.info(
            "claim-citation mapping complete",
            extra=bind(
                stage=self.identifier,
                mapped_citations=len(claims_by_citation),
                uncited_claims=len(mapping.uncited_claim_ids),
                coverage=round(mapping.citation_coverage, 3),
            ),
        )
        return mapping
