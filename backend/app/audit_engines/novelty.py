"""Novelty Audit Engine (``ENG-NOVELTY``) — Document 2, §7.5.

**Governing question.** Does the output communicate efficiently, minimizing
unnecessary repetition while preserving important content?

**Inputs.** AI Output. *Cross-engine input:* consumes Coverage results for the
Coverage Cross-check (Document 2, §8) — which is why the orchestrator runs
Novelty in wave 2, after Coverage.

**Classification.** Quality Dimension · Critical Finding Capability: No ·
Does Not Support N/A.

Capability No is not an oversight. A repetitive text is badly made, not
untrustworthy, so Novelty can lower the Quality band but can never gate trust
(Document 3, §5).

**Frozen pipeline (Document 2, §7.5), stage by stage.**

1. Input (AI Output)
2. Text Segmentation — reads ``context.sentences``
3. Sentence Embedding Generation — :class:`EmbeddingService` (§5.5)
4. Semantic & Literal Duplicate Detection
5. Candidate Redundancy Identification
6. LLM-based Functional Repetition Review — :class:`FunctionalRepetitionJudge` (§5.4)
7. Coverage Cross-check — ``prior_results["Coverage"]`` (§8)
8. Novelty Score
9. Confidence
10. Recommendations

**Outputs.** Score · Confidence · Redundancy Ledger · Evidence ·
Recommendations.

**Stage 2 is still Novelty's stage.** It reads the shared segmentation rather
than carrying its own splitter — reuse of a mechanism is not relocation of a
stage (see :mod:`app.shared.context`). Two engines reporting different sentence
counts for one document would be a report nobody can defend.

**Why stages 6 and 7 both exist, and why 7 comes second.** Stage 4 finds text
that *looks* duplicated. Stage 6 asks a reader-like judge whether it earns its
place. Stage 7 then checks that answer against what Coverage found important —
and this is the order the specification freezes, which is also the order that
works: the judge decides on the writing, and the cross-check can then *rescue* a
passage the judge condemned but the reference material needs restated.

The rescue is the point of the cross-check. Coverage rewards an output for
conveying a high-salience key point; if Novelty then told the writer to delete
the sentence that conveys it, the two engines would issue opposite instructions
about the same text and the report would be incoherent. So a confirmed-redundant
segment that restates a salient key point Coverage found present is reclassified
as functional — **and the override is recorded in the ledger, never applied
silently**, exactly as Relevance records its deterministic overrides.
"""

from __future__ import annotations

import itertools
from dataclasses import replace
from typing import Mapping, Sequence

from app.audit_engines.base import AuditEngine
from app.audit_engines.registry import register_engine
from app.core.logging import bind, get_logger
from app.shared.confidence_service import ConfidenceSignal, signal
from app.shared.context import SharedContext
from app.shared.embedding_service import EmbeddingService, relatedness
from app.shared.evidence_pipeline import EvidenceCollector
from app.shared.quality_units import RedundancyCandidate
from app.shared.schemas import AuditResult, LedgerEntry, Severity
from app.shared.scoring import clamp
from app.shared.text_segmentation import TextSpan, normalize_whitespace
from app.shared.verification.base import Judgment
from app.shared.verification.novelty import FunctionalRepetitionJudge
from app.shared.vocabularies import RedundancyVerdict

__all__ = ["NoveltyAuditEngine"]

logger = get_logger(__name__)


