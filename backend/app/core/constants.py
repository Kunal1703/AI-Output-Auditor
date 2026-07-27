"""Frozen metric/layer matrix for the AI Output Auditor.

The in-code transcription of the evaluation framework: the eighteen metrics
across three layers plus a cross-cutting band, each with its layer and its role
in the verdict (gating / partially gating / compensatory / mechanism).

Nothing here is a tunable — thresholds and weights are configuration and live in
``config/settings.yaml``. This module holds only the frozen facts of the
framework, as reference data for the metric registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from app.shared.schemas import GateRole, Layer

__all__ = [
    # --- AI Output Auditor — new metric/layer matrix (MB1) ------------------ #
    "MetricRepresentation",
    "MetricSpec",
    "METRIC_SPECS",
    "ALL_METRICS",
    "METRICS_BY_LAYER",
    "metric_spec",
]


# =========================================================================== #
# AI Output Auditor — metric / layer matrix
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
