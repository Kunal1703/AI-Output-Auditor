"""Engine Orchestrator — runs the eight engines in the frozen order.

Document 4 §6 and §12 fix the schedule, and Document 2 §8 fixes why:

* **Wave 1** (parallel): Relevance, Accuracy, Coverage, Credibility,
  Readability, Diversity — no cross-engine inputs.
* **Wave 2**: Novelty — its pipeline performs a Coverage Cross-check (Document
  2, §7.5, stage 7), so Coverage must finish first.
* **Wave 3**: Engagement — its pipeline reuses Relevance, Coverage, Readability,
  and Novelty results (Document 2, §7.7, stage 3).

**The ordering is a data dependency, not a performance choice.** Running Novelty
before Coverage would not be slower, it would be *wrong* — the cross-check would
have nothing to check against. Concurrency is the system's single biggest
latency win (Document 4, §12), and the waves preserve as much of it as the
dependencies allow: six engines at once, and only two forced to be sequential.

**Why there is no error handling here.** :meth:`AuditEngine.run` already
guarantees that every engine returns an ``AuditResult`` rather than raising —
timeouts and failures become zero-confidence degraded results (Document 4, §12).
So the orchestrator can use ``asyncio.gather`` without ``return_exceptions`` and
trust that a failure in one engine cannot prevent the next wave from starting.
Adding a second layer of catching here would only obscure where degradation
actually happens.

**What the orchestrator does not do:** interpret anything. It returns eight
``AuditResult`` objects. Reading them is the Decision Engine's job, and the seam
between measurement and decision is what lets each be tested alone
(Document 1, §3).
"""

from __future__ import annotations

import asyncio
import time
from typing import Mapping, Protocol

from app.audit_engines.base import AuditEngine
from app.core.constants import ALL_DIMENSIONS, CROSS_ENGINE_INPUTS, EXECUTION_WAVES
from app.core.errors import ConfigurationError
from app.core.logging import bind, get_logger
from app.shared.context import SharedContext
from app.shared.schemas import AuditResult

__all__ = ["ProgressCallback", "EngineOrchestrator"]

logger = get_logger(__name__)


class ProgressCallback(Protocol):
    """Reports engine completion so the API can serve real progress.

    Document 4 §8 requires that "the Audit Progress step reflects actual engine
    completion from the status endpoint" — a fake progress bar would undercut a
    system whose entire premise is not overstating what it knows.
    """

    def __call__(self, completed: int, total: int, dimension: str) -> None:
        """Report that ``dimension`` finished.

        Args:
            completed: Engines finished so far.
            total: Engines in the run — always eight.
            dimension: The dimension that just finished.
        """
        ...


