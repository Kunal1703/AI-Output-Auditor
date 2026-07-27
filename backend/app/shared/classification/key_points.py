"""Key point weighting — Coverage's stages 3 and 4.

Two *separate* frozen stages, implemented as two classifiers because Document 2
§7.3 runs them as two:

* **Stage 3 — Salience Assignment** — how important is this key point?
* **Stage 4 — Category & Severity Assignment** — what kind of information is it,
  and how bad is it to omit?

**Salience is what makes Coverage fair.** The engine's stated purpose is
completeness *"without penalizing appropriate summarization"* (§7.3), and a
summary omits by design — that is what a summary is. Without salience, every
absent key point would look like a failure and every summary would score
terribly for doing its job. Salience is the signal that separates a legitimate
compression from a Critical Omission, and it is the reason Coverage can be
strict about the second without being unfair about the first.

**Why salience and severity are distinct.** They are correlated but not the same
question. A key point can be highly salient to the source (the study's headline
result) while its omission from *this particular* output is only moderately
severe (the output is a two-line abstract that never claimed completeness).
Salience is about the source; severity is about the consequence of dropping it.
Stage 4 sees both the categories and the salience already assigned, so it can
weigh them together.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Sequence

from app.shared.classification.base import (
    LLMClassifier,
    coerce_unit_float,
    render_units,
)
from app.shared.extraction.models import KeyPoint

__all__ = ["SalienceAssigner"]


class SalienceAssigner(LLMClassifier[KeyPoint]):
    """Stage 3 — assigns each key point a salience in [0, 1].

    Salience is judged **relative to the reference source**, not to the AI
    Output. The question is "how central is this to what the source says?", and
    the output is deliberately not in view — letting the model see what was
    written would invite it to rationalize whatever got omitted as unimportant,
    which is precisely the judgment Coverage exists to make independently.
    """

    engine = "coverage"
    stage = "salience_assignment"
    version = "v1"
    id_attr = "key_point_id"
    unit_name = "key point"
    collection_key = "assignments"

    def _response_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "assignments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "salience": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                                "description": "How central this point is to "
                                "the source document's message.",
                            },
                            "rationale": {"type": "string"},
                        },
                        "required": ["id", "salience"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["assignments"],
            "additionalProperties": False,
        }

    def _prompt_variables(self, units: Sequence[KeyPoint], **kwargs: Any) -> dict[str, Any]:
        return {"key_points": render_units(units, id_attr="key_point_id")}

    def _apply(self, unit: KeyPoint, record: dict[str, Any]) -> KeyPoint:
        """Attach the salience."""
        salience = coerce_unit_float(record.get("salience"), "salience")
        attributes = dict(unit.attributes)
        rationale = record.get("rationale")
        if isinstance(rationale, str) and rationale.strip():
            attributes["salience_rationale"] = rationale.strip()
        return replace(unit, salience=salience, attributes=attributes)
