"""Frozen system constants for the AI Trust & Quality Auditor.

This module is the single in-code transcription of the classification data that
Documents 2 and 3 declare frozen:

* the eight dimensions and their engine ids (Document 2, §1 and §7);
* the Dimension Classification & Capability Matrix (Document 2, §4.1);
* the ledger name each engine populates (Document 2, §6.3);
* the cross-engine execution ordering (Document 2, §8; Document 4, §6).

Nothing here is a tunable. Thresholds and weights are configuration and live in
``config/settings.yaml``; this module holds only the facts the specification
freezes. The Decision Engine consumes ``dimension_type`` as fixed input rather
than computing it (Document 3, §3), so this table is the authority for routing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from app.shared.schemas import CriticalFindingCapability, DimensionType, GateRole, Layer

__all__ = [
    "DimensionSpec",
    "DIMENSION_SPECS",
    "ALL_DIMENSIONS",
    "TRUST_RELEVANT_DIMENSIONS",
    "QUALITY_CONTRIBUTING_DIMENSIONS",
    "CRITICAL_FINDING_CAPABLE_DIMENSIONS",
    "EXECUTION_WAVES",
    "CROSS_ENGINE_INPUTS",
    "spec_for",
    # --- AI Output Auditor — new metric/layer matrix (MB1) ------------------ #
    "MetricRepresentation",
    "MetricSpec",
    "METRIC_SPECS",
    "ALL_METRICS",
    "METRICS_BY_LAYER",
    "metric_spec",
]


@dataclass(frozen=True)
class DimensionSpec:
    """The frozen descriptor for one audit dimension.

    Attributes:
        dimension: Human-readable dimension name, e.g. ``"Accuracy"``.
        engine_id: Stable engine identifier from Document 2 §7, e.g.
            ``"ENG-ACCURACY"``.
        dimension_type: Trust / Quality / Hybrid routing class consumed by the
            Decision Engine (Document 3, §3).
        critical_finding_capability: Whether the engine may emit Critical
            Findings. Engines with ``NO`` always return an empty
            ``critical_findings`` array, and an empty array is therefore
            expected rather than anomalous (Document 3, §3).
        supports_na: Whether the engine may legitimately return ``"N/A"``
            instead of a score. Only Diversity does today (Document 2, §7.8).
        ledger_name: The engine's named ledger (Document 2, §6.3).
        governing_question: The question the engine answers (Document 2, §1).
    """

    dimension: str
    engine_id: str
    dimension_type: DimensionType
    critical_finding_capability: CriticalFindingCapability
    supports_na: bool
    ledger_name: str
    governing_question: str


#: The frozen Dimension Classification & Capability Matrix (Document 2, §4.1),
#: enriched with ledger names (§6.3) and governing questions (§1).
DIMENSION_SPECS: Mapping[str, DimensionSpec] = {
    spec.dimension: spec
    for spec in (
        DimensionSpec(
            dimension="Relevance",
            engine_id="ENG-RELEVANCE",
            dimension_type=DimensionType.HYBRID,
            critical_finding_capability=CriticalFindingCapability.YES,
            supports_na=False,
            ledger_name="Requirement Checklist",
            governing_question=(
                "Does the output satisfy the user's instruction and intent "
                "without off-topic content?"
            ),
        ),
        DimensionSpec(
            dimension="Accuracy",
            engine_id="ENG-ACCURACY",
            dimension_type=DimensionType.TRUST,
            critical_finding_capability=CriticalFindingCapability.YES,
            supports_na=False,
            ledger_name="Claim Verification Ledger",
            governing_question=(
                "Is every factual claim supported, contradicted, or "
                "unverifiable against available evidence?"
            ),
        ),
        DimensionSpec(
            dimension="Coverage",
            engine_id="ENG-COVERAGE",
            dimension_type=DimensionType.HYBRID,
            critical_finding_capability=CriticalFindingCapability.YES,
            supports_na=False,
            ledger_name="Coverage Ledger",
            governing_question=(
                "Does the output include all important information from the "
                "reference source without over-penalizing summarization?"
            ),
        ),
        DimensionSpec(
            dimension="Credibility",
            engine_id="ENG-CREDIBILITY",
            dimension_type=DimensionType.TRUST,
            critical_finding_capability=CriticalFindingCapability.YES,
            supports_na=False,
            ledger_name="Citation Ledger",
            governing_question=(
                "Are factual claims supported by trustworthy, correctly cited, "
                "verifiable sources?"
            ),
        ),
        DimensionSpec(
            dimension="Novelty",
            engine_id="ENG-NOVELTY",
            dimension_type=DimensionType.QUALITY,
            critical_finding_capability=CriticalFindingCapability.NO,
            supports_na=False,
            ledger_name="Redundancy Ledger",
            governing_question=(
                "Does the output communicate efficiently, minimizing "
                "unnecessary repetition while preserving important content?"
            ),
        ),
        DimensionSpec(
            dimension="Readability",
            engine_id="ENG-READABILITY",
            dimension_type=DimensionType.QUALITY,
            critical_finding_capability=CriticalFindingCapability.NO,
            supports_na=False,
            ledger_name="Readability Ledger",
            governing_question=(
                "Is the content easy for its intended audience to understand "
                "(clarity, coherence, structure)?"
            ),
        ),
        DimensionSpec(
            dimension="Engagement",
            engine_id="ENG-ENGAGEMENT",
            dimension_type=DimensionType.QUALITY,
            critical_finding_capability=CriticalFindingCapability.NO,
            supports_na=False,
            ledger_name="Engagement Ledger",
            governing_question=(
                "Does the content help the user achieve their goal without "
                "manipulative or misleading communication?"
            ),
        ),
        DimensionSpec(
            dimension="Diversity",
            engine_id="ENG-DIVERSITY",
            dimension_type=DimensionType.QUALITY,
            critical_finding_capability=CriticalFindingCapability.NO,
            supports_na=True,
            ledger_name="Diversity Ledger",
            governing_question=(
                "Where appropriate, does the content fairly represent "
                "legitimate perspectives while avoiding false balance?"
            ),
        ),
    )
}

#: All eight dimension names, in specification order (Document 2, §1).
ALL_DIMENSIONS: tuple[str, ...] = tuple(DIMENSION_SPECS)

#: Dimensions that participate in Trust Evaluation: the Trust dimensions plus
#: the trust-gating contribution of the Hybrid dimensions (Document 3, §6).
TRUST_RELEVANT_DIMENSIONS: tuple[str, ...] = tuple(
    spec.dimension
    for spec in DIMENSION_SPECS.values()
    if spec.dimension_type in (DimensionType.TRUST, DimensionType.HYBRID)
)

#: Dimensions that participate in Quality Evaluation: the Quality dimensions
#: plus the quality contribution of the Hybrid dimensions (Document 3, §7).
#: Trust dimensions do not contribute to the Quality Verdict.
QUALITY_CONTRIBUTING_DIMENSIONS: tuple[str, ...] = tuple(
    spec.dimension
    for spec in DIMENSION_SPECS.values()
    if spec.dimension_type in (DimensionType.QUALITY, DimensionType.HYBRID)
)

#: The four engines that may emit Critical Findings and can therefore gate
#: trust (Document 3, §5). Quality dimensions never appear here.
CRITICAL_FINDING_CAPABLE_DIMENSIONS: tuple[str, ...] = tuple(
    spec.dimension
    for spec in DIMENSION_SPECS.values()
    if spec.critical_finding_capability is CriticalFindingCapability.YES
)

#: The frozen orchestration schedule (Document 2, §8; Document 4, §6 and §12).
#:
#: Engines run in parallel except where cross-engine inputs force ordering.
#: Wave 1 runs the six engines with no cross-engine inputs; Novelty follows
#: because it performs a Coverage Cross-check; Engagement runs last because it
#: reuses Relevance, Coverage, Readability, and Novelty results.
EXECUTION_WAVES: tuple[tuple[str, ...], ...] = (
    ("Relevance", "Accuracy", "Coverage", "Credibility", "Readability", "Diversity"),
    ("Novelty",),
    ("Engagement",),
)

#: Which prior engine results each engine receives as ``prior_audit_results``
#: (Document 2, §8). Engines absent from this mapping have no cross-engine
#: inputs and must never read another engine's output.
CROSS_ENGINE_INPUTS: Mapping[str, tuple[str, ...]] = {
    "Novelty": ("Coverage",),
    "Engagement": ("Relevance", "Coverage", "Readability", "Novelty"),
}


def spec_for(dimension: str) -> DimensionSpec:
    """Return the frozen descriptor for ``dimension``.

    Args:
        dimension: A dimension name, e.g. ``"Credibility"``.

    Returns:
        The matching :class:`DimensionSpec`.

    Raises:
        KeyError: If ``dimension`` is not one of the frozen eight. The
            dimension set is closed; new dimensions are explicitly out of
            scope (Document 4, §14).
    """
    try:
        return DIMENSION_SPECS[dimension]
    except KeyError as exc:
        raise KeyError(
            f"{dimension!r} is not one of the eight frozen dimensions: "
            f"{', '.join(ALL_DIMENSIONS)}"
        ) from exc


# =========================================================================== #
# AI Output Auditor — new metric/layer matrix (MB1)
# =========================================================================== #
#
# The frozen metric table of the *new* evaluation framework, transcribed here
# alongside the legacy dimension matrix above (which the shipping application
# still consumes). Eighteen metrics across three layers plus a cross-cutting
# band, each with its layer and its role in the verdict (Evaluation Framework
# §1 and §8). This is the authority the new Decision Engine (MB4) will route on;
# in MB1 it is data only, and no metric runs.


class MetricRepresentation(str, Enum):
    """How a metric reports its result (Evaluation Framework §8)."""

    SCORE = "score"
    FINDINGS = "findings"
    SCORE_AND_FINDINGS = "score_and_findings"
    SCORE_OR_NA = "score_or_na"
    MECHANISM = "mechanism"


@dataclass(frozen=True)
class MetricSpec:
    """The frozen descriptor for one metric in the new framework.

    Attributes:
        metric: Human-readable metric name, e.g. ``"Faithfulness"``.
        layer: Which evaluation layer it belongs to.
        gate_role: Its role in the verdict — gating, partially gating,
            compensatory, or a cross-cutting mechanism.
        representation: How it reports (score / findings / N/A / mechanism).
        supports_na: Whether the metric may legitimately return N/A
            (Compression alone today).
        governing_question: The question the metric answers.
    """

    metric: str
    layer: Layer
    gate_role: GateRole
    representation: MetricRepresentation
    supports_na: bool
    governing_question: str


#: The frozen metric matrix (Evaluation Framework §2–§5 and §8).
METRIC_SPECS: Mapping[str, MetricSpec] = {
    spec.metric: spec
    for spec in (
        # -- Layer 1 — Grounding (gating, non-compensatory) ----------------- #
        MetricSpec(
            "Faithfulness",
            Layer.L1_GROUNDING,
            GateRole.GATING,
            MetricRepresentation.SCORE,
            False,
            "Is every claim in the output supported by the source, with nothing "
            "fabricated or contradicting it?",
        ),
        MetricSpec(
            "Hallucinations",
            Layer.L1_GROUNDING,
            GateRole.GATING,
            MetricRepresentation.FINDINGS,
            False,
            "Which content is ungrounded — intrinsic (contradicts) or extrinsic "
            "(unsupported)?",
        ),
        MetricSpec(
            "Factual & Numeric Accuracy",
            Layer.L1_GROUNDING,
            GateRole.GATING,
            MetricRepresentation.FINDINGS,
            False,
            "Are specific facts — numbers, dates, names, quantities — correct "
            "against the source?",
        ),
        MetricSpec(
            "Unsupported Claims",
            Layer.L1_GROUNDING,
            GateRole.GATING,
            MetricRepresentation.FINDINGS,
            False,
            "Which statements have no support in the source without directly "
            "contradicting it?",
        ),
        MetricSpec(
            "Contradictions",
            Layer.L1_GROUNDING,
            GateRole.GATING,
            MetricRepresentation.FINDINGS,
            False,
            "Do any output statements directly conflict with the source or with "
            "each other?",
        ),
        MetricSpec(
            "Reasoning Transparency",
            Layer.L1_GROUNDING,
            GateRole.GATING,
            MetricRepresentation.FINDINGS,
            False,
            "Do conclusions and causal claims follow from the source rather than "
            "being ungrounded inferential leaps?",
        ),
        # -- Layer 2 — Information Quality (partially gating) --------------- #
        MetricSpec(
            "Coverage",
            Layer.L2_INFO,
            GateRole.PARTIAL_GATING,
            MetricRepresentation.SCORE,
            False,
            "Does the output capture the source's important information "
            "(salience-weighted recall) without over-penalizing summarization?",
        ),
        MetricSpec(
            "Missing Critical Facts",
            Layer.L2_INFO,
            GateRole.PARTIAL_GATING,
            MetricRepresentation.FINDINGS,
            False,
            "Which specific high-salience source items are absent from the "
            "output?",
        ),
        MetricSpec(
            "Meaning Preservation",
            Layer.L2_INFO,
            GateRole.PARTIAL_GATING,
            MetricRepresentation.SCORE_AND_FINDINGS,
            False,
            "Is the source's overall meaning, proportion, emphasis, and context "
            "preserved without distortion or reversal?",
        ),
        MetricSpec(
            "Compression Quality",
            Layer.L2_INFO,
            GateRole.COMPENSATORY,
            MetricRepresentation.SCORE_OR_NA,
            True,
            "For outputs that compress the source, was the shortening a good "
            "trade-off — dropping noise, keeping signal?",
        ),
        # -- Layer 3 — Presentation Quality (compensatory) ----------------- #
        MetricSpec(
            "Readability & Coherence",
            Layer.L3_PRESENTATION,
            GateRole.COMPENSATORY,
            MetricRepresentation.SCORE,
            False,
            "Is the output clear, coherent, and fluent for its intended reader?",
        ),
        MetricSpec(
            "Structure & Organization",
            Layer.L3_PRESENTATION,
            GateRole.COMPENSATORY,
            MetricRepresentation.SCORE,
            False,
            "Is the output organized appropriately for its type (ordering, "
            "sectioning, formatting)?",
        ),
        MetricSpec(
            "Conciseness / Non-Redundancy",
            Layer.L3_PRESENTATION,
            GateRole.COMPENSATORY,
            MetricRepresentation.SCORE,
            False,
            "Is the output efficient — free of unnecessary repetition or filler "
            "— without harming coverage?",
        ),
        MetricSpec(
            "Bias / Objectivity",
            Layer.L3_PRESENTATION,
            GateRole.COMPENSATORY,
            MetricRepresentation.SCORE_AND_FINDINGS,
            False,
            "Does the output introduce slant, framing, or emphasis not present "
            "in the source?",
        ),
        # -- Cross-cutting mechanisms --------------------------------------- #
        MetricSpec(
            "Attribution",
            Layer.CROSS,
            GateRole.MECHANISM,
            MetricRepresentation.MECHANISM,
            False,
            "For every output claim, which source location supports it — or an "
            "explicit 'Not Found'?",
        ),
        MetricSpec(
            "Evidence",
            Layer.CROSS,
            GateRole.MECHANISM,
            MetricRepresentation.MECHANISM,
            False,
            "What located source↔output span pairs back every finding and score?",
        ),
        MetricSpec(
            "Confidence",
            Layer.CROSS,
            GateRole.MECHANISM,
            MetricRepresentation.MECHANISM,
            False,
            "How certain is the auditor in each metric result, reported "
            "separately from the score?",
        ),
        MetricSpec(
            "Recommendations",
            Layer.CROSS,
            GateRole.MECHANISM,
            MetricRepresentation.MECHANISM,
            False,
            "What prioritized, evidence-linked fixes should be applied?",
        ),
    )
}

#: All eighteen metric names, in framework order.
ALL_METRICS: tuple[str, ...] = tuple(METRIC_SPECS)

#: Metric names grouped by layer, in framework order.
METRICS_BY_LAYER: Mapping[Layer, tuple[str, ...]] = {
    layer: tuple(s.metric for s in METRIC_SPECS.values() if s.layer is layer)
    for layer in (Layer.L1_GROUNDING, Layer.L2_INFO, Layer.L3_PRESENTATION, Layer.CROSS)
}


def metric_spec(metric: str) -> MetricSpec:
    """Return the frozen descriptor for ``metric``.

    Args:
        metric: A metric name, e.g. ``"Coverage"``.

    Returns:
        The matching :class:`MetricSpec`.

    Raises:
        KeyError: If ``metric`` is not one of the eighteen framework metrics.
    """
    try:
        return METRIC_SPECS[metric]
    except KeyError as exc:
        raise KeyError(
            f"{metric!r} is not one of the framework metrics: "
            f"{', '.join(ALL_METRICS)}"
        ) from exc
