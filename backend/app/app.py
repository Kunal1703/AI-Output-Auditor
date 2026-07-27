"""Service container — wiring and dependency injection for the AI Output Auditor.

The single composition root. Every service is constructed once here at startup
and injected into the pipeline; nothing reaches for a module-level global.

**Why a container instead of module-level globals.** Every service here is
stateful in a way that matters — the LLM provider holds a connection pool, the
embedding service holds a model and a cache, the NLI service holds the local
cross-encoder. Constructing them once means the whole pipeline shares one of each
rather than opening several, and injecting them means a test can swap the LLM for
a fake and run offline.

**Two scopes, deliberately separated:**

* :class:`ServiceContainer` — **application-scoped**. Built once at startup, torn
  down at shutdown. The embedding cache lives here so it spans runs.
* The per-output ``EvidenceStore`` — **run-scoped**, created inside the
  :class:`~app.orchestration.audit_orchestrator.AuditOrchestrator` for each
  output so evidence ids are unique within a run and never leak across runs.
"""

from __future__ import annotations

from app.attribution.attribution import AttributionService
from app.core.config import Settings, load_settings
from app.core.errors import ConfigurationError
from app.core.logging import bind, configure_logging, get_logger
from app.evaluators.bias import BiasEvaluator
from app.evaluators.conciseness import ConcisenessEvaluator
from app.evaluators.coverage import CoverageEvaluator
from app.evaluators.faithfulness import FaithfulnessEvaluator
from app.evaluators.meaning_preservation import MeaningPreservationEvaluator
from app.evaluators.numeric_accuracy import NumericAccuracyEvaluator
from app.evaluators.readability import ReadabilityEvaluator
from app.orchestration.audit_orchestrator import AuditOrchestrator
from app.orchestration.decision import GroundingDecisionEngine
from app.preprocessing.content_extractor import DefaultContentExtractor
from app.preprocessing.input_router import DefaultInputRouter, InputRouter
from app.shared.classification.key_points import SalienceAssigner
from app.shared.confidence_service import DefaultConfidenceService
from app.shared.deterministic_validators import DefaultDeterministicValidators
from app.shared.document_analysis import warm_language_detection
from app.shared.embedding_service import LocalEmbeddingService, build_embedding_cache
from app.shared.extraction.claims import ClaimExtractionService
from app.shared.extraction.key_points import KeyPointExtractionService
from app.shared.llm_providers.registry import build_provider
from app.shared.llm_service import DefaultLLMService, LLMService
from app.shared.nli_service import LocalNLIService, NLIService
from app.shared.prompt_manager import FilePromptManager
from app.shared.retrieval_service import DefaultRetrievalService

__all__ = ["ServiceContainer", "build_container"]

logger = get_logger(__name__)


