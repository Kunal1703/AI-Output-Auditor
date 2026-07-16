"""Confidence Service — the shared confidence utilities every engine uses.

Document 4 §4: "Provides the frozen confidence computation utilities each engine
already relies on (per Document 2)." Document 2 §5.10 makes Confidence
Estimation a shared component and requires it to be reported *separately from
the score*.

**That separation is the entire point.** Confidence is a first-class gate on
assertability (Document 3, §8): a high score with low confidence is never
upgraded to *Trusted* — it routes a trust-relevant dimension to *Unable to
Verify*. Folding confidence into a score would erase the difference between
"this is good" and "we could not check", which is the difference the auditor
exists to preserve.

**Division of labor.** This service combines signals; it does not invent them.
Each engine knows what makes *it* confident — Accuracy cares whether a reference
document was supplied and how many claims it could actually verify; Credibility
cares whether cited sources were reachable. Those are per-engine judgments and
live in the engines. Turning a set of signals into one number is the same
arithmetic everywhere, so it lives here.

**Why a weighted mean and not something cleverer.** Document 2 §5.10 names the
component but prescribes no formula, and §2 puts thresholds and model choices
out of scope. A weighted mean over explicit, individually-explainable signals is
the option that keeps Document 3 §13's "reconstructable from the inputs"
promise: every confidence value in a report can be traced to the signals that
produced it and re-derived by hand. A learned or opaque combiner could not.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Sequence

from app.core.logging import bind, get_logger
from app.shared.schemas import Confidence

__all__ = [
    "ConfidenceSignal",
    "ConfidenceService",
    "DefaultConfidenceService",
    "signal",
]

logger = get_logger(__name__)


@dataclass(frozen=True)
class ConfidenceSignal:
    """One input to a confidence estimate.

    Engines report *why* they are or are not confident — evidence was retrieved
    or was not, a judge returned a decisive verdict or hedged, a deterministic
    validator gave a definite answer. Keeping signals itemized rather than
    collapsing them into a bare number is what lets the report state the reason
    for *Unable to Verify* (Document 3, §8) instead of just asserting it.

    Attributes:
        name: What was measured, e.g. ``"reference_available"``.
        value: The signal's value, in [0, 1]. Higher means more confident.
        weight: Relative influence on the estimate. Must be non-negative; a
            zero-weight signal is recorded for explanation but does not move the
            number.
        rationale: Human-readable explanation, surfaced in the report.
    """

    name: str
    value: float
    weight: float = 1.0
    rationale: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 1.0:
            raise ValueError(
                f"confidence signal {self.name!r} has value {self.value}; "
                "signals must be in [0, 1]"
            )
        if self.weight < 0.0:
            raise ValueError(
                f"confidence signal {self.name!r} has negative weight {self.weight}"
            )


def signal(name: str, value: float, weight: float = 1.0, rationale: str = "") -> ConfidenceSignal:
    """Build a :class:`ConfidenceSignal`, clamping ``value`` into [0, 1].

    Engines derive signals from ratios that can drift fractionally outside the
    range through floating-point error. Clamping here keeps every call site from
    needing its own ``min(1.0, max(0.0, ...))``.
    """
    return ConfidenceSignal(
        name=name, value=min(1.0, max(0.0, value)), weight=weight, rationale=rationale
    )


class ConfidenceService(abc.ABC):
    """The interface engines use to produce their confidence value."""

    @abc.abstractmethod
    def estimate(self, signals: Sequence[ConfidenceSignal]) -> Confidence:
        """Combine signals into one confidence value in [0, 1].

        Args:
            signals: The engine's confidence signals.

        Returns:
            The confidence value for the engine's ``AuditResult``.
        """

    @abc.abstractmethod
    def degraded(self, reason: str) -> Confidence:
        """Return the confidence to report when a dimension could not be evaluated.

        Used when an engine times out or its provider fails. Document 4 §12
        requires a timed-out engine to return a low-confidence result rather
        than crash, and Document 3 §8 requires that result to read as a
        verification gap — biasing toward *Unable to Verify*, never toward a
        silent pass.

        Args:
            reason: Why the dimension degraded, for logging and the report.

        Returns:
            A confidence low enough to block a favorable trust verdict.
        """

    @abc.abstractmethod
    def explain(self, signals: Sequence[ConfidenceSignal]) -> str:
        """Render the signals as a human-readable rationale.

        Document 3 §12 requires the report to state *why* confidence is what it
        is, especially when it is low enough to force *Unable to Verify*.
        """


class DefaultConfidenceService(ConfidenceService):
    """Weighted-mean estimator over explicit, explainable signals.

    Note:
        Stateless and deterministic — the same signals always give the same
        number. That matters: Document 4 §11 wants results stable across
        re-runs, and confidence is one of the few places where a stray
        nondeterminism would be invisible rather than obvious.
    """

    def estimate(self, signals: Sequence[ConfidenceSignal]) -> Confidence:
        """Combine signals into a confidence value.

        Returns ``0.0`` for an empty signal set. That is not a neutral default —
        it is the honest one. An engine that reported no reason to be confident
        has given none, and on a trust-relevant dimension a fabricated middling
        confidence is exactly how unearned trust leaks through (Document 3, §8).

        Args:
            signals: The engine's signals.

        Returns:
            The weighted mean of the signal values, in [0, 1].
        """
        if not signals:
            return 0.0

        total_weight = sum(s.weight for s in signals)
        if total_weight <= 0.0:
            # Every signal was zero-weighted: recorded for explanation, but the
            # engine expressed no basis for confidence.
            return 0.0

        weighted = sum(s.value * s.weight for s in signals)
        return min(1.0, max(0.0, weighted / total_weight))

    def degraded(self, reason: str) -> Confidence:
        """Return the confidence for a dimension that could not be evaluated.

        Returns ``0.0``: the engine learned nothing, so it can support no
        conclusion at all. Any non-zero value would be a claim to partial
        knowledge the engine does not have, and on a trust-relevant dimension
        that is exactly how unearned trust leaks through.
        """
        logger.debug("confidence degraded", extra=bind(reason=reason))
        return 0.0

    def explain(self, signals: Sequence[ConfidenceSignal]) -> str:
        """Render the signals as a human-readable rationale.

        Ordered weakest-first: the reader wants to know what *limits* confidence,
        and burying the weakest signal under the strongest ones would answer the
        opposite question.
        """
        if not signals:
            return "No confidence signals were reported."

        ordered = sorted(signals, key=lambda s: s.value)
        parts = [
            f"{s.rationale or s.name} ({s.value:.0%})"
            for s in ordered
            if s.weight > 0.0
        ]
        return "; ".join(parts) if parts else "No weighted confidence signals."
