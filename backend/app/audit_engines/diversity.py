"""Diversity Audit Engine (``ENG-DIVERSITY``) — Document 2, §7.8.

**Governing question.** Where appropriate, does the content fairly represent
legitimate perspectives while avoiding false balance?

**Inputs.** Prompt + AI Output.

**Classification.** Quality Dimension (applicability-gated) · Critical Finding
Capability: No · **Supports N/A** — the only engine that does.

**Frozen pipeline with its applicability branch (Document 2, §7.8).**

1. Input (Prompt + AI Output)
2. Applicability Classification — :class:`ApplicabilityClassifier` (§5.2)
3. Applicability branch:
   * **No →** Return N/A (terminate; no score produced).
   * **Yes →** continue.
4. Stance Contract Detection — :class:`StanceContractDetector` (§5.2)
5. Retrieval of Credible Perspectives — :class:`RetrievalService` (§5.3)
6. Viewpoint Extraction — :class:`ViewpointExtractionService` (§5.1)
7. Balance Evaluation — :class:`BalanceEvaluationJudge` (§5.4)
8. Bias & Loaded Language Detection — :class:`BiasDetectionStage` (§5.4)
9. Evidence Collection — :class:`EvidenceCollector` (§5.7)
10. Diversity Score
11. Confidence
12. Recommendations

**Outputs.** Applicable (Yes/No) · Applicability Reason · Score (or N/A) ·
Confidence · Diversity Ledger · Evidence · Recommendations.

**Contract mapping (Document 2, §6.5).** The frozen *Applicable* and
*Applicability Reason* outputs are carried in ``metadata.applicable`` and
``metadata.applicability_reason``; ``score`` is ``"N/A"`` when applicable is
False, and the ledger is empty. :meth:`AuditEngine.build_metadata` enforces those
pairings.

**Why the branch terminates rather than scoring low.** "Avoiding false balance"
is the whole point. Demanding perspective balance from a factual or technical
output would reward manufacturing a controversy that does not exist. So when the
dimension does not apply, the engine returns N/A and the Decision Engine excludes
it from the Quality Verdict entirely — removed from numerator *and* denominator,
never scored as zero (Document 3, §9). An inapplicable dimension must neither
help nor harm.

Returning N/A is also invisible to trust: Diversity is a Quality dimension with
no critical-finding capability, so it cannot affect the Trust Verdict either way.

**The stance contract sets the standard, and that is why stage 4 precedes the
judgment.** An essay that announces it is arguing a position is not required to
give equal room to the other side — that is what an argument is. Judging every
output against the neutral standard would report every honest argument as biased.

What an argument must still not do is *misrepresent* the opposition, and the
credit table charges that identically under both contracts. And a piece that
argues while presenting itself as a neutral survey is *Neutral* by stage 4's
definition — "Declared" advocacy means declared — so it is held to the strict
standard and the imbalance it was hiding is what the score reports. That case
needs no separate mechanism, and an earlier draft's extra "undisclosed stance"
penalty was both redundant and dead code; see
:class:`~app.shared.classification.diversity.StanceDecision`.

**A note on stage 5 and this deployment's retrieval.** §7.8 stage 5 retrieves
credible perspectives; the frozen stack (Document 4, §2) provides document
chunking and URL fetching but no search backend. So the engine retrieves from
what it actually has — the reference source when one was supplied, and the
output's own cited sources when the request opted into external retrieval — and
when it has neither, it says so through a confidence signal rather than
pretending the stage ran. Viewpoints are then grounded in the model's own
knowledge, which is a weaker footing and is reported as one.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from app.audit_engines.base import AuditEngine
from app.audit_engines.registry import register_engine
from app.core.logging import bind, get_logger
from app.shared.classification.diversity import (
    ApplicabilityClassifier,
    StanceContractDetector,
    StanceDecision,
)
from app.shared.confidence_service import ConfidenceSignal, signal
from app.shared.context import SharedContext
from app.shared.deterministic_validators import URL_PATTERN
from app.shared.evidence_pipeline import EvidenceCollector, format_for_prompt
from app.shared.extraction.models import ExtractionResult, Viewpoint
from app.shared.extraction.viewpoints import ViewpointExtractionService
from app.shared.quality_units import BiasItem
from app.shared.retrieval_service import RetrievalService
from app.shared.schemas import (
    AuditResult,
    EvidenceItem,
    LedgerEntry,
    Severity,
    SEVERITY_ORDER,
)
from app.shared.scoring import apply_penalty, weighted_mean
from app.shared.verification.base import Judgment
from app.shared.verification.diversity import BalanceEvaluationJudge, BiasDetectionStage
from app.shared.vocabularies import BalanceVerdict, StanceContract

__all__ = ["DiversityAuditEngine"]

logger = get_logger(__name__)

#: Credit each balance verdict earns, by stance contract.
#:
#: The two columns are the stance contract doing its work. Under **Neutral**, a
#: survey that underrepresents a legitimate position has broken its promise to
#: the reader. Under **Declared Advocacy**, the same treatment is what an
#: argument *is*, so it costs far less — but *Misrepresented* costs the same
#: under both, because a strawman is dishonest whatever the stance, and
#: *Omitted* still costs an argument something, since an argument that never
#: engages its strongest objection is a weak argument.
_BALANCE_CREDIT: Mapping[StanceContract, Mapping[BalanceVerdict, float]] = {
    StanceContract.NEUTRAL: {
        BalanceVerdict.FAIRLY_REPRESENTED: 1.0,
        BalanceVerdict.UNDERREPRESENTED: 0.5,
        BalanceVerdict.MISREPRESENTED: 0.15,
        BalanceVerdict.OMITTED: 0.0,
    },
    StanceContract.DECLARED_ADVOCACY: {
        BalanceVerdict.FAIRLY_REPRESENTED: 1.0,
        BalanceVerdict.UNDERREPRESENTED: 0.9,
        BalanceVerdict.MISREPRESENTED: 0.15,
        BalanceVerdict.OMITTED: 0.6,
    },
}


@register_engine
class DiversityAuditEngine(AuditEngine):
    """Measures perspective balance, where the dimension applies.

    Shared Components used (Document 2, §7.8): LLM Service, Retrieval Service,
    Evidence Store, Confidence Estimator, Recommendation Generator, Prompt
    Templates, JSON Models.
    """

    dimension = "Diversity"

    async def _execute(
        self, context: SharedContext, prior_results: Mapping[str, AuditResult]
    ) -> AuditResult:
        """Run the frozen Diversity pipeline, including the applicability branch."""
        cfg = self.services.settings.engines.diversity
        collector = EvidenceCollector(self.services.evidence, self.dimension)

        # -- Stage 2: Applicability Classification ------------------------- #
        applicability = await self._applicability.classify_applicability(
            context.prompt or "", context.ai_output
        )

        # -- Stage 3: Applicability branch --------------------------------- #
        if not applicability.applicable:
            return self._not_applicable_result(context, applicability.reason)

        # -- Stage 4: Stance Contract Detection ---------------------------- #
        stance = await self._stance_detector.detect(
            context.prompt or "", context.ai_output
        )

        # -- Stage 5: Retrieval of Credible Perspectives ------------------- #
        perspectives = await self._retrieve_perspectives(
            context, applicability.topic, collector, cfg
        )

        # -- Stage 6: Viewpoint Extraction --------------------------------- #
        extraction = await self._viewpoint_extraction.extract(
            context.ai_output,
            prompt=context.prompt or "(no prompt was supplied)",
            perspectives=format_for_prompt(perspectives)
            if perspectives
            else "(no perspectives could be retrieved; rely on your own knowledge "
            "of the question and expect the auditor to discount this accordingly)",
        )
        if extraction.is_empty:
            return self._no_viewpoints_result(context, applicability.topic)

        # -- Stage 7: Balance Evaluation ----------------------------------- #
        judgments = await self._balance_judge.evaluate(
            extraction.units,
            ai_output=context.ai_output,
            stance=self._render_stance(stance),
            topic=applicability.topic or "(not stated)",
        )

        # -- Stage 8: Bias & Loaded Language Detection --------------------- #
        bias_items = await self._bias_detection.detect(
            context.ai_output,
            stance=self._render_stance(stance),
            topic=applicability.topic or "(not stated)",
        )

        # -- Stage 9: Evidence Collection ---------------------------------- #
        ledger = self._build_ledger(judgments, bias_items, stance, collector)

        # -- Stage 10: Diversity Score ------------------------------------- #
        score = self._score(judgments, bias_items, stance, cfg)

        # -- Stage 11: Confidence ------------------------------------------ #
        signals = self._confidence_signals(
            context, extraction, judgments, perspectives, stance
        )
        confidence = self.services.confidence.estimate(signals)

        # -- Stage 12: Recommendations ------------------------------------- #
        recommendations = self._recommendations(
            judgments, bias_items, stance, collector
        )

        logger.info(
            "diversity complete",
            extra=bind(
                audit_id=context.audit_id,
                applicable=True,
                stance=stance.stance.value,
                perspectives_retrieved=len(perspectives),
                viewpoints=len(extraction.units),
                omitted=self._count(judgments, BalanceVerdict.OMITTED),
                misrepresented=self._count(judgments, BalanceVerdict.MISREPRESENTED),
                bias_items=len(bias_items),
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
            # Always empty: capability No (Document 2, §4.1). Unbalanced content
            # is badly made, not untrustworthy.
            critical_findings=[],
            metadata=self.build_metadata(),
        )

    # -- Injected services -------------------------------------------------- #

    @property
    def _applicability(self) -> ApplicabilityClassifier:
        return self.services.service("applicability_classifier")  # type: ignore[return-value]

    @property
    def _stance_detector(self) -> StanceContractDetector:
        return self.services.service("stance_contract")  # type: ignore[return-value]

    @property
    def _viewpoint_extraction(self) -> ViewpointExtractionService:
        return self.services.service("viewpoint_extraction")  # type: ignore[return-value]

    @property
    def _balance_judge(self) -> BalanceEvaluationJudge:
        return self.services.service("balance_evaluation")  # type: ignore[return-value]

    @property
    def _bias_detection(self) -> BiasDetectionStage:
        return self.services.service("bias_detection")  # type: ignore[return-value]

    @property
    def _retrieval(self) -> RetrievalService:
        return self.services.service("retrieval")  # type: ignore[return-value]

    # -- Stage 5 ------------------------------------------------------------ #

    async def _retrieve_perspectives(
        self,
        context: SharedContext,
        topic: str,
        collector: EvidenceCollector,
        cfg,
    ) -> list[EvidenceItem]:
        """Retrieve credible perspectives on the topic.

        Reference source first, then the output's own cited sources when the
        request opted into external retrieval. The ordering mirrors Accuracy's
        reference-first rule (§7.2, stage 5) for the same reason: material the
        user supplied is sanctioned, and material fetched from the open web is
        not unless they said so.

        Returns an empty list when nothing is retrievable, which is a common and
        legitimate state — most audits arrive with no reference source and no
        external retrieval. The engine then extracts viewpoints from the model's
        own knowledge and :meth:`_confidence_signals` reports the weaker footing,
        rather than the engine claiming a grounding it does not have.
        """
        items: list[EvidenceItem] = []

        if context.has_reference_source and topic:
            chunks = self._retrieval.chunk(
                context.reference_source or "", source_ref="reference_source"
            )
            passages = await self._retrieval.search(
                topic, chunks, top_k=cfg.perspective_top_k
            )
            for passage in passages:
                if passage.score < cfg.perspective_similarity_threshold:
                    continue
                items.append(
                    collector.retrieved_source(
                        content=passage.chunk.text,
                        source_ref=passage.chunk.source_ref or "reference_source",
                        locator=f"chunk[{passage.chunk.chunk_id}]"
                        f"@{passage.chunk.start}:{passage.chunk.end}",
                    )
                )

        if context.options.get("external_retrieval"):
            urls = list(dict.fromkeys(URL_PATTERN.findall(context.ai_output)))
            for url in urls[: cfg.max_sources_fetched]:
                document = await self._retrieval.fetch(url)
                if not document.reachable or not document.has_content:
                    continue
                items.append(
                    collector.retrieved_source(
                        content=document.text[: cfg.source_excerpt_chars],
                        source_ref=url,
                    )
                )

        logger.info(
            "diversity perspectives retrieved",
            extra=bind(
                audit_id=context.audit_id,
                retrieved=len(items),
                had_reference=context.has_reference_source,
                external=bool(context.options.get("external_retrieval")),
            ),
        )
        return items

    @staticmethod
    def _render_stance(stance: StanceDecision) -> str:
        """Render the stance contract for the stage 7 and 8 prompts."""
        return f"{stance.stance.value}. {stance.reason}".strip()

    # -- Stage 9 ------------------------------------------------------------ #

    def _build_ledger(
        self,
        judgments: Sequence[Judgment[Viewpoint, BalanceVerdict]],
        bias_items: Sequence[BiasItem],
        stance: StanceDecision,
        collector: EvidenceCollector,
    ) -> list[LedgerEntry]:
        """Build the Diversity Ledger (Document 2, §6.3).

        The §6.3 unit is a "Viewpoint / bias item" — both kinds appear here.
        The stance contract is recorded on every viewpoint row: the same verdict
        means different things under the two contracts, and a reader who cannot
        see which one applied cannot check the score.
        """
        entries: list[LedgerEntry] = []

        for judgment in judgments:
            viewpoint = judgment.unit
            refs: list[str] = []
            if viewpoint.source_span:
                refs.append(collector.output_span(viewpoint.source_span).evidence_id)
            if judgment.rationale:
                refs.append(collector.judge_rationale(judgment.rationale).evidence_id)

            entries.append(
                LedgerEntry(
                    entry_id=viewpoint.viewpoint_id,
                    unit=viewpoint.text,
                    unit_type="Viewpoint",
                    verdict=(
                        judgment.verdict.value if judgment.verdict else "Not evaluated"
                    ),
                    severity=self._balance_severity(judgment, stance),
                    evidence_refs=refs,
                    rationale=(
                        judgment.rationale
                        or "The balance evaluation returned no verdict for this "
                        "viewpoint, so it is excluded from the score and lowers "
                        "confidence instead."
                    ),
                    attributes={
                        "legitimacy": viewpoint.legitimacy,
                        "in_output": viewpoint.in_output,
                        "stance_contract": stance.stance.value,
                        "judged": judgment.is_judged,
                    },
                )
            )

        for item in bias_items:
            refs = []
            if item.source_span:
                refs.append(collector.output_span(item.source_span).evidence_id)
            refs.append(collector.judge_rationale(item.explanation).evidence_id)

            entries.append(
                LedgerEntry(
                    entry_id=item.bias_id,
                    unit=item.text,
                    unit_type="Bias item",
                    verdict=item.bias_type,
                    severity=item.severity,
                    evidence_refs=refs,
                    rationale=item.explanation,
                    attributes={
                        "bias_type": item.bias_type,
                        "stance_contract": stance.stance.value,
                        "located": item.source_span is not None,
                    },
                )
            )

        return entries

    @staticmethod
    def _balance_severity(
        judgment: Judgment[Viewpoint, BalanceVerdict], stance: StanceDecision
    ) -> Severity | None:
        """Grade a balance failure by its verdict, legitimacy, and the stance."""
        if judgment.verdict is None:
            return None
        legitimacy = judgment.unit.legitimacy
        weight = legitimacy if legitimacy is not None else 0.5

        if judgment.verdict is BalanceVerdict.MISREPRESENTED:
            # Strictest under both contracts: a strawman is dishonest whether or
            # not the piece admits it is arguing.
            return Severity.HIGH if weight >= 0.5 else Severity.MEDIUM
        if judgment.verdict is BalanceVerdict.OMITTED:
            if stance.stance is StanceContract.DECLARED_ADVOCACY:
                return Severity.LOW if weight >= 0.7 else None
            return Severity.HIGH if weight >= 0.7 else Severity.MEDIUM
        if judgment.verdict is BalanceVerdict.UNDERREPRESENTED:
            if stance.stance is StanceContract.DECLARED_ADVOCACY:
                return None
            return Severity.MEDIUM if weight >= 0.7 else Severity.LOW
        return None

    # -- Stage 10 ----------------------------------------------------------- #

    def _score(
        self,
        judgments: Sequence[Judgment[Viewpoint, BalanceVerdict]],
        bias_items: Sequence[BiasItem],
        stance: StanceDecision,
        cfg,
    ) -> float:
        """Compute the Diversity score.

        A legitimacy-weighted balance rate, penalized by confirmed bias and by an
        undisclosed stance.

        **Legitimacy is the weight, and it is what prevents false balance.**
        Omitting a mainstream expert position costs the score heavily; omitting a
        fringe claim costs almost nothing, because weighting is by how
        well-founded the viewpoint is. An unweighted rate would reward giving
        equal room to anything anyone has said — which is the failure §7.8 names
        by name.

        **The credit table depends on the stance contract**, so an argument is
        not scored as a failed survey. See :data:`_BALANCE_CREDIT`. This is also
        what catches undeclared advocacy, and it needs no separate mechanism to
        do it: a piece that argues a position while presenting itself as neutral
        is *Neutral* by stage 4's definition, so the strict column applies and
        the imbalance it was hiding is precisely what the score reports.

        **Bias is penalized rather than averaged**, because loaded framing is a
        fault that naming every viewpoint does not offset. Averaging would let a
        thorough survey buy the right to sneer at one of the positions in it.

        Returns:
            The score in [0, 1].
        """
        credit = _BALANCE_CREDIT[stance.stance]
        outcomes = [
            (
                credit[j.verdict],
                max(j.unit.legitimacy if j.unit.legitimacy is not None else 0.5, 0.05),
            )
            for j in judgments
            if j.verdict is not None
        ]
        base = weighted_mean(outcomes, default=1.0)

        penalties = {
            item.bias_id: cfg.bias_penalty.get(item.severity.value, 0.05)
            for item in bias_items
        }
        return apply_penalty(base, penalties)

    # -- Stage 11 ----------------------------------------------------------- #

    def _confidence_signals(
        self,
        context: SharedContext,
        extraction: ExtractionResult[Viewpoint],
        judgments: Sequence[Judgment[Viewpoint, BalanceVerdict]],
        perspectives: Sequence[EvidenceItem],
        stance: StanceDecision,
    ) -> list[ConfidenceSignal]:
        """Report why Diversity is or is not confident in its own judgment."""
        total = len(extraction.units)
        judged = sum(1 for j in judgments if j.is_judged)
        rated = sum(1 for j in judgments if j.unit.legitimacy is not None)

        signals = [
            signal(
                "viewpoints_evaluated",
                judged / total if total else 0.0,
                weight=4.0,
                rationale=(
                    f"The balance evaluation returned a verdict for {judged} of "
                    f"{total} viewpoints"
                ),
            ),
            signal(
                "perspectives_retrieved",
                1.0 if perspectives else 0.0,
                # Heavy: this is the difference between viewpoints grounded in
                # retrieved sources and viewpoints the model recalled. Both are
                # usable; only the first is evidence, and Document 2 §5.10
                # reports confidence separately precisely so the engine can say
                # which one it had.
                weight=3.0,
                rationale=(
                    f"{len(perspectives)} credible perspectives were retrieved to "
                    "ground the viewpoints"
                    if perspectives
                    else "No perspectives could be retrieved, so the viewpoints "
                    "rest on the model's own knowledge of the question rather "
                    "than on evidence"
                ),
            ),
            signal(
                "legitimacy_assigned",
                rated / total if total else 0.0,
                weight=3.0,
                rationale=(
                    f"{rated} of {total} viewpoints carry a legitimacy rating; "
                    "without it the score cannot tell a serious omission from "
                    "declining to platform a fringe claim"
                ),
            ),
            signal(
                "prompt_available",
                1.0 if context.has_prompt else 0.0,
                weight=1.0,
                rationale=(
                    "A prompt was supplied, so the question the content set out "
                    "to address is known"
                    if context.has_prompt
                    else "No prompt was supplied, so the question had to be "
                    "inferred from the output itself"
                ),
            ),
            signal(
                "viewpoints_located",
                extraction.location_rate,
                weight=1.0,
                rationale=(
                    f"{extraction.located_count} of {total} viewpoints were traced "
                    "to a span of the output"
                ),
            ),
        ]

        hints = [j.confidence_hint for j in judgments if j.confidence_hint is not None]
        signals.append(
            signal(
                "evaluator_certainty",
                sum(hints) / len(hints) if hints else 0.5,
                weight=2.0,
                rationale=(
                    f"The balance evaluator reported a mean certainty of "
                    f"{(sum(hints) / len(hints)) if hints else 0.5:.0%}"
                ),
            )
        )
        return signals

    # -- Stage 12 ----------------------------------------------------------- #

    def _recommendations(
        self,
        judgments: Sequence[Judgment[Viewpoint, BalanceVerdict]],
        bias_items: Sequence[BiasItem],
        stance: StanceDecision,
        collector: EvidenceCollector,
    ):
        """Produce recommendations for balance failures and biased framing.

        A viewpoint whose severity came back ``None`` earns no recommendation.
        That is the stance contract doing its job: telling a declared argument to
        give equal room to the position it is arguing against is advice that
        would make it a worse argument, and this engine does not give it.
        """
        recommendations = []

        for judgment in judgments:
            severity = self._balance_severity(judgment, stance)
            if severity is None or not judgment.rationale:
                continue
            viewpoint = judgment.unit
            refs = [collector.judge_rationale(judgment.rationale).evidence_id]
            if viewpoint.source_span:
                refs.append(collector.output_span(viewpoint.source_span).evidence_id)

            if judgment.verdict is BalanceVerdict.MISREPRESENTED:
                text = (
                    f"State this viewpoint as its holders would: {viewpoint.text!r}. "
                    f"{judgment.rationale}"
                )
            elif judgment.verdict is BalanceVerdict.OMITTED:
                text = (
                    f"Engage with the omitted viewpoint: {viewpoint.text!r}. "
                    f"{judgment.rationale}"
                )
            else:
                text = (
                    f"Give fuller treatment to this viewpoint: {viewpoint.text!r}. "
                    f"{judgment.rationale}"
                )

            created = self.services.recommendations.create(
                dimension=self.dimension,
                text=text,
                severity=severity,
                evidence_refs=refs,
            )
            if created is not None:
                recommendations.append(created)

        for item in bias_items:
            refs = [collector.judge_rationale(item.explanation).evidence_id]
            if item.source_span:
                refs.append(collector.output_span(item.source_span).evidence_id)
            created = self.services.recommendations.create(
                dimension=self.dimension,
                text=(
                    f"Reframe the {item.bias_type}: {item.text!r}. {item.explanation}"
                ),
                severity=item.severity,
                evidence_refs=refs,
            )
            if created is not None:
                recommendations.append(created)

        recommendations.sort(key=lambda r: SEVERITY_ORDER[r.severity], reverse=True)
        return recommendations

    # -- Branch and early exits --------------------------------------------- #

    def _not_applicable_result(self, context: SharedContext, reason: str) -> AuditResult:
        """Return N/A and terminate (Document 2, §7.8, stage 3).

        The engine's defining behavior, and the only N/A in the system.

        ``score="N/A"`` paired with ``applicable=False`` — :meth:`build_metadata`
        enforces the pairing, and ``AuditResult.validate_contract`` rejects one
        without the other. The Decision Engine then excludes the dimension from
        the Quality Verdict entirely: out of the numerator *and* the denominator
        (Document 3, §9). Not scored zero, not scored one, not silently dropped.

        **Confidence is high, and that is not a contradiction.** The engine is
        confident in the judgment it actually made — that the dimension does not
        apply. That is a real conclusion reached by a real stage, and it is a
        different thing from the score, which does not exist. This is exactly why
        Document 2 §5.10 reports the two separately.

        The reason is carried verbatim into the report so the exclusion is
        auditable rather than mysterious.
        """
        logger.info(
            "diversity not applicable; returning N/A",
            extra=bind(audit_id=context.audit_id, reason=reason[:120]),
        )
        return AuditResult(
            score="N/A",
            confidence=0.9,
            ledger=[],
            evidence=[],
            recommendations=[],
            critical_findings=[],
            metadata=self.build_metadata(applicable=False, applicability_reason=reason),
        )

    def _no_viewpoints_result(self, context: SharedContext, topic: str) -> AuditResult:
        """Result when the dimension applies but no viewpoints were extracted.

        Not the same as N/A, and it must not be reported as one. Stage 2 decided
        the question *is* contested; stage 6 then found nothing to weigh. Those
        two cannot both be right, so the honest reading is that a stage failed —
        and a failed measurement is a confidence problem (Document 3, §8), not an
        applicability one. Reaching for N/A here would let an extraction failure
        quietly excuse the dimension from the report.
        """
        logger.warning(
            "diversity: applicable but no viewpoints extracted",
            extra=bind(audit_id=context.audit_id, topic=topic[:80]),
        )
        return AuditResult(
            score=1.0,
            confidence=0.1,
            ledger=[],
            evidence=[],
            recommendations=[],
            critical_findings=[],
            metadata=self.build_metadata(),
        )

    @staticmethod
    def _count(
        judgments: Sequence[Judgment[Viewpoint, BalanceVerdict]],
        verdict: BalanceVerdict,
    ) -> int:
        """Count judgments with a given verdict."""
        return sum(1 for j in judgments if j.verdict is verdict)
