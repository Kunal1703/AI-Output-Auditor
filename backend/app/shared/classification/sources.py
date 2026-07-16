"""Source Classification — Credibility's stage 7.

Document 2 §5.2 and §7.4, stage 7. Labels each citation's source with one of the
frozen classes (§6.4): Primary / Secondary / Government / Academic.

**Descriptive, not a ranking.** This implementation does not treat one class as
automatically more trustworthy than another. A primary source can be a personal
blog; a secondary one can be a systematic review. Document 2 fixes the
vocabulary but never says "Academic outranks Secondary", and inventing that
hierarchy would be a metric decision the specification did not make.

What the class *does* do is inform the score as one signal among several —
alongside whether the citation resolves (stage 4) and whether the source actually
supports its claim (stage 6). Of those three, grounding is the one that carries
real weight: an academic paper that does not support the claim attached to it is
worse than a blog post that does.

**The deterministic hint.** Domain is a strong, free, zero-variance signal —
``.gov`` is a government source and no model judgment improves on that. The
engine passes the URL's host so the model can use it; the model still decides,
because ``.org`` alone settles nothing.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Sequence
from urllib.parse import urlparse

from app.shared.classification.base import LLMClassifier, coerce_enum
from app.shared.extraction.models import Citation
from app.shared.vocabularies import SourceClass

__all__ = ["SourceClassifier", "domain_of"]


def domain_of(url: str | None) -> str | None:
    """Return the host of a URL, or ``None`` if it has none.

    Args:
        url: The URL.

    Returns:
        The lowercase host, without a leading ``www.``.
    """
    if not url:
        return None
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return None
    return host.removeprefix("www.") or None


class SourceClassifier(LLMClassifier[Citation]):
    """Stage 7 — labels each citation's source class.

    Note:
        A citation the model does not classify keeps ``source_class=None``.
        Credibility treats that as "class unknown" rather than defaulting —
        an invented class would put a fact in the Citation Ledger that nobody
        established.
    """

    engine = "credibility"
    stage = "source_classification"
    version = "v1"
    id_attr = "citation_id"
    unit_name = "citation"
    collection_key = "classifications"

    def _response_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "classifications": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "source_class": {
                                "type": "string",
                                "enum": [c.value for c in SourceClass],
                            },
                            "rationale": {"type": "string"},
                        },
                        "required": ["id", "source_class"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["classifications"],
            "additionalProperties": False,
        }

    def _prompt_variables(self, units: Sequence[Citation], **kwargs: Any) -> dict[str, Any]:
        """Render citations with their domain and any fetched source title.

        The domain and title are facts already gathered by earlier stages
        (stage 4's verification, stage 5's retrieval). Passing them costs
        nothing and makes the classification far better grounded than the
        citation string alone — "Smith et al. (2023)" says little; the same
        citation resolving to ``nih.gov`` says a lot.
        """
        rendered = []
        for unit in units:
            rendered.append(
                {
                    "id": unit.citation_id,
                    "text": unit.text[:300],
                    "domain": domain_of(unit.url),
                    "doi": unit.doi,
                    "source_title": unit.attributes.get("source_title"),
                }
            )
        return {"citations": json.dumps(rendered, ensure_ascii=False, indent=2)}

    def _apply(self, unit: Citation, record: dict[str, Any]) -> Citation:
        """Attach the source class."""
        source_class = coerce_enum(
            record.get("source_class"), SourceClass, "source_class"
        )
        attributes = dict(unit.attributes)
        rationale = record.get("rationale")
        if isinstance(rationale, str) and rationale.strip():
            attributes["source_class_rationale"] = rationale.strip()
        return replace(unit, source_class=source_class, attributes=attributes)
