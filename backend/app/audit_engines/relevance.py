"""Relevance Audit Engine (``ENG-RELEVANCE``) — Document 2, §7.1.

**Governing question.** Does the output satisfy the user's instruction and intent
without off-topic content?

**Inputs.** Prompt + AI Output.

**Classification.** Hybrid Dimension · Critical Finding Capability: Yes ·
Does Not Support N/A.

Hybrid because it does two jobs at once: a violated *hard* requirement is a
trust-gating Critical Finding, while the degree of intent fulfillment is a
quality signal. The Decision Engine consumes both — the finding in Trust
Evaluation, the score in Quality Evaluation (Document 3, §6–§7).

**Frozen pipeline (Document 2, §7.1), stage by stage.**

1. Input (Prompt + AI Output)
2. LLM-based Requirement Extraction — :class:`RequirementExtractionService` (§5.1)
3. Hard / Soft Requirement Classification — :class:`RequirementClassifier` (§5.2)
4. Per-Requirement Evaluation — :class:`RequirementEvaluationJudge` (§5.4)
5. Evidence Generation — :class:`EvidenceCollector`
6. Sentence Embedding-based Scope Drift Detection — :class:`EmbeddingService` (§5.5)
7. Deterministic Constraint Checks — :class:`DeterministicValidators` (§5.6)
8. Final Relevance Score
9. Confidence Score
10. Recommendations

**Two decisions worth understanding.**

*Stage 7 overrides stage 4 where they disagree.* The frozen order runs the LLM
evaluation first and the deterministic checks after — and where a validator can
answer a requirement, its answer wins. "The response must not exceed 200 words"
is settled by counting words, not by asking a model to estimate. A judge that
guesses "looks about right" at 470 words is simply wrong, and Document 4 §11
prefers the check that cannot vary. The override is recorded in the ledger so
the disagreement is visible rather than silently resolved.

*No prompt means no measurement.* Relevance measures against stated intent. With
no prompt there is nothing to measure against, and the engine degrades to zero
confidence rather than inventing a verdict — which routes the run toward
*Unable to Verify* on this trust-relevant dimension (Document 3, §8) instead of
passing content nobody specified.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from app.audit_engines.base import AuditEngine
from app.audit_engines.registry import register_engine
from app.core.logging import bind, get_logger
from app.shared.classification.requirements import RequirementClassifier
from app.shared.confidence_service import ConfidenceSignal, signal
from app.shared.context import SharedContext
from app.shared.deterministic_validators import (
    DeterministicValidators,
    ValidationOutcome,
)
from app.shared.embedding_service import EmbeddingService, relatedness
from app.shared.evidence_pipeline import EvidenceCollector
from app.shared.extraction.models import Requirement
from app.shared.extraction.requirements import RequirementExtractionService
from app.shared.schemas import (
    AuditResult,
    CriticalFinding,
    LedgerEntry,
    Severity,
)
from app.shared.scoring import clamp, weighted_mean
from app.shared.text_segmentation import TextSpan
from app.shared.verification.base import Judgment
from app.shared.verification.requirements import RequirementEvaluationJudge
from app.shared.vocabularies import RequirementType, RequirementVerdict

__all__ = ["RelevanceAuditEngine"]

logger = get_logger(__name__)

#: Credit each verdict earns toward the score.
_VERDICT_CREDIT: dict[RequirementVerdict, float] = {
    RequirementVerdict.SATISFIED: 1.0,
    RequirementVerdict.PARTIALLY_SATISFIED: 0.5,
    RequirementVerdict.VIOLATED: 0.0,
}


@register_engine
class RelevanceAuditEngine(AuditEngine):
    """Measures instruction and intent fulfillment.

    Shared Components used (Document 2, §7.1): LLM Service, Embedding Service,
    Deterministic Validators, Evidence Store, Confidence Estimator,
    Recommendation Generator, Prompt Templates, JSON Models.
    """

    dimension = "Relevance"

    async def _execute(
        self, context: SharedContext, prior_results: Mapping[str, AuditResult]
    ) -> AuditResult:
        """Run the frozen Relevance pipeline."""
        cfg = self.services.settings.engines.relevance
        collector = EvidenceCollector(self.services.evidence, self.dimension)

        if not context.has_prompt:
            return self._no_prompt_result()

        # -- Stage 2: Requirement Extraction ------------------------------- #
        extraction = await self._requirement_extraction.extract(context.prompt or "")
        if extraction.is_empty:
            return self._no_requirements_result(collector)

        # -- Stage 3: Hard / Soft Classification --------------------------- #
        classified = await self._requirement_classifier.classify(extraction.units)

        # -- Stage 4: Per-Requirement Evaluation --------------------------- #
        judgments = await self._evaluation_judge.judge(
            classified, ai_output=context.ai_output
        )

        # -- Stage 6: Scope Drift Detection -------------------------------- #
        drift = await self._scope_drift(context, cfg)

        # -- Stage 7: Deterministic Constraint Checks ---------------------- #
        constraints = self._constraints_from(classified)
        checks = (
            self._validators.check_constraints(context.ai_output, constraints)
            if constraints
            else []
        )
        judgments = self._apply_deterministic_overrides(judgments, checks, collector)

        # -- Stage 5: Evidence Generation ---------------------------------- #
        ledger = self._build_ledger(judgments, collector, context)
        self._record_drift_evidence(drift, collector)

        findings = self._detect_critical_findings(judgments, collector, context, cfg)

        # -- Stage 8: Final Relevance Score -------------------------------- #
        score = self._score(judgments, drift, cfg)

        # -- Stage 9: Confidence ------------------------------------------- #
        signals = self._confidence_signals(extraction, classified, judgments, drift, checks)
        confidence = self.services.confidence.estimate(signals)

        # -- Stage 10: Recommendations ------------------------------------- #
        recommendations = self._recommendations(judgments, drift, collector, context)

        logger.info(
            "relevance complete",
            extra=bind(
                audit_id=context.audit_id,
                requirements=len(classified),
                hard=sum(1 for r in classified if r.requirement_type is RequirementType.HARD),
                violated=self._count(judgments, RequirementVerdict.VIOLATED),
                drift_ratio=round(drift["ratio"], 3),
                deterministic_checks=len(checks),
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
    def _requirement_extraction(self) -> RequirementExtractionService:
        return self.services.service("requirement_extraction")  # type: ignore[return-value]

    @property
    def _requirement_classifier(self) -> RequirementClassifier:
        return self.services.service("requirement_classifier")  # type: ignore[return-value]

    @property
    def _evaluation_judge(self) -> RequirementEvaluationJudge:
        return self.services.service("requirement_evaluation")  # type: ignore[return-value]

    @property
    def _validators(self) -> DeterministicValidators:
        return self.services.service("validators")  # type: ignore[return-value]

    @property
    def _embeddings(self) -> EmbeddingService:
        return self.services.service("embedding")  # type: ignore[return-value]

    # -- Stage 6 ------------------------------------------------------------ #

    async def _scope_drift(self, context: SharedContext, cfg) -> dict[str, Any]:
        """Detect sentences that depart from the prompt's topic.

        Embeds the prompt and every sentence of the output, then measures each
        sentence's similarity to the prompt. Sentences below the configured
        floor are drifting.

        Reuses ``context.sentences`` — the shared segmentation — rather than
        splitting the text again, and the embeddings land in the shared cache
        (Document 4, §12).

        Similarity is :func:`~app.shared.embedding_service.relatedness`, on the
        scale ``scope_drift_threshold`` is calibrated against. Rescaling cosine
        into [0, 1] instead would push every sentence above any sane threshold
        and silently detect no drift at all.

        Returns:
            The drifting spans, the drift ratio, and the per-sentence scores.
        """
        sentences = context.sentences
        if not sentences or not context.prompt:
            return {"spans": [], "ratio": 0.0, "scores": {}}

        vectors = await self._embeddings.embed(
            [context.prompt, *(s.text for s in sentences)]
        )
        prompt_vector, sentence_vectors = vectors[0], vectors[1:]

        drifting: list[TextSpan] = []
        scores: dict[int, float] = {}
        for span, vector in zip(sentences, sentence_vectors):
            similarity = relatedness(prompt_vector, vector)
            scores[span.index] = similarity
            if similarity < cfg.scope_drift_threshold:
                drifting.append(span)

        return {
            "spans": drifting,
            "ratio": len(drifting) / len(sentences),
            "scores": scores,
        }

    def _record_drift_evidence(
        self, drift: dict[str, Any], collector: EvidenceCollector
    ) -> None:
        """Record each drifting sentence as evidence.

        Capped at the worst offenders: a wholly off-topic answer would otherwise
        produce an evidence item per sentence and bury the report in a hundred
        near-identical entries.
        """
        for span in drift["spans"][:10]:
            collector.output_span(span)

    # -- Stage 7 ------------------------------------------------------------ #

    @staticmethod
    def _constraints_from(requirements: Sequence[Requirement]) -> dict[str, Any]:
        """Collect the machine-checkable constraints stage 3 extracted.

        Only requirements the classifier rendered into a constraint appear here.
        The rest need reading comprehension and stay with the stage 4 judge.
        """
        constraints: dict[str, Any] = {}
        for requirement in requirements:
            kind = requirement.attributes.get("constraint_kind")
            value = requirement.attributes.get("constraint_value")
            if not isinstance(kind, str) or value is None:
                continue
            if kind in ("must_contain", "must_not_contain"):
                constraints.setdefault(kind, []).append(value)
            else:
                constraints[kind] = value
        return constraints

    def _apply_deterministic_overrides(
        self,
        judgments: Sequence[Judgment[Requirement, RequirementVerdict]],
        checks: Sequence[ValidationOutcome],
        collector: EvidenceCollector,
    ) -> list[Judgment[Requirement, RequirementVerdict]]:
        """Let deterministic checks override the judge where they disagree.

        A word count is a fact; a model's impression of length is a guess. Where
        a validator can answer a requirement, its answer replaces the judge's —
        Document 4 §11 prefers the check that cannot vary between runs.

        The override is recorded in the ledger rather than applied silently, so
        a reader can see that the judge said "satisfied" and the counter said
        470 words against a 200-word limit. Hiding that would make the ledger
        misrepresent how the verdict was reached.
        """
        by_kind = {check.check: check for check in checks}
        if not by_kind:
            return list(judgments)

        updated: list[Judgment[Requirement, RequirementVerdict]] = []
        for judgment in judgments:
            kind = judgment.unit.attributes.get("constraint_kind")
            check = by_kind.get(kind) if isinstance(kind, str) else None
            if check is None:
                updated.append(judgment)
                continue

            deterministic = (
                RequirementVerdict.SATISFIED
                if check.passed
                else RequirementVerdict.VIOLATED
            )
            if deterministic is judgment.verdict:
                updated.append(judgment)
                continue

            item = collector.validator_result(check.check, check.detail)
            note = (
                f"Deterministic check overrides the evaluation "
                f"({judgment.verdict.value if judgment.verdict else 'no verdict'} "
                f"-> {deterministic.value}): {check.detail}"
            )
            logger.info(
                "deterministic check overrode the judge",
                extra=bind(
                    requirement_id=judgment.unit.requirement_id,
                    check=check.check,
                    judge=judgment.verdict.value if judgment.verdict else None,
                    deterministic=deterministic.value,
                ),
            )
            updated.append(
                Judgment(
                    unit=judgment.unit,
                    verdict=deterministic,
                    rationale=f"{note} (Evaluation said: {judgment.rationale})".strip(),
                    evidence_refs=(*judgment.evidence_refs, item.evidence_id),
                    confidence_hint=1.0,  # A count is certain.
                )
            )
        return updated

    # -- Stage 5 ------------------------------------------------------------ #

    def _build_ledger(
        self,
        judgments: Sequence[Judgment[Requirement, RequirementVerdict]],
        collector: EvidenceCollector,
        context: SharedContext,
    ) -> list[LedgerEntry]:
        """Build the Requirement Checklist (Document 2, §6.3)."""
        entries: list[LedgerEntry] = []
        for judgment in judgments:
            requirement = judgment.unit
            refs = list(judgment.evidence_refs)
            if requirement.source_span:
                refs.append(collector.prompt_span(requirement.source_span).evidence_id)
            if judgment.rationale:
                refs.append(collector.judge_rationale(judgment.rationale).evidence_id)

            entries.append(
                LedgerEntry(
                    entry_id=requirement.requirement_id,
                    unit=requirement.text,
                    unit_type="Requirement",
                    verdict=(
                        judgment.verdict.value if judgment.verdict else "Not evaluated"
                    ),
                    severity=self._requirement_severity(judgment),
                    evidence_refs=refs,
                    rationale=judgment.rationale
                    or "The evaluation stage returned no verdict for this requirement.",
                    attributes={
                        "requirement_type": (
                            requirement.requirement_type.value
                            if requirement.requirement_type
                            else None
                        ),
                        "constraint_kind": requirement.attributes.get("constraint_kind"),
                        "deterministic": requirement.attributes.get("constraint_kind")
                        is not None,
                    },
                )
            )
        return entries

    @staticmethod
    def _requirement_severity(
        judgment: Judgment[Requirement, RequirementVerdict],
    ) -> Severity | None:
        """Severity for a ledger row, from the verdict and the requirement type."""
        if judgment.verdict is RequirementVerdict.VIOLATED:
            return (
                Severity.HIGH
                if judgment.unit.requirement_type is RequirementType.HARD
                else Severity.MEDIUM
            )
        if judgment.verdict is RequirementVerdict.PARTIALLY_SATISFIED:
            return Severity.LOW
        return None

    # -- Critical findings -------------------------------------------------- #

    def _detect_critical_findings(
        self,
        judgments: Sequence[Judgment[Requirement, RequirementVerdict]],
        collector: EvidenceCollector,
        context: SharedContext,
        cfg,
    ) -> list[CriticalFinding]:
        """Raise a finding for each violated **Hard** requirement.

        Three exclusions, each deliberate:

        * **Soft requirements never qualify.** Document 2 §3 defines a Hard
          requirement as one "whose violation is treated as a critical/blocking
          issue" — the Soft type exists precisely to *not* be that.
        * **Partially Satisfied never qualifies.** A shortfall is not a breach,
          and gating trust on "gave three examples when asked for five" would be
          absurd.
        * **Unclassified requirements never qualify.** If stage 3 did not
          establish that a requirement was blocking, trust must not be gated on
          the assumption that it was.
        """
        findings: list[CriticalFinding] = []
        for judgment in judgments:
            requirement = judgment.unit
            if judgment.verdict is not RequirementVerdict.VIOLATED:
                continue
            if requirement.requirement_type is not RequirementType.HARD:
                continue

            refs = list(judgment.evidence_refs)
            if requirement.source_span:
                refs.append(collector.prompt_span(requirement.source_span).evidence_id)
            if not refs:
                refs.append(
                    collector.judge_rationale(
                        judgment.rationale or "The requirement was not satisfied."
                    ).evidence_id
                )

            findings.append(
                CriticalFinding(
                    finding_id=f"cf_{requirement.requirement_id}",
                    dimension=self.dimension,
                    type="Violated hard requirement",
                    severity=cfg.hard_requirement_blocking_severity,
                    description=(
                        f"The instruction requires: {requirement.text!r}. The "
                        f"output does not satisfy it. {judgment.rationale}".strip()
                    ),
                    evidence_refs=refs,
                    centrality=None,
                )
            )
        return findings

    # -- Stage 8 ------------------------------------------------------------ #

    def _score(
        self,
        judgments: Sequence[Judgment[Requirement, RequirementVerdict]],
        drift: dict[str, Any],
        cfg,
    ) -> float:
        """Compute the Relevance score.

        Requirement satisfaction, weighted by type, then reduced by scope drift
        beyond the configured tolerance.

        Hard requirements weigh 1.0 and Soft 0.5: both matter to relevance, but
        an explicit constraint matters more than a preference. Unevaluated
        requirements are excluded — like Accuracy's Unverifiable claims, a
        requirement nothing was learned about should cost confidence, not score.

        Drift is tolerated up to ``scope_drift_tolerance`` before it bites. Some
        drift is normal prose — transitions, framing, caveats — and penalizing
        the first off-topic sentence would fault ordinary writing.
        """
        outcomes: list[tuple[float, float]] = []
        for judgment in judgments:
            if judgment.verdict is None:
                continue
            weight = (
                1.0
                if judgment.unit.requirement_type is RequirementType.HARD
                else 0.5
            )
            outcomes.append((_VERDICT_CREDIT[judgment.verdict], weight))

        base = weighted_mean(outcomes, default=1.0)

        excess = max(0.0, drift["ratio"] - cfg.scope_drift_tolerance)
        if excess <= 0.0:
            return base
        # Scale the excess by the room above tolerance so a wholly off-topic
        # answer (ratio 1.0) drives the drift factor to zero.
        headroom = max(1e-6, 1.0 - cfg.scope_drift_tolerance)
        return clamp(base * (1.0 - clamp(excess / headroom)))

    # -- Stage 9 ------------------------------------------------------------ #

    def _confidence_signals(
        self,
        extraction,
        classified: Sequence[Requirement],
        judgments: Sequence[Judgment[Requirement, RequirementVerdict]],
        drift: dict[str, Any],
        checks: Sequence[ValidationOutcome],
    ) -> list[ConfidenceSignal]:
        """Report why Relevance is or is not confident in its own judgment."""
        total = len(classified)
        evaluated = sum(1 for j in judgments if j.is_judged)
        typed = sum(1 for r in classified if r.requirement_type is not None)
        deterministic = sum(
            1 for r in classified if r.attributes.get("constraint_kind")
        )

        signals = [
            signal(
                "requirements_evaluated",
                evaluated / total if total else 0.0,
                weight=4.0,
                rationale=(
                    f"{evaluated} of {total} requirements were evaluated against "
                    "the output"
                ),
            ),
            signal(
                "requirements_classified",
                typed / total if total else 0.0,
                weight=3.0,
                rationale=(
                    f"{typed} of {total} requirements were classified Hard or "
                    "Soft; an unclassified requirement cannot gate trust"
                ),
            ),
            signal(
                "deterministic_coverage",
                (deterministic / total) if total else 0.0,
                weight=1.0,
                rationale=(
                    f"{deterministic} of {total} requirements could be checked "
                    "deterministically, with no model variability"
                ),
            ),
            signal(
                "requirements_located",
                extraction.location_rate,
                weight=1.0,
                rationale=(
                    f"{extraction.located_count} of {len(extraction.units)} "
                    "requirements were traced to the prompt's wording"
                ),
            ),
        ]

        hints = [j.confidence_hint for j in judgments if j.confidence_hint is not None]
        signals.append(
            signal(
                "evaluation_certainty",
                sum(hints) / len(hints) if hints else 0.5,
                weight=2.0,
                rationale=(
                    f"The evaluator reported a mean certainty of "
                    f"{(sum(hints) / len(hints)) if hints else 0.5:.0%}"
                ),
            )
        )
        return signals

    # -- Stage 10 ----------------------------------------------------------- #

    def _recommendations(
        self,
        judgments: Sequence[Judgment[Requirement, RequirementVerdict]],
        drift: dict[str, Any],
        collector: EvidenceCollector,
        context: SharedContext,
    ):
        """Produce recommendations for unmet requirements and scope drift."""
        recommendations = []

        for judgment in judgments:
            requirement = judgment.unit
            if judgment.verdict in (None, RequirementVerdict.SATISFIED):
                continue

            refs = list(judgment.evidence_refs)
            if requirement.source_span:
                refs.append(collector.prompt_span(requirement.source_span).evidence_id)
            if not refs:
                continue

            is_hard = requirement.requirement_type is RequirementType.HARD
            if judgment.verdict is RequirementVerdict.VIOLATED:
                severity = Severity.HIGH if is_hard else Severity.MEDIUM
                text = f"Satisfy the instruction: {requirement.text!r}."
            else:
                severity = Severity.MEDIUM if is_hard else Severity.LOW
                text = (
                    f"Fully address the instruction: {requirement.text!r}. "
                    "It is only partly satisfied."
                )

            created = self.services.recommendations.create(
                dimension=self.dimension,
                text=text,
                severity=severity,
                evidence_refs=refs,
            )
            if created is not None:
                recommendations.append(created)

        if drift["spans"]:
            refs = [
                collector.output_span(span).evidence_id for span in drift["spans"][:3]
            ]
            created = self.services.recommendations.create(
                dimension=self.dimension,
                text=(
                    f"Remove or refocus the {len(drift['spans'])} sentence(s) that "
                    "depart from the requested topic."
                ),
                severity=Severity.LOW,
                evidence_refs=refs,
            )
            if created is not None:
                recommendations.append(created)

        return recommendations

    # -- Early exits -------------------------------------------------------- #

    def _no_prompt_result(self) -> AuditResult:
        """Result when no prompt was supplied.

        Relevance measures the output against *stated intent*. With no prompt
        there is no intent, so there is nothing to measure — and this engine is
        trust-relevant, so it must not invent a pass. Zero confidence routes the
        run toward *Unable to Verify* (Document 3, §8), which is the honest
        report: relevance was not assessed because nothing said what the output
        was supposed to do.
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

    def _no_requirements_result(self, collector: EvidenceCollector) -> AuditResult:
        """Result when the prompt imposes no extractable requirements.

        A real case — "tell me about Paris" constrains almost nothing. There is
        little to violate, so the score is high, but confidence is modest
        because the measurement rested on almost nothing.
        """
        return AuditResult(
            score=1.0,
            confidence=0.35,
            ledger=[],
            evidence=[],
            recommendations=[],
            critical_findings=[],
            metadata=self.build_metadata(),
        )

    @staticmethod
    def _count(
        judgments: Sequence[Judgment[Requirement, RequirementVerdict]],
        verdict: RequirementVerdict,
    ) -> int:
        """Count judgments with a given verdict."""
        return sum(1 for j in judgments if j.verdict is verdict)
