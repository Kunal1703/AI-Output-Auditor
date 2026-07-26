"""Bias / Objectivity — introduced slant relative to the source.

An output can be factually grounded yet editorialize (Evaluation Framework §4.4).
The key design insight is that bias here is measured **relative to the source**,
not as an absolute political lean — so an off-the-shelf classifier is the wrong
tool. This evaluator uses the deterministic half of the recommended approach
(Metric Research §14): a **loaded-language lexicon** pass over the output, where a
charged term counts as *introduced* bias only when it is **absent from the
source**. Score falls with each introduced term; each is an ``INTRODUCED_BIAS``
finding.

Compensatory Layer-3 metric — minor slant modulates the score. (Escalation of
egregious slant to a Meaning-Preservation gate is the Decision Engine's job in
MB4; this evaluator surfaces the findings it needs.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import Settings
from app.evaluators.base import band_from_score, finding_ids, to_span
from app.shared.evidence_pipeline import EvidenceCollector
from app.shared.evidence_store import EvidenceStore
from app.shared.lexicons.loaded_language import LOADED_TERMS, iter_loaded_terms
from app.shared.output_context import OutputContext
from app.shared.schemas import (
    Finding,
    FindingSeverity,
    FindingType,
    GateRole,
    Layer,
    MetricResult,
)
from app.shared.scoring import clamp
from app.shared.text_segmentation import TextSpan

__all__ = ["BiasEvaluator", "BiasResult"]

_METRIC_ID = "Bias / Objectivity"

#: Term → category, and one compiled word-boundary matcher over all terms.
_TERM_CATEGORY = {term: category for term, category in iter_loaded_terms()}
_WORD_RE = re.compile(r"[A-Za-z']+")
_LOADED_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in sorted(_TERM_CATEGORY, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

#: Cap on findings emitted, so a long opinion piece cannot flood the report.
_MAX_FINDINGS = 40


@dataclass(frozen=True)
class BiasResult:
    """The Bias / Objectivity outcome for one output."""

    metric_result: MetricResult
    findings: tuple[Finding, ...]


class BiasEvaluator:
    """Scores objectivity by introduced loaded language relative to the source.

    Args:
        settings: Supplies ``bias.*``.
    """

    metric_id = _METRIC_ID
    layer = Layer.L3_PRESENTATION
    gate_role = GateRole.COMPENSATORY

    def __init__(self, settings: Settings) -> None:
        self._cfg = settings.bias

    def evaluate(
        self, output: OutputContext, evidence_store: EvidenceStore
    ) -> BiasResult:
        """Score objectivity and surface introduced loaded language.

        Args:
            output: The output being audited (source reached via ``output.source``).
            evidence_store: The run-scoped evidence store.

        Returns:
            The Bias result — objectivity score, findings, evidence.
        """
        collector = EvidenceCollector(evidence_store, _METRIC_ID)
        ids = finding_ids("bias")

        source_words = {w.lower() for w in _WORD_RE.findall(output.source.text)}

        findings: list[Finding] = []
        introduced_terms: set[str] = set()
        for match in _LOADED_RE.finditer(output.text):
            term = match.group(0).lower()
            if term in source_words:
                continue  # present in the source too — not introduced by the output
            introduced_terms.add(term)
            if len(findings) < _MAX_FINDINGS:
                findings.append(self._bias_finding(next(ids), match, term, collector))

        penalty = min(self._cfg.max_penalty, len(introduced_terms) * self._cfg.term_penalty)
        score = clamp(1.0 - penalty)

        metric = MetricResult(
            metric_id=_METRIC_ID,
            layer=Layer.L3_PRESENTATION,
            gate_role=GateRole.COMPENSATORY,
            score=score,
            band=band_from_score(score),
            confidence=self._confidence(output.statistics.word_count),
            applicable=True,
            findings=list(findings),
            metadata={
                "introduced_terms": sorted(introduced_terms),
                "introduced_count": len(introduced_terms),
                "lexicon_categories": len(LOADED_TERMS),
            },
        )
        return BiasResult(metric_result=metric, findings=tuple(findings))

    def _bias_finding(
        self, finding_id: str, match: re.Match, term: str, collector: EvidenceCollector
    ) -> Finding:
        """A loaded term the output introduces that the source never uses."""
        span = TextSpan(
            text=match.group(0), start=match.start(), end=match.end(), kind="loaded_term"
        )
        evidence = collector.output_span(span)
        category = _TERM_CATEGORY.get(term, "loaded")
        return Finding(
            finding_id=finding_id,
            metric=_METRIC_ID,
            layer=Layer.L3_PRESENTATION,
            type=FindingType.INTRODUCED_BIAS,
            severity=FindingSeverity.MINOR,
            note=(
                f"The output introduces loaded/{category} language absent from the "
                f"source: {match.group(0)!r}."
            ),
            output_span=to_span(span, "output"),
            evidence_refs=[evidence.evidence_id],
        )

    @staticmethod
    def _confidence(word_count: int) -> float:
        """Deterministic lexical check — confident, scaled slightly by length."""
        return round(min(0.85, 0.6 + word_count / 500.0), 4)
