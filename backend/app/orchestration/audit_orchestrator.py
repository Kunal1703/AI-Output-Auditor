"""Audit Orchestrator — the single owner of evaluator execution order (MB4).

This is the **only** component that sequences the pipeline. It runs each output
through the completed MB2/MB3 evaluators in dependency order, exactly once each,
then assembles the finalized ``OutputAudit`` and ``ComparativeReport``.

Execution order (per output):

    Attribution → Faithfulness → Numeric Accuracy → Coverage →
    Meaning Preservation → Readability → Conciseness → Bias

The evaluators remain pure computation units: they never call one another, the
Decision Engine, or the report builder. Where one evaluator's *output* feeds
another (Faithfulness and Coverage read the ``AttributionResult``; Meaning
Preservation reads the ``CoverageResult``), the orchestrator computes it once and
passes it in — so nothing is recomputed:

* the ``AttributionResult`` is built once and cached on the ``OutputContext``
  (no duplicate retrieval / NLI / claim extraction);
* the source's key points + embeddings are cached on the ``SourceContext`` and
  shared across outputs;
* Coverage's result is passed to Meaning Preservation rather than recomputed.
"""

from __future__ import annotations

from app.attribution.attribution import AttributionService
from app.core.config import Settings
from app.core.logging import bind, get_logger
from app.evaluators.bias import BiasEvaluator
from app.evaluators.conciseness import ConcisenessEvaluator
from app.evaluators.coverage import CoverageEvaluator
from app.evaluators.faithfulness import FaithfulnessEvaluator
from app.evaluators.meaning_preservation import MeaningPreservationEvaluator
from app.evaluators.numeric_accuracy import NumericAccuracyEvaluator
from app.evaluators.readability import ReadabilityEvaluator
from app.orchestration.assembly import assemble_output_audit, build_comparative_report
from app.orchestration.decision import GroundingDecisionEngine
from app.preprocessing.input_router import AuditContexts
from app.shared.confidence_service import ConfidenceService
from app.shared.evidence_store import InMemoryEvidenceStore
from app.shared.output_context import OutputContext
from app.shared.schemas import ComparativeReport, MetricResult, OutputAudit

__all__ = ["AuditOrchestrator"]

logger = get_logger(__name__)


class AuditOrchestrator:
    """Runs the finalized evaluation pipeline and assembles the report.

    Args:
        settings: Configuration (verdict thresholds, confidence floor).
        attribution: The MB2 attribution substrate.
        faithfulness, numeric_accuracy, coverage, meaning_preservation,
            readability, conciseness, bias: the MB2/MB3 evaluators.
        decision_engine: The MB4 layered Decision Engine.
        confidence_service: Shared confidence estimator (reused for the overall).
    """

    def __init__(
        self,
        settings: Settings,
        attribution: AttributionService,
        faithfulness: FaithfulnessEvaluator,
        numeric_accuracy: NumericAccuracyEvaluator,
        coverage: CoverageEvaluator,
        meaning_preservation: MeaningPreservationEvaluator,
        readability: ReadabilityEvaluator,
        conciseness: ConcisenessEvaluator,
        bias: BiasEvaluator,
        decision_engine: GroundingDecisionEngine,
        confidence_service: ConfidenceService,
    ) -> None:
        self._settings = settings
        self._attribution = attribution
        self._faithfulness = faithfulness
        self._numeric_accuracy = numeric_accuracy
        self._coverage = coverage
        self._meaning = meaning_preservation
        self._readability = readability
        self._conciseness = conciseness
        self._bias = bias
        self._decision = decision_engine
        self._confidence = confidence_service

    async def run(self, contexts: AuditContexts) -> ComparativeReport:
        """Audit every output against the source and assemble the report.

        Args:
            contexts: One shared ``SourceContext`` and N ``OutputContext`` from
                the input router.

        Returns:
            The finalized ``ComparativeReport``.
        """
        audits: list[OutputAudit] = []
        for output in contexts.outputs:
            audits.append(await self._audit_one(output))

        report = build_comparative_report(
            audit_id=contexts.audit_id,
            source=contexts.source.source_meta(),
            output_audits=audits,
        )
        logger.info(
            "comparative audit complete",
            extra=bind(
                audit_id=contexts.audit_id,
                outputs=len(audits),
                winner=report.comparison.ranking[0] if report.comparison.ranking else None,
                verdicts={a.output_id: a.verdict.value for a in audits},
            ),
        )
        return report

    async def _audit_one(self, output: OutputContext) -> OutputAudit:
        """Run one output through the pipeline in order, exactly once each."""
        store = InMemoryEvidenceStore(run_id=f"{output.audit_id}:{output.output_id}")

        # -- Grounding substrate (once; cached on the output) --------------- #
        attribution = await self._attribution.attribute(output, store)

        # -- Layer 1 — Grounding -------------------------------------------- #
        faithfulness = self._faithfulness.evaluate(attribution)
        numeric = self._numeric_accuracy.evaluate(output, store)

        # -- Layer 2 — Information Quality ---------------------------------- #
        coverage = await self._coverage.evaluate(output, attribution, store)
        meaning = self._meaning.evaluate(attribution, coverage)

        # -- Layer 3 — Presentation ----------------------------------------- #
        readability = self._readability.evaluate(output, store)
        conciseness = await self._conciseness.evaluate(output, store)
        bias = self._bias.evaluate(output, store)

        metric_results: list[MetricResult] = [
            faithfulness.metric_result,
            numeric.metric_result,
            coverage.metric_result,
            meaning.metric_result,
            readability.metric_result,
            conciseness.metric_result,
            bias.metric_result,
        ]

        # -- Decision + assembly (projection only) -------------------------- #
        decision = self._decision.decide(metric_results)
        audit = assemble_output_audit(
            output_id=output.output_id,
            producer=output.producer,
            output_type=output.output_type,
            metric_results=metric_results,
            faithfulness_id=faithfulness.metric_result.metric_id,
            attribution_entries=attribution.schema_entries,
            decision=decision,
            confidence_service=self._confidence,
            evidence_store=store,
            min_confidence=self._settings.verdict.min_grounding_confidence,
        )
        logger.info(
            "output audited",
            extra=bind(
                audit_id=output.audit_id,
                output_id=output.output_id,
                verdict=decision.verdict.value,
                quality=decision.quality_score,
                findings=len(audit.findings),
            ),
        )
        return audit
