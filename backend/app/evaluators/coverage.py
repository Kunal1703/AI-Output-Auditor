"""Coverage / Completeness — salience-weighted recall, derived from Attribution.

Coverage is the recall complement to Faithfulness's precision (Evaluation
Framework §3.1): did the output capture the source's *important* information,
without over-penalizing summarization? Each source key point is judged
**Covered / Partially Covered / Missing**, the score is the salience-weighted
coverage rate, and absent high-salience points become **Missing Critical Fact**
findings (§3.2).

**Reuse, not re-computation.** Per the MB3 constraint, Coverage does **not**
retrieve or run NLI again. It reuses:

* the source **key points + salience** already produced by ``SourceContext``
  (``KeyPointExtractionService`` + ``SalienceAssigner``);
* the MB2 **AttributionResult** — which output claims were entailed by which
  source sentences — to decide whether each key point's source sentence is
  reflected in the output. A source sentence that entails a supported output
  claim is *covered*; one that an output claim merely engaged (neutral) is
  *partial*; one no output claim reached is *missing*.

Salience is the weight, which is what keeps a good summary from scoring poorly:
dropping a peripheral aside barely moves the score, dropping the headline fact
moves it a lot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.attribution.attribution import AttributionResult
from app.core.config import Settings
from app.evaluators.base import band_from_score, finding_ids, to_span
from app.shared.evidence_pipeline import EvidenceCollector
from app.shared.evidence_store import EvidenceStore
from app.shared.extraction.models import KeyPoint
from app.shared.nli_service import NLILabel
from app.shared.output_context import OutputContext
from app.shared.schemas import (
    Finding,
    FindingSeverity,
    FindingType,
    GateRole,
    Layer,
    MetricResult,
)
from app.shared.scoring import importance_weighted_rate
from app.shared.text_segmentation import TextSpan

if TYPE_CHECKING:
    from app.shared.classification.key_points import SalienceAssigner
    from app.shared.extraction.key_points import KeyPointExtractionService

__all__ = ["CoverageEvaluator", "CoverageResult", "KeyPointCoverage"]

_METRIC_ID = "Coverage"

_COVERED = "covered"
_PARTIAL = "partial"
_MISSING = "missing"


@dataclass(frozen=True)
class KeyPointCoverage:
    """One source key point's coverage verdict.

    Attributes:
        key_point: The source key point.
        verdict: ``covered`` / ``partial`` / ``missing``.
        salience: Its salience in [0, 1] (0.5 when unassigned).
        located: Whether the key point was traced to a source sentence.
    """

    key_point: KeyPoint
    verdict: str
    salience: float
    located: bool


@dataclass(frozen=True)
class CoverageResult:
    """The Coverage outcome for one output.

    Attributes:
        metric_result: The standardized :class:`MetricResult`.
        missing_critical_facts: Findings for absent high-salience key points.
        key_point_coverage: Per-key-point verdicts (reused by Meaning
            Preservation).
    """

    metric_result: MetricResult
    missing_critical_facts: tuple[Finding, ...]
    key_point_coverage: tuple[KeyPointCoverage, ...]

    @property
    def covered(self) -> int:
        return sum(1 for k in self.key_point_coverage if k.verdict == _COVERED)

    @property
    def partial(self) -> int:
        return sum(1 for k in self.key_point_coverage if k.verdict == _PARTIAL)

    @property
    def missing(self) -> int:
        return sum(1 for k in self.key_point_coverage if k.verdict == _MISSING)


class CoverageEvaluator:
    """Measures completeness of an output against the source key points.

    Args:
        settings: Supplies ``coverage.*``.
        key_point_extraction: Shared key-point extraction service (reused).
        salience_assigner: Shared salience assigner (reused).
    """

    metric_id = _METRIC_ID
    layer = Layer.L2_INFO
    gate_role = GateRole.PARTIAL_GATING

    def __init__(
        self,
        settings: Settings,
        key_point_extraction: "KeyPointExtractionService",
        salience_assigner: "SalienceAssigner",
    ) -> None:
        self._cfg = settings.coverage
        self._key_point_extraction = key_point_extraction
        self._salience_assigner = salience_assigner

    async def evaluate(
        self,
        output: OutputContext,
        attribution: AttributionResult,
        evidence_store: EvidenceStore,
    ) -> CoverageResult:
        """Score coverage and surface missing critical facts.

        Args:
            output: The output being audited (its source is ``output.source``).
            attribution: The MB2 attribution map for this output (reused, not
                recomputed).
            evidence_store: The run-scoped evidence store.

        Returns:
            The Coverage result — score, missing-critical findings, per-key-point
            verdicts, and evidence.
        """
        collector = EvidenceCollector(evidence_store, _METRIC_ID)
        ids = finding_ids("cov")

        key_points = await output.source.key_points(
            self._key_point_extraction, self._salience_assigner
        )
        source_sentences = output.source.sentences
        sentence_state = self._sentence_state(attribution, source_sentences)

        coverage: list[KeyPointCoverage] = []
        outcomes: list[tuple[float, float]] = []
        findings: list[Finding] = []
        partial_credit = self._cfg.partial_credit

        for point in key_points:
            idx = self._sentence_index(point.source_span, source_sentences)
            located = idx is not None
            state = sentence_state.get(idx) if located else None
            verdict = (
                _COVERED
                if state == _COVERED
                else _PARTIAL
                if state == _PARTIAL
                else _MISSING
            )
            salience = point.salience if point.salience is not None else 0.5
            coverage.append(KeyPointCoverage(point, verdict, salience, located))

            credit = 1.0 if verdict == _COVERED else partial_credit if verdict == _PARTIAL else 0.0
            outcomes.append((credit, max(salience, 0.05)))

            # Evidence: the source passage carrying this key point.
            if point.source_span is not None:
                collector.reference_passage(point.source_span, source_ref="source")

            if verdict == _MISSING and salience >= self._cfg.critical_omission_salience:
                finding = self._missing_fact_finding(next(ids), point, salience, collector)
                if finding is not None:
                    findings.append(finding)

        score = importance_weighted_rate(outcomes, default=1.0) if outcomes else None
        metric = MetricResult(
            metric_id=_METRIC_ID,
            layer=Layer.L2_INFO,
            gate_role=GateRole.PARTIAL_GATING,
            score=score,
            band=band_from_score(score),
            confidence=self._confidence(coverage),
            applicable=True,
            applicability_reason=(
                "" if key_points else "No key points could be extracted from the source."
            ),
            findings=list(findings),
            metadata={
                "key_points": len(key_points),
                "covered": sum(1 for k in coverage if k.verdict == _COVERED),
                "partial": sum(1 for k in coverage if k.verdict == _PARTIAL),
                "missing": sum(1 for k in coverage if k.verdict == _MISSING),
                "missing_critical": len(findings),
            },
        )
        return CoverageResult(
            metric_result=metric,
            missing_critical_facts=tuple(findings),
            key_point_coverage=tuple(coverage),
        )

    def _sentence_state(
        self, attribution: AttributionResult, source_sentences: tuple[TextSpan, ...]
    ) -> dict[int, str]:
        """Map each source sentence index to covered/partial from attribution.

        A source sentence that entails a SUPPORTED output claim is covered; one
        an output claim reached but did not clearly support (neutral) is partial.
        Contradicted claims are a grounding fault (Faithfulness's domain), not
        coverage, so they do not mark a sentence covered.
        """
        start_to_index = {span.start: span.index for span in source_sentences}
        state: dict[int, str] = {}
        for att in attribution.attributions:
            if att.source_passage is None:
                continue
            idx = start_to_index.get(att.source_passage.chunk.start)
            if idx is None:
                continue
            if att.nli_label is NLILabel.SUPPORTED:
                state[idx] = _COVERED
            elif att.nli_label is NLILabel.NEUTRAL and state.get(idx) != _COVERED:
                state[idx] = _PARTIAL
        return state

    @staticmethod
    def _sentence_index(
        span: TextSpan | None, source_sentences: tuple[TextSpan, ...]
    ) -> int | None:
        """The index of the source sentence containing ``span``, if locatable."""
        if span is None:
            return None
        for sentence in source_sentences:
            if sentence.start <= span.start < sentence.end:
                return sentence.index
        return None

    def _missing_fact_finding(
        self,
        finding_id: str,
        point: KeyPoint,
        salience: float,
        collector: EvidenceCollector,
    ) -> Finding | None:
        """Build a Missing-Critical-Fact finding for an absent key point."""
        if point.source_span is None:
            # No evidence to point at in the source; a finding must be checkable.
            return None
        evidence = collector.reference_passage(point.source_span, source_ref="source")
        severity = (
            FindingSeverity.CRITICAL
            if salience >= self._cfg.critical_severity_salience
            else FindingSeverity.MAJOR
        )
        return Finding(
            finding_id=finding_id,
            metric=_METRIC_ID,
            layer=Layer.L2_INFO,
            type=FindingType.MISSING_CRITICAL_FACT,
            severity=severity,
            note=(
                f"The output omits a high-salience source key point "
                f"(salience {salience:.2f}): {point.text!r}."
            ),
            source_span=to_span(point.source_span, "source"),
            evidence_refs=[evidence.evidence_id],
            centrality=salience,
        )

    @staticmethod
    def _confidence(coverage: list[KeyPointCoverage]) -> float:
        """Confidence: how many key points could be located and judged."""
        if not coverage:
            return 0.2
        located = sum(1 for k in coverage if k.located) / len(coverage)
        return round(0.4 + 0.6 * located, 4)
