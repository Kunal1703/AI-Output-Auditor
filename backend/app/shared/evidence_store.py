"""Evidence Store — collects evidence and keeps every reference resolvable.

Document 4 §4: "Collects, normalizes, and stores evidence spans/passages and
links them to ledger entries and findings." Written by all engines; read by the
Decision Engine and the report builder.

This is where the evidence-first principle becomes mechanical. Document 3 §12
guarantees that every claim in the report links to an ``AuditResult`` field, and
§10 forbids emitting a recommendation with no traceable evidence. Both hold only
if evidence ids are unique within a run and every reference resolves — so this
store owns id minting and provides :meth:`resolve` for verification.

Scope is one audit run. Nothing persists across runs; persistent storage is
explicitly out of scope (Document 4, §14).
"""

from __future__ import annotations

import abc
import itertools
from typing import Iterable

from app.shared.schemas import EvidenceItem

__all__ = ["EvidenceStore", "InMemoryEvidenceStore"]


class EvidenceStore(abc.ABC):
    """The interface engines use to record evidence."""

    @abc.abstractmethod
    def add(
        self,
        dimension: str,
        kind: str,
        content: str,
        locator: str | None = None,
        source_ref: str | None = None,
    ) -> EvidenceItem:
        """Record one piece of evidence and mint its id.

        Args:
            dimension: The recording engine's dimension.
            kind: Evidence class, e.g. ``"output_span"``, ``"reference_passage"``,
                ``"retrieved_source"``, ``"validator_result"``.
            content: The located text.
            locator: Where it sits in its source, for UI highlighting.
            source_ref: Origin — URL, DOI, or reference-document id.

        Returns:
            The stored item, carrying its assigned ``evidence_id``.
        """

    @abc.abstractmethod
    def get(self, evidence_id: str) -> EvidenceItem | None:
        """Return one item by id, or None if unknown."""

    @abc.abstractmethod
    def for_dimension(self, dimension: str) -> list[EvidenceItem]:
        """Return every item recorded by one dimension, in insertion order."""

    @abc.abstractmethod
    def all(self) -> list[EvidenceItem]:
        """Return every item in the run, in insertion order."""

    @abc.abstractmethod
    def resolve(self, evidence_ids: Iterable[str]) -> tuple[list[EvidenceItem], list[str]]:
        """Resolve ids to items, reporting any that do not exist.

        Returning the dangling ids rather than raising is deliberate. A finding
        with an unresolvable pointer is a traceability defect the report must be
        able to surface honestly, not a crash — the run still has to produce a
        verdict, and Document 3 §8 says an incomplete measurement biases toward
        *Unable to Verify* rather than aborting.

        Args:
            evidence_ids: The ids to resolve.

        Returns:
            ``(found, missing)``.
        """


class InMemoryEvidenceStore(EvidenceStore):
    """Per-run, in-memory evidence store.

    Args:
        run_id: Optional prefix for minted ids, useful when debugging logs that
            interleave several runs.

    Note:
        Not thread-safe, and does not need to be. The orchestrator runs engines
        as asyncio tasks on one event loop, so ``add`` never interleaves
        mid-statement. Moving engines to threads or processes would require a
        lock here.
    """

    def __init__(self, run_id: str | None = None) -> None:
        self._run_id = run_id
        self._items: dict[str, EvidenceItem] = {}
        self._counter = itertools.count(1)

    def _next_id(self) -> str:
        return f"ev_{next(self._counter)}"

    def add(
        self,
        dimension: str,
        kind: str,
        content: str,
        locator: str | None = None,
        source_ref: str | None = None,
    ) -> EvidenceItem:
        """Record evidence and mint its id. See :meth:`EvidenceStore.add`."""
        item = EvidenceItem(
            evidence_id=self._next_id(),
            dimension=dimension,
            kind=kind,
            content=content,
            locator=locator,
            source_ref=source_ref,
        )
        self._items[item.evidence_id] = item
        return item

    def get(self, evidence_id: str) -> EvidenceItem | None:
        """Return one item by id, or None."""
        return self._items.get(evidence_id)

    def for_dimension(self, dimension: str) -> list[EvidenceItem]:
        """Return every item recorded by one dimension."""
        return [item for item in self._items.values() if item.dimension == dimension]

    def all(self) -> list[EvidenceItem]:
        """Return every item in the run."""
        return list(self._items.values())

    def resolve(
        self, evidence_ids: Iterable[str]
    ) -> tuple[list[EvidenceItem], list[str]]:
        """Resolve ids to items. See :meth:`EvidenceStore.resolve`."""
        found: list[EvidenceItem] = []
        missing: list[str] = []
        for evidence_id in evidence_ids:
            item = self._items.get(evidence_id)
            (found.append(item) if item is not None else missing.append(evidence_id))
        return found, missing
