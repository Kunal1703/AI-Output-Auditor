"""The AuditEngine interface — the contract every dimension implements.

Document 4 §3 names this ``base.py``: "AuditEngine interface -> returns
AuditResult". Document 2 §4 gives every engine the same execution shape::

    Input → Extraction/Segmentation → Classification & Scoring →
    Verification/Evidence → Finding Detection → Score → Confidence →
    Recommendations → Output

Engines differ in their inputs, their unit of evaluation, and their verdict
vocabulary — but never in what they return. All eight produce an
``AuditResult``, which is why the Decision Engine can depend on the contract
alone and never on engine internals (Document 3, §13).

**Two objects, two jobs — do not confuse them.**

* :class:`EngineServices` — the *services* an engine may call (LLM, embedding,
  evidence store, …). Injected once at construction; identical for every engine.
* :class:`~app.shared.context.SharedContext` — the *content* under audit for one
  run, plus the store engines use to share derived work. Passed per call.

**The template-method split is the important design here.** Subclasses implement
:meth:`_execute`; callers invoke :meth:`run`. In between, :meth:`run` applies
three guarantees that Document 4 §12 requires of every engine and that no
subclass should be trusted to remember:

1. **Timeout.** A slow engine cannot stall the run past its budget.
2. **Degradation.** A failure produces a low-confidence ``AuditResult``, never
   an exception. The Decision Engine reads that as a verification gap and
   resolves toward *Unable to Verify* (Document 3, §8) — never a silent pass.
3. **Metadata correctness.** ``metadata`` is stamped from the frozen matrix in
   ``core.constants``, so an engine cannot misdeclare its own ``dimension_type``
   or critical-finding capability and thereby corrupt Decision Engine routing.

Subclasses must not override :meth:`run`.
"""

from __future__ import annotations

import abc
import asyncio
from typing import Mapping

from app.core.config import Settings
from app.core.constants import DimensionSpec, spec_for
from app.core.logging import bind, get_logger
from app.shared.confidence_service import ConfidenceService
from app.shared.context import SharedContext
from app.shared.evidence_store import EvidenceStore
from app.shared.recommendation_service import RecommendationService
from app.shared.schemas import AuditResult, AuditResultMetadata

__all__ = ["AuditEngine", "EngineServices"]

logger = get_logger(__name__)


class EngineServices:
    """The Shared Services an engine may call, injected rather than imported.

    Document 4 §4 requires services to be constructed once and handed to engines
    by dependency injection. Bundling them keeps engine constructors uniform,
    which is what allows the registry to instantiate all eight identically.

    This carries *capabilities*, not content. The content under audit arrives
    per call as a :class:`~app.shared.context.SharedContext`.

    Args:
        settings: Loaded configuration — thresholds and model selection.
        evidence_store: Run-scoped evidence store.
        recommendation_service: Recommendation shaping for this run.
        confidence_service: Shared confidence utilities.
        services: Additional shared services keyed by name — ``llm``,
            ``embedding``, ``retrieval``, ``prompts``, ``validators``. Kept as a
            mapping so an engine that needs no LLM is not forced to accept one.
    """

    def __init__(
        self,
        settings: Settings,
        evidence_store: EvidenceStore,
        recommendation_service: RecommendationService,
        confidence_service: ConfidenceService,
        services: Mapping[str, object] | None = None,
    ) -> None:
        self.settings = settings
        self.evidence = evidence_store
        self.recommendations = recommendation_service
        self.confidence = confidence_service
        self._services: Mapping[str, object] = dict(services or {})

    def service(self, name: str) -> object:
        """Return a shared service by name.

        Args:
            name: Service key, e.g. ``"llm"``.

        Returns:
            The service instance.

        Raises:
            KeyError: If the service was not wired. This is a container bug, not
                a runtime condition — fail loudly rather than degrade a
                dimension over a typo in the wiring.
        """
        try:
            return self._services[name]
        except KeyError as exc:
            raise KeyError(
                f"Shared service {name!r} was not provided to this engine. "
                f"Available: {', '.join(sorted(self._services)) or 'none'}."
            ) from exc


