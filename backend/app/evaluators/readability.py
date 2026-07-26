"""Readability & Coherence — clarity heuristics over the output.

A correct output that is hard to read has low practical value (Evaluation
Framework §4.1). This evaluator **reuses the existing deterministic readability
analysis** (``DeterministicValidators.analyze_readability`` — sentence
complexity, reading indices, grammar, structure heuristics) rather than
duplicating any of it, and projects the measured outcomes onto a 0–1 score with
confidence. It is a compensatory Layer-3 metric and never gates.

The LLM coherence/fluency review that the legacy Readability engine layers on top
(weighted 3:1) is intentionally *not* invoked here — MB3 keeps this lightweight
and model-free; the deterministic heuristics alone give a defensible score and
confidence. Adding the judge later is additive.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.evaluators.base import band_from_score, finding_ids, to_span
from app.shared.deterministic_validators import DeterministicValidators, ValidationOutcome
from app.shared.evidence_pipeline import EvidenceCollector
from app.shared.evidence_store import EvidenceStore
from app.shared.output_context import OutputContext
from app.shared.schemas import (
    Finding,
    FindingSeverity,
    FindingType,
    GateRole,
    Layer,
    MetricResult,
    Severity,
    Span,
)
from app.shared.scoring import clamp
from app.shared.text_segmentation import TextSpan

__all__ = ["ReadabilityEvaluator", "ReadabilityResult"]

_METRIC_ID = "Readability & Coherence"

#: Score penalty per failed heuristic, by the validator's reported severity.
_PENALTY = {Severity.HIGH: 0.15, Severity.MEDIUM: 0.08, Severity.LOW: 0.03}


@dataclass(frozen=True)
class ReadabilityResult:
    """The Readability outcome for one output."""

    metric_result: MetricResult
    findings: tuple[Finding, ...]


class ReadabilityEvaluator:
    """Scores readability from the reused deterministic heuristics.

    Args:
        settings: Supplies ``engines.readability`` (the tuned heuristic bounds
            and confidence knobs are reused, not re-tuned).
        validators: The shared deterministic validator suite.
    """

    metric_id = _METRIC_ID
    layer = Layer.L3_PRESENTATION
    gate_role = GateRole.COMPENSATORY

    def __init__(self, settings: Settings, validators: DeterministicValidators) -> None:
        self._cfg = settings.engines.readability
        self._validators = validators

    def evaluate(
        self, output: OutputContext, evidence_store: EvidenceStore
    ) -> ReadabilityResult:
        """Score readability and surface located issues.

        Args:
            output: The output being audited.
            evidence_store: The run-scoped evidence store.

        Returns:
            The Readability result — score, confidence, findings, evidence.
        """
        collector = EvidenceCollector(evidence_store, _METRIC_ID)
        ids = finding_ids("read")
        words = output.statistics.word_count

        if words < self._cfg.min_words_for_review:
            return ReadabilityResult(
                metric_result=MetricResult(
                    metric_id=_METRIC_ID,
                    layer=Layer.L3_PRESENTATION,
                    gate_role=GateRole.COMPENSATORY,
                    score=None,
                    confidence=0.2,
                    applicable=True,
                    applicability_reason=(
                        f"The output is {words} words — too short to assess "
                        "coherence or structure."
                    ),
                    metadata={"word_count": words},
                ),
                findings=(),
            )

        outcomes = self._validators.analyze_readability(
            output.text,
            [span.text for span in output.sentences],
            thresholds=self._cfg.thresholds(),
        )
        failed = [o for o in outcomes if not o.passed]

        penalty = sum(_PENALTY.get(o.severity, 0.05) for o in failed if o.severity)
        score = clamp(1.0 - penalty)

        findings: list[Finding] = []
        for outcome in failed:
            evidence = collector.validator_result(outcome.check, outcome.detail)
            findings.append(
                Finding(
                    finding_id=next(ids),
                    metric=_METRIC_ID,
                    layer=Layer.L3_PRESENTATION,
                    type=FindingType.READABILITY_ISSUE,
                    severity=(
                        FindingSeverity.MAJOR
                        if outcome.severity is Severity.HIGH
                        else FindingSeverity.MINOR
                    ),
                    note=outcome.detail,
                    output_span=self._issue_span(outcome),
                    evidence_refs=[evidence.evidence_id],
                )
            )

        metric = MetricResult(
            metric_id=_METRIC_ID,
            layer=Layer.L3_PRESENTATION,
            gate_role=GateRole.COMPENSATORY,
            score=score,
            band=band_from_score(score),
            confidence=self._confidence(words, len(outcomes)),
            applicable=True,
            findings=list(findings),
            metadata={
                "word_count": words,
                "checks_ran": len(outcomes),
                "checks_failed": len(failed),
            },
        )
        return ReadabilityResult(metric_result=metric, findings=tuple(findings))

    @staticmethod
    def _issue_span(outcome: ValidationOutcome) -> Span | None:
        """Build an output span for an issue that carries offsets, else None."""
        start = outcome.observed.get("start")
        end = outcome.observed.get("end")
        text = outcome.observed.get("sentence") or outcome.observed.get("match")
        if isinstance(start, int) and isinstance(end, int) and isinstance(text, str):
            return to_span(TextSpan(text=text, start=start, end=end, kind="readability"), "output")
        return None

    def _confidence(self, words: int, checks_ran: int) -> float:
        """Confidence: content sufficiency blended with how many checks ran."""
        content = min(1.0, words / self._cfg.words_for_full_confidence)
        checks = min(1.0, checks_ran / self._cfg.expected_check_count)
        return round(0.6 * content + 0.4 * checks, 4)
