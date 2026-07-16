"""Accuracy Audit Engine (``ENG-ACCURACY``) — Document 2, §7.2.

**Governing question.** Is every factual claim supported, contradicted, or
unverifiable against available evidence?

**Inputs.** AI Output + Reference Source (if available).

**Classification.** Trust Dimension · Critical Finding Capability: Yes ·
Does Not Support N/A.

**Frozen pipeline (Document 2, §7.2), stage by stage.**

1. Input (AI Output + Reference Source if available)
2. LLM-based Claim Extraction — :class:`ClaimExtractionService` (§5.1)
3. Claim Classification (Factual / Opinion / Non-verifiable) — :class:`ClaimClassifier`
4. Claim Centrality & Severity Assignment — :class:`ClaimCentralityAssigner`
5. Evidence Retrieval (Reference Document first; external retrieval optional)
6. LLM-based Claim Verification — :class:`ClaimVerificationJudge`
7. Verdict per Claim (Supported / Contradicted / Unverifiable)
8. Evidence Collection — :class:`EvidenceCollector`
9. Critical Finding Detection
10. Confidence Estimation
11. Final Accuracy Score

**Three decisions in this engine deserve to be understood before changing it.**

*Unverifiable claims are excluded from the score, not scored as zero.* The score
answers "of what could be checked, how much held up?" A claim the evidence could
not settle has not failed — nothing was learned about it. Scoring it zero would
report unverified content as *inaccurate*, which is a false accusation. Instead
it drives **confidence** down, and low confidence on a Trust dimension routes the
run to *Unable to Verify* (Document 3, §8). That is the two-axis design working
exactly as intended: the score says what the evidence showed, the confidence says
how much evidence there was.

*Reference-first is frozen and is not a preference.* Stage 5 consults the
supplied reference before anything external, and external retrieval stays
opt-in. Without a reference and without that option, claims are legitimately
Unverifiable — which is the honest outcome, not a defect.

*A contradicted claim is a Critical Finding regardless of the score.* Stage 9
does not consult the score. One contradicted central claim gates trust
non-compensatorily (Document 3, §5) even if nineteen other claims are supported
and the score is 0.95. The score and the gate are separate mechanisms and the
engine must not let one speak for the other.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from app.audit_engines.base import AuditEngine
from app.audit_engines.registry import register_engine
from app.core.logging import bind, get_logger
from app.shared.classification.claims import ClaimCentralityAssigner, ClaimClassifier
from app.shared.confidence_service import ConfidenceSignal, signal
from app.shared.context import SharedContext, SharedKeys
from app.shared.evidence_pipeline import EvidenceCollector
from app.shared.extraction.claims import ClaimExtractionService
from app.shared.extraction.models import Claim
from app.shared.retrieval_service import Chunk, RetrievalService
from app.shared.schemas import (
    AuditResult,
    CriticalFinding,
    EvidenceItem,
    LedgerEntry,
    Severity,
    SEVERITY_ORDER,
)
from app.shared.scoring import importance_weighted_rate
from app.shared.verification.base import Judgment
from app.shared.verification.claims import ClaimVerificationJudge
from app.shared.vocabularies import ClaimType, ClaimVerdict

__all__ = ["AccuracyAuditEngine"]

logger = get_logger(__name__)

@register_engine
class AccuracyAuditEngine(AuditEngine):
    """Verifies factual claims against available evidence.

    Shared Components used (Document 2, §7.2): LLM Service, Retrieval Service,
    Evidence Store, Confidence Estimator, Recommendation Generator, Prompt
    Templates, JSON Models.
    """

    dimension = "Accuracy"

    async def _execute(
        self, context: SharedContext, prior_results: Mapping[str, AuditResult]
    ) -> AuditResult:
        """Run the frozen Accuracy pipeline."""
        cfg = self.services.settings.engines.accuracy
        collector = EvidenceCollector(self.services.evidence, self.dimension)

        # -- Stage 2: Claim Extraction ------------------------------------- #
        # Shared with Credibility, which needs the same claims to map citations
        # against (§7.4, stage 3). Both engines run in wave 1, so this is one
        # extraction call rather than two.
        extraction = await context.get_or_compute(
            SharedKeys.EXTRACTED_CLAIMS,
            lambda: self._claim_extraction.extract(context.ai_output),
        )
        if extraction.is_empty:
            return self._no_claims_result(context, extraction.truncated)

        # -- Stage 3: Claim Classification --------------------------------- #
        classified = await self._claim_classifier.classify(extraction.units)

        # -- Stage 4: Centrality & Severity -------------------------------- #
        # Only factual claims proceed. An opinion has no truth value, so the
        # severity of it being "wrong" is not a coherent question.
        factual = tuple(c for c in classified if c.claim_type is ClaimType.FACTUAL)
        non_factual = tuple(c for c in classified if c.claim_type is not ClaimType.FACTUAL)

        if not factual:
            return self._no_factual_claims_result(context, classified, collector)

        weighted = await self._centrality_assigner.classify(factual)

        # -- Stage 5: Evidence Retrieval (reference first) ------------------ #
        chunks = await self._reference_chunks(context)
        evidence_by_claim = await self._retrieve_evidence(weighted, chunks, collector, cfg)

        # -- Stage 6-7: Verification and per-claim verdict ------------------ #
        all_evidence = [
            item for items in evidence_by_claim.values() for item in items
        ]
        judgments = await self._verification_judge.judge(weighted, all_evidence)

        # -- Stage 8: Evidence Collection ---------------------------------- #
        ledger = self._build_ledger(
            judgments, non_factual, evidence_by_claim, collector
        )

        # -- Stage 9: Critical Finding Detection --------------------------- #
        findings = self._detect_critical_findings(judgments, evidence_by_claim, cfg)

        # -- Stage 10: Confidence Estimation -------------------------------- #
        signals = self._confidence_signals(
            context, extraction, weighted, judgments, evidence_by_claim
        )
        confidence = self.services.confidence.estimate(signals)

        # -- Stage 11: Final Accuracy Score --------------------------------- #
        score = self._score(judgments)

        recommendations = self._recommendations(judgments, collector, evidence_by_claim)

        logger.info(
            "accuracy complete",
            extra=bind(
                audit_id=context.audit_id,
                claims=len(classified),
                factual=len(factual),
                supported=self._count(judgments, ClaimVerdict.SUPPORTED),
                contradicted=self._count(judgments, ClaimVerdict.CONTRADICTED),
                unverifiable=self._count(judgments, ClaimVerdict.UNVERIFIABLE),
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
    def _claim_extraction(self) -> ClaimExtractionService:
        return self.services.service("claim_extraction")  # type: ignore[return-value]

    @property
    def _claim_classifier(self) -> ClaimClassifier:
        return self.services.service("claim_classifier")  # type: ignore[return-value]

    @property
    def _centrality_assigner(self) -> ClaimCentralityAssigner:
        return self.services.service("claim_centrality")  # type: ignore[return-value]

    @property
    def _verification_judge(self) -> ClaimVerificationJudge:
        return self.services.service("claim_verification")  # type: ignore[return-value]

    @property
    def _retrieval(self) -> RetrievalService:
        return self.services.service("retrieval")  # type: ignore[return-value]

    # -- Stage 5 ------------------------------------------------------------ #

    async def _reference_chunks(self, context: SharedContext) -> list[Chunk]:
        """Chunk the reference document once per run, shared with Coverage.

        Reference-first (Document 2, §7.2, stage 5): this is the only corpus
        consulted unless the request opted into external retrieval.
        """
        if not context.has_reference_source:
            return []
        return await context.get_or_compute(
            SharedKeys.REFERENCE_CHUNKS,
            lambda: self._retrieval.chunk(
                context.reference_source or "", source_ref="reference_source"
            ),
        )

    async def _retrieve_evidence(
        self,
        claims: Sequence[Claim],
        chunks: Sequence[Chunk],
        collector: EvidenceCollector,
        cfg,
    ) -> dict[str, list[EvidenceItem]]:
        """Retrieve supporting passages for each claim, above the similarity floor.

        Passages below the floor are dropped rather than passed along. A judge
        shown irrelevant text is more likely to rationalize support from it than
        to answer *Unverifiable* — so weak retrieval is worse than no retrieval,
        and the threshold exists to keep noise out of the judgment.
        """
        evidence: dict[str, list[EvidenceItem]] = {}
        if not chunks:
            return evidence

        for claim in claims:
            passages = await self._retrieval.search(
                claim.text, chunks, top_k=cfg.evidence_top_k
            )
            kept = [
                p for p in passages if p.score >= cfg.evidence_similarity_threshold
            ]
            items: list[EvidenceItem] = []
            for passage in kept:
                items.append(
                    collector.retrieved_source(
                        content=passage.chunk.text,
                        source_ref=passage.chunk.source_ref or "reference_source",
                        locator=f"chunk[{passage.chunk.chunk_id}]"
                        f"@{passage.chunk.start}:{passage.chunk.end}",
                    )
                )
            if items:
                evidence[claim.claim_id] = items
        return evidence

    # -- Stage 8 ------------------------------------------------------------ #

    def _build_ledger(
        self,
        judgments: Sequence[Judgment[Claim, ClaimVerdict]],
        non_factual: Sequence[Claim],
        evidence_by_claim: Mapping[str, list[EvidenceItem]],
        collector: EvidenceCollector,
    ) -> list[LedgerEntry]:
        """Build the Claim Verification Ledger (Document 2, §6.3).

        Non-factual claims appear too, with their classification as the verdict.
        Showing them keeps the ledger a complete account of what extraction
        found: a reader who sees ten claims in the text and seven in the ledger
        would reasonably wonder what happened to the other three.
        """
        entries: list[LedgerEntry] = []

        for judgment in judgments:
            claim = judgment.unit
            refs = [i.evidence_id for i in evidence_by_claim.get(claim.claim_id, [])]

            if judgment.rationale:
                rationale_item = collector.judge_rationale(
                    judgment.rationale,
                    locator=claim.source_span.locator() if claim.source_span else None,
                )
                refs.append(rationale_item.evidence_id)
            if claim.source_span:
                refs.append(collector.output_span(claim.source_span).evidence_id)

            entries.append(
                LedgerEntry(
                    entry_id=claim.claim_id,
                    unit=claim.text,
                    unit_type="Claim",
                    verdict=(
                        judgment.verdict.value
                        if judgment.verdict
                        else "Unverifiable"
                    ),
                    severity=self._claim_severity(claim),
                    evidence_refs=refs,
                    rationale=judgment.rationale or self._unjudged_rationale(judgment),
                    attributes={
                        "claim_type": ClaimType.FACTUAL.value,
                        "centrality": claim.centrality,
                        "evidence_count": len(
                            evidence_by_claim.get(claim.claim_id, [])
                        ),
                        "judged": judgment.is_judged,
                    },
                )
            )

        for claim in non_factual:
            entries.append(
                LedgerEntry(
                    entry_id=claim.claim_id,
                    unit=claim.text,
                    unit_type="Claim",
                    verdict="Not verified",
                    severity=None,
                    evidence_refs=(
                        [collector.output_span(claim.source_span).evidence_id]
                        if claim.source_span
                        else []
                    ),
                    rationale=(
                        f"Classified {claim.claim_type.value if claim.claim_type else 'unclassified'}; "
                        "not a checkable factual assertion, so it is excluded from "
                        "verification and from the score."
                    ),
                    attributes={
                        "claim_type": (
                            claim.claim_type.value if claim.claim_type else None
                        ),
                        "excluded_from_score": True,
                    },
                )
            )

        return entries

    @staticmethod
    def _unjudged_rationale(judgment: Judgment[Claim, ClaimVerdict]) -> str:
        """Explain a claim the judge did not return a verdict for."""
        return (
            "The verification stage returned no verdict for this claim, so it is "
            "recorded as Unverifiable and lowers confidence rather than the score."
        )

    @staticmethod
    def _claim_severity(claim: Claim) -> Severity | None:
        """Read the severity stage 4 assigned to a claim."""
        raw = claim.attributes.get("severity")
        if isinstance(raw, str):
            try:
                return Severity(raw)
            except ValueError:
                return None
        return None

    # -- Stage 9 ------------------------------------------------------------ #

    def _detect_critical_findings(
        self,
        judgments: Sequence[Judgment[Claim, ClaimVerdict]],
        evidence_by_claim: Mapping[str, list[EvidenceItem]],
        cfg,
    ) -> list[CriticalFinding]:
        """Detect contradicted claims and raise them as Critical Findings.

        **Only Contradicted qualifies.** An Unverifiable claim is a gap, not a
        finding — raising it here would gate trust to *Untrusted* on the basis
        that the auditor could not check something, which is exactly the
        confusion Document 3 §8 draws *Unable to Verify* to avoid.

        Severity comes from stage 4's per-claim assignment, not from a constant:
        a contradicted claim about the study's headline result and one about an
        incidental date are both contradictions, and only their severity
        distinguishes them.
        """
        findings: list[CriticalFinding] = []

        for judgment in judgments:
            if judgment.verdict is not ClaimVerdict.CONTRADICTED:
                continue

            claim = judgment.unit
            severity = self._claim_severity(claim) or Severity.HIGH
            centrality = claim.centrality if claim.centrality is not None else 1.0

            if SEVERITY_ORDER[severity] < SEVERITY_ORDER[cfg.contradiction_blocking_severity]:
                continue
            if centrality < cfg.min_centrality_for_finding:
                continue

            refs = [i.evidence_id for i in evidence_by_claim.get(claim.claim_id, [])]
            if not refs:
                # Document 3 §12 requires every finding to carry evidence. A
                # contradiction with nothing to point at cannot be justified to
                # a reader, so it stays in the ledger and out of the gate.
                logger.warning(
                    "contradicted claim has no evidence; not raising a finding",
                    extra=bind(claim_id=claim.claim_id),
                )
                continue

            findings.append(
                CriticalFinding(
                    finding_id=f"cf_{claim.claim_id}",
                    dimension=self.dimension,
                    type="Contradicted claim",
                    severity=severity,
                    description=(
                        f"The output asserts: {claim.text!r}. The available "
                        f"evidence contradicts it. {judgment.rationale}".strip()
                    ),
                    evidence_refs=refs,
                    centrality=claim.centrality,
                )
            )

        findings.sort(
            key=lambda f: (SEVERITY_ORDER[f.severity], f.centrality or 0.0),
            reverse=True,
        )
        return findings

    # -- Stage 10 ----------------------------------------------------------- #

    def _confidence_signals(
        self,
        context: SharedContext,
        extraction,
        claims: Sequence[Claim],
        judgments: Sequence[Judgment[Claim, ClaimVerdict]],
        evidence_by_claim: Mapping[str, list[EvidenceItem]],
    ) -> list[ConfidenceSignal]:
        """Report why Accuracy is or is not confident in its own judgment.

        Weighted toward *evidence availability*, because that is what Accuracy's
        judgment actually rests on. A verdict of "all supported" reached with no
        reference document is not a confident pass — it is a guess, and the
        confidence must say so loudly enough for Document 3 §8 to route it to
        *Unable to Verify*.
        """
        total = len(claims)
        judged = sum(1 for j in judgments if j.is_judged)
        with_evidence = sum(1 for c in claims if evidence_by_claim.get(c.claim_id))
        unverifiable = self._count(judgments, ClaimVerdict.UNVERIFIABLE)

        signals = [
            signal(
                "reference_available",
                1.0 if context.has_reference_source else 0.0,
                weight=3.0,
                rationale=(
                    "A reference source was supplied to verify against"
                    if context.has_reference_source
                    else "No reference source was supplied, so claims could only "
                    "be checked against nothing"
                ),
            ),
            signal(
                "evidence_retrieved",
                with_evidence / total if total else 0.0,
                weight=3.0,
                rationale=(
                    f"Evidence was retrieved for {with_evidence} of {total} "
                    "factual claims"
                ),
            ),
            signal(
                "claims_judged",
                judged / total if total else 0.0,
                weight=2.0,
                rationale=f"The verifier returned a verdict for {judged} of {total} claims",
            ),
            signal(
                "verdicts_decisive",
                1.0 - (unverifiable / total) if total else 0.0,
                # The heaviest signal, because it measures how much of the
                # content the score actually covers. Unverifiable claims are
                # excluded from the score by design, so a score computed over
                # one of twenty claims looks identical to one computed over all
                # twenty — and only this signal reveals the difference. Under-
                # weighting it would let "we checked one claim and it was fine"
                # be asserted as confidently as "we checked everything".
                weight=4.0,
                rationale=(
                    f"{unverifiable} of {total} claims could not be settled on "
                    "the available evidence"
                ),
            ),
            signal(
                "claims_located",
                extraction.location_rate,
                weight=1.0,
                rationale=(
                    f"{extraction.located_count} of {len(extraction.units)} claims "
                    "were traced to a span of the output"
                ),
            ),
        ]

        # The verifier's own stated certainty. Without it every signal above can
        # max out — full evidence, everything judged — and the engine reports
        # 1.0: an absolute claim to correctness that no LLM judgment earns.
        # Document 2 §5.10 reports confidence separately precisely so the
        # auditor can be honest about this; the judge told us how sure it was,
        # and ignoring that would be discarding the most direct evidence we have
        # about the reliability of our own verdicts.
        hints = [j.confidence_hint for j in judgments if j.confidence_hint is not None]
        if hints:
            signals.append(
                signal(
                    "verifier_certainty",
                    sum(hints) / len(hints),
                    weight=2.0,
                    rationale=(
                        f"The verifier reported a mean certainty of "
                        f"{sum(hints) / len(hints):.0%} across {len(hints)} verdicts"
                    ),
                )
            )
        else:
            signals.append(
                signal(
                    "verifier_certainty",
                    0.5,
                    weight=2.0,
                    rationale="The verifier reported no certainty for its verdicts",
                )
            )
        if extraction.truncated:
            signals.append(
                signal(
                    "source_complete",
                    0.0,
                    weight=2.0,
                    rationale="The output was truncated for extraction, so some "
                    "claims were never seen",
                )
            )
        return signals

    # -- Stage 11 ----------------------------------------------------------- #

    @staticmethod
    def _score(judgments: Sequence[Judgment[Claim, ClaimVerdict]]) -> float:
        """Compute the Accuracy score.

        Importance-weighted rate over the claims that were actually settled:

        * **Supported** → credit 1.0
        * **Contradicted** → credit 0.0
        * **Unverifiable** → *excluded from both numerator and denominator*

        Excluding Unverifiable is the load-bearing decision. The score answers
        "of what could be checked, how much held up?" — a claim nothing was
        learned about has no place in that average, and scoring it zero would
        report unverified content as inaccurate. Its cost lands on confidence
        instead (Document 3, §8).

        Importance is centrality: a contradiction in a load-bearing claim should
        move the score further than one in an aside, and a plain rate could not
        express that.

        Returns:
            The score in [0, 1]. Returns ``1.0`` when nothing was settled — but
            paired with near-zero confidence from stage 10, which is what makes
            it read as "undetermined" rather than "perfect". The Decision Engine
            never sees the score without the confidence beside it.
        """
        outcomes: list[tuple[float, float]] = []
        for judgment in judgments:
            if judgment.verdict is ClaimVerdict.SUPPORTED:
                credit = 1.0
            elif judgment.verdict is ClaimVerdict.CONTRADICTED:
                credit = 0.0
            else:
                continue  # Unverifiable or unjudged: excluded by design.

            centrality = judgment.unit.centrality
            importance = centrality if centrality is not None else 0.5
            outcomes.append((credit, max(importance, 0.05)))

        return importance_weighted_rate(outcomes, default=1.0)

    # -- Recommendations ---------------------------------------------------- #

    def _recommendations(
        self,
        judgments: Sequence[Judgment[Claim, ClaimVerdict]],
        collector: EvidenceCollector,
        evidence_by_claim: Mapping[str, list[EvidenceItem]],
    ):
        """Produce recommendations for contradicted and unverifiable claims.

        Every one carries an evidence pointer: Document 3 §10 drops a
        recommendation with no traceable evidence, so one emitted without a
        reference would simply be discarded downstream.
        """
        recommendations = []

        for judgment in judgments:
            claim = judgment.unit
            refs = [i.evidence_id for i in evidence_by_claim.get(claim.claim_id, [])]
            if not refs and claim.source_span:
                refs = [collector.output_span(claim.source_span).evidence_id]
            if not refs:
                continue

            if judgment.verdict is ClaimVerdict.CONTRADICTED:
                created = self.services.recommendations.create(
                    dimension=self.dimension,
                    text=(
                        f"Remove or correct the contradicted claim: {claim.text!r}. "
                        "The available evidence says otherwise."
                    ),
                    severity=self._claim_severity(claim) or Severity.HIGH,
                    evidence_refs=refs,
                )
            elif judgment.verdict is ClaimVerdict.UNVERIFIABLE:
                created = self.services.recommendations.create(
                    dimension=self.dimension,
                    text=(
                        f"Provide a source for the unverified claim: {claim.text!r}. "
                        "The available evidence could neither confirm nor refute it."
                    ),
                    severity=Severity.MEDIUM,
                    evidence_refs=refs,
                )
            else:
                continue

            if created is not None:
                recommendations.append(created)

        return recommendations

    # -- Early exits -------------------------------------------------------- #

    def _no_claims_result(self, context: SharedContext, truncated: bool) -> AuditResult:
        """Result for an output extraction found no claims in.

        Deliberately **not** a confident pass. Content with no factual claims may
        be a genuinely claim-free text (a poem, a greeting) or an extraction
        failure, and Accuracy cannot tell which. Reporting high confidence would
        mean asserting "nothing here is inaccurate" on the strength of having
        looked and found nothing — which is the reasoning that lets a
        hallucination through when extraction has a bad day.
        """
        return AuditResult(
            score=1.0,
            confidence=0.2 if not truncated else 0.0,
            ledger=[],
            evidence=[],
            recommendations=[],
            critical_findings=[],
            metadata=self.build_metadata(),
        )

    def _no_factual_claims_result(
        self,
        context: SharedContext,
        classified: Sequence[Claim],
        collector: EvidenceCollector,
    ) -> AuditResult:
        """Result for an output whose claims are all opinion or non-verifiable.

        A real and legitimate outcome — an editorial makes assertions but no
        checkable ones. Accuracy has nothing to verify and says so with modest
        confidence: the classification itself is a real measurement, so this is
        better founded than finding no claims at all.
        """
        ledger = [
            LedgerEntry(
                entry_id=claim.claim_id,
                unit=claim.text,
                unit_type="Claim",
                verdict="Not verified",
                evidence_refs=(
                    [collector.output_span(claim.source_span).evidence_id]
                    if claim.source_span
                    else []
                ),
                rationale=(
                    f"Classified {claim.claim_type.value if claim.claim_type else 'unclassified'}; "
                    "not a checkable factual assertion."
                ),
                attributes={
                    "claim_type": claim.claim_type.value if claim.claim_type else None,
                    "excluded_from_score": True,
                },
            )
            for claim in classified
        ]
        return AuditResult(
            score=1.0,
            confidence=0.4,
            ledger=ledger,
            evidence=self.services.evidence.for_dimension(self.dimension),
            recommendations=[],
            critical_findings=[],
            metadata=self.build_metadata(),
        )

    @staticmethod
    def _count(
        judgments: Sequence[Judgment[Claim, ClaimVerdict]], verdict: ClaimVerdict
    ) -> int:
        """Count judgments with a given verdict."""
        return sum(1 for j in judgments if j.verdict is verdict)
