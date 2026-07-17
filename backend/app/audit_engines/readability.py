"""Readability Audit Engine (``ENG-READABILITY``) — Document 2, §7.6.

**Governing question.** Is the content easy for its intended audience to
understand (clarity, coherence, structure)?

**Inputs.** AI Output.

**Classification.** Quality Dimension · Critical Finding Capability: No ·
Does Not Support N/A.

**Frozen pipeline (Document 2, §7.6), stage by stage.**

1. Input (AI Output)
2. Deterministic Analysis — ``validators.analyze_readability`` (§5.6)
3. LLM Readability Review (Clarity, Coherence, Structure) — :class:`ReadabilityReviewJudge` (§5.4)
4. Issue Classification — :class:`IssueClassifier` (§5.2)
5. Severity Assignment — :class:`IssueSeverityAssigner` (§5.2)
6. Evidence Collection — :class:`EvidenceCollector` (§5.7)
7. Readability Score
8. Confidence
9. Recommendations

**Outputs.** Score · Confidence · Readability Ledger · Evidence ·
Recommendations.

**Note the ordering.** Deterministic analysis runs *before* the LLM review, not
after. The cheap, reproducible signals are gathered first and give the reviewer
something concrete to reason about — and Document 4 §11 wants as much of the
verdict as possible resting on checks that do not vary between runs.

**Three decisions in this engine deserve to be understood before changing it.**

*Deterministic issues skip stages 4 and 5, and that is the point of having a
deterministic stage.* An issue produced by a rule arrives already classified —
the check that raised it *is* its category — and already severitied, by that
rule. Sending it to a model to be relabelled would ask a model what a regex
already knows, and would reintroduce the run-to-run variance the stage exists to
keep out (Document 4, §11). Reviewed issues, which arrive as free text, go
through both stages.

*A failed deterministic bound is not a readability verdict.* "The longest
sentence runs 68 words" is a fact; whether that sentence is *hard to read* is the
reviewer's judgment, made with the sentence in front of it. So stage 2 supplies
context to stage 3 rather than pre-empting it, and the score weights the review
above the measurements.

*The ledger carries the three aspects as well as the issues.* Document 2 §6.3
names *Issue* as this ledger's unit, and every issue is here. The three aspect
rows are additive: the score is computed from the aspect verdicts, and a ledger
that omitted them could not explain the number sitting next to it — which
Document 3 §13 requires it to do. Accuracy sets the precedent, recording
non-factual claims it never verifies so its ledger stays a complete account.

This engine is also the clearest case for the two-axis separation: polished prose
scores well here while Credibility is simultaneously gating the content to
*Untrusted* over a fabricated citation. Readability lowers or raises the Quality
band and touches trust never (Document 3, §7).
"""

from __future__ import annotations

import itertools
from typing import Mapping, Sequence

from app.audit_engines.base import AuditEngine
from app.audit_engines.registry import register_engine
from app.core.logging import bind, get_logger
from app.shared.classification.readability import (
    IssueClassifier,
    IssueSeverityAssigner,
)
from app.shared.confidence_service import ConfidenceSignal, signal
from app.shared.context import SharedContext
from app.shared.deterministic_validators import (
    DeterministicValidators,
    ValidationOutcome,
)
from app.shared.evidence_pipeline import EvidenceCollector
from app.shared.quality_units import (
    READABILITY_ASPECTS,
    ReadabilityAspect,
    ReadabilityIssue,
)
from app.shared.schemas import AuditResult, LedgerEntry, Severity, SEVERITY_ORDER
from app.shared.scoring import weighted_mean
from app.shared.text_segmentation import locate_span
from app.shared.verification.base import Judgment
from app.shared.verification.readability import (
    ReadabilityReview,
    ReadabilityReviewJudge,
    ReviewedIssue,
)
from app.shared.vocabularies import ReadabilityVerdict

__all__ = ["ReadabilityAuditEngine"]

logger = get_logger(__name__)

#: Credit each aspect verdict earns toward the score.
#:
#: *Acceptable* sits nearer the top than the middle on purpose: prose a reader
#: follows with some effort is ordinary competent writing, not a defect, and
#: scoring it 0.5 would report the median document as half-unreadable. *Unclear*
#: keeps a small floor because an aspect can fail while the content still
#: communicates something — the Quality band is compensatory (Document 3, §7),
#: and a zero here would speak with more certainty than a three-value verdict
#: earns.
_ASPECT_CREDIT: Mapping[ReadabilityVerdict, float] = {
    ReadabilityVerdict.CLEAR: 1.0,
    ReadabilityVerdict.ACCEPTABLE: 0.65,
    ReadabilityVerdict.UNCLEAR: 0.15,
}


