"""Readability issue labelling — Readability's stages 4 and 5.

Two *separate* frozen stages, implemented as two classifiers because Document 2
§7.6 runs them as two and §5.2 catalogues them as two ("Issue Classification and
Severity Assignment"):

* **Stage 4 — Issue Classification** — what kind of problem is this?
* **Stage 5 — Severity Assignment** — how much does it cost the reader?

**Why they are separate questions.** A category is about the *nature* of a
problem; a severity is about its *consequence*, and the two come apart in both
directions. An undefined acronym and a 70-word sentence are both clarity issues
and cost the reader very differently. A missing heading in a 200-word answer and
one in a 3,000-word report are both structure issues, and only the second matters.
Splitting the stages means severity is judged with the category already fixed,
rather than the model deciding both at once and letting one drag the other.

**Only reviewed issues come through here.** Issues from the deterministic stage
arrive already classified — the check that produced one *is* its category, and
its severity came from a rule rather than a guess. Asking a model to relabel
"mean sentence length is 34 words, above the 25-word bound" would be asking what
a regex already knows, which Document 4 §11 rules out wherever a deterministic
answer exists. Readability's engine filters accordingly before calling these.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Sequence

from app.shared.classification.base import LLMClassifier, coerce_enum
from app.shared.quality_units import ReadabilityIssue
from app.shared.schemas import Severity

__all__ = ["IssueClassifier", "IssueSeverityAssigner"]


class IssueClassifier(LLMClassifier[ReadabilityIssue]):
    """Stage 4 — assigns each reviewed issue a category.

    The category vocabulary is **free-form**. Document 2 fixes no readability
    taxonomy, and inventing a closed one here would be a design change the
    specification did not ask for — the same call Coverage's
    :class:`~app.shared.classification.key_points.CategorySeverityAssigner`
    makes for key-point categories. The prompt names the common classes and lets
    the model name others.
    """

    engine = "readability"
    stage = "issue_classification"
    version = "v1"
    id_attr = "issue_id"
    unit_name = "issue"
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
                            "category": {
                                "type": "string",
                                "description": "What kind of readability "
                                "problem this is, e.g. ambiguous wording, "
                                "undefined jargon, sentence complexity, "
                                "missing transition, disordered structure.",
                            },
                            "rationale": {"type": "string"},
                        },
                        "required": ["id", "category"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["classifications"],
            "additionalProperties": False,
        }

    def _prompt_variables(
        self, units: Sequence[ReadabilityIssue], **kwargs: Any
    ) -> dict[str, Any]:
        """Render each issue with the aspect it was raised under and its quote."""
        rendered = [
            {
                "id": issue.issue_id,
                "aspect": issue.aspect,
                "issue": issue.text,
                "quote": issue.quote or "",
            }
            for issue in units
        ]
        return {"issues": json.dumps(rendered, ensure_ascii=False, indent=2)}

    def _apply(
        self, unit: ReadabilityIssue, record: dict[str, Any]
    ) -> ReadabilityIssue:
        """Attach the category."""
        category = record.get("category")
        if not isinstance(category, str) or not category.strip():
            raise ValueError("category: expected a non-empty string")

        attributes = dict(unit.attributes)
        rationale = record.get("rationale")
        if isinstance(rationale, str) and rationale.strip():
            attributes["category_rationale"] = rationale.strip()
        return replace(unit, category=category.strip().lower(), attributes=attributes)


class IssueSeverityAssigner(LLMClassifier[ReadabilityIssue]):
    """Stage 5 — assigns each reviewed issue a severity.

    **Severity here can never gate trust.** Readability's critical-finding
    capability is *No* (Document 2, §4.1), so a ``critical`` severity on a
    readability issue means "this badly obstructs the reader", not "this content
    is untrustworthy". It orders recommendations and weights the score; it does
    not reach the Trust Verdict, and it has no path by which it could
    (Document 3, §5).
    """

    engine = "readability"
    stage = "issue_severity"
    version = "v1"
    id_attr = "issue_id"
    unit_name = "issue"
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
                            "severity": {
                                "type": "string",
                                "enum": [s.value for s in Severity],
                                "description": "How much this costs a reader "
                                "trying to understand the content.",
                            },
                            "rationale": {"type": "string"},
                        },
                        "required": ["id", "severity"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["assignments"],
            "additionalProperties": False,
        }

    def _prompt_variables(
        self, units: Sequence[ReadabilityIssue], **kwargs: Any
    ) -> dict[str, Any]:
        """Render each issue with its stage-4 category already attached.

        Stage 5 runs after stage 4 in the frozen pipeline, so the category is
        available — and severity is a better judgment with it in view. "Undefined
        jargon" and "disordered structure" warrant different severities for the
        same length of quote, and the category is what says which one this is.
        """
        rendered = [
            {
                "id": issue.issue_id,
                "aspect": issue.aspect,
                "category": issue.category or "unclassified",
                "issue": issue.text,
                "quote": issue.quote or "",
            }
            for issue in units
        ]
        return {"issues": json.dumps(rendered, ensure_ascii=False, indent=2)}

    def _apply(
        self, unit: ReadabilityIssue, record: dict[str, Any]
    ) -> ReadabilityIssue:
        """Attach the severity, preserving the stage-4 category."""
        severity = coerce_enum(record.get("severity"), Severity, "severity")

        attributes = dict(unit.attributes)
        rationale = record.get("rationale")
        if isinstance(rationale, str) and rationale.strip():
            attributes["severity_rationale"] = rationale.strip()
        return replace(unit, severity=severity, attributes=attributes)
