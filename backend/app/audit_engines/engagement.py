"""Engagement Audit Engine (``ENG-ENGAGEMENT``) — Document 2, §7.7.

**Alternate title.** Usefulness & Communicative Integrity.

**Governing question.** Does the content help the user achieve their goal
without manipulative or misleading communication?

**Inputs.** Prompt + AI Output. *Cross-engine input:* consumes prior audit
results from Relevance, Coverage, Readability, and Novelty (Document 2, §8) —
which is why the orchestrator runs it last, in wave 3.

**Classification.** Quality Dimension · Critical Finding Capability: No ·
Does Not Support N/A.

**Frozen pipeline (Document 2, §7.7), stage by stage.**

1. Input (Prompt + AI Output)
2. Context & Task Identification — :class:`TaskIdentificationStage`
3. Reuse Previous Audit Results (Relevance, Coverage, Readability, Novelty)
4. LLM-based Task Fitness Evaluation — :class:`TaskFitnessJudge` (§5.4)
5. Manipulation Pattern Detection — ``validators.detect_manipulation_patterns`` (§5.6)
6. LLM Manipulation Verification — :class:`ManipulationVerificationJudge` (§5.4)
7. Evidence Collection — :class:`EvidenceCollector` (§5.7)
8. Engagement Score
9. Confidence
10. Recommendations

**Outputs.** Score · Confidence · Engagement Ledger · Evidence ·
Recommendations.

**Stage 3 is a reuse stage, not a re-measurement stage.** Document 2 §4 is
explicit that Engagement "reuses the results of other engines rather than
recomputing overlapping signals". Whether the output was on-instruction, was
complete, was clear, was efficient — all four are already measured, by engines
with more evidence than this one has. So the four results enter here twice, and
neither time is a re-measurement: they are shown to the fitness judge as context,
and their scores contribute a single confidence-weighted term to the score at
weight 1 against the judge's 3.

That 3:1 is deliberate. Engagement must not collapse into an average of the other
four — it would then report nothing they do not already say, and a document could
never be *useless but well-made*, which is a real and common thing for a document
to be. Its own judgment leads; the reuse informs.

**Detection then verification.** Stage 5 pattern-matches; stage 6 judges. A
rhetorical question or an emphatic headline is a *pattern*, not manipulation, and
flagging on the regex alone would make this engine cry wolf on every article that
quotes a scam it is criticising.

**Two halves, never fused.** Usefulness (stages 2–4) and integrity (stages 5–6)
measure different things, and the score keeps them apart: fitness sets the level,
and confirmed manipulation is a penalty applied on top. Content that serves its
user perfectly *and* manipulates them scores badly here — which it should, and
which averaging the two would hide.
"""

from __future__ import annotations

import itertools
from typing import Mapping, Sequence

from app.audit_engines.base import AuditEngine
from app.audit_engines.registry import register_engine
from app.core.constants import CROSS_ENGINE_INPUTS
from app.core.logging import bind, get_logger
from app.shared.confidence_service import ConfidenceSignal, signal
from app.shared.context import SharedContext
from app.shared.deterministic_validators import (
    DeterministicValidators,
    ValidationOutcome,
)
from app.shared.evidence_pipeline import EvidenceCollector
from app.shared.quality_units import ManipulationCandidate, TaskContext, TaskCriterion
from app.shared.schemas import AuditResult, LedgerEntry, Severity, SEVERITY_ORDER
from app.shared.scoring import apply_penalty, weighted_mean
from app.shared.task_identification import TaskIdentificationStage
from app.shared.text_segmentation import TextSpan
from app.shared.verification.base import Judgment
from app.shared.verification.engagement import (
    ManipulationVerificationJudge,
    TaskFitnessJudge,
)
from app.shared.vocabularies import ManipulationVerdict, TaskFitnessVerdict

__all__ = ["EngagementAuditEngine"]

logger = get_logger(__name__)

#: Credit each task-fitness verdict earns toward the usefulness term.
_FITNESS_CREDIT: Mapping[TaskFitnessVerdict, float] = {
    TaskFitnessVerdict.MET: 1.0,
    TaskFitnessVerdict.PARTIALLY_MET: 0.5,
    TaskFitnessVerdict.UNMET: 0.0,
}