class EngineOrchestrator:
    """Executes the eight engines, honoring the frozen cross-engine ordering.

    Args:
        engines: Engine instances keyed by dimension, from the registry.

    Raises:
        ConfigurationError: If a dimension named in the frozen execution plan
            has no engine. Caught at construction rather than mid-run: a
            half-populated orchestrator would silently produce a report missing
            a dimension.
    """

    def __init__(self, engines: Mapping[str, AuditEngine]) -> None:
        missing = [d for wave in EXECUTION_WAVES for d in wave if d not in engines]
        if missing:
            raise ConfigurationError(
                f"Orchestrator is missing engines for: {', '.join(missing)}."
            )
        self._engines = dict(engines)

    @staticmethod
    def execution_plan() -> tuple[tuple[str, ...], ...]:
        """Return the frozen wave schedule.

        Each tuple is a wave whose engines run concurrently; waves run in order.
        Exposed so tests can assert the ordering guarantee directly (Document 4,
        §10 requires an integration test that the orchestrator honors it).

        Returns:
            The waves, in execution order.
        """
        return EXECUTION_WAVES

    @staticmethod
    def inputs_for(dimension: str) -> tuple[str, ...]:
        """Return the dimensions whose results ``dimension`` consumes.

        Args:
            dimension: The dimension about to run.

        Returns:
            The prior dimensions it receives as ``prior_audit_results``. Empty
            for the six engines with no cross-engine inputs — they must never
            read another engine's output (Document 2, §8).
        """
        return CROSS_ENGINE_INPUTS.get(dimension, ())

    @property
    def engine_count(self) -> int:
        """The number of engines in a run — the ``engines_total`` of the status
        contract (Document 4, §7)."""
        return sum(len(wave) for wave in EXECUTION_WAVES)

    def _prior_results_for(
        self, dimension: str, completed: Mapping[str, AuditResult]
    ) -> dict[str, AuditResult]:
        """Assemble the cross-engine inputs one engine is entitled to.

        Deliberately narrow. An engine receives *only* the dimensions Document 2
        §8 names for it — never the whole result set. Handing Accuracy the full
        map would let it quietly start reading Credibility, breaking the
        independence the specification relies on and creating an ordering
        dependency nobody declared.

        A named input missing from ``completed`` is omitted rather than faked.
        That happens when a prior wave degraded, and the consuming engine is the
        only thing that knows what a missing input means for its own result.
        """
        return {
            name: completed[name]
            for name in self.inputs_for(dimension)
            if name in completed
        }

    async def run(
        self,
        context: SharedContext,
        on_progress: ProgressCallback | None = None,
    ) -> dict[str, AuditResult]:
        """Execute all eight engines and return their results.

        Walks :meth:`execution_plan`, running each wave concurrently and passing
        each engine only the prior results :meth:`inputs_for` names for it. The
        same ``context`` instance goes to every engine — its lazy properties and
        ``get_or_compute`` store are what let two engines share a derivation
        instead of each paying for it.

        Args:
            context: The run's normalized content and shared derivation store.
            on_progress: Invoked as each engine completes, backing the status
                endpoint's ``engines_completed``. Exceptions raised by the
                callback are logged and swallowed — a progress reporter must
                never be able to fail an audit.

        Returns:
            One ``AuditResult`` per dimension, keyed by dimension. Always eight
            entries: a failed engine yields a degraded result, not an absence.
        """
        started = time.perf_counter()
        results: dict[str, AuditResult] = {}
        completed = 0
        total = self.engine_count

        logger.info("orchestration started", extra=bind(**context.describe()))

        for wave_number, wave in enumerate(self.execution_plan(), start=1):
            wave_started = time.perf_counter()
            logger.info(
                "wave started",
                extra=bind(
                    audit_id=context.audit_id,
                    wave=wave_number,
                    dimensions=list(wave),
                    parallel=len(wave),
                ),
            )

            # gather() without return_exceptions: AuditEngine.run is contractually
            # total — it degrades rather than raises — so an exception escaping
            # here is a bug in the framework, and it should surface loudly rather
            # than be silently collected.
            wave_results = await asyncio.gather(
                *(
                    self._engines[dimension].run(
                        context, self._prior_results_for(dimension, results)
                    )
                    for dimension in wave
                )
            )

            for dimension, result in zip(wave, wave_results):
                results[dimension] = result
                completed += 1
                self._report(on_progress, completed, total, dimension)

            logger.info(
                "wave finished",
                extra=bind(
                    audit_id=context.audit_id,
                    wave=wave_number,
                    duration_ms=round((time.perf_counter() - wave_started) * 1000, 2),
                    engines_completed=completed,
                    engines_total=total,
                ),
            )

        degraded = [d for d, r in results.items() if r.confidence == 0.0]
        logger.info(
            "orchestration finished",
            extra=bind(
                audit_id=context.audit_id,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                engines_completed=completed,
                degraded_dimensions=degraded,
                shared_derivations=list(context.derived_keys),
                shared_artifacts=list(context.artifact_keys),
            ),
        )
        return results

    @staticmethod
    def _report(
        on_progress: ProgressCallback | None,
        completed: int,
        total: int,
        dimension: str,
    ) -> None:
        """Invoke the progress callback, never letting it break the run."""
        if on_progress is None:
            return
        try:
            on_progress(completed, total, dimension)
        except Exception as exc:
            logger.warning(
                "progress callback raised; continuing",
                extra=bind(dimension=dimension, error=type(exc).__name__),
            )

    def validate_plan(self) -> None:
        """Assert the execution plan satisfies the frozen cross-engine ordering.

        Checks that every dimension appears exactly once and that each engine's
        declared inputs complete in an *earlier* wave. Cheap, and it turns a
        whole class of ordering mistakes into a startup failure rather than a
        subtly wrong audit — Novelty reading a Coverage result that had not been
        computed yet would not crash, it would just cross-check against nothing.

        Raises:
            ConfigurationError: If the plan is inconsistent with Document 2 §8.
        """
        seen: dict[str, int] = {}
        for wave_number, wave in enumerate(self.execution_plan()):
            for dimension in wave:
                if dimension in seen:
                    raise ConfigurationError(
                        f"{dimension} appears in more than one wave."
                    )
                seen[dimension] = wave_number

        missing = set(ALL_DIMENSIONS) - set(seen)
        if missing:
            raise ConfigurationError(
                f"Execution plan omits: {', '.join(sorted(missing))}."
            )

        for dimension, wave_number in seen.items():
            for required in self.inputs_for(dimension):
                if required not in seen:
                    raise ConfigurationError(
                        f"{dimension} requires {required}, which is not in the plan."
                    )
                if seen[required] >= wave_number:
                    raise ConfigurationError(
                        f"{dimension} (wave {wave_number + 1}) requires {required} "
                        f"(wave {seen[required] + 1}); inputs must complete in an "
                        "earlier wave (Document 2, §8)."
                    )
