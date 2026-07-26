"""Metric evaluators for the AI Output Auditor (MB2+).

Each evaluator audits one output against the source for one metric of the new
evaluation framework, producing a :class:`~app.shared.schemas.MetricResult` with
evidence-linked findings. Isolated from the legacy ``audit_engines`` pipeline.

MB2 ships the Layer-1 grounding core: Faithfulness (derived from Attribution) and
the deterministic Factual & Numeric Accuracy. Later layers land in MB3+.
"""

from app.evaluators.faithfulness import FaithfulnessEvaluator, FaithfulnessResult
from app.evaluators.numeric_accuracy import (
    NumericAccuracyEvaluator,
    NumericAccuracyResult,
)

__all__ = [
    "FaithfulnessEvaluator",
    "FaithfulnessResult",
    "NumericAccuracyEvaluator",
    "NumericAccuracyResult",
]
