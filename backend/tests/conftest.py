"""Shared pytest fixtures (Document 4, §10).

**Mock the LLM and the network; keep everything else real.** Embeddings,
segmentation, validators, chunking, and the Decision Engine all run for real in
these suites — only the model and the socket are scripted. That is what §10 means
by "Mock the LLM/network in unit and engine tests for determinism and speed;
reserve real provider calls for a small E2E set", and it is why a passing suite
means something: the arithmetic under test is the arithmetic that ships.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Sequence

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.audit_engines.base import EngineServices  # noqa: E402
from app.core.config import Settings, load_settings  # noqa: E402
from app.shared.confidence_service import DefaultConfidenceService  # noqa: E402
from app.shared.context import SharedContext  # noqa: E402
from app.shared.deterministic_validators import (  # noqa: E402
    DefaultDeterministicValidators,
)
from app.shared.embedding_service import (  # noqa: E402
    LocalEmbeddingService,
    build_embedding_cache,
)
from app.shared.evidence_store import InMemoryEvidenceStore  # noqa: E402
from app.shared.llm_providers.base import ChatMessage  # noqa: E402
from app.shared.llm_service import LLMService  # noqa: E402
from app.shared.prompt_manager import FilePromptManager  # noqa: E402
from app.shared.recommendation_service import (  # noqa: E402
    DefaultRecommendationService,
)
from app.shared.retrieval_service import DefaultRetrievalService  # noqa: E402
from app.shared.schemas import InputType, PreprocessedContent  # noqa: E402
from app.shared.text_segmentation import TextSegmenter  # noqa: E402


class ScriptedLLM(LLMService):
    """Routes each call to a scripted response by a marker in the prompt.

    Matching on prompt text rather than on call order is deliberate: the engines
    run concurrently in waves, so call order is not stable and a positional fake
    would produce flaky tests that fail for reasons unrelated to the code.

    Args:
        routes: ``(marker, responder)`` pairs. The first marker found in the
            rendered prompt wins, so order from most to least specific.
    """

    def __init__(
        self, routes: Sequence[tuple[str, Callable[[str], Any] | Any]] = ()
    ) -> None:
        self._routes = list(routes)
        self.calls: list[str] = []

    async def complete(self, messages, **kwargs):  # pragma: no cover - unused
        raise NotImplementedError("scripted stages use complete_json")

    async def complete_json(self, messages: Sequence[ChatMessage], **kwargs) -> Any:
        prompt = "\n".join(m.content for m in messages)
        for marker, responder in self._routes:
            if marker in prompt:
                self.calls.append(marker)
                return responder(prompt) if callable(responder) else responder
        raise AssertionError(
            f"ScriptedLLM: no route matched. Markers: {[m for m, _ in self._routes]}"
        )

    async def health(self) -> bool:
        return True

    def call_count(self, marker: str) -> int:
        """How many times a marker was hit — proves shared derivations."""
        return sum(1 for call in self.calls if call == marker)


class FailingLLM(ScriptedLLM):
    """An LLM that always fails permanently, for degradation tests."""

    async def complete_json(self, messages, **kwargs):
        from app.core.errors import ProviderError

        raise ProviderError("scripted provider outage", retryable=False)


@pytest.fixture(scope="session")
def settings() -> Settings:
    """The real configuration, loaded once."""
    return load_settings()


@pytest.fixture(scope="session")
def embeddings(settings: Settings) -> LocalEmbeddingService:
    """One real embedding service for the session.

    Session-scoped because loading the model costs seconds and it is stateless
    across tests. The shared cache is the point of the design (Document 4, §12),
    so sharing it here mirrors production rather than diverging from it.
    """
    return LocalEmbeddingService(settings, cache=build_embedding_cache(settings))


@pytest.fixture
def make_services(
    settings: Settings, embeddings: LocalEmbeddingService
) -> Callable[[LLMService], EngineServices]:
    """Build ``EngineServices`` around a scripted LLM, everything else real."""

    def build(llm: LLMService, run_id: str = "run_test") -> EngineServices:
        prompts = FilePromptManager(settings)

        from app.shared.classification.claims import (
            ClaimCentralityAssigner,
            ClaimClassifier,
        )
        from app.shared.classification.diversity import (
            ApplicabilityClassifier,
            StanceContractDetector,
        )
        from app.shared.classification.key_points import (
            CategorySeverityAssigner,
            SalienceAssigner,
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
        from app.shared.task_identification import TaskIdentificationStage
        from app.shared.verification.claims import ClaimVerificationJudge
        from app.shared.verification.coverage import CoverageVerificationJudge
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

        return EngineServices(
            settings=settings,
            evidence_store=InMemoryEvidenceStore(run_id=run_id),
            recommendation_service=DefaultRecommendationService(run_id=run_id),
            confidence_service=DefaultConfidenceService(),
            services={
                "llm": llm,
                "embedding": embeddings,
                "retrieval": DefaultRetrievalService(settings, embeddings),
                "prompts": prompts,
                "validators": DefaultDeterministicValidators(settings),
                "segmenter": TextSegmenter(),
                "requirement_extraction": RequirementExtractionService(llm, prompts),
                "claim_extraction": ClaimExtractionService(llm, prompts),
                "key_point_extraction": KeyPointExtractionService(llm, prompts),
                "citation_extraction": CitationExtractionService(llm, prompts),
                "viewpoint_extraction": ViewpointExtractionService(llm, prompts),
                "claim_classifier": ClaimClassifier(llm, prompts),
                "claim_centrality": ClaimCentralityAssigner(llm, prompts),
                "requirement_classifier": RequirementClassifier(llm, prompts),
                "salience_assigner": SalienceAssigner(llm, prompts),
                "category_severity": CategorySeverityAssigner(llm, prompts),
                "source_classifier": SourceClassifier(llm, prompts),
                "issue_classifier": IssueClassifier(llm, prompts),
                "issue_severity": IssueSeverityAssigner(llm, prompts),
                "applicability_classifier": ApplicabilityClassifier(llm, prompts),
                "stance_contract": StanceContractDetector(llm, prompts),
                "claim_verification": ClaimVerificationJudge(llm, prompts),
                "coverage_verification": CoverageVerificationJudge(llm, prompts),
                "grounding_verification": GroundingVerificationJudge(llm, prompts),
                "requirement_evaluation": RequirementEvaluationJudge(llm, prompts),
                "readability_review": ReadabilityReviewJudge(llm, prompts),
                "functional_repetition": FunctionalRepetitionJudge(llm, prompts),
                "task_identification": TaskIdentificationStage(llm, prompts),
                "task_fitness": TaskFitnessJudge(llm, prompts),
                "manipulation_verification": ManipulationVerificationJudge(llm, prompts),
                "balance_evaluation": BalanceEvaluationJudge(llm, prompts),
                "bias_detection": BiasDetectionStage(llm, prompts),
                "claim_citation_mapper": ClaimCitationMapper(llm, prompts),
            },
        )

    return build


@pytest.fixture
def make_context() -> Callable[..., SharedContext]:
    """Build a ``SharedContext`` exactly as preprocessing does."""

    def build(
        ai_output: str,
        prompt: str | None = None,
        reference_source: str | None = None,
        audit_id: str = "aud_test",
    ) -> SharedContext:
        return SharedContext.build(
            audit_id,
            PreprocessedContent(
                content_id="cnt_test",
                ai_output=ai_output,
                prompt=prompt,
                reference_source=reference_source,
                input_type=InputType.TEXT,
            ),
        )

    return build


def assert_contract_valid(result, *, quality_engine: bool = False) -> None:
    """Assert the universal ``AuditResult`` guarantees.

    Every engine must hold these on every path, including the degraded one. They
    are asserted in one helper so that a new engine test cannot forget them.
    """
    assert not result.validate_contract(), result.validate_contract()
    assert 0.0 <= result.confidence <= 1.0
    if quality_engine:
        # Capability No (Document 2, §4.1): a Quality dimension can never gate
        # trust, so it can never emit a finding.
        assert result.critical_findings == []

    known = {item.evidence_id for item in result.evidence}
    for holder in (*result.recommendations, *result.critical_findings):
        assert holder.evidence_refs, f"{holder} carries no evidence"
        assert set(holder.evidence_refs) <= known, "dangling evidence reference"
