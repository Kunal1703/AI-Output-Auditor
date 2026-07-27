"""Evidence pipeline — building, linking, and formatting located support.

Document 4 §4 gives the Evidence Store three jobs: *collects, normalizes, and
stores* evidence and *links it to ledger entries and findings*. ``evidence_store``
owns storage and id minting. This module owns the other two: turning raw
material into normalized :class:`~app.shared.schemas.EvidenceItem` objects, and
rendering them for the two audiences that consume them.

**Why this is infrastructure and not judgment.** Evidence is the *support* for a
conclusion, not the conclusion. Recording that a claim sits at characters
120–186 of the output, or that a URL returned 404, is a fact. Deciding that the
404 makes a citation fabricated is Credibility's stage 9 (Document 2, §7.4).
This module records; the engines conclude.

**Why a per-dimension collector.** Every engine writes evidence, and each would
otherwise repeat its own dimension name, its own span-to-locator conversion, and
its own kind strings on every call. That is the duplication Document 4 §15 rules
out. :class:`EvidenceCollector` binds the dimension once and offers one method
per evidence kind, so an engine writes ``collector.output_span(span)`` and gets
a normalized, linkable item back.

**Why formatting lives here.** The same evidence is read twice, by two very
different consumers: an LLM judge that needs it packed into a prompt, and a
human reading the report. Both formats derive from one item, so they belong
together — and keeping them out of the engines stops eight engines from
inventing eight prompt layouts for the same passage.
"""

from __future__ import annotations

from app.shared.evidence_store import EvidenceStore
from app.shared.schemas import EvidenceItem
from app.shared.text_segmentation import TextSpan

__all__ = [
    "EvidenceKind",
    "EvidenceCollector",
]


class EvidenceKind:
    """Evidence classes recorded by the engines.

    Constants rather than an enum: Document 2 §5.7 requires evidence collection
    of every engine but fixes no vocabulary, so an engine may introduce a kind
    of its own. These cover the cases the frozen pipelines imply.
    """

    #: A span of the AI Output — the text under audit itself.
    OUTPUT_SPAN = "output_span"
    #: A passage of the supplied reference source (Accuracy, Coverage).
    REFERENCE_PASSAGE = "reference_passage"
    #: Content fetched from an external source (Credibility, Diversity).
    RETRIEVED_SOURCE = "retrieved_source"
    #: The result of a deterministic check — a URL probe, a length count.
    VALIDATOR_RESULT = "validator_result"
    #: A span of the user's prompt (Relevance).
    PROMPT_SPAN = "prompt_span"
    #: A judge's rationale, recorded so a verdict traces to its reasoning.
    JUDGE_RATIONALE = "judge_rationale"


class EvidenceCollector:
    """A per-dimension façade over the run's :class:`EvidenceStore`.

    Args:
        store: The run-scoped evidence store. Shared across engines — ids are
            unique within the run, which is what lets a report resolve any
            reference.
        dimension: The engine's dimension, stamped on every item so the store
            never has to be told twice.

    Example:
        Recording a located claim and a failed URL probe::

            ev = collector.output_span(claim.source_span)
            probe = collector.validator_result(
                "url_resolves", "HTTP 404 for https://example.org/paper",
                source_ref="https://example.org/paper",
            )
    """

    def __init__(self, store: EvidenceStore, dimension: str) -> None:
        self._store = store
        self._dimension = dimension

    @property
    def dimension(self) -> str:
        """The dimension this collector writes for."""
        return self._dimension

    def _add(
        self,
        kind: str,
        content: str,
        locator: str | None = None,
        source_ref: str | None = None,
    ) -> EvidenceItem:
        return self._store.add(
            dimension=self._dimension,
            kind=kind,
            content=content,
            locator=locator,
            source_ref=source_ref,
        )

    def output_span(self, span: TextSpan) -> EvidenceItem:
        """Record a span of the AI Output.

        The locator is derived from the span's offsets, so the Evidence Viewer
        can highlight the exact characters rather than search for the text
        again — a search that would land on the wrong instance whenever the
        phrase repeats.
        """
        return self._add(
            EvidenceKind.OUTPUT_SPAN, content=span.text, locator=span.locator()
        )

    def prompt_span(self, span: TextSpan) -> EvidenceItem:
        """Record a span of the user's prompt."""
        return self._add(
            EvidenceKind.PROMPT_SPAN, content=span.text, locator=span.locator()
        )

    def reference_passage(
        self, span: TextSpan, source_ref: str | None = None
    ) -> EvidenceItem:
        """Record a passage of the supplied reference source."""
        return self._add(
            EvidenceKind.REFERENCE_PASSAGE,
            content=span.text,
            locator=span.locator(),
            source_ref=source_ref,
        )

    def retrieved_source(
        self, content: str, source_ref: str, locator: str | None = None
    ) -> EvidenceItem:
        """Record content fetched from an external source.

        Args:
            content: The retrieved passage.
            source_ref: Where it came from — a URL or DOI. Required: retrieved
                evidence with no provenance cannot be checked by a reader, which
                defeats the point of recording it.
            locator: Position within the source, when known.
        """
        return self._add(
            EvidenceKind.RETRIEVED_SOURCE,
            content=content,
            locator=locator,
            source_ref=source_ref,
        )

    def validator_result(
        self, check: str, detail: str, source_ref: str | None = None
    ) -> EvidenceItem:
        """Record the outcome of a deterministic check.

        The most durable evidence the auditor has: a URL probe or a word count
        carries no model variability, so it reads identically on every re-run
        (Document 4, §11).

        Args:
            check: What was checked, e.g. ``"url_resolves"``.
            detail: What was observed, e.g. ``"HTTP 404"``.
            source_ref: The subject of the check, when it has one.
        """
        return self._add(
            EvidenceKind.VALIDATOR_RESULT,
            content=f"{check}: {detail}",
            source_ref=source_ref,
        )

    def judge_rationale(self, rationale: str, locator: str | None = None) -> EvidenceItem:
        """Record a judge's stated reasoning for a verdict.

        Document 3 §13 requires every decision to be reconstructable. When a
        verdict rests on an LLM judgment, the rationale *is* the support — and
        without it the report can state the what but never the why.
        """
        return self._add(
            EvidenceKind.JUDGE_RATIONALE, content=rationale, locator=locator
        )

    def refs(self, *items: EvidenceItem | None) -> list[str]:
        """Collect ids from items, dropping ``None``.

        Convenience for building an ``evidence_refs`` list where some evidence
        is conditional — an unlocated claim has no span item, and the caller
        should not have to filter by hand.
        """
        return [item.evidence_id for item in items if item is not None]