class AuditEngine(abc.ABC):
    """Base class for all eight Audit Engines.

    Subclasses declare :attr:`dimension` and implement :meth:`_execute`. Every
    other concern — metadata stamping, timeouts, degradation — is handled by
    :meth:`run`.

    Args:
        services: The engine's injected Shared Services and configuration.
    """

    #: The dimension this engine measures. Must be one of the frozen eight; it
    #: is the key used to look up the engine's classification and capability.
    dimension: str = ""

    def __init__(self, services: EngineServices) -> None:
        if not self.dimension:
            raise TypeError(
                f"{type(self).__name__} must declare a 'dimension' class attribute."
            )
        self.services = services
        self.spec: DimensionSpec = spec_for(self.dimension)

    @property
    def engine_id(self) -> str:
        """The engine's stable identifier, e.g. ``"ENG-ACCURACY"``."""
        return self.spec.engine_id

    def build_metadata(
        self, applicable: bool = True, applicability_reason: str = ""
    ) -> AuditResultMetadata:
        """Build the result metadata from the frozen classification matrix.

        Engines call this rather than constructing metadata by hand. The
        classification fields come from ``core.constants``, so an engine cannot
        misreport its own ``dimension_type`` or capability — the Decision Engine
        routes on those values, and a wrong one would silently misroute a trust
        dimension into the compensatory quality average.

        Args:
            applicable: Runtime applicability. Only Diversity may pass False.
            applicability_reason: Required when ``applicable`` is False, so the
                exclusion is auditable in the report (Document 3, §9).

        Returns:
            The populated metadata.

        Raises:
            ValueError: If a dimension that does not support N/A declares itself
                inapplicable, or a reason is missing.
        """
        if not applicable:
            if not self.spec.supports_na:
                raise ValueError(
                    f"{self.dimension} does not support N/A and cannot be marked "
                    "inapplicable (Document 2, §4.1)."
                )
            if not applicability_reason.strip():
                raise ValueError(
                    f"{self.dimension} must supply an applicability_reason when "
                    "returning N/A, so the exclusion is auditable."
                )
        return AuditResultMetadata(
            dimension=self.spec.dimension,
            engine_id=self.spec.engine_id,
            dimension_type=self.spec.dimension_type,
            critical_finding_capability=self.spec.critical_finding_capability,
            supports_na=self.spec.supports_na,
            applicable=applicable,
            applicability_reason=applicability_reason,
        )

    def degraded_result(self, reason: str) -> AuditResult:
        """Build the ``AuditResult`` for a dimension that could not be evaluated.

        Document 4 §12: "A timed-out engine returns a low-confidence/undetermined
        result, not a crash", and a failing trust-relevant dimension biases the
        Decision Engine toward *Unable to Verify*, never a silent pass.

        The result reports ``score=0.0`` with ``confidence=0.0``. Confidence is
        what carries the meaning: zero confidence tells the Decision Engine this
        dimension supports no conclusion at all, so the score is never read as a
        genuine failing measurement. This is exactly the "high score + low
        confidence is not assertable" machinery of Document 3 §8, applied to a
        gap rather than a judgment.

        Note the deliberate omission of a critical finding. A dimension that
        could not be evaluated has not *found* anything — manufacturing a
        finding here would forge evidence and force *Untrusted* where the honest
        answer is *Unable to Verify*.

        Args:
            reason: Why the dimension degraded. Surfaced in the report.

        Returns:
            A contract-valid, zero-confidence result.
        """
        return AuditResult(
            score=0.0,
            confidence=self.services.confidence.degraded(reason),
            ledger=[],
            evidence=[],
            recommendations=[],
            critical_findings=[],
            metadata=self.build_metadata(),
        )

    @abc.abstractmethod
    async def _execute(
        self,
        context: SharedContext,
        prior_results: Mapping[str, AuditResult],
    ) -> AuditResult:
        """Run this engine's frozen pipeline.

        Implemented by each engine following the stage sequence frozen in
        Document 2 §7 — Accuracy, Credibility, Relevance, and Coverage in
        Milestone 3; Novelty, Readability, Engagement, and Diversity in
        Milestone 4. Implementations are free to raise: :meth:`run` converts a
        failure into a degraded result.

        Args:
            context: The run's :class:`~app.shared.context.SharedContext` — the
                Engine Input Contract (``ai_output``, ``prompt``,
                ``reference_source``) plus ``get_or_compute`` for derivations
                worth sharing with the other engines rather than recomputing.
            prior_results: Results from previously executed engines, keyed by
                dimension. Populated only for the two engines with frozen
                cross-engine inputs — Novelty (Coverage) and Engagement
                (Relevance, Coverage, Readability, Novelty). Every other engine
                receives an empty mapping and must not read another engine's
                output (Document 2, §8).

        Returns:
            This dimension's ``AuditResult``.
        """

    async def run(
        self,
        context: SharedContext,
        prior_results: Mapping[str, AuditResult] | None = None,
    ) -> AuditResult:
        """Execute the engine with timeout and degradation guarantees.

        The orchestrator calls this, never :meth:`_execute`. Do not override it:
        the guarantees it applies are required of every engine, and an engine
        that bypassed them could crash a run or, worse, return a result that
        looks confident when the measurement never happened.

        Args:
            context: The run's :class:`~app.shared.context.SharedContext`.
            prior_results: Cross-engine inputs, per Document 2 §8.

        Returns:
            This dimension's ``AuditResult``. Always returns — a failure yields
            :meth:`degraded_result` rather than propagating.
        """
        timeout = self.services.settings.orchestrator.engine_timeout_seconds
        log_context = bind(
            audit_id=context.audit_id,
            dimension=self.dimension,
            engine_id=self.engine_id,
        )

        try:
            result = await asyncio.wait_for(
                self._execute(context, dict(prior_results or {})), timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.error(
                "engine timed out; degrading dimension",
                extra=bind(**log_context, timeout_s=timeout),
            )
            return self.degraded_result(
                f"{self.dimension} exceeded its {timeout}s budget and could not "
                "be evaluated."
            )
        except asyncio.CancelledError:
            # Cooperative cancellation is not an engine failure — never swallow
            # it into a degraded result, or shutdown will hang.
            raise
        except Exception as exc:
            logger.error(
                "engine failed; degrading dimension",
                extra=bind(**log_context, error=type(exc).__name__),
                exc_info=True,
            )
            return self.degraded_result(
                f"{self.dimension} could not be evaluated: {type(exc).__name__}."
            )

        violations = result.validate_contract()
        if violations:
            # A malformed result must not reach the Decision Engine looking
            # authoritative. Degrade it, so it lands on the documented
            # verification-gap path instead.
            logger.error(
                "engine returned a contract-invalid result; degrading dimension",
                extra=bind(**log_context, violations=violations),
            )
            return self.degraded_result(
                f"{self.dimension} returned a result violating the AuditResult "
                "contract."
            )
        return result
