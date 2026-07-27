"""LLM Extraction — the shared decomposition component (Document 2, §5.1).

    *LLM-based decomposition of an input into atomic units of evaluation.*

A subpackage rather than four flat modules because Document 2 §5 catalogs these
as **one** shared component with four instantiations. Grouping them keeps the
shared machinery (:mod:`base`) in one place and makes the remaining two a prompt
plus a unit constructor.

| Instantiation | Input | Consumed by | Status |
|---|---|---|---|
| Requirement Extraction | Prompt | Relevance, stage 2 | **Milestone 2** |
| Claim Extraction | AI Output | Accuracy, stage 2 | **Milestone 2** |
| Key Point Extraction | Reference Source | Coverage, stage 2 | Milestone 3 |
| Citation Extraction | AI Output | Credibility, stage 2 | Milestone 3 |

**The boundary that governs this whole subpackage.** Document 2 keeps extraction
(§5.1) and Classification & Weighting (§5.2) as separate components, and the
frozen pipelines run them as separate stages. Extraction fills ``text`` and
leaves ``requirement_type``, ``claim_type``, and ``centrality`` as ``None``. If
a change here would set one of those, it belongs in an engine, not here.
"""

from app.shared.extraction.base import ExtractionError, LLMExtractionService
from app.shared.extraction.claims import ClaimExtractionService
from app.shared.extraction.key_points import KeyPointExtractionService
from app.shared.extraction.models import (
    Claim,
    ClaimType,
    ExtractionResult,
    KeyPoint,
)

__all__ = [
    "Claim",
    "ClaimExtractionService",
    "ClaimType",
    "ExtractionError",
    "ExtractionResult",
    "KeyPoint",
    "KeyPointExtractionService",
    "LLMExtractionService",
]
