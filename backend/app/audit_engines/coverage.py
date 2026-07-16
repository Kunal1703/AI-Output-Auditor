"""Coverage Audit Engine (``ENG-COVERAGE``) — Document 2, §7.3.

**Governing question.** Does the output include all important information from
the reference source without over-penalizing summarization?

**Inputs.** Reference Source + AI Output. Unlike Accuracy, Coverage *requires*
the reference source in order to score — there is no ground truth to compare
completeness against without it (Document 2, §6.1).

**Classification.** Hybrid Dimension · Critical Finding Capability: Yes
(Critical Omissions) · Does Not Support N/A.

**Frozen pipeline (Document 2, §7.3), stage by stage.**

1. Input (Reference Source + AI Output)
2. LLM Key Point Extraction — :class:`KeyPointExtractionService` (§5.1)
3. Salience Assignment — :class:`SalienceAssigner` (§5.2)
4. Category & Severity Assignment — :class:`CategorySeverityAssigner` (§5.2)
5. Coverage Verification (Present / Partial / Absent) — :class:`CoverageVerificationJudge` (§5.4)
6. Evidence Collection
7. Critical Omission Detection
8. Coverage Score
9. Confidence
10. Recommendations

**"Without over-penalizing summarization" is the engine's hardest constraint,**
and three mechanisms serve it:

* **Salience** (stage 3) — the score weights each key point by how central it is
  to the source. A summary that drops peripheral detail barely moves; one that
  drops the headline finding moves a lot.
* **Partial credit** (stage 5) — a key point mentioned briefly is covered, if not
  in full. A two-value vocabulary would force it to Present or Absent and make
  the engine either blind to compression loss or hostile to summarizing.
* **A salience *and* severity floor on Critical Omissions** (stage 7) — only a
  high-salience, high-severity absence gates trust. Everything else is a score
  effect. Without this, every summary would be *Untrusted* for being a summary.

**A missing reference is a verification gap, not a zero.** Coverage does not
support N/A (§4.1), so it cannot excuse itself. It returns zero confidence
instead, which the Decision Engine reads as a gap and resolves toward *Unable to
Verify* (Document 3, §8) — the honest report that completeness was not assessed,
rather than a false claim that the output is incomplete.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from app.audit_engines.base import AuditEngine
from app.audit_engines.registry import register_engine
from app.core.logging import bind, get_logger
from app.shared.classification.key_points import (
    CategorySeverityAssigner,
    SalienceAssigner,
)
from app.shared.confidence_service import ConfidenceSignal, signal
from app.shared.context import SharedContext
from app.shared.evidence_pipeline import EvidenceCollector
from app.shared.extraction.key_points import KeyPointExtractionService
from app.shared.extraction.models import KeyPoint
from app.shared.schemas import (
    AuditResult,
    CriticalFinding,
    LedgerEntry,
    Severity,
    SEVERITY_ORDER,
)
from app.shared.scoring import importance_weighted_rate
from app.shared.verification.base import Judgment
from app.shared.verification.coverage import CoverageVerificationJudge
from app.shared.vocabularies import CoverageVerdict

__all__ = ["CoverageAuditEngine"]

logger = get_logger(__name__)


@register_engine
class CoverageAuditEngine(AuditEngine):
    """Measures completeness against the reference source.

    Shared Components used (Document 2, §7.3): LLM Service, Evidence Store,
    Confidence Estimator, Recommendation Generator, Prompt Templates, JSON
    Models.
    """

    dimension = "Coverage"

    async def _execute(
        self, context: SharedContext, prior_results: Mapping[str, AuditResult]
    ) -> AuditResult:
        """Run the frozen Coverage pipeline."""
        cfg = self.services.settings.engines.coverage
        collector = EvidenceCollector(self.services.evidence, self.dimension)

        if not context.has_reference_source:
            return self._no_reference_result()

        # -- Stage 2: Key Point Extraction --------------------------------- #
        extraction = await self._key_point_extraction.extract(
            context.reference_source or ""
        )
        if extraction.is_empty:
            return self._no_key_points_result()

        # -- Stage 3: Salience Assignment ---------------------------------- #
        salient = await self._salience_assigner.classify(extraction.units)

        # -- Stage 4: Category & Severity Assignment ------------------------ #
        weighted = await self._category_severity.classify(salient)

        # -- Stage 5: Coverage Verification -------------------------------- #
        judgments = await self._coverage_judge.judge(
            weighted, ai_output=context.ai_output
        )

        # -- Stage 6: Evidence Collection ---------------------------------- #
        ledger = self._build_ledger(judgments, collector)

        # -- Stage 7: Critical Omission Detection --------------------------- #
        findings = self._detect_critical_omissions(judgments, collector, cfg)

        # -- Stage 8: Coverage Score ---------------------------------------- #
        score = self._score(judgments, cfg)

        # -- Stage 9: Confidence -------------------------------------------- #
        signals = self._confidence_signals(extraction, weighted, judgments)
        confidence = self.services.confidence.estimate(signals)

        # -- Stage 10: Recommendations -------------------------------------- #
        recommendations = self._recommendations(judgments, collector)

        logger.info(
            "coverage complete",
            extra=bind(
                audit_id=context.audit_id,
                key_points=len(weighted),
                present=self._count(judgments, CoverageVerdict.PRESENT),
                partial=self._count(judgments, CoverageVerdict.PARTIAL),
                absent=self._count(judgments, CoverageVerdict.ABSENT),
                findings=len(findings),
                score=round(score, 3),
                confidence=round(confidence, 3),
            ),
        )

        return AuditResult(
            score=score,
            confidence=confidence,
            ledger=ledger,
            evidence=self.services.evidence.for_dimension(self.dimension),
            recommendations=recommendations,
            critical_findings=findings,
            metadata=self.build_metadata(),
        )

    # -- Injected services -------------------------------------------------- #

    @property
    def _key_point_extraction(self) -> KeyPointExtractionService:
        return self.services.service("key_point_extraction")  # type: ignore[return-value]

    @property
    def _salience_assigner(self) -> SalienceAssigner:
        return self.services.service("salience_assigner")  # type: ignore[return-value]

    @property
    def _category_severity(self) -> CategorySeverityAssigner:
        return self.services.service("category_severity")  # type: ignore[return-value]

    @property
    def _coverage_judge(self) -> CoverageVerificationJudge:
        return self.services.service("coverage_verification")  # type: ignore[return-value]

    # -- Stage 6 ------------------------------------------------------------ #

    def _build_ledger(
        self,
        judgments: Sequence[Judgment[KeyPoint, CoverageVerdict]],
        collector: EvidenceCollector,
    ) -> list[LedgerEntry]:
        """Build the Coverage Ledger (Document 2, §6.3)."""
        entries: list[LedgerEntry] = []
        for judgment in judgments:
            point = judgment.unit
            refs: list[str] = []
            if point.source_span:
                refs.append(
                    collector.reference_passage(
                        point.source_span, source_ref="reference_source"
                    ).evidence_id
                )
            if judgment.rationale:
                refs.append(collector.judge_rationale(judgment.rationale).evidence_id)

            entries.append(
                LedgerEntry(
                    entry_id=point.key_point_id,
                    unit=point.text,
                    unit_type="Key Point",
                    verdict=(
                        judgment.verdict.value if judgment.verdict else "Not evaluated"
                    ),
                    severity=(
                        point.severity
                        if judgment.verdict is CoverageVerdict.ABSENT
                        else None
                    ),
                    evidence_refs=refs,
                    rationale=judgment.rationale
                    or "The coverage stage returned no verdict for this key point.",
                    attributes={
                        "salience": point.salience,
                        "category": point.category,
                        "omission_severity": (
                            point.severity.value if point.severity else None
                        ),
                    },
                )
            )
        return entries

    # -- Stage 7 ------------------------------------------------------------ #

    def _detect_critical_omissions(
        self,
        judgments: Sequence[Judgment[KeyPoint, CoverageVerdict]],
        collector: EvidenceCollector,
        cfg,
    ) -> list[CriticalFinding]:
        """Raise Critical Omissions for high-salience, high-severity absences.

        Coverage's critical-finding class (Document 2, §6.5): the finding is
        carried in ``critical_findings``, not a separate field.

        **Four filters, and every one protects summarization.** An omission
        qualifies only if it is *Absent* (not Partial), *salient* above the
        floor, *severe* above the floor, and *traceable* to the reference. Drop
        any of them and a legitimate summary — which omits by design — starts
        producing trust gates for doing its job.
        """
        findings: list[CriticalFinding] = []

        for judgment in judgments:
            if judgment.verdict is not CoverageVerdict.ABSENT:
                continue

            point = judgment.unit
            if point.salience is None or point.salience < cfg.critical_omission_salience:
                continue
            if point.severity is None:
                continue
            if SEVERITY_ORDER[point.severity] < SEVERITY_ORDER[cfg.critical_omission_severity]:
                continue

            refs: list[str] = []
            if point.source_span:
                refs.append(
                    collector.reference_passage(
                        point.source_span, source_ref="reference_source"
                    ).evidence_id
                )
            if judgment.rationale:
                refs.append(collector.judge_rationale(judgment.rationale).evidence_id)
            if not refs:
                # Document 3 §12 requires every finding to carry evidence. An
                # omission we cannot point to in the source cannot be shown to
                # a reader, so it stays in the ledger and out of the gate.
                logger.warning(
                    "critical omission has no evidence; not raising a finding",
                    extra=bind(key_point_id=point.key_point_id),
                )
                continue

            findings.append(
                CriticalFinding(
                    finding_id=f"cf_{point.key_point_id}",
                    dimension=self.dimension,
                    type="Critical omission",
                    severity=point.severity,
                    description=(
                        f"The output omits a key point of the source: "
                        f"{point.text!r}. {judgment.rationale}".strip()
                    ),
                    evidence_refs=refs,
                    centrality=point.salience,
                )
            )

        findings.sort(
            key=lambda f: (SEVERITY_ORDER[f.severity], f.centrality or 0.0),
            reverse=True,
        )
        return findings

    # -- Stage 8 ------------------------------------------------------------ #

    @staticmethod
    def _score(
        judgments: Sequence[Judgment[KeyPoint, CoverageVerdict]], cfg
    ) -> float:
        """Compute the Coverage score.

        Salience-weighted coverage rate:

        * **Present** → credit 1.0
        * **Partial** → credit ``coverage.partial_credit`` (0.5 by default)
        * **Absent** → credit 0.0
        * unjudged → excluded, like Accuracy's Unverifiable claims

        Salience is the weight, and it is what makes the score fair to
        summaries. A summary that keeps every salient point and drops the
        peripheral ones scores well — which is correct, because that is a good
        summary. A plain coverage rate would score it poorly for the same
        behavior.

        Returns:
            The score in [0, 1]. Every key point carries a small floor weight so
            that a source whose points were all judged salience-zero still
            produces a meaningful rate rather than a divide-by-nothing.
        """
        credit = {
            CoverageVerdict.PRESENT: 1.0,
            CoverageVerdict.PARTIAL: cfg.partial_credit,
            CoverageVerdict.ABSENT: 0.0,
        }
        outcomes: list[tuple[float, float]] = []
        for judgment in judgments:
            if judgment.verdict is None:
                continue
            salience = judgment.unit.salience
            importance = salience if salience is not None else 0.5
            outcomes.append((credit[judgment.verdict], max(importance, 0.05)))

        return importance_weighted_rate(outcomes, default=1.0)

    # -- Stage 9 ------------------------------------------------------------ #

    def _confidence_signals(
        self,
        extraction,
        points: Sequence[KeyPoint],
        judgments: Sequence[Judgment[KeyPoint, CoverageVerdict]],
    ) -> list[ConfidenceSignal]:
        """Report why Coverage is or is not confident in its own judgment."""
        total = len(points)
        judged = sum(1 for j in judgments if j.is_judged)
        weighted = sum(1 for p in points if p.salience is not None)
        categorized = sum(1 for p in points if p.severity is not None)

        signals = [
            signal(
                "key_points_judged",
                judged / total if total else 0.0,
                weight=4.0,
                rationale=(
                    f"{judged} of {total} key points were checked against the output"
                ),
            ),
            signal(
                "salience_assigned",
                weighted / total if total else 0.0,
                weight=3.0,
                rationale=(
                    f"{weighted} of {total} key points carry a salience; without "
                    "it, the score cannot distinguish a fair summary from a gap"
                ),
            ),
            signal(
                "severity_assigned",
                categorized / total if total else 0.0,
                weight=2.0,
                rationale=(
                    f"{categorized} of {total} key points carry an omission "
                    "severity; an omission without one cannot gate trust"
                ),
            ),
            signal(
                "key_points_located",
                extraction.location_rate,
                weight=1.0,
                rationale=(
                    f"{extraction.located_count} of {len(extraction.units)} key "
                    "points were traced to a passage of the source"
                ),
            ),
        ]
        if extraction.truncated:
            signals.append(
                signal(
                    "reference_complete",
                    0.0,
                    weight=3.0,
                    rationale=(
                        "The reference source was truncated for extraction, so "
                        "some key points were never seen and their omission "
                        "could not be detected"
                    ),
                )
            )

        hints = [j.confidence_hint for j in judgments if j.confidence_hint is not None]
        signals.append(
            signal(
                "verification_certainty",
                sum(hints) / len(hints) if hints else 0.5,
                weight=2.0,
                rationale=(
                    f"The coverage verifier reported a mean certainty of "
                    f"{(sum(hints) / len(hints)) if hints else 0.5:.0%}"
                ),
            )
        )
        return signals

    # -- Stage 10 ----------------------------------------------------------- #

    def _recommendations(
        self,
        judgments: Sequence[Judgment[KeyPoint, CoverageVerdict]],
        collector: EvidenceCollector,
    ):
        """Produce recommendations for absent and partially covered key points.

        Ordered by salience so the most consequential gap is proposed first —
        the Decision Engine orders across dimensions (Document 3, §10), but
        within Coverage the engine already knows which omission matters most.
        """
        ranked = sorted(
            judgments,
            key=lambda j: (j.unit.salience or 0.0),
            reverse=True,
        )
        recommendations = []

        for judgment in ranked:
            point = judgment.unit
            if judgment.verdict not in (CoverageVerdict.ABSENT, CoverageVerdict.PARTIAL):
                continue
            if not point.source_span:
                continue

            refs = [
                collector.reference_passage(
                    point.source_span, source_ref="reference_source"
                ).evidence_id
            ]

            if judgment.verdict is CoverageVerdict.ABSENT:
                severity = point.severity or Severity.MEDIUM
                text = f"Add the omitted key point: {point.text!r}."
            else:
                severity = Severity.LOW
                text = (
                    f"Expand on the partially covered key point: {point.text!r}. "
                    "The output mentions it but does not convey it fully."
                )

            created = self.services.recommendations.create(
                dimension=self.dimension,
                text=text,
                severity=severity,
                evidence_refs=refs,
            )
            if created is not None:
                recommendations.append(created)

        return recommendations

    # -- Early exits -------------------------------------------------------- #

    def _no_reference_result(self) -> AuditResult:
        """Result when no reference source was supplied.

        Document 2 §6.1 requires a reference for Coverage to score, and §4.1
        forbids Coverage from returning N/A — so it cannot excuse itself the way
        Diversity can. The resolution is a **verification gap**: zero
        confidence, which the Decision Engine reads as "not measured" and
        resolves toward *Unable to Verify* (Document 3, §8).

        The alternative — scoring 0.0 with real confidence — would assert that
        the output *is* incomplete, on the basis of never having looked. That is
        the false accusation this design exists to prevent, and it would be
        levelled at every audit submitted without ground truth.
        """
        return AuditResult(
            score=0.0,
            confidence=0.0,
            ledger=[],
            evidence=[],
            recommendations=[],
            critical_findings=[],
            metadata=self.build_metadata(),
        )

    def _no_key_points_result(self) -> AuditResult:
        """Result when extraction found no key points in the reference.

        Rare and suspicious: a reference document with nothing important in it is
        more likely an extraction failure than a genuinely empty source. Low
        confidence says so rather than reporting perfect coverage of nothing.
        """
        return AuditResult(
            score=1.0,
            confidence=0.2,
            ledger=[],
            evidence=[],
            recommendations=[],
            critical_findings=[],
            metadata=self.build_metadata(),
        )

    @staticmethod
    def _count(
        judgments: Sequence[Judgment[KeyPoint, CoverageVerdict]],
        verdict: CoverageVerdict,
    ) -> int:
        """Count judgments with a given verdict."""
        return sum(1 for j in judgments if j.verdict is verdict)
