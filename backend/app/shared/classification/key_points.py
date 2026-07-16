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
    coerce_enum,
    coerce_unit_float,
    render_units,
)
from app.shared.extraction.models import KeyPoint
from app.shared.schemas import Severity

__all__ = ["SalienceAssigner", "CategorySeverityAssigner"]


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


class CategorySeverityAssigner(LLMClassifier[KeyPoint]):
    """Stage 4 — assigns each key point a category and an omission severity.

    **Category** is what kind of information the point is — a finding, a caveat,
    a limitation, a method, a figure. It is free-form: Document 2 fixes no
    taxonomy, and inventing a closed one here would be a design change the
    specification did not ask for. The prompt suggests common categories and
    lets the model name others.

    **Severity** is the impact of omitting the point. It becomes the severity of
    any Critical Omission raised about it — which is what the Decision Engine
    compares against the configured trust-blocking threshold (Document 3, §5).
    So this stage is where "the output dropped the study's central caveat"
    becomes, or does not become, a trust gate.
    """

    engine = "coverage"
    stage = "category_severity"
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
                            "category": {
                                "type": "string",
                                "description": "What kind of information this "
                                "is, e.g. finding, caveat, method, limitation.",
                            },
                            "severity": {
                                "type": "string",
                                "enum": [s.value for s in Severity],
                                "description": "Impact of omitting this point.",
                            },
                            "rationale": {"type": "string"},
                        },
                        "required": ["id", "category", "severity"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["assignments"],
            "additionalProperties": False,
        }

    def _prompt_variables(self, units: Sequence[KeyPoint], **kwargs: Any) -> dict[str, Any]:
        """Render key points with their stage-3 salience already attached.

        Stage 4 runs after stage 3 in the frozen pipeline, so the salience is
        available — and severity is a better judgment with it in view. A
        low-salience aside and the source's headline finding warrant different
        omission severities, and that is exactly what salience encodes.
        """
        rendered = []
        for unit in units:
            salience = (
                f" [salience {unit.salience:.2f}]" if unit.salience is not None else ""
            )
            rendered.append(
                {"id": unit.key_point_id, "text": f"{unit.text}{salience}"}
            )
        import json  # noqa: PLC0415

        return {"key_points": json.dumps(rendered, ensure_ascii=False, indent=2)}

    def _apply(self, unit: KeyPoint, record: dict[str, Any]) -> KeyPoint:
        """Attach the category and omission severity, preserving salience."""
        severity = coerce_enum(record.get("severity"), Severity, "severity")
        category = record.get("category")
        if not isinstance(category, str) or not category.strip():
            raise ValueError("category: expected a non-empty string")

        attributes = dict(unit.attributes)
        rationale = record.get("rationale")
        if isinstance(rationale, str) and rationale.strip():
            attributes["severity_rationale"] = rationale.strip()

        return replace(
            unit,
            category=category.strip().lower(),
            severity=severity,
            attributes=attributes,
        )
