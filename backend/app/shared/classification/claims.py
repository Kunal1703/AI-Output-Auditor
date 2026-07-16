"""Claim classification and weighting — Accuracy's stages 3 and 4.

Two *separate* frozen stages, implemented as two classifiers because Document 2
§7.2 runs them as two:

* **Stage 3 — Claim Classification** (Factual / Opinion / Non-verifiable)
* **Stage 4 — Claim Centrality & Severity Assignment**

**Why they are not merged into one call.** They answer different questions with
different consequences, and the pipeline is explicit about the order. Stage 3
decides *whether a claim is checkable at all* — and only Factual claims proceed
to retrieval and verification (stages 5–7). Stage 4 decides *how much a claim
matters* — which sets the severity of any Critical Finding about it and breaks
ties when the Decision Engine orders findings (Document 3, §5).

Collapsing them would also corrupt stage 4's input: centrality is a judgment
about load-bearing *factual* claims, and asking for it before opinions are
filtered out invites the model to rate the centrality of a subjective aside.
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
from app.shared.extraction.models import Claim
from app.shared.schemas import Severity
from app.shared.vocabularies import ClaimType

__all__ = ["ClaimClassifier", "ClaimCentralityAssigner"]


class ClaimClassifier(LLMClassifier[Claim]):
    """Stage 3 — labels each claim Factual / Opinion / Non-verifiable.

    The gate that decides which claims Accuracy will actually try to verify.
    Getting it wrong is costly in both directions: an opinion marked Factual
    goes for verification, comes back *Unverifiable*, and depresses a score it
    should never have touched; a factual claim marked Opinion escapes checking
    entirely, which is how a hallucination reaches a *Trusted* verdict.
    """

    engine = "accuracy"
    stage = "claim_classification"
    version = "v1"
    id_attr = "claim_id"
    unit_name = "claim"
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
                            "claim_type": {
                                "type": "string",
                                "enum": [t.value for t in ClaimType],
                            },
                            "rationale": {"type": "string"},
                        },
                        "required": ["id", "claim_type"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["classifications"],
            "additionalProperties": False,
        }

    def _prompt_variables(self, units: Sequence[Claim], **kwargs: Any) -> dict[str, Any]:
        return {"claims": render_units(units, id_attr="claim_id")}

    def _apply(self, unit: Claim, record: dict[str, Any]) -> Claim:
        """Attach the claim type, preserving everything else."""
        claim_type = coerce_enum(record.get("claim_type"), ClaimType, "claim_type")
        attributes = dict(unit.attributes)
        rationale = record.get("rationale")
        if isinstance(rationale, str) and rationale.strip():
            attributes["classification_rationale"] = rationale.strip()
        return replace(unit, claim_type=claim_type, attributes=attributes)


class ClaimCentralityAssigner(LLMClassifier[Claim]):
    """Stage 4 — assigns each claim a centrality and a severity.

    **Centrality** is how load-bearing the claim is to the output's message, in
    [0, 1]. **Severity** is the impact if the claim turns out to be wrong.

    Both feed the Decision Engine rather than the score directly: severity sets
    the grade of any Critical Finding raised about the claim, and centrality is
    the third tiebreaker when findings are ordered — "a hallucination in a
    load-bearing claim outranks one in an incidental claim" (Document 3, §5).

    Note:
        Only Factual claims should be passed here. Opinions have no truth value,
        so the severity of their being "wrong" is not a coherent question.
        Accuracy filters before calling.
    """

    engine = "accuracy"
    stage = "claim_centrality"
    version = "v1"
    id_attr = "claim_id"
    unit_name = "claim"
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
                            "centrality": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                                "description": "How load-bearing the claim is "
                                "to the output's message.",
                            },
                            "severity": {
                                "type": "string",
                                "enum": [s.value for s in Severity],
                                "description": "Impact if this claim is wrong.",
                            },
                            "rationale": {"type": "string"},
                        },
                        "required": ["id", "centrality", "severity"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["assignments"],
            "additionalProperties": False,
        }

    def _prompt_variables(self, units: Sequence[Claim], **kwargs: Any) -> dict[str, Any]:
        return {"claims": render_units(units, id_attr="claim_id")}

    def _apply(self, unit: Claim, record: dict[str, Any]) -> Claim:
        """Attach centrality and severity, preserving the claim type."""
        centrality = coerce_unit_float(record.get("centrality"), "centrality")
        severity = coerce_enum(record.get("severity"), Severity, "severity")

        attributes = dict(unit.attributes)
        attributes["severity"] = severity.value
        rationale = record.get("rationale")
        if isinstance(rationale, str) and rationale.strip():
            attributes["centrality_rationale"] = rationale.strip()

        return replace(unit, centrality=centrality, attributes=attributes)
