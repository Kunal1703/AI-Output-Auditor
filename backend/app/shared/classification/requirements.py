"""Hard / Soft Requirement Classification — Relevance's stage 3.

Document 2 §5.2 and §7.1, stage 3. Splits extracted requirements into the two
frozen types (§6.4):

* **Hard** — "a requirement whose violation is treated as a critical/blocking
  issue" (Document 2, §3).
* **Soft** — "a requirement representing intent or preference rather than a
  strict constraint".

**This is the highest-stakes classification in the system.** It is the stage that
decides whether a failure becomes a Critical Finding, and a Critical Finding
gates the Trust Verdict to *Untrusted* non-compensatorily (Document 3, §5). Mark
a stylistic preference Hard and polished, accurate content gets branded
untrustworthy for ignoring a suggestion. Mark an explicit constraint Soft and a
genuine instruction violation slips through as a minor quality note.

The prompt therefore pushes toward Soft on genuine ambiguity. That asymmetry is
deliberate but it is *not* a bias toward passing: a misjudged Soft still lowers
the Relevance score and still produces a recommendation — it just does not
detonate the trust gate on a judgment call. Document 3 §13's fail-safe principle
is about not asserting *unearned trust*; it is equally about not asserting
unearned condemnation.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Sequence

from app.shared.classification.base import LLMClassifier, coerce_enum, render_units
from app.shared.extraction.models import Requirement
from app.shared.vocabularies import RequirementType

__all__ = ["RequirementClassifier"]


class RequirementClassifier(LLMClassifier[Requirement]):
    """Stage 3 — labels each requirement Hard or Soft.

    Note:
        A requirement the model does not return a label for stays ``None``.
        Relevance treats an unclassified requirement as non-gating — it cannot
        raise a Critical Finding on a requirement whose blocking status was
        never established, because that would gate trust on an unanswered
        question.
    """

    engine = "relevance"
    stage = "requirement_classification"
    version = "v1"
    id_attr = "requirement_id"
    unit_name = "requirement"
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
                            "requirement_type": {
                                "type": "string",
                                "enum": [t.value for t in RequirementType],
                            },
                            "rationale": {"type": "string"},
                            "constraint": {
                                "type": "object",
                                "description": "Machine-checkable form of the "
                                "requirement, when it has one.",
                                "properties": {
                                    "kind": {
                                        "type": "string",
                                        "enum": [
                                            "max_words",
                                            "min_words",
                                            "max_characters",
                                            "min_characters",
                                            "language",
                                            "format",
                                            "must_contain",
                                            "must_not_contain",
                                        ],
                                    },
                                    "value": {
                                        "type": ["string", "number"],
                                    },
                                },
                                "required": ["kind", "value"],
                                "additionalProperties": False,
                            },
                        },
                        "required": ["id", "requirement_type"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["classifications"],
            "additionalProperties": False,
        }

    def _prompt_variables(
        self, units: Sequence[Requirement], **kwargs: Any
    ) -> dict[str, Any]:
        return {"requirements": render_units(units, id_attr="requirement_id")}

    def _apply(self, unit: Requirement, record: dict[str, Any]) -> Requirement:
        """Attach the type and any machine-checkable constraint.

        The optional ``constraint`` is what lets stage 7 check a requirement
        *deterministically* instead of asking a judge. "The response must not
        exceed 200 words" becomes ``{"kind": "max_words", "value": 200}``, and a
        word count then answers it with no model variability at all — which
        Document 4 §11 prefers wherever it is achievable.

        The model translates the requirement into the constraint; it never
        evaluates it. Counting the words is the validator's job.
        """
        requirement_type = coerce_enum(
            record.get("requirement_type"), RequirementType, "requirement_type"
        )

        attributes = dict(unit.attributes)
        rationale = record.get("rationale")
        if isinstance(rationale, str) and rationale.strip():
            attributes["classification_rationale"] = rationale.strip()

        constraint = record.get("constraint")
        if isinstance(constraint, dict):
            kind = constraint.get("kind")
            value = constraint.get("value")
            if isinstance(kind, str) and value is not None:
                attributes["constraint_kind"] = kind
                attributes["constraint_value"] = value

        return replace(unit, requirement_type=requirement_type, attributes=attributes)
