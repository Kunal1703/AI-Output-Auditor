"""Recommendation Service — standardizes the shape of engine recommendations.

Document 4 §4: "Standardizes the shape of engine-produced recommendations
(text + severity + evidence link)." Written by all engines; consumed by the
Decision Engine's prioritization (Document 3, §10).

Note the division of labor, which this module exists to keep clean:

* **Engines** decide *what* to recommend. They call this service to shape it.
* **This service** mints ids and enforces the evidence requirement.
* **The Decision Engine** orders and tiers what the engines produced. It never
  rewrites or invents a recommendation (Document 3, §10).

The evidence requirement is enforced here, at creation, rather than later during
prioritization. Document 3 §10 is unambiguous — "A recommendation without
traceable evidence is not emitted" — and catching it at the point of creation
names the engine responsible, instead of surfacing it as an anonymous dropped
entry at report time.
"""

from __future__ import annotations

import abc
import itertools
from typing import Sequence

from app.core.logging import bind, get_logger
from app.shared.schemas import Recommendation, Severity

__all__ = ["RecommendationService", "DefaultRecommendationService"]

logger = get_logger(__name__)


class RecommendationService(abc.ABC):
    """The interface engines use to produce standardized recommendations."""

    @abc.abstractmethod
    def create(
        self,
        dimension: str,
        text: str,
        severity: Severity,
        evidence_refs: Sequence[str],
    ) -> Recommendation | None:
        """Shape one engine recommendation.

        Args:
            dimension: The emitting dimension.
            text: The recommended action, in plain language.
            severity: Source severity, driving tier assignment and intra-tier
                ordering downstream.
            evidence_refs: Evidence and/or ledger ids that motivated this.
                Required.

        Returns:
            The shaped recommendation, or ``None`` if it was rejected for
            carrying no evidence.
        """


class DefaultRecommendationService(RecommendationService):
    """Mints recommendation ids and enforces the evidence requirement.

    Args:
        run_id: Optional prefix for minted ids, for log correlation.

    Note:
        Not thread-safe; see the note on
        :class:`~app.shared.evidence_store.InMemoryEvidenceStore`. Engines run
        as asyncio tasks on a single loop.
    """

    def __init__(self, run_id: str | None = None) -> None:
        self._run_id = run_id
        self._counter = itertools.count(1)

    def create(
        self,
        dimension: str,
        text: str,
        severity: Severity,
        evidence_refs: Sequence[str],
    ) -> Recommendation | None:
        """Shape one recommendation. See :meth:`RecommendationService.create`.

        Returns ``None`` rather than raising when evidence is absent. A missing
        evidence link is an engine defect worth logging, but it must not abort
        an audit — the other seven dimensions still have a verdict to deliver.
        """
        if not evidence_refs:
            logger.warning(
                "dropped recommendation with no evidence",
                extra=bind(dimension=dimension, severity=severity.value),
            )
            return None
        return Recommendation(
            recommendation_id=f"rec_{next(self._counter)}",
            dimension=dimension,
            text=text.strip(),
            severity=severity,
            evidence_refs=list(evidence_refs),
        )
