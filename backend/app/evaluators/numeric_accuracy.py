"""Factual & Numeric Accuracy — deterministic figure/date/quantity checking.

Numbers, dates, percentages, and quantities are *deterministically checkable*,
and this is the one dimension where a rule beats a model outright (Metric
Research §3): a fluent LLM judge will read "5.7%" as "6.0%", but arithmetic will
not. So no model is in the loop.

The check compares the output's numeric ledger against the source's (both from
:mod:`app.shared.numeric_ledger`). For each output value:

* if a **context-aligned** source value of the same kind/unit **matches** (within
  a rounding tolerance) → supported, and the source quote is recorded as
  proof-carrying evidence;
* if a context-aligned source value **differs** beyond the tolerance → a
  **Numeric Error** finding, carrying the stated value, the correct value from
  the source, and the source quote;
* if no source value shares its context → it is left to Faithfulness's
  unsupported-claim path; a merely-absent number is not, on its own, "incorrect".

"Context-aligned" means the two values sit in sentences with enough token
overlap to be about the same fact, which is what keeps the check from comparing
unrelated numbers.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.evaluators.base import band_from_score, finding_ids, to_span
from app.shared.evidence_pipeline import EvidenceCollector
from app.shared.evidence_store import EvidenceStore
from app.shared.numeric_ledger import (
    NumericKind,
    NumericMention,
    mentions_equal,
    relative_difference,
    token_overlap,
)
from app.shared.output_context import OutputContext
from app.shared.schemas import (
    Finding,
    FindingSeverity,
    FindingType,
    GateRole,
    Layer,
    MetricResult,
)
from app.shared.text_segmentation import TextSpan

__all__ = ["NumericAccuracyEvaluator", "NumericAccuracyResult"]

_METRIC_ID = "Factual & Numeric Accuracy"


@dataclass(frozen=True)
class NumericAccuracyResult:
    """The Numeric Accuracy outcome for one output.

    Attributes:
        metric_result: The standardized :class:`MetricResult`.
        errors: The Numeric Error findings (context-aligned mismatches).
    """

    metric_result: MetricResult
    errors: tuple[Finding, ...]


class NumericAccuracyEvaluator:
    """Deterministically checks the output's figures against the source.

    Args:
        settings: Supplies ``numeric.rounding_tolerance``,
            ``numeric.context_overlap_min``, and
            ``numeric.major_relative_difference``.
    """

    metric_id = _METRIC_ID
    layer = Layer.L1_GROUNDING
    gate_role = GateRole.GATING

    def __init__(self, settings: Settings) -> None:
        self._cfg = settings.numeric

    def evaluate(
        self, output: OutputContext, evidence_store: EvidenceStore
    ) -> NumericAccuracyResult:
        """Check every output numeric value against the source ledger.

        Args:
            output: The output (its source is reached via ``output.source``).
            evidence_store: The run-scoped evidence store.

        Returns:
            The Numeric Accuracy result — score, error findings, and evidence.
        """
        collector = EvidenceCollector(evidence_store, _METRIC_ID)
        ids = finding_ids("num")

        source_mentions = output.source.numeric_mentions
        output_mentions = output.numeric_mentions
        source_sentences = output.source.sentences

        errors: list[Finding] = []
        matched = 0
        checked = 0

        for mention in output_mentions:
            candidates = [s for s in source_mentions if _comparable(mention, s)]
            if not candidates:
                continue  # not verifiable against the source; not a numeric error

            # A matching value anywhere in a comparable source mention supports it.
            equal = next(
                (
                    s
                    for s in candidates
                    if mentions_equal(mention, s, self._cfg.rounding_tolerance)
                ),
                None,
            )
            if equal is not None:
                checked += 1
                matched += 1
                self._record_support(collector, mention, equal, source_sentences)
                continue

            # No match: is there a context-aligned source value that differs?
            best, overlap = self._best_context_match(
                mention, candidates, source_sentences
            )
            if best is None or overlap < self._cfg.context_overlap_min:
                continue  # differing value about a different fact; not an error

            checked += 1
            errors.append(
                self._error_finding(
                    next(ids), mention, best, source_sentences, collector
                )
            )

        score = matched / checked if checked else None
        metric = MetricResult(
            metric_id=_METRIC_ID,
            layer=Layer.L1_GROUNDING,
            gate_role=GateRole.GATING,
            score=score,
            band=band_from_score(score),
            confidence=self._confidence(checked, len(output_mentions)),
            applicable=True,
            applicability_reason=(
                ""
                if checked
                else "No output figures could be aligned to a source value."
            ),
            findings=list(errors),
            metadata={
                "output_values": len(output_mentions),
                "source_values": len(source_mentions),
                "checked": checked,
                "matched": matched,
                "errors": len(errors),
            },
        )
        return NumericAccuracyResult(metric_result=metric, errors=tuple(errors))

    def _best_context_match(
        self,
        mention: NumericMention,
        candidates: list[NumericMention],
        source_sentences: tuple[TextSpan, ...],
    ) -> tuple[NumericMention | None, float]:
        """Pick the comparable source value whose sentence best matches context."""
        best: NumericMention | None = None
        best_overlap = 0.0
        for candidate in candidates:
            overlap = token_overlap(mention.sentence, candidate.sentence)
            if overlap > best_overlap:
                best, best_overlap = candidate, overlap
        return best, best_overlap

    def _error_finding(
        self,
        finding_id: str,
        mention: NumericMention,
        source: NumericMention,
        source_sentences: tuple[TextSpan, ...],
        collector: EvidenceCollector,
    ) -> Finding:
        """Build a Numeric Error finding with proof-carrying source evidence."""
        source_sentence_span = _sentence_span(source, source_sentences)

        output_ev = collector.output_span(mention.span)
        source_ev = (
            collector.reference_passage(source_sentence_span, source_ref="source")
            if source_sentence_span is not None
            else collector.reference_passage(source.span, source_ref="source")
        )

        rel = relative_difference(mention.value, source.value)
        severity = (
            FindingSeverity.CRITICAL
            if rel >= self._cfg.major_relative_difference
            else FindingSeverity.MAJOR
        )
        return Finding(
            finding_id=finding_id,
            metric=_METRIC_ID,
            layer=Layer.L1_GROUNDING,
            type=FindingType.NUMERIC_ERROR,
            severity=severity,
            note=(
                f"Output states {mention.raw!r} but the source says "
                f"{source.raw!r} in the same context."
            ),
            output_span=to_span(mention.span, "output"),
            source_span=to_span(
                source_sentence_span or source.span, "source"
            ),
            evidence_refs=collector.refs(output_ev, source_ev),
        )

    def _record_support(
        self,
        collector: EvidenceCollector,
        mention: NumericMention,
        source: NumericMention,
        source_sentences: tuple[TextSpan, ...],
    ) -> None:
        """Record proof-carrying evidence that a value is grounded in the source."""
        collector.output_span(mention.span)
        source_sentence_span = _sentence_span(source, source_sentences)
        collector.reference_passage(
            source_sentence_span or source.span, source_ref="source"
        )

    def _confidence(self, checked: int, total: int) -> float:
        """Confidence: high (deterministic), scaled by how much was checkable."""
        if total == 0:
            return 0.5  # nothing numeric to check — neither confident nor not
        return round(0.7 + 0.3 * (checked / total), 4)


def _comparable(a: NumericMention, b: NumericMention) -> bool:
    """Whether two mentions measure the same kind of thing and are comparable."""
    if a.kind is NumericKind.DATE and b.kind is NumericKind.DATE:
        return True  # dates compare as year(-month) magnitudes
    if a.kind != b.kind:
        return False
    return a.comparable_unit == b.comparable_unit


def _sentence_span(
    mention: NumericMention, sentences: tuple[TextSpan, ...]
) -> TextSpan | None:
    """The full source sentence containing a mention, for a readable quote."""
    if 0 <= mention.sentence_index < len(sentences):
        return sentences[mention.sentence_index]
    return None