@register_engine
class EngagementAuditEngine(AuditEngine):
    """Measures task fitness and communicative integrity.

    Shared Components used (Document 2, §7.7): LLM Service, Deterministic
    Validators, Evidence Store, Confidence Estimator, Recommendation Generator,
    Prompt Templates, JSON Models. Cross-engine inputs: Relevance, Coverage,
    Readability, Novelty.
    """

    dimension = "Engagement"

    async def _execute(
        self, context: SharedContext, prior_results: Mapping[str, AuditResult]
    ) -> AuditResult:
        """Run the frozen Engagement pipeline."""
        cfg = self.services.settings.engines.engagement
        collector = EvidenceCollector(self.services.evidence, self.dimension)

        # -- Stage 2: Context & Task Identification ------------------------ #
        task = await self._task_identification.identify(
            context.prompt or "", context.ai_output
        )

        # -- Stage 3: Reuse Previous Audit Results ------------------------- #
        reused = self._reuse_prior_results(prior_results)

        # -- Stage 4: Task Fitness Evaluation ------------------------------ #
        fitness: tuple[Judgment[TaskCriterion, TaskFitnessVerdict], ...] = ()
        if task.criteria:
            fitness = await self._fitness_judge.judge(
                task.criteria,
                ai_output=context.ai_output,
                prompt=context.prompt or "",
                task=self._render_task(task),
                prior_findings=self._render_prior(reused),
            )

        # -- Stage 5: Manipulation Pattern Detection ----------------------- #
        outcomes = self._validators.detect_manipulation_patterns(context.ai_output)
        candidates = self._candidates_from(outcomes, context)

        # -- Stage 6: Manipulation Verification ---------------------------- #
        manipulation: tuple[
            Judgment[ManipulationCandidate, ManipulationVerdict], ...
        ] = ()
        if candidates:
            manipulation = await self._manipulation_judge.judge(
                candidates, ai_output=context.ai_output
            )

        # -- Stage 7: Evidence Collection ---------------------------------- #
        ledger = self._build_ledger(fitness, manipulation, collector)

        # -- Stage 8: Engagement Score ------------------------------------- #
        score = self._score(fitness, manipulation, reused, cfg)

        # -- Stage 9: Confidence ------------------------------------------- #
        signals = self._confidence_signals(
            task, fitness, manipulation, outcomes, reused, prior_results
        )
        confidence = self.services.confidence.estimate(signals)

        # -- Stage 10: Recommendations ------------------------------------- #
        recommendations = self._recommendations(fitness, manipulation, collector)

        logger.info(
            "engagement complete",
            extra=bind(
                audit_id=context.audit_id,
                task_identified=task.identified,
                criteria=len(task.criteria),
                met=self._count(fitness, TaskFitnessVerdict.MET),
                unmet=self._count(fitness, TaskFitnessVerdict.UNMET),
                candidates=len(candidates),
                manipulative=self._count(
                    manipulation, ManipulationVerdict.MANIPULATIVE
                ),
                reused_dimensions=sorted(reused),
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
            # Always empty: capability No (Document 2, §4.1). Manipulation is a
            # communication failure, not a trust gate — Accuracy and Credibility
            # gate trust on what the content *asserts*, and this engine has no
            # path to the Trust Verdict by design.
            critical_findings=[],
            metadata=self.build_metadata(),
        )

    # -- Injected services -------------------------------------------------- #

    @property
    def _task_identification(self) -> TaskIdentificationStage:
        return self.services.service("task_identification")  # type: ignore[return-value]

    @property
    def _fitness_judge(self) -> TaskFitnessJudge:
        return self.services.service("task_fitness")  # type: ignore[return-value]

    @property
    def _manipulation_judge(self) -> ManipulationVerificationJudge:
        return self.services.service("manipulation_verification")  # type: ignore[return-value]

    @property
    def _validators(self) -> DeterministicValidators:
        return self.services.service("validators")  # type: ignore[return-value]

    # -- Stage 3 ------------------------------------------------------------ #

    @staticmethod
    def _reuse_prior_results(
        prior_results: Mapping[str, AuditResult],
    ) -> dict[str, AuditResult]:
        """Collect the four prior results this engine is entitled to.

        Filtered to the dimensions Document 2 §8 names for Engagement, read from
        the frozen constant rather than a literal list — the orchestrator already
        passes only these, and reading the same source twice means a change to
        §8's mapping cannot leave the two disagreeing.

        Degraded results are dropped. A zero-confidence result carries no
        information (``AuditEngine.degraded_result`` reports ``score=0.0`` with
        ``confidence=0.0``), and treating its 0.0 as a measurement would let
        another engine's outage depress Engagement's score — one dimension's
        failure cascading into a second dimension's false quality signal.
        """
        return {
            dimension: result
            for dimension, result in prior_results.items()
            if dimension in CROSS_ENGINE_INPUTS["Engagement"]
            and result.confidence > 0.0
            and isinstance(result.score, float)
        }

    @staticmethod
    def _render_task(task: TaskContext) -> str:
        """Render the identified task for the fitness prompt."""
        return (
            f"Task type: {task.task_type}\n"
            f"User's goal: {task.goal}\n"
            f"Audience: {task.audience or 'unstated'}"
        )

    @staticmethod
    def _render_prior(reused: Mapping[str, AuditResult]) -> str:
        """Render the prior findings for the fitness prompt.

        Scores *and* confidences. A judge told "Coverage: 0.40" would treat the
        gap as established; told "Coverage: 0.40 (confidence 0.15)" it can see
        that Coverage barely measured anything and weigh it accordingly. Passing
        the score alone would launder a low-confidence measurement into a fact —
        the exact collapse Document 3 §8 exists to prevent.
        """
        if not reused:
            return (
                "(No prior audit results were available. Judge the output on its "
                "own terms.)"
            )
        lines = []
        for dimension, result in sorted(reused.items()):
            recommendations = "; ".join(r.text for r in result.recommendations[:3])
            lines.append(
                f"- **{dimension}**: score {result.score:.2f} "
                f"(confidence {result.confidence:.2f})"
                + (f" — noted: {recommendations}" if recommendations else "")
            )
        return "\n".join(lines)

    # -- Stage 5 ------------------------------------------------------------ #

    def _candidates_from(
        self, outcomes: Sequence[ValidationOutcome], context: SharedContext
    ) -> tuple[ManipulationCandidate, ...]:
        """Turn matched patterns into candidates for the stage 6 judge.

        Each carries the sentence it sits in. The judge cannot rule on "act now"
        stripped of its surroundings — whether the urgency is real is a fact
        about the rest of the paragraph, not about the phrase.
        """
        candidates: list[ManipulationCandidate] = []
        ids = itertools.count(1)

        for outcome in outcomes:
            if outcome.passed:
                continue  # The "nothing matched" outcome.
            start = outcome.observed.get("start")
            end = outcome.observed.get("end")
            phrase = str(outcome.observed.get("match", "")).strip()
            if not phrase or not isinstance(start, int) or not isinstance(end, int):
                continue

            span = TextSpan(
                text=context.ai_output[start:end],
                start=start,
                end=end,
                index=len(candidates),
                kind="manipulation",
            )
            candidates.append(
                ManipulationCandidate(
                    candidate_id=f"man_{next(ids)}",
                    family=str(outcome.observed.get("family", "unknown")),
                    text=phrase,
                    source_span=span,
                    pattern_severity=outcome.severity or Severity.LOW,
                    attributes={
                        "context": self._sentence_around(context, start),
                        "detail": outcome.detail,
                        "check": outcome.check,
                    },
                )
            )
        return tuple(candidates)

    @staticmethod
    def _sentence_around(context: SharedContext, offset: int) -> str:
        """Return the sentence containing ``offset``, for the judge's context."""
        for span in context.sentences:
            if span.start <= offset < span.end:
                return span.text
        return ""

    # -- Stage 7 ------------------------------------------------------------ #

    def _build_ledger(
        self,
        fitness: Sequence[Judgment[TaskCriterion, TaskFitnessVerdict]],
        manipulation: Sequence[Judgment[ManipulationCandidate, ManipulationVerdict]],
        collector: EvidenceCollector,
    ) -> list[LedgerEntry]:
        """Build the Engagement Ledger (Document 2, §6.3).

        The §6.3 unit is a "Task-fitness / manipulation item" — the two kinds the
        specification names, and both appear here. Fitness first: usefulness is
        the engine's primary question, and integrity qualifies it.
        """
        entries: list[LedgerEntry] = []

        for judgment in fitness:
            criterion = judgment.unit
            refs: list[str] = []
            if judgment.rationale:
                refs.append(collector.judge_rationale(judgment.rationale).evidence_id)

            entries.append(
                LedgerEntry(
                    entry_id=criterion.criterion_id,
                    unit=criterion.text,
                    unit_type="Task fitness",
                    verdict=(
                        judgment.verdict.value if judgment.verdict else "Not evaluated"
                    ),
                    severity=self._fitness_severity(judgment, criterion),
                    evidence_refs=refs,
                    rationale=(
                        judgment.rationale
                        or "The fitness evaluation returned no verdict for this "
                        "criterion, so it is excluded from the score and lowers "
                        "confidence instead."
                    ),
                    attributes={
                        "importance": round(criterion.importance, 2),
                        "judged": judgment.is_judged,
                    },
                )
            )

        for judgment in manipulation:
            candidate = judgment.unit
            refs = []
            if candidate.source_span:
                refs.append(collector.output_span(candidate.source_span).evidence_id)
            refs.append(
                collector.validator_result(
                    str(candidate.attributes.get("check", "manipulation")),
                    str(candidate.attributes.get("detail", candidate.text)),
                ).evidence_id
            )
            if judgment.rationale:
                refs.append(collector.judge_rationale(judgment.rationale).evidence_id)

            entries.append(
                LedgerEntry(
                    entry_id=candidate.candidate_id,
                    unit=candidate.text,
                    unit_type="Manipulation item",
                    verdict=(
                        judgment.verdict.value if judgment.verdict else "Not verified"
                    ),
                    severity=(
                        candidate.pattern_severity
                        if judgment.verdict is ManipulationVerdict.MANIPULATIVE
                        else None
                    ),
                    evidence_refs=refs,
                    rationale=(
                        judgment.rationale
                        or "The manipulation verification returned no verdict for "
                        "this candidate. A matched pattern is not a finding, so it "
                        "costs the score nothing and lowers confidence instead."
                    ),
                    attributes={
                        "pattern_family": candidate.family,
                        "pattern_severity": candidate.pattern_severity.value,
                        "judged": judgment.is_judged,
                        "context": candidate.attributes.get("context"),
                    },
                )
            )

        return entries

    @staticmethod
    def _fitness_severity(
        judgment: Judgment[TaskCriterion, TaskFitnessVerdict], criterion: TaskCriterion
    ) -> Severity | None:
        """Grade an unmet criterion by how much the user's goal needed it."""
        if judgment.verdict is TaskFitnessVerdict.UNMET:
            return Severity.HIGH if criterion.importance >= 0.7 else Severity.MEDIUM
        if judgment.verdict is TaskFitnessVerdict.PARTIALLY_MET:
            return Severity.MEDIUM if criterion.importance >= 0.7 else Severity.LOW
        return None

    # -- Stage 8 ------------------------------------------------------------ #

    def _score(
        self,
        fitness: Sequence[Judgment[TaskCriterion, TaskFitnessVerdict]],
        manipulation: Sequence[Judgment[ManipulationCandidate, ManipulationVerdict]],
        reused: Mapping[str, AuditResult],
        cfg,
    ) -> float:
        """Compute the Engagement score.

        Two terms and a penalty:

        * **Task fitness** (weight 3) — the importance-weighted rate at which the
          output meets the criteria. This engine's own judgment, and it leads.
        * **Reused prior results** (weight 1) — the confidence-weighted mean of
          the Relevance, Coverage, Readability, and Novelty scores. Stage 3's
          reuse, entering the arithmetic. Weighted low on purpose: Engagement
          must not become an average of the other four, or it would report
          nothing they do not already say and could never find a document that is
          well-made and useless.
        * **Manipulation penalty** — subtracted, not averaged. Integrity is not a
          strength that offsets a weakness; content that manipulates its reader
          has done something wrong that being useful does not excuse, and
          averaging would let a high fitness score dilute it away.

        Weighting the reuse by each engine's *confidence* is what keeps a
        low-confidence measurement from being laundered into a fact here
        (Document 3, §8).

        Returns:
            The score in [0, 1].
        """
        terms: list[tuple[float, float]] = []

        outcomes = [
            (_FITNESS_CREDIT[j.verdict], max(j.unit.importance, 0.05))
            for j in fitness
            if j.verdict is not None
        ]
        if outcomes:
            terms.append((weighted_mean(outcomes, default=1.0), 3.0))

        reuse = [(float(result.score), result.confidence) for result in reused.values()]
        if reuse:
            terms.append((weighted_mean(reuse, default=1.0), 1.0))

        base = weighted_mean(terms, default=1.0)
        return apply_penalty(base, self._manipulation_penalties(manipulation, cfg))

    @staticmethod
    def _manipulation_penalties(
        manipulation: Sequence[Judgment[ManipulationCandidate, ManipulationVerdict]],
        cfg,
    ) -> dict[str, float]:
        """Size the penalty for each confirmed manipulation item.

        Only **confirmed** manipulation is charged. A *Borderline* item is pushy
        rather than deceptive and costs a fraction; a *Legitimate* item costs
        nothing, and an unverified candidate costs nothing either — a pattern the
        judge never ruled on has not been shown to manipulate anyone, and
        charging for it would let the regex convict on its own.
        """
        penalties: dict[str, float] = {}
        for judgment in manipulation:
            if judgment.verdict is ManipulationVerdict.MANIPULATIVE:
                weight = 1.0
            elif judgment.verdict is ManipulationVerdict.BORDERLINE:
                weight = cfg.borderline_penalty_factor
            else:
                continue
            severity = judgment.unit.pattern_severity
            penalties[judgment.unit.candidate_id] = (
                cfg.manipulation_penalty.get(severity.value, 0.05) * weight
            )
        return penalties

    # -- Stage 9 ------------------------------------------------------------ #

    def _confidence_signals(
        self,
        task: TaskContext,
        fitness: Sequence[Judgment[TaskCriterion, TaskFitnessVerdict]],
        manipulation: Sequence[Judgment[ManipulationCandidate, ManipulationVerdict]],
        outcomes: Sequence[ValidationOutcome],
        reused: Mapping[str, AuditResult],
        prior_results: Mapping[str, AuditResult],
    ) -> list[ConfidenceSignal]:
        """Report why Engagement is or is not confident in its own judgment."""
        expected = len(CROSS_ENGINE_INPUTS["Engagement"])
        criteria = len(task.criteria)
        judged = sum(1 for j in fitness if j.is_judged)
        verified = sum(1 for j in manipulation if j.is_judged)

        signals = [
            signal(
                "task_identified",
                1.0 if task.identified else 0.0,
                # Heaviest, with criteria_evaluated: without a task there is no
                # goal, and "does this help the user achieve their goal" then has
                # no answer at all — not a low score, no answer. Document 3 §8
                # wants that to read as a gap, never as a failing measurement.
                weight=4.0,
                rationale=(
                    f"The user's task was identified as {task.task_type!r} with "
                    f"{criteria} success criteria"
                    if task.identified
                    else "No prompt was supplied, so the user's goal could not be "
                    "identified and task fitness could not be evaluated"
                ),
            ),
            signal(
                "criteria_evaluated",
                judged / criteria if criteria else 0.0,
                weight=4.0,
                rationale=(
                    f"The fitness evaluation returned a verdict for {judged} of "
                    f"{criteria} criteria"
                ),
            ),
            signal(
                "prior_results_available",
                len(reused) / expected,
                weight=2.0,
                rationale=(
                    f"{len(reused)} of {expected} prior audit results were usable "
                    f"for reuse ({', '.join(sorted(reused)) or 'none'})"
                ),
            ),
            signal(
                "manipulation_checked",
                1.0 if outcomes else 0.0,
                weight=2.0,
                rationale=(
                    "The manipulation pattern check ran over the output"
                    if outcomes
                    else "The manipulation pattern check produced no result"
                ),
            ),
        ]

        if manipulation:
            signals.append(
                signal(
                    "candidates_verified",
                    verified / len(manipulation),
                    weight=2.0,
                    rationale=(
                        f"{verified} of {len(manipulation)} matched patterns were "
                        "ruled on by the verification stage"
                    ),
                )
            )

        hints = [
            j.confidence_hint
            for j in (*fitness, *manipulation)
            if j.confidence_hint is not None
        ]
        signals.append(
            signal(
                "judge_certainty",
                sum(hints) / len(hints) if hints else 0.5,
                weight=2.0,
                rationale=(
                    f"The fitness and manipulation judges reported a mean "
                    f"certainty of {(sum(hints) / len(hints)) if hints else 0.5:.0%}"
                ),
            )
        )
        return signals

    # -- Stage 10 ----------------------------------------------------------- #

    def _recommendations(
        self,
        fitness: Sequence[Judgment[TaskCriterion, TaskFitnessVerdict]],
        manipulation: Sequence[Judgment[ManipulationCandidate, ManipulationVerdict]],
        collector: EvidenceCollector,
    ):
        """Produce recommendations for unmet criteria and confirmed manipulation.

        Every one carries evidence: Document 3 §10 drops a recommendation with no
        traceable pointer, and for a fitness verdict the judge's rationale is the
        only evidence there is.
        """
        recommendations = []

        for judgment in manipulation:
            if judgment.verdict not in (
                ManipulationVerdict.MANIPULATIVE,
                ManipulationVerdict.BORDERLINE,
            ):
                continue
            candidate = judgment.unit
            refs: list[str] = []
            if candidate.source_span:
                refs.append(collector.output_span(candidate.source_span).evidence_id)
            refs.append(
                collector.validator_result(
                    str(candidate.attributes.get("check", "manipulation")),
                    str(candidate.attributes.get("detail", candidate.text)),
                ).evidence_id
            )
            confirmed = judgment.verdict is ManipulationVerdict.MANIPULATIVE
            created = self.services.recommendations.create(
                dimension=self.dimension,
                text=(
                    (
                        f"Rewrite the {candidate.family.replace('_', ' ')} phrasing "
                        f"{candidate.text!r}: {judgment.rationale}"
                    )
                    if confirmed
                    else (
                        f"Consider softening the "
                        f"{candidate.family.replace('_', ' ')} phrasing "
                        f"{candidate.text!r}: {judgment.rationale}"
                    )
                ),
                severity=candidate.pattern_severity if confirmed else Severity.LOW,
                evidence_refs=refs,
            )
            if created is not None:
                recommendations.append(created)

        unmet = [
            j
            for j in fitness
            if j.verdict in (TaskFitnessVerdict.UNMET, TaskFitnessVerdict.PARTIALLY_MET)
        ]
        unmet.sort(key=lambda j: j.unit.importance, reverse=True)

        for judgment in unmet:
            if not judgment.rationale:
                continue
            refs = [collector.judge_rationale(judgment.rationale).evidence_id]
            created = self.services.recommendations.create(
                dimension=self.dimension,
                text=(
                    f"Serve the user's goal more directly — {judgment.unit.text} "
                    f"{judgment.rationale}"
                ),
                severity=self._fitness_severity(judgment, judgment.unit)
                or Severity.LOW,
                evidence_refs=refs,
            )
            if created is not None:
                recommendations.append(created)

        recommendations.sort(key=lambda r: SEVERITY_ORDER[r.severity], reverse=True)
        return recommendations

    @staticmethod
    def _count(judgments: Sequence[Judgment], verdict) -> int:
        """Count judgments with a given verdict."""
        return sum(1 for j in judgments if j.verdict is verdict)
