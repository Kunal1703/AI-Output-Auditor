"""Service container — wiring and dependency injection.

Document 4 §3 designates this module ``app.py``: "wiring / dependency
injection". §4 states the rule it implements: services are "constructed once in
``app.py``" and handed to engines and the Decision Engine.

**Why a container instead of module-level globals.** Every service here is
stateful in a way that matters — the LLM provider holds a connection pool, the
embedding service holds a model and a cache, and the evidence store is scoped to
a single run. Constructing them once at startup means eight concurrent engines
share one pool rather than opening eight. Injecting them rather than importing
them means a test can swap the LLM for a fake and get deterministic, offline
engine suites (Document 4, §10).

**Three scopes, deliberately separated:**

* :class:`ServiceContainer` — **application-scoped**. Built once at startup, torn
  down at shutdown. The embedding cache lives here so it spans runs: re-auditing
  the same content, or two texts sharing boilerplate, costs one encode.
* :meth:`ServiceContainer.engine_services` — **run-scoped**. The evidence store
  and recommendation service mint ids that must be unique within a run and must
  not leak across runs. Sharing them application-wide would let evidence from
  one audit resolve inside another's report.
* The ``SharedContext`` — **per audit**, produced by Preprocessing and passed
  through the orchestrator. Carries the content and the derivation store.
"""

from __future__ import annotations

from app.audit_engines.base import EngineServices
from app.audit_engines.registry import (
    build_engines,
    registered_dimensions,
    validate_registry,
)
from app.audit_engines.orchestrator import EngineOrchestrator
from app.core.config import Settings, load_settings
from app.core.logging import bind, configure_logging, get_logger
from app.decision_engine.workflow import DecisionEngine
from app.preprocessing.content_extractor import DefaultContentExtractor
from app.preprocessing.input_router import DefaultInputRouter, InputRouter
from app.shared.confidence_service import DefaultConfidenceService
from app.shared.deterministic_validators import DefaultDeterministicValidators
from app.shared.document_analysis import warm_language_detection
from app.shared.embedding_service import LocalEmbeddingService, build_embedding_cache
from app.shared.evidence_store import InMemoryEvidenceStore
from app.shared.classification.claims import ClaimCentralityAssigner, ClaimClassifier
from app.shared.classification.key_points import (
    CategorySeverityAssigner,
    SalienceAssigner,
)
from app.shared.classification.diversity import (
    ApplicabilityClassifier,
    StanceContractDetector,
)
from app.shared.classification.readability import (
    IssueClassifier,
    IssueSeverityAssigner,
)
from app.shared.classification.requirements import RequirementClassifier
from app.shared.classification.sources import SourceClassifier
from app.shared.extraction.citations import CitationExtractionService
from app.shared.extraction.claims import ClaimExtractionService
from app.shared.extraction.key_points import KeyPointExtractionService
from app.shared.extraction.requirements import RequirementExtractionService
from app.shared.extraction.viewpoints import ViewpointExtractionService
from app.shared.mapping import ClaimCitationMapper
from app.shared.verification.claims import ClaimVerificationJudge
from app.shared.verification.coverage import CoverageVerificationJudge
from app.shared.task_identification import TaskIdentificationStage
from app.shared.verification.diversity import (
    BalanceEvaluationJudge,
    BiasDetectionStage,
)
from app.shared.verification.engagement import (
    ManipulationVerificationJudge,
    TaskFitnessJudge,
)
from app.shared.verification.grounding import GroundingVerificationJudge
from app.shared.verification.novelty import FunctionalRepetitionJudge
from app.shared.verification.readability import ReadabilityReviewJudge
from app.shared.verification.requirements import RequirementEvaluationJudge
from app.shared.llm_providers.registry import build_provider
from app.shared.llm_service import DefaultLLMService, LLMService
from app.shared.prompt_manager import FilePromptManager
from app.shared.recommendation_service import DefaultRecommendationService
from app.shared.retrieval_service import DefaultRetrievalService
from app.shared.text_segmentation import TextSegmenter