@register_engine
class ReadabilityAuditEngine(AuditEngine):
    """Measures clarity, coherence, and document structure.

    Shared Components used (Document 2, §7.6): Deterministic Validators, LLM
    Service, Evidence Store, Confidence Estimator, Recommendation Generator,
    Prompt Templates, JSON Models.
    """

    dimension = "Readability"

    async def _execute(
        self, context: SharedContext, prior_results: Mapping[str, AuditResult]
    ) -> AuditResult:
        """Run the frozen Readability pipeline."""
        cfg = self.services.settings.engines.readability
        collector = EvidenceCollector(self.services.evidence, self.dimension)
        issue_ids = itertools.count(1)

        if context.statistics.word_count < cfg.min_words_for_review:
            return self._too_short_result(context, cfg)

        # -- Stage 2: Deterministic Analysis ------------------------------- #
        # Reads context.sentences rather than re-segmenting: the auditor reports
        # one sentence count for one document (see SharedContext).
        outcomes = self._validators.analyze_readability(
            context.ai_output,
            sentences=[span.text for span in context.sentences],
            thresholds=cfg.thresholds(),
        )

        # -- Stage 3: LLM Readability Review ------------------------------- #
        review = await self._review_judge.review(
            READABILITY_ASPECTS,
            ai_output=context.ai_output,
            deterministic_analysis=self._render_analysis(outcomes),
        )

        # -- Stages 4-5: Issue Classification and Severity Assignment ------- #
        deterministic_issues = self._deterministic_issues(outcomes, context, issue_ids)
        reviewed = self._reviewed_issues(review.issues, context, issue_ids)

        classified = await self._issue_classifier.classify(reviewed) if reviewed else ()
        labelled = (
            await self._severity_assigner.classify(classified) if classified else ()
        )
        issues = [*deterministic_issues, *labelled]

        # -- Stage 6: Evidence Collection ---------------------------------- #
        ledger = self._build_ledger(review, issues, outcomes, collector)

        # -- Stage 7: Readability Score ------------------------------------ #
        score = self._score(review.aspects, outcomes)

        # -- Stage 8: Confidence ------------------------------------------- #
        signals = self._confidence_signals(context, review, outcomes, issues, cfg)
        confidence = self.services.confidence.estimate(signals)

        # -- Stage 9: Recommendations -------------------------------------- #
        recommendations = self._recommendations(issues, collector)

        logger.info(
            "readability complete",
            extra=bind(
                audit_id=context.audit_id,
                aspects_judged=review.judged_count,
                deterministic_checks=len(outcomes),
                deterministic_failed=sum(1 for o in outcomes if not o.passed),
                issues=len(issues),
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
            # Always empty: capability No (Document 2, §4.1). A dimension that
            # cannot emit a finding cannot gate trust, which is precisely why
            # badly-written content is never Untrusted for being badly written.
            critical_findings=[],
            metadata=self.build_metadata(),
        )

    # -- Injected services -------------------------------------------------- #

    @property
    def _validators(self) -> DeterministicValidators:
        return self.services.service("validators")  # type: ignore[return-value]

    @property
    def _review_judge(self) -> ReadabilityReviewJudge:
        return self.services.service("readability_review")  # type: ignore[return-value]

    @property
    def _issue_classifier(self) -> IssueClassifier:
        return self.services.service("issue_classifier")  # type: ignore[return-value]

    @property
    def _severity_assigner(self) -> IssueSeverityAssigner:
        return self.services.service("issue_severity")  # type: ignore[return-value]

    # -- Stage 2 ------------------------------------------------------------ #

    @staticmethod
    def _render_analysis(outcomes: Sequence[ValidationOutcome]) -> str:
        """Render the deterministic measurements for the reviewer's prompt.

        Both passing and failing checks are shown. A reviewer told only what
        failed would read the list as a charge sheet and find problems to match
        it; told that the reading ease is fine and the longest sentence is not,
        it has the actual shape of the text.
        """
        if not outcomes:
            return "(no deterministic measurements were available)"
        return "\n".join(
            f"- {'OK  ' if outcome.passed else 'FLAG'} {outcome.detail}"
            for outcome in outcomes
        )

    def _deterministic_issues(
        self,
        outcomes: Sequence[ValidationOutcome],
        context: SharedContext,
        ids: itertools.count,
    ) -> list[ReadabilityIssue]:
        """Turn failed deterministic checks into pre-classified issues.

        These bypass stages 4 and 5 by construction — see the module docstring.
        The check name is the category, the validator's severity is the severity,
        and both are reproducible in a way no model's label is.
        """
        issues: list[ReadabilityIssue] = []
        for outcome in outcomes:
            if outcome.passed:
                continue

            quote = outcome.observed.get("sentence")
            quote = quote if isinstance(quote, str) and quote.strip() else None
            span = (
                locate_span(context.ai_output, quote, kind="readability_issue")
                if quote
                else None
            )

            issues.append(
                ReadabilityIssue(
                    issue_id=f"iss_{next(ids)}",
                    text=outcome.detail,
                    aspect=_ASPECT_OF_CHECK.get(outcome.check, "structure"),
                    quote=quote,
                    source_span=span,
                    origin="deterministic",
                    category=outcome.check,
                    severity=outcome.severity or Severity.LOW,
                    attributes={"observed": outcome.observed, "check": outcome.check},
                )
            )
        return issues

    # -- Stages 4-5 --------------------------------------------------------- #

    @staticmethod
    def _reviewed_issues(
        reviewed: Sequence[ReviewedIssue],
        context: SharedContext,
        ids: itertools.count,
    ) -> tuple[ReadabilityIssue, ...]:
        """Turn the reviewer's issues into units for stages 4 and 5.

        Each is located by its quote where the quote can be found. An issue whose
        quote does not appear in the output keeps the quote as text but gets no
        span — :func:`locate_span` returns ``None`` rather than fuzzy-matching,
        because a highlight pointing at text the model did not actually quote is
        worse than no highlight.
        """
        issues: list[ReadabilityIssue] = []
        for item in reviewed:
            span = (
                locate_span(context.ai_output, item.quote, kind="readability_issue")
                if item.quote
                else None
            )
            issues.append(
                ReadabilityIssue(
                    issue_id=f"iss_{next(ids)}",
                    text=item.text,
                    aspect=item.aspect,
                    quote=item.quote or None,
                    source_span=span,
                    origin="review",
                )
            )
        return tuple(issues)

    # -- Stage 6 ------------------------------------------------------------ #

    def _build_ledger(
        self,
        review: ReadabilityReview,
        issues: Sequence[ReadabilityIssue],
        outcomes: Sequence[ValidationOutcome],
        collector: EvidenceCollector,
    ) -> list[LedgerEntry]:
        """Build the Readability Ledger (Document 2, §6.3).

        Aspects first, then issues — the order a reader wants: the verdict, then
        what is behind it.
        """
        entries: list[LedgerEntry] = []

        for judgment in review.aspects:
            aspect = judgment.unit
            refs: list[str] = []
            if judgment.rationale:
                refs.append(collector.judge_rationale(judgment.rationale).evidence_id)

            entries.append(
                LedgerEntry(
                    entry_id=aspect.aspect_id,
                    unit=aspect.name,
                    unit_type="Aspect",
                    verdict=(
                        judgment.verdict.value if judgment.verdict else "Not reviewed"
                    ),
                    severity=None,
                    evidence_refs=refs,
                    rationale=(
                        judgment.rationale
                        or "The review returned no verdict for this aspect, so it "
                        "is excluded from the score and lowers confidence instead."
                    ),
                    attributes={
                        "judged": judgment.is_judged,
                        "issue_count": sum(
                            1 for i in issues if i.aspect == aspect.aspect_id
                        ),
                    },
                )
            )

        for issue in issues:
            refs = []
            if issue.source_span:
                refs.append(collector.output_span(issue.source_span).evidence_id)
            if issue.is_deterministic:
                refs.append(
                    collector.validator_result(
                        str(issue.attributes.get("check", "readability")),
                        issue.text,
                    ).evidence_id
                )

            entries.append(
                LedgerEntry(
                    entry_id=issue.issue_id,
                    unit=issue.text,
                    unit_type="Issue",
                    verdict=issue.category or "unclassified",
                    severity=issue.severity,
                    evidence_refs=refs,
                    rationale=self._issue_rationale(issue),
                    attributes={
                        "aspect": issue.aspect,
                        "origin": issue.origin,
                        "quote": issue.quote,
                        "classified": issue.is_classified,
                        **(
                            {"observed": issue.attributes["observed"]}
                            if "observed" in issue.attributes
                            else {}
                        ),
                    },
                )
            )

        return entries

    @staticmethod
    def _issue_rationale(issue: ReadabilityIssue) -> str:
        """Explain where an issue came from and how it was labelled."""
        if issue.is_deterministic:
            return (
                "Raised by a deterministic check, which supplied its category "
                "and severity directly. This result is identical on every re-run."
            )
        if not issue.is_classified:
            return (
                "Raised by the readability review. The labelling stage returned "
                "no category or severity for it, so it is recorded but does not "
                "carry weight."
            )
        reasons = [
            issue.attributes.get("category_rationale"),
            issue.attributes.get("severity_rationale"),
        ]
        stated = "; ".join(r for r in reasons if isinstance(r, str) and r.strip())
        return stated or "Raised by the readability review."

    # -- Stage 7 ------------------------------------------------------------ #

    @staticmethod
    def _score(
        aspects: Sequence[Judgment[ReadabilityAspect, ReadabilityVerdict]],
        outcomes: Sequence[ValidationOutcome],
    ) -> float:
        """Compute the Readability score.

        Two terms, combined by weighted mean:

        * **The aspect review** (weight 3) — the substantive judgment. Clarity,
          coherence, and structure are what the dimension is *about*, and only a
          reader-like judgment can assess them.
        * **The deterministic pass rate** (weight 1) — a corroborating signal.
          It cannot vary between runs, which makes it worth having, but it
          measures proxies: sentence length is evidence about readability, not
          readability itself.

        The 3:1 weighting is the whole argument for this shape. Inverting it
        would let a document of short, simple, disconnected sentences outscore a
        well-argued one with long sentences — which is exactly the mistake
        readability formulas make and exactly why the review exists.

        Unjudged aspects are excluded rather than scored zero, on the same
        principle as Accuracy's Unverifiable claims: an aspect nothing was
        learned about has not failed. The cost lands on confidence.

        Returns:
            The score in [0, 1]. ``1.0`` when nothing could be measured at all —
            but paired with the near-zero confidence stage 8 reports for that
            case, which is what makes it read as "undetermined" rather than
            "perfect".
        """
        terms: list[tuple[float, float]] = []

        credits = [
            _ASPECT_CREDIT[j.verdict] for j in aspects if j.verdict is not None
        ]
        if credits:
            terms.append((sum(credits) / len(credits), 3.0))

        if outcomes:
            passed = sum(1 for outcome in outcomes if outcome.passed)
            terms.append((passed / len(outcomes), 1.0))

        return weighted_mean(terms, default=1.0)

    # -- Stage 8 ------------------------------------------------------------ #

    def _confidence_signals(
        self,
        context: SharedContext,
        review: ReadabilityReview,
        outcomes: Sequence[ValidationOutcome],
        issues: Sequence[ReadabilityIssue],
        cfg,
    ) -> list[ConfidenceSignal]:
        """Report why Readability is or is not confident in its own judgment."""
        total_aspects = len(READABILITY_ASPECTS)
        reviewed = [i for i in issues if not i.is_deterministic]
        labelled = sum(1 for i in reviewed if i.is_classified)

        signals = [
            signal(
                "aspects_reviewed",
                review.judged_count / total_aspects,
                # Heaviest: the review is the dimension's substantive judgment.
                # The measurements corroborate it; they cannot replace it, and a
                # score resting on them alone is a formula, not an assessment.
                weight=4.0,
                rationale=(
                    f"{review.judged_count} of {total_aspects} aspects were "
                    "reviewed"
                ),
            ),
            signal(
                "deterministic_checks_ran",
                min(1.0, len(outcomes) / cfg.expected_check_count),
                weight=2.0,
                rationale=(
                    f"{len(outcomes)} deterministic checks produced a "
                    "measurement"
                ),
            ),
            signal(
                "content_sufficient",
                min(1.0, context.statistics.word_count / cfg.words_for_full_confidence),
                weight=2.0,
                rationale=(
                    f"The output runs {context.statistics.word_count} words; "
                    "coherence and structure are harder to assess in a short text"
                ),
            ),
        ]

        if reviewed:
            signals.append(
                signal(
                    "issues_labelled",
                    labelled / len(reviewed),
                    weight=2.0,
                    rationale=(
                        f"{labelled} of {len(reviewed)} reviewed issues carry "
                        "both a category and a severity"
                    ),
                )
            )
            located = sum(1 for i in reviewed if i.source_span is not None)
            signals.append(
                signal(
                    "issues_located",
                    located / len(reviewed),
                    weight=1.0,
                    rationale=(
                        f"{located} of {len(reviewed)} reviewed issues were "
                        "traced to a span of the output"
                    ),
                )
            )

        # The reviewer's own stated certainty. Without it every signal above can
        # max out and the engine reports 1.0 — an absolute claim to correctness
        # that no LLM judgment earns (Document 2, §5.10).
        hints = [
            j.confidence_hint for j in review.aspects if j.confidence_hint is not None
        ]
        signals.append(
            signal(
                "reviewer_certainty",
                sum(hints) / len(hints) if hints else 0.5,
                weight=2.0,
                rationale=(
                    f"The reviewer reported a mean certainty of "
                    f"{(sum(hints) / len(hints)) if hints else 0.5:.0%}"
                ),
            )
        )
        return signals

    # -- Stage 9 ------------------------------------------------------------ #

    def _recommendations(
        self, issues: Sequence[ReadabilityIssue], collector: EvidenceCollector
    ):
        """Produce a recommendation per issue, worst first.

        Ordered by severity so the most obstructive problem is proposed first.
        The Decision Engine orders across dimensions (Document 3, §10); within
        Readability the engine already knows which issue costs the reader most.

        Every recommendation carries evidence — Document 3 §10 drops one that
        does not, so an issue with neither a span nor a validator result to point
        at is left in the ledger and out of the action list.
        """
        ranked = sorted(
            issues,
            key=lambda i: SEVERITY_ORDER[i.severity or Severity.INFO],
            reverse=True,
        )
        recommendations = []

        for issue in ranked:
            if issue.severity is None:
                continue

            refs: list[str] = []
            if issue.source_span:
                refs.append(collector.output_span(issue.source_span).evidence_id)
            if issue.is_deterministic:
                refs.append(
                    collector.validator_result(
                        str(issue.attributes.get("check", "readability")),
                        issue.text,
                    ).evidence_id
                )
            if not refs:
                continue

            created = self.services.recommendations.create(
                dimension=self.dimension,
                text=self._recommendation_text(issue),
                severity=issue.severity,
                evidence_refs=refs,
            )
            if created is not None:
                recommendations.append(created)

        return recommendations

    @staticmethod
    def _recommendation_text(issue: ReadabilityIssue) -> str:
        """Phrase an issue as an action."""
        if issue.quote:
            return (
                f"Revise for {issue.category or issue.aspect}: {issue.text} "
                f"Affected text: {issue.quote!r}."
            )
        return f"Revise for {issue.category or issue.aspect}: {issue.text}"

    # -- Early exit --------------------------------------------------------- #

    def _too_short_result(self, context: SharedContext, cfg) -> AuditResult:
        """Result for an output too short to assess.

        Coherence and structure are properties of how parts relate, and a
        one-sentence answer has no parts. Reporting a confident *Clear* would
        assert an assessment that was never possible; reporting *Unclear* would
        fault a short answer for being short. Neither is honest, so the engine
        reports a neutral score with low confidence and lets the Decision Engine
        weigh the contribution down accordingly (Document 3, §8).

        Readability cannot return N/A (Document 2, §4.1), so this is the closest
        honest answer available to it — the same resolution Coverage reaches for
        a missing reference.
        """
        logger.info(
            "readability: output too short to assess",
            extra=bind(
                audit_id=context.audit_id,
                word_count=context.statistics.word_count,
                minimum=cfg.min_words_for_review,
            ),
        )
        return AuditResult(
            score=1.0,
            confidence=0.15,
            ledger=[],
            evidence=[],
            recommendations=[],
            critical_findings=[],
            metadata=self.build_metadata(),
        )


#: Which aspect each deterministic check belongs to.
#:
#: The mapping is what lets a rule-produced issue skip stage 4: the check *is*
#: its classification. Unlisted checks fall back to ``structure``, the aspect
#: whose measurements are the least sentence-local.
_ASPECT_OF_CHECK: Mapping[str, str] = {
    "mean_sentence_length": "clarity",
    "longest_sentence": "clarity",
    "reading_ease": "clarity",
    "grade_level": "clarity",
    "repeated_words": "clarity",
    "sentence_termination": "clarity",
    "paragraph_length": "structure",
    "structural_aids": "structure",
}