@register_engine
class NoveltyAuditEngine(AuditEngine):
    """Measures communication efficiency and redundancy.

    Shared Components used (Document 2, §7.5): Embedding Service, LLM Service,
    Evidence Store, Confidence Estimator, Recommendation Generator, Prompt
    Templates, JSON Models. Cross-engine input: Coverage.
    """

    dimension = "Novelty"

    async def _execute(
        self, context: SharedContext, prior_results: Mapping[str, AuditResult]
    ) -> AuditResult:
        """Run the frozen Novelty pipeline."""
        cfg = self.services.settings.engines.novelty
        collector = EvidenceCollector(self.services.evidence, self.dimension)

        # -- Stage 2: Text Segmentation ------------------------------------ #
        segments = self._segments(context, cfg)
        if len(segments) < 2:
            return self._too_short_result(context, len(segments))

        # -- Stage 3: Sentence Embedding Generation ------------------------ #
        vectors = await self._embeddings.embed([span.text for span in segments])

        # -- Stages 4-5: Duplicate Detection and Candidate Identification --- #
        candidates = self._identify_candidates(segments, vectors, cfg)
        if not candidates:
            return self._no_redundancy_result(context, segments, cfg)

        # -- Stage 6: Functional Repetition Review ------------------------- #
        judgments = await self._repetition_judge.judge(
            candidates, ai_output=context.ai_output
        )

        # -- Stage 7: Coverage Cross-check --------------------------------- #
        judgments = await self._coverage_cross_check(
            judgments, prior_results.get("Coverage"), cfg
        )

        # -- Stage 8: Novelty Score ---------------------------------------- #
        redundant_words, total_words = self._redundancy_mass(judgments, context)
        score = clamp(1.0 - (redundant_words / total_words if total_words else 0.0))

        ledger = self._build_ledger(judgments, collector)

        # -- Stage 9: Confidence ------------------------------------------- #
        signals = self._confidence_signals(
            context, segments, judgments, prior_results.get("Coverage"), cfg
        )
        confidence = self.services.confidence.estimate(signals)

        # -- Stage 10: Recommendations ------------------------------------- #
        recommendations = self._recommendations(judgments, collector)

        logger.info(
            "novelty complete",
            extra=bind(
                audit_id=context.audit_id,
                segments=len(segments),
                candidates=len(candidates),
                redundant=self._count(judgments, RedundancyVerdict.REDUNDANT),
                functional=self._count(judgments, RedundancyVerdict.FUNCTIONAL),
                rescued=sum(
                    1 for j in judgments if j.unit.attributes.get("coverage_rescued")
                ),
                redundant_words=redundant_words,
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
            # Always empty: capability No (Document 2, §4.1).
            critical_findings=[],
            metadata=self.build_metadata(),
        )

    # -- Injected services -------------------------------------------------- #

    @property
    def _embeddings(self) -> EmbeddingService:
        return self.services.service("embedding")  # type: ignore[return-value]

    @property
    def _repetition_judge(self) -> FunctionalRepetitionJudge:
        return self.services.service("functional_repetition")  # type: ignore[return-value]

    # -- Stage 2 ------------------------------------------------------------ #

    @staticmethod
    def _segments(context: SharedContext, cfg) -> tuple[TextSpan, ...]:
        """Return the segments to compare, reusing the shared segmentation.

        Very short segments are dropped. "Yes." and "It depends." are similar to
        each other and to almost everything else — they carry too little signal
        for an embedding comparison to mean anything, and including them would
        fill the candidate list with noise the judge then has to clear.
        """
        return tuple(
            span
            for span in context.sentences
            if len(span.text.split()) >= cfg.min_segment_words
        )

    # -- Stages 4-5 --------------------------------------------------------- #

    def _identify_candidates(
        self,
        segments: Sequence[TextSpan],
        vectors: Sequence[Sequence[float]],
        cfg,
    ) -> tuple[RedundancyCandidate, ...]:
        """Find segment pairs similar enough to question.

        Similarity is :func:`~app.shared.embedding_service.relatedness` — raw
        cosine clamped at zero, on the scale ``semantic_threshold`` is calibrated
        against. Rescaling into [0, 1] would compress every pair into [0.5, 0.9]
        and either flag everything or nothing (see that function's docstring).

        Each segment is paired with its **single most similar predecessor**, not
        with every one above the threshold. Three restatements of one idea are
        one redundancy problem with three instances; emitting all six pairs would
        triple-count it in the ledger, in the score, and in the judge's workload.

        Ordering is fixed: the later segment is always the candidate. The first
        statement of an idea is not the redundant one.
        """
        candidates: list[RedundancyCandidate] = []
        ids = itertools.count(1)
        normalized = [normalize_whitespace(span.text).lower() for span in segments]

        for index in range(1, len(segments)):
            best_score = 0.0
            best_index = -1
            for earlier in range(index):
                score = relatedness(vectors[index], vectors[earlier])
                if score > best_score:
                    best_score, best_index = score, earlier

            if best_index < 0:
                continue

            literal = self._is_literal_duplicate(
                normalized[index], normalized[best_index], cfg
            )
            if best_score < cfg.semantic_threshold and not literal:
                continue

            candidates.append(
                RedundancyCandidate(
                    candidate_id=f"red_{next(ids)}",
                    segment=segments[index],
                    earlier=segments[best_index],
                    similarity=best_score,
                    is_literal=literal,
                )
            )

        # Worst first, then capped: a pathologically repetitive text could
        # otherwise send a hundred pairs to the judge and blow the engine's
        # timeout, degrading the dimension to nothing at all. The most similar
        # pairs are the ones worth the call.
        candidates.sort(key=lambda c: c.similarity, reverse=True)
        return tuple(candidates[: cfg.max_candidates])

    @staticmethod
    def _is_literal_duplicate(left: str, right: str, cfg) -> bool:
        """Whether two normalized segments are literal duplicates.

        Exact match, or token overlap (Jaccard) above the configured floor. The
        overlap case catches the near-verbatim repeat that differs by an article
        or a connective — literal repetition by any reader's standard, and one an
        exact-match test would miss entirely.
        """
        if left == right:
            return True
        left_tokens, right_tokens = set(left.split()), set(right.split())
        if not left_tokens or not right_tokens:
            return False
        union = left_tokens | right_tokens
        return len(left_tokens & right_tokens) / len(union) >= cfg.literal_threshold

    # -- Stage 7 ------------------------------------------------------------ #

    async def _coverage_cross_check(
        self,
        judgments: Sequence[Judgment[RedundancyCandidate, RedundancyVerdict]],
        coverage: AuditResult | None,
        cfg,
    ) -> list[Judgment[RedundancyCandidate, RedundancyVerdict]]:
        """Rescue redundant segments that restate a salient covered key point.

        Reads Coverage's ledger through the ``AuditResult`` contract alone —
        never Coverage's internals — which is what lets the cross-check exist
        without coupling the two engines (Document 3, §13).

        Only two kinds of key point qualify: **salient** ones, above the
        configured floor, and ones Coverage found *Present* or *Partial*. A
        segment restating a peripheral detail is padding whatever Coverage
        thinks of the detail, and a segment restating an *absent* key point is a
        contradiction in terms.

        A rescue **never** flips Functional to Redundant. It runs one way only,
        because the cross-check exists to protect content, not to find more of it
        to delete.
        """
        redundant = [j for j in judgments if j.verdict is RedundancyVerdict.REDUNDANT]
        key_points = self._salient_key_points(coverage, cfg)
        if not redundant or not key_points:
            return list(judgments)

        texts = [j.unit.segment.text for j in redundant]
        point_texts = [text for text, _ in key_points]
        vectors = await self._embeddings.embed([*texts, *point_texts])
        segment_vectors = vectors[: len(texts)]
        point_vectors = vectors[len(texts) :]

        rescued: dict[str, tuple[str, float, float]] = {}
        for judgment, vector in zip(redundant, segment_vectors):
            for (point_text, salience), point_vector in zip(key_points, point_vectors):
                score = relatedness(vector, point_vector)
                if score >= cfg.coverage_match_threshold:
                    rescued[judgment.unit.candidate_id] = (point_text, salience, score)
                    break

        if not rescued:
            return list(judgments)

        updated: list[Judgment[RedundancyCandidate, RedundancyVerdict]] = []
        for judgment in judgments:
            match = rescued.get(judgment.unit.candidate_id)
            if match is None:
                updated.append(judgment)
                continue

            point_text, salience, score = match
            candidate = replace(
                judgment.unit,
                covers_key_point=point_text,
                key_point_salience=salience,
                attributes={
                    **judgment.unit.attributes,
                    "coverage_rescued": True,
                    "coverage_match_score": round(score, 3),
                    "review_verdict": RedundancyVerdict.REDUNDANT.value,
                },
            )
            updated.append(
                Judgment(
                    unit=candidate,
                    verdict=RedundancyVerdict.FUNCTIONAL,
                    rationale=(
                        f"{judgment.rationale} Coverage cross-check: this passage "
                        f"restates a key point of the reference source that "
                        f"Coverage found present and rated {salience:.2f} salient "
                        f"({point_text!r}). Repetition that carries important "
                        "content is functional, so the review's verdict is "
                        "overridden here."
                    ).strip(),
                    evidence_refs=judgment.evidence_refs,
                    confidence_hint=judgment.confidence_hint,
                )
            )

        logger.info(
            "coverage cross-check rescued redundant segments",
            extra=bind(rescued=len(rescued), redundant_before=len(redundant)),
        )
        return updated

    @staticmethod
    def _salient_key_points(
        coverage: AuditResult | None, cfg
    ) -> list[tuple[str, float]]:
        """Read the salient, covered key points out of Coverage's ledger.

        Returns an empty list when Coverage is absent, degraded, or found
        nothing — every one of which is a legitimate state, most commonly
        because no reference source was supplied. The cross-check then simply
        does not run, and the confidence signal says so rather than the engine
        pretending it did.
        """
        if coverage is None or coverage.confidence == 0.0:
            return []

        points: list[tuple[str, float]] = []
        for entry in coverage.ledger:
            if entry.unit_type != "Key Point":
                continue
            if entry.verdict not in ("Present", "Partial"):
                continue
            salience = entry.attributes.get("salience")
            if not isinstance(salience, (int, float)):
                continue
            if float(salience) < cfg.coverage_salience_floor:
                continue
            points.append((entry.unit, float(salience)))
        return points

    # -- Stage 8 ------------------------------------------------------------ #

    @staticmethod
    def _redundancy_mass(
        judgments: Sequence[Judgment[RedundancyCandidate, RedundancyVerdict]],
        context: SharedContext,
    ) -> tuple[int, int]:
        """Measure how much of the document is confirmed-redundant text.

        Mass, not count. A redundant 40-word paragraph wastes more of a reader's
        time than a redundant 6-word aside, and a plain count of candidates would
        call them equal. Words are the unit a reader actually pays in.

        Only **confirmed** redundancy counts. Functional repetition is free, and
        an unjudged candidate costs nothing either — a candidate the review never
        answered for has not been shown to be redundant, and charging the score
        for it would penalize the output for the model's silence. That cost lands
        on confidence instead (Document 3, §8).

        Returns:
            ``(redundant_words, total_words)``.
        """
        seen: set[int] = set()
        redundant_words = 0
        for judgment in judgments:
            if judgment.verdict is not RedundancyVerdict.REDUNDANT:
                continue
            span = judgment.unit.segment
            if span.index in seen:
                continue
            seen.add(span.index)
            redundant_words += len(span.text.split())
        return redundant_words, context.statistics.word_count

    def _build_ledger(
        self,
        judgments: Sequence[Judgment[RedundancyCandidate, RedundancyVerdict]],
        collector: EvidenceCollector,
    ) -> list[LedgerEntry]:
        """Build the Redundancy Ledger (Document 2, §6.3).

        Both segments of every pair are recorded as evidence. A reader shown only
        the passage marked redundant has no way to check the verdict —
        redundancy is a claim about a *relationship*, and half of it proves
        nothing.
        """
        entries: list[LedgerEntry] = []
        for judgment in judgments:
            candidate = judgment.unit
            refs = [
                collector.output_span(candidate.segment).evidence_id,
                collector.output_span(candidate.earlier).evidence_id,
            ]
            if judgment.rationale:
                refs.append(collector.judge_rationale(judgment.rationale).evidence_id)

            entries.append(
                LedgerEntry(
                    entry_id=candidate.candidate_id,
                    unit=candidate.segment.text,
                    unit_type="Text segment",
                    verdict=(
                        judgment.verdict.value if judgment.verdict else "Not reviewed"
                    ),
                    severity=(
                        Severity.LOW
                        if judgment.verdict is RedundancyVerdict.REDUNDANT
                        else None
                    ),
                    evidence_refs=refs,
                    rationale=(
                        judgment.rationale
                        or "The repetition review returned no verdict for this "
                        "candidate, so it is not counted as redundant and lowers "
                        "confidence instead."
                    ),
                    attributes={
                        "similarity": round(candidate.similarity, 3),
                        "literal_duplicate": candidate.is_literal,
                        "echoes_segment": candidate.earlier.text,
                        "echoes_span": candidate.earlier.locator(),
                        "judged": judgment.is_judged,
                        **(
                            {
                                "coverage_rescued": True,
                                "review_verdict": candidate.attributes.get(
                                    "review_verdict"
                                ),
                                "covers_key_point": candidate.covers_key_point,
                                "key_point_salience": candidate.key_point_salience,
                            }
                            if candidate.attributes.get("coverage_rescued")
                            else {}
                        ),
                    },
                )
            )
        return entries

    # -- Stage 9 ------------------------------------------------------------ #

    def _confidence_signals(
        self,
        context: SharedContext,
        segments: Sequence[TextSpan],
        judgments: Sequence[Judgment[RedundancyCandidate, RedundancyVerdict]],
        coverage: AuditResult | None,
        cfg,
    ) -> list[ConfidenceSignal]:
        """Report why Novelty is or is not confident in its own judgment."""
        total = len(judgments)
        judged = sum(1 for j in judgments if j.is_judged)
        cross_checked = coverage is not None and coverage.confidence > 0.0

        signals = [
            signal(
                "candidates_reviewed",
                judged / total if total else 1.0,
                # Heaviest: an unreviewed candidate is excluded from the score,
                # so a score computed over two of ten candidates looks identical
                # to one computed over all ten. Only this signal reveals the
                # difference — the same reasoning as Accuracy's verdicts_decisive.
                weight=4.0,
                rationale=(
                    f"The repetition review returned a verdict for {judged} of "
                    f"{total} candidates"
                ),
            ),
            signal(
                "segments_compared",
                1.0 if len(segments) >= 2 else 0.0,
                weight=2.0,
                rationale=(
                    f"{len(segments)} segments were embedded and compared pairwise"
                ),
            ),
            signal(
                "coverage_cross_check",
                1.0 if cross_checked else 0.0,
                weight=2.0,
                rationale=(
                    "Coverage results were available to protect repetition that "
                    "carries important content"
                    if cross_checked
                    else "No usable Coverage result was available, so repetition "
                    "that restates important content could not be distinguished "
                    "from padding by cross-check"
                ),
            ),
            signal(
                "content_sufficient",
                min(1.0, context.statistics.word_count / cfg.words_for_full_confidence),
                weight=1.0,
                rationale=(
                    f"The output runs {context.statistics.word_count} words; "
                    "redundancy is harder to establish in a short text"
                ),
            ),
        ]

        hints = [j.confidence_hint for j in judgments if j.confidence_hint is not None]
        signals.append(
            signal(
                "reviewer_certainty",
                sum(hints) / len(hints) if hints else 0.5,
                weight=2.0,
                rationale=(
                    f"The repetition reviewer reported a mean certainty of "
                    f"{(sum(hints) / len(hints)) if hints else 0.5:.0%}"
                ),
            )
        )
        return signals

    # -- Stage 10 ----------------------------------------------------------- #

    def _recommendations(
        self,
        judgments: Sequence[Judgment[RedundancyCandidate, RedundancyVerdict]],
        collector: EvidenceCollector,
    ):
        """Recommend cutting each confirmed-redundant passage, longest first.

        Only confirmed redundancy earns a recommendation. Telling a writer to
        delete their conclusion because it restates their introduction is advice
        that makes the document worse, and it is exactly what stages 6 and 7
        exist to prevent.
        """
        redundant = [j for j in judgments if j.verdict is RedundancyVerdict.REDUNDANT]
        redundant.sort(key=lambda j: len(j.unit.segment.text.split()), reverse=True)

        recommendations = []
        for judgment in redundant:
            candidate = judgment.unit
            refs = [
                collector.output_span(candidate.segment).evidence_id,
                collector.output_span(candidate.earlier).evidence_id,
            ]
            created = self.services.recommendations.create(
                dimension=self.dimension,
                text=(
                    f"Cut or merge the repeated passage: "
                    f"{candidate.segment.snippet(120)!r}. It restates "
                    f"{candidate.earlier.snippet(120)!r} without adding to it."
                ),
                # Low by design. Redundancy costs a reader time, not
                # understanding, and Document 3 §10 reserves the higher tiers for
                # trust-relevant issues and material quality damage. Inflating it
                # would push cosmetic edits above real problems in the merged
                # action list.
                severity=Severity.LOW,
                evidence_refs=refs,
            )
            if created is not None:
                recommendations.append(created)
        return recommendations

    # -- Early exits -------------------------------------------------------- #

    def _too_short_result(self, context: SharedContext, segments: int) -> AuditResult:
        """Result for an output with too few segments to compare.

        One sentence cannot repeat itself. This is a *confident* 1.0: unlike the
        cases where a measurement failed, the measurement here succeeded and
        found that redundancy is impossible. Reporting low confidence would be
        false modesty about something the engine actually knows — and confidence
        is not a politeness, it is the Decision Engine's gate on assertability
        (Document 3, §8).
        """
        logger.info(
            "novelty: too few segments to compare",
            extra=bind(audit_id=context.audit_id, segments=segments),
        )
        return AuditResult(
            score=1.0,
            confidence=0.6,
            ledger=[],
            evidence=[],
            recommendations=[],
            critical_findings=[],
            metadata=self.build_metadata(),
        )

    def _no_redundancy_result(
        self, context: SharedContext, segments: Sequence[TextSpan], cfg
    ) -> AuditResult:
        """Result for an output whose segments are all distinct.

        A real, well-founded measurement: every segment was embedded and compared
        against every predecessor, and none crossed the threshold. Nothing was
        left unchecked, so the confidence here is nothing like the hedged
        confidence of :meth:`_too_short_result` — the engine looked at the whole
        document and the answer was no.
        """
        signals = self._confidence_signals(context, segments, (), None, cfg)
        logger.info(
            "novelty: no redundancy candidates",
            extra=bind(audit_id=context.audit_id, segments=len(segments)),
        )
        return AuditResult(
            score=1.0,
            confidence=self.services.confidence.estimate(signals),
            ledger=[],
            evidence=[],
            recommendations=[],
            critical_findings=[],
            metadata=self.build_metadata(),
        )

    @staticmethod
    def _count(
        judgments: Sequence[Judgment[RedundancyCandidate, RedundancyVerdict]],
        verdict: RedundancyVerdict,
    ) -> int:
        """Count judgments with a given verdict."""
        return sum(1 for j in judgments if j.verdict is verdict)