# Importing the engines package registers all eight engines by side effect, so
# validate_registry() below can prove none is missing before we serve traffic.
import app.audit_engines  # noqa: F401  (registration side effects)

__all__ = ["ServiceContainer", "build_container"]

logger = get_logger(__name__)


class ServiceContainer:
    """Holds the application-scoped services and hands them out.

    Args:
        settings: The loaded configuration. Injected so tests can build a
            container with alternative thresholds.

    Attributes:
        settings: The configuration in force.
        llm: The Shared LLM Service — the only path from an engine to a model.
        embedding_cache: The shared embedding cache. Application-scoped so
            Relevance and Novelty share one entry per text (Document 4, §12).
        embeddings: The Shared Embedding Service.
        retrieval: The Shared Retrieval Service.
        prompts: The Prompt Manager.
        validators: The Deterministic Validators.
        confidence: The Shared Confidence Estimator.
        input_router: Preprocessing entry point; produces the ``SharedContext``.
        decision_engine: The Document 3 reasoning layer.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        provider = build_provider(settings)
        self.llm: LLMService = DefaultLLMService(provider, settings)

        # Built here, not inside the embedding service: one cache shared by
        # every engine and every run is the entire point (Document 4, §12).
        self.embedding_cache = build_embedding_cache(settings)
        self.embeddings = LocalEmbeddingService(settings, cache=self.embedding_cache)

        self.retrieval = DefaultRetrievalService(settings, self.embeddings)
        self.prompts = FilePromptManager(settings)
        self.validators = DefaultDeterministicValidators(settings)
        self.confidence = DefaultConfidenceService()
        self.segmenter = TextSegmenter()

        # LLM Extraction (§5.1), Classification & Weighting (§5.2), and
        # Verification / Judge (§5.4). All stateless and provider-agnostic —
        # they hold only the LLM Service and the Prompt Manager — so they are
        # application-scoped rather than rebuilt per run.
        self.requirement_extraction = RequirementExtractionService(
            self.llm, self.prompts
        )
        self.claim_extraction = ClaimExtractionService(self.llm, self.prompts)
        self.key_point_extraction = KeyPointExtractionService(self.llm, self.prompts)
        self.citation_extraction = CitationExtractionService(self.llm, self.prompts)
        self.viewpoint_extraction = ViewpointExtractionService(self.llm, self.prompts)

        self.claim_classifier = ClaimClassifier(self.llm, self.prompts)
        self.claim_centrality = ClaimCentralityAssigner(self.llm, self.prompts)
        self.requirement_classifier = RequirementClassifier(self.llm, self.prompts)
        self.salience_assigner = SalienceAssigner(self.llm, self.prompts)
        self.category_severity = CategorySeverityAssigner(self.llm, self.prompts)
        self.source_classifier = SourceClassifier(self.llm, self.prompts)
        self.issue_classifier = IssueClassifier(self.llm, self.prompts)
        self.issue_severity = IssueSeverityAssigner(self.llm, self.prompts)
        self.applicability_classifier = ApplicabilityClassifier(self.llm, self.prompts)
        self.stance_contract = StanceContractDetector(self.llm, self.prompts)

        self.claim_verification = ClaimVerificationJudge(self.llm, self.prompts)
        self.coverage_verification = CoverageVerificationJudge(self.llm, self.prompts)
        self.grounding_verification = GroundingVerificationJudge(self.llm, self.prompts)
        self.requirement_evaluation = RequirementEvaluationJudge(self.llm, self.prompts)
        self.readability_review = ReadabilityReviewJudge(self.llm, self.prompts)
        self.functional_repetition = FunctionalRepetitionJudge(self.llm, self.prompts)
        self.task_fitness = TaskFitnessJudge(self.llm, self.prompts)
        self.manipulation_verification = ManipulationVerificationJudge(
            self.llm, self.prompts
        )
        self.balance_evaluation = BalanceEvaluationJudge(self.llm, self.prompts)
        self.bias_detection = BiasDetectionStage(self.llm, self.prompts)

        self.task_identification = TaskIdentificationStage(self.llm, self.prompts)
        self.claim_citation_mapper = ClaimCitationMapper(self.llm, self.prompts)

        self._extractor = DefaultContentExtractor(settings)
        self.input_router: InputRouter = DefaultInputRouter(self._extractor)
        # The Decision Engine shares the engines' §5.10 Confidence Estimator, so
        # a confidence figure in the report is combined by the same arithmetic
        # that produced the per-dimension figures it combines.
        self.decision_engine = DecisionEngine(settings, confidence=self.confidence)

        # Fail the boot rather than discover a missing dimension mid-audit: a
        # report is defined over all eight, and seven would be a verdict built
        # on an incomplete measurement set.
        validate_registry()
        EngineOrchestrator(build_engines(self.engine_services("startup"))).validate_plan()

        # ~575ms of profile loading, paid here instead of on the event loop
        # inside the first audit. See warm_language_detection().
        language_ready = warm_language_detection()

        templates = self.prompts.available()
        logger.info(
            "service container ready",
            extra=bind(
                llm_provider=provider.name,
                llm_model=settings.llm.model,
                llm_configured=settings.llm_configured,
                embedding_model=settings.embedding.model,
                embedding_cache=settings.embedding.cache_enabled,
                prompt_templates=len(templates),
                language_detection=language_ready,
                environment=settings.environment,
            ),
        )
        self._warn_on_missing_prompts()

    def _warn_on_missing_prompts(self) -> None:
        """Warn at startup for any extraction service whose prompt is absent.

        A missing prompt is a deployment mistake, and it surfaces as a degraded
        trust dimension — which reads in the report as "we could not verify",
        indistinguishable from a genuinely unverifiable input. Naming it at boot
        turns a confusing verdict into an obvious fix.

        Warns rather than raises: the specification is explicit that a provider
        or prompt problem degrades a dimension (Document 4, §12), and the other
        seven still have a verdict to deliver.
        """
        stages = (
            self.requirement_extraction,
            self.claim_extraction,
            self.key_point_extraction,
            self.citation_extraction,
            self.viewpoint_extraction,
            self.claim_classifier,
            self.claim_centrality,
            self.requirement_classifier,
            self.salience_assigner,
            self.category_severity,
            self.source_classifier,
            self.issue_classifier,
            self.issue_severity,
            self.applicability_classifier,
            self.stance_contract,
            self.claim_verification,
            self.coverage_verification,
            self.grounding_verification,
            self.requirement_evaluation,
            self.readability_review,
            self.functional_repetition,
            self.task_fitness,
            self.manipulation_verification,
            self.balance_evaluation,
            self.bias_detection,
            self.task_identification,
            self.claim_citation_mapper,
        )
        missing = [
            f"{s.engine}/{s.stage}.{s.version}"
            for s in stages
            if not self.prompts.exists(s.engine, s.stage, s.version)
        ]
        if missing:
            logger.warning(
                "prompt templates missing; the owning stages will degrade",
                extra=bind(missing=missing, count=len(missing)),
            )

    def engine_services(self, run_id: str) -> EngineServices:
        """Build the run-scoped service bundle for one audit.

        The evidence store and recommendation service are created fresh per run.
        Their ids (``ev_1``, ``rec_1``, …) are unique within a run only, and the
        report resolves references against them — reusing one across runs would
        let one audit's evidence resolve inside another's report.

        The embedding cache is deliberately *not* per-run: its entries are
        content-addressed by model and text, so sharing them across runs is both
        safe and the reason it exists.

        Args:
            run_id: The ``audit_id``, used to correlate logs.

        Returns:
            The services handed to every engine in this run.
        """
        return EngineServices(
            settings=self.settings,
            evidence_store=InMemoryEvidenceStore(run_id=run_id),
            recommendation_service=DefaultRecommendationService(run_id=run_id),
            confidence_service=self.confidence,
            services={
                "llm": self.llm,
                "embedding": self.embeddings,
                "retrieval": self.retrieval,
                "prompts": self.prompts,
                "validators": self.validators,
                "segmenter": self.segmenter,
                # LLM Extraction (§5.1). Each engine calls only the one its
                # frozen pipeline names.
                "requirement_extraction": self.requirement_extraction,
                "claim_extraction": self.claim_extraction,
                "key_point_extraction": self.key_point_extraction,
                "citation_extraction": self.citation_extraction,
                "viewpoint_extraction": self.viewpoint_extraction,
                # Classification & Weighting (§5.2).
                "claim_classifier": self.claim_classifier,
                "claim_centrality": self.claim_centrality,
                "requirement_classifier": self.requirement_classifier,
                "salience_assigner": self.salience_assigner,
                "category_severity": self.category_severity,
                "source_classifier": self.source_classifier,
                "issue_classifier": self.issue_classifier,
                "issue_severity": self.issue_severity,
                "applicability_classifier": self.applicability_classifier,
                "stance_contract": self.stance_contract,
                # Verification / Judge (§5.4).
                "claim_verification": self.claim_verification,
                "coverage_verification": self.coverage_verification,
                "grounding_verification": self.grounding_verification,
                "requirement_evaluation": self.requirement_evaluation,
                "readability_review": self.readability_review,
                "functional_repetition": self.functional_repetition,
                "task_fitness": self.task_fitness,
                "manipulation_verification": self.manipulation_verification,
                "balance_evaluation": self.balance_evaluation,
                "bias_detection": self.bias_detection,
                # Engagement stage 2.
                "task_identification": self.task_identification,
                # Credibility stage 3.
                "claim_citation_mapper": self.claim_citation_mapper,
            },
        )

    def orchestrator(self, run_id: str) -> EngineOrchestrator:
        """Build a run-scoped orchestrator with all eight engines.

        Args:
            run_id: The ``audit_id`` for this run.

        Returns:
            An orchestrator whose engines share this run's services.
        """
        return EngineOrchestrator(build_engines(self.engine_services(run_id)))

    async def health(self) -> dict[str, object]:
        """Collect readiness facts for ``GET /health`` (Document 4, §7).

        Returns:
            Provider identity, configuration state, provider reachability, and
            embedding-cache effectiveness.
        """
        cache = self.embeddings.cache_stats
        return {
            "llm_provider": self.settings.llm.provider,
            "llm_model": self.settings.llm.model,
            "llm_configured": self.settings.llm_configured,
            "llm_reachable": await self.llm.health(),
            "engines_registered": len(registered_dimensions()),
            "embedding_model": self.settings.embedding.model,
            "embedding_cache_enabled": self.settings.embedding.cache_enabled,
            "embedding_cache_hit_rate": round(cache.hit_rate, 4),
            "prompt_templates": len(self.prompts.available()),
        }

    async def aclose(self) -> None:
        """Release application-scoped resources on shutdown."""
        await self.llm.aclose()
        await self.embeddings.aclose()
        await self.retrieval.aclose()
        await self._extractor.aclose()
        self.embedding_cache.clear()
        logger.info("service container closed")


def build_container(settings: Settings | None = None) -> ServiceContainer:
    """Load configuration, configure logging, and build the container.

    The single composition root. Called by the FastAPI lifespan handler at
    startup, and by tests that want a real container.

    Args:
        settings: Pre-built configuration. Loaded from ``config/settings.yaml``
            plus the environment when omitted.

    Returns:
        The ready container.

    Raises:
        ConfigurationError: If configuration is invalid, the LLM provider is
            unknown, or an engine is missing. All are startup failures by
            design — better a failed boot than a wrong verdict.
    """
    resolved = settings or load_settings()
    configure_logging(level=resolved.log_level, fmt=resolved.log_format)
    return ServiceContainer(resolved)