class ServiceContainer:
    """Holds the application-scoped services and hands them out.

    Args:
        settings: The loaded configuration. Injected so tests can build a
            container with alternative thresholds.

    Attributes:
        settings: The configuration in force.
        llm: The Shared LLM Service — the only path to a model.
        embedding_cache: The shared embedding cache (application-scoped).
        embeddings: The Shared Embedding Service.
        nli: The local NLI cross-encoder — the backbone of Layer 1 & Attribution.
        retrieval: The Shared Retrieval Service.
        prompts: The Prompt Manager.
        validators: The Deterministic Validators (readability heuristics).
        confidence: The Shared Confidence Estimator.
        input_router: Preprocessing entry point; produces the audit contexts.
        audit_orchestrator: The sole owner of evaluator execution order.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        provider = build_provider(settings)
        self.llm: LLMService = DefaultLLMService(provider, settings)

        # Built here, not inside the embedding service: one cache shared across
        # every evaluator and every run is the point.
        self.embedding_cache = build_embedding_cache(settings)
        self.embeddings = LocalEmbeddingService(settings, cache=self.embedding_cache)

        # Local NLI cross-encoder — the backbone of Layer 1 and Attribution. Same
        # dependency class as embeddings; loaded lazily (or warmed at startup),
        # so constructing it here never pulls in torch.
        self.nli: NLIService = LocalNLIService(settings)

        self.retrieval = DefaultRetrievalService(settings, self.embeddings)
        self.prompts = FilePromptManager(settings)
        self.validators = DefaultDeterministicValidators(settings)
        self.confidence = DefaultConfidenceService()

        # LLM extraction / weighting stages the pipeline reuses. Stateless and
        # provider-agnostic (they hold only the LLM Service and Prompt Manager),
        # so they are application-scoped.
        self.claim_extraction = ClaimExtractionService(self.llm, self.prompts)
        self.key_point_extraction = KeyPointExtractionService(self.llm, self.prompts)
        self.salience_assigner = SalienceAssigner(self.llm, self.prompts)

        # -- The AI Output Auditor pipeline --------------------------------- #
        # Attribution is the grounding substrate; the seven evaluators derive
        # from it (and from the shared services); the Decision Engine turns their
        # metric results into a verdict; the orchestrator owns execution order.
        self.attribution = AttributionService(
            settings, self.retrieval, self.nli, self.embeddings, self.claim_extraction
        )
        self.faithfulness = FaithfulnessEvaluator(settings)
        self.numeric_accuracy = NumericAccuracyEvaluator(settings)
        self.coverage = CoverageEvaluator(
            settings, self.key_point_extraction, self.salience_assigner
        )
        self.meaning_preservation = MeaningPreservationEvaluator(settings)
        self.readability = ReadabilityEvaluator(settings, self.validators)
        self.conciseness = ConcisenessEvaluator(settings, self.embeddings)
        self.bias = BiasEvaluator(settings)

        self.grounding_decision = GroundingDecisionEngine(settings)
        self.audit_orchestrator = AuditOrchestrator(
            settings,
            self.attribution,
            self.faithfulness,
            self.numeric_accuracy,
            self.coverage,
            self.meaning_preservation,
            self.readability,
            self.conciseness,
            self.bias,
            self.grounding_decision,
            self.confidence,
        )

        self._extractor = DefaultContentExtractor(settings)
        self.input_router: InputRouter = DefaultInputRouter(self._extractor)

        # ~575ms of profile loading, paid here instead of on the event loop
        # inside the first audit. See warm_language_detection().
        language_ready = warm_language_detection()

        logger.info(
            "service container ready",
            extra=bind(
                llm_provider=provider.name,
                llm_model=settings.llm.model,
                llm_configured=settings.llm_configured,
                embedding_model=settings.embedding.model,
                nli_model=settings.nli.model,
                prompt_templates=len(self.prompts.available()),
                language_detection=language_ready,
                environment=settings.environment,
            ),
        )
        self._warn_on_missing_prompts()

    def _warn_on_missing_prompts(self) -> None:
        """Warn at startup for any LLM stage whose prompt template is absent.

        A missing prompt is a deployment mistake that surfaces as a degraded
        metric — indistinguishable in the report from a genuinely inconclusive
        input. Naming it at boot turns a confusing verdict into an obvious fix.
        Warns rather than raises, matching the graceful-degradation policy.
        """
        stages = (
            self.claim_extraction,
            self.key_point_extraction,
            self.salience_assigner,
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

    async def verify_model(self) -> None:
        """Fail fast if the configured model is not one the provider will serve.

        Providers retire models: a wrong model id turns every LLM stage into a
        degradation and the audit into an *Unable to Verify*. The honest place to
        catch it is startup, with a message that names the models the key has.

        Skips silently when availability cannot be determined (offline, or a
        provider with no model endpoint), so "cannot check" never hardens into a
        false startup failure.

        Raises:
            ConfigurationError: The provider enumerated its models and the
                configured one is definitively absent.
        """
        configured = self.settings.llm.model
        models = await self.llm.available_models()
        if models is None:
            logger.warning(
                "could not verify LLM model availability; proceeding",
                extra=bind(provider=self.settings.llm.provider, model=configured),
            )
            return
        if configured not in models:
            raise ConfigurationError(
                f"Configured LLM model {configured!r} is not available to the "
                f"{self.settings.llm.provider!r} key. Available models: "
                f"{', '.join(sorted(models))}. Set LLM_MODEL in backend/.env (or "
                "llm.model in config/settings.yaml) to one of these."
            )
        logger.info(
            "llm model verified as available",
            extra=bind(provider=self.settings.llm.provider, model=configured),
        )

    async def warm_nli(self) -> bool:
        """Load the NLI model at startup when configured to.

        Gated on ``nli.warm_on_startup`` so a deployment can defer the ~180MB
        load to first use. Non-fatal: a failed load (offline, no cached model)
        leaves ``nli_ready`` False and the app still boots.

        Returns:
            True if the NLI model is ready after the call, else False.
        """
        if not self.settings.nli.warm_on_startup:
            logger.info(
                "NLI warm-up skipped (nli.warm_on_startup is false)",
                extra=bind(nli_model=self.settings.nli.model),
            )
            return self.nli.is_ready
        ready = await self.nli.warm()
        logger.info(
            "NLI warm-up complete",
            extra=bind(nli_model=self.settings.nli.model, nli_ready=ready),
        )
        return ready

    async def health(self) -> dict[str, object]:
        """Collect readiness facts for ``GET /health``.

        Returns:
            Provider identity, configuration state, provider reachability,
            whether the configured model is actually served, embedding-cache
            effectiveness, and NLI-service readiness.
        """
        cache = self.embeddings.cache_stats
        models = await self.llm.available_models()
        # None -> could not enumerate; True/False only when we actually know.
        model_available = (
            None if models is None else self.settings.llm.model in models
        )
        return {
            "llm_provider": self.settings.llm.provider,
            "llm_model": self.settings.llm.model,
            "llm_configured": self.settings.llm_configured,
            "llm_reachable": await self.llm.health(),
            "llm_model_available": model_available,
            "embedding_model": self.settings.embedding.model,
            "embedding_cache_enabled": self.settings.embedding.cache_enabled,
            "embedding_cache_hit_rate": round(cache.hit_rate, 4),
            "prompt_templates": len(self.prompts.available()),
            "nli_model": self.nli.model_name,
            "nli_ready": self.nli.is_ready,
        }

    async def aclose(self) -> None:
        """Release application-scoped resources on shutdown."""
        await self.llm.aclose()
        await self.embeddings.aclose()
        await self.nli.aclose()
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
        ConfigurationError: If configuration is invalid or the LLM provider is
            unknown. A startup failure by design — better a failed boot than a
            wrong verdict.
    """
    resolved = settings or load_settings()
    configure_logging(level=resolved.log_level, fmt=resolved.log_format)
    return ServiceContainer(resolved)
