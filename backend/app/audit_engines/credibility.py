"""Credibility Audit Engine (``ENG-CREDIBILITY``) — Document 2, §7.4.

**Governing question.** Are factual claims supported by trustworthy, correctly
cited, verifiable sources?

**Inputs.** AI Output.

**Classification.** Trust Dimension · Critical Finding Capability: Yes ·
Does Not Support N/A.

**Frozen pipeline (Document 2, §7.4), stage by stage.**

1. Input (AI Output)
2. LLM Citation Extraction — :class:`CitationExtractionService` (§5.1)
3. Claim-to-Citation Mapping — :class:`ClaimCitationMapper`
4. URL / DOI Verification — :class:`DeterministicValidators` (§5.6)
5. Source Retrieval — :class:`RetrievalService` (§5.3)
6. Grounding Verification — :class:`GroundingVerificationJudge` (§5.4)
7. Source Classification — :class:`SourceClassifier` (§5.2)
8. Evidence Collection
9. Critical Finding Detection
10. Credibility Score
11. Confidence
12. Recommendations

**This engine carries the system's headline scenario.** Document 1 §9 and
Document 4 §13 both use a fabricated citation as *the* demonstration that trust
is non-compensatory: Credibility finds a citation that does not exist, emits a
Critical Finding, and the Decision Engine gates the verdict to *Untrusted*
regardless of how well the content reads.

**Three failures that look alike and are not.** The pipeline separates them
deliberately, and conflating any two would make the report wrong:

* **Fabricated** — stage 4 says the URL or DOI does not resolve. The source does
  not exist.
* **Misattributed** — stage 4 passes, stage 6 says *Unrelated* or *Contradicts*.
  The source exists and says nothing of the kind, or the opposite. More
  insidious than fabrication: it survives every link check and looks
  authoritative to anyone who does not follow the reference.
* **Unlinked** — the citation has no URL or DOI at all. "Smith et al. (2023)"
  may be a perfectly real paper. **This is not a finding.** Treating an unlinked
  citation as fabricated would accuse ordinary academic prose of inventing its
  sources, which is exactly the false accusation the auditor must never make.
"""

from __future__ import annotations

import asyncio
from typing import Mapping, Sequence

from app.audit_engines.base import AuditEngine
from app.audit_engines.registry import register_engine
from app.core.logging import bind, get_logger
from app.shared.classification.sources import SourceClassifier
from app.shared.confidence_service import ConfidenceSignal, signal
from app.shared.context import SharedContext, SharedKeys
from app.shared.deterministic_validators import (
    DeterministicValidators,
    ValidationOutcome,
)
from app.shared.evidence_pipeline import EvidenceCollector
from app.shared.extraction.citations import CitationExtractionService
from app.shared.extraction.claims import ClaimExtractionService
from app.shared.extraction.models import Citation, Claim
from app.shared.mapping import CitationMapping, ClaimCitationMapper
from app.shared.retrieval_service import FetchedDocument, RetrievalService
from app.shared.schemas import (
    AuditResult,
    CriticalFinding,
    EvidenceItem,
    LedgerEntry,
    Severity,
)
from app.shared.scoring import weighted_mean
from app.shared.verification.base import Judgment
from app.shared.verification.grounding import GroundingVerificationJudge
from app.shared.vocabularies import ClaimType, GroundingVerdict

__all__ = ["CredibilityAuditEngine"]

logger = get_logger(__name__)

@register_engine
class CredibilityAuditEngine(AuditEngine):
    """Verifies citations and the trustworthiness of sources.

    Shared Components used (Document 2, §7.4): LLM Service, Retrieval Service,
    Deterministic Validators, Evidence Store, Confidence Estimator,
    Recommendation Generator, Prompt Templates, JSON Models.
    """

    dimension = "Credibility"

    async def _execute(
        self, context: SharedContext, prior_results: Mapping[str, AuditResult]
    ) -> AuditResult:
        """Run the frozen Credibility pipeline."""
        cfg = self.services.settings.engines.credibility
        collector = EvidenceCollector(self.services.evidence, self.dimension)

        # -- Stage 2: Citation Extraction ---------------------------------- #
        extraction = await self._citation_extraction.extract(context.ai_output)
        if extraction.is_empty:
            return await self._no_citations_result(context, collector)

        citations = list(extraction.units)

        # -- Stage 3: Claim-to-Citation Mapping ---------------------------- #
        claims = await self._factual_claims(context)
        mapping = await self._mapper.map(claims, citations)
        citations = self._attach_mapped_claims(citations, claims, mapping)

        # -- Stage 4: URL / DOI Verification ------------------------------- #
        verifications = await self._verify_links(citations, collector)

        # -- Stage 5: Source Retrieval ------------------------------------- #
        fetched = await self._fetch_sources(citations, verifications, cfg)

        # -- Stage 6: Grounding Verification ------------------------------- #
        groundable = [
            c
            for c in citations
            if fetched.get(c.citation_id) and fetched[c.citation_id].has_content
            and c.attributes.get("mapped_claim_texts")
        ]
        source_evidence = self._source_evidence(groundable, fetched, collector, cfg)
        judgments = (
            await self._grounding_judge.judge(groundable, source_evidence)
            if groundable
            else ()
        )
        grounding = {j.unit.citation_id: j for j in judgments}

        # -- Stage 7: Source Classification -------------------------------- #
        citations = list(
            await self._source_classifier.classify(self._with_titles(citations, fetched))
        )

        # -- Stage 8: Evidence Collection ---------------------------------- #
        ledger = self._build_ledger(
            citations, verifications, fetched, grounding, collector
        )

        # -- Stage 9: Critical Finding Detection --------------------------- #
        findings = self._detect_critical_findings(
            citations, verifications, grounding, collector, cfg
        )

        # -- Stage 10: Credibility Score ----------------------------------- #
        score = self._score(citations, verifications, fetched, grounding)

        # -- Stage 11: Confidence ------------------------------------------ #
        signals = self._confidence_signals(
            extraction, citations, verifications, fetched, grounding, mapping
        )
        confidence = self.services.confidence.estimate(signals)

        # -- Stage 12: Recommendations ------------------------------------- #
        recommendations = self._recommendations(
            citations, verifications, grounding, mapping, collector
        )

        logger.info(
            "credibility complete",
            extra=bind(
                audit_id=context.audit_id,
                citations=len(citations),
                linked=sum(1 for c in citations if c.is_locatable_source),
                resolved=sum(1 for v in verifications.values() if v.passed),
                grounded=len(grounding),
                uncited_claims=len(mapping.uncited_claim_ids),
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
    def _citation_extraction(self) -> CitationExtractionService:
        return self.services.service("citation_extraction")  # type: ignore[return-value]

    @property
    def _claim_extraction(self) -> ClaimExtractionService:
        return self.services.service("claim_extraction")  # type: ignore[return-value]

    @property
    def _mapper(self) -> ClaimCitationMapper:
        return self.services.service("claim_citation_mapper")  # type: ignore[return-value]

    @property
    def _validators(self) -> DeterministicValidators:
        return self.services.service("validators")  # type: ignore[return-value]

    @property
    def _retrieval(self) -> RetrievalService:
        return self.services.service("retrieval")  # type: ignore[return-value]

    @property
    def _grounding_judge(self) -> GroundingVerificationJudge:
        return self.services.service("grounding_verification")  # type: ignore[return-value]

    @property
    def _source_classifier(self) -> SourceClassifier:
        return self.services.service("source_classifier")  # type: ignore[return-value]

    # -- Stage 3 ------------------------------------------------------------ #

    async def _factual_claims(self, context: SharedContext) -> list[Claim]:
        """Extract the output's claims, sharing the derivation with Accuracy.

        Only factual claims are mapped. An opinion needs no source, and counting
        it among the uncited would report a transparency problem that does not
        exist.

        Note:
            The claims here are *unclassified* — Accuracy's stage 3 does the
            classification, and this engine must not read Accuracy's results
            (Document 2 §8 gives Credibility no cross-engine inputs). So the
            filter below is a light heuristic on the shared extraction, and the
            mapper's prompt does the real work of deciding what needed a source.
        """
        if not context.ai_output.strip():
            return []
        result = await context.get_or_compute(
            SharedKeys.EXTRACTED_CLAIMS,
            lambda: self._claim_extraction.extract(context.ai_output),
        )
        return [
            c
            for c in result.units
            if c.claim_type is None or c.claim_type is ClaimType.FACTUAL
        ]

    @staticmethod
    def _attach_mapped_claims(
        citations: Sequence[Citation],
        claims: Sequence[Claim],
        mapping: CitationMapping,
    ) -> list[Citation]:
        """Record each citation's mapped claim texts for the grounding judge."""
        from dataclasses import replace

        by_id = {c.claim_id: c.text for c in claims}
        updated: list[Citation] = []
        for citation in citations:
            ids = mapping.claims_by_citation.get(citation.citation_id, ())
            attributes = dict(citation.attributes)
            attributes["mapped_claim_ids"] = list(ids)
            attributes["mapped_claim_texts"] = [by_id[i] for i in ids if i in by_id]
            updated.append(replace(citation, attributes=attributes))
        return updated

    # -- Stage 4 ------------------------------------------------------------ #

    async def _verify_links(
        self, citations: Sequence[Citation], collector: EvidenceCollector
    ) -> dict[str, ValidationOutcome]:
        """Resolve every URL and DOI, concurrently.

        Deterministic and zero-variance (Document 4, §11): a 404 reads the same
        on every re-run. Concurrent because a dozen sequential HTTP probes would
        dominate the engine's timeout budget.

        Unlinked citations are skipped entirely — there is nothing to resolve,
        and recording a failure for them would manufacture the fabrication
        finding this engine most needs to avoid.
        """
        linked = [c for c in citations if c.is_locatable_source]
        if not linked:
            return {}

        async def probe(citation: Citation) -> tuple[str, ValidationOutcome]:
            if citation.doi:
                outcome = await self._validators.verify_doi(citation.doi)
            else:
                outcome = await self._validators.verify_url(citation.url or "")
            return citation.citation_id, outcome

        results = await asyncio.gather(*(probe(c) for c in linked))
        verifications = dict(results)

        for citation_id, outcome in verifications.items():
            collector.validator_result(
                check=outcome.check,
                detail=outcome.detail,
                source_ref=outcome.observed.get("url") or outcome.observed.get("doi"),
            )
        return verifications

    # -- Stage 5 ------------------------------------------------------------ #

    async def _fetch_sources(
        self,
        citations: Sequence[Citation],
        verifications: Mapping[str, ValidationOutcome],
        cfg,
    ) -> dict[str, FetchedDocument]:
        """Fetch the sources that resolved, up to the configured ceiling.

        Only citations whose links resolved are fetched — there is nothing to
        retrieve from a dead URL, and the fabrication finding is already
        established by stage 4.
        """
        fetchable = [
            c
            for c in citations
            if c.is_locatable_source
            and verifications.get(c.citation_id)
            and verifications[c.citation_id].passed
        ][: cfg.max_sources_fetched]

        if not fetchable:
            return {}

        async def get(citation: Citation) -> tuple[str, FetchedDocument]:
            target = (
                f"https://doi.org/{citation.doi}" if citation.doi else citation.url or ""
            )
            return citation.citation_id, await self._retrieval.fetch(target)

        return dict(await asyncio.gather(*(get(c) for c in fetchable)))

    def _source_evidence(
        self,
        citations: Sequence[Citation],
        fetched: Mapping[str, FetchedDocument],
        collector: EvidenceCollector,
        cfg,
    ) -> list[EvidenceItem]:
        """Record fetched source content as evidence for the grounding judge."""
        items: list[EvidenceItem] = []
        for citation in citations:
            document = fetched.get(citation.citation_id)
            if document is None or not document.has_content:
                continue
            items.append(
                collector.retrieved_source(
                    content=document.text[: cfg.source_excerpt_chars],
                    source_ref=document.url,
                    locator=f"citation[{citation.citation_id}]",
                )
            )
        return items

    @staticmethod
    def _with_titles(
        citations: Sequence[Citation], fetched: Mapping[str, FetchedDocument]
    ) -> list[Citation]:
        """Attach fetched source titles, which sharpen source classification."""
        from dataclasses import replace

        updated: list[Citation] = []
        for citation in citations:
            document = fetched.get(citation.citation_id)
            if document is None or not document.title:
                updated.append(citation)
                continue
            attributes = dict(citation.attributes)
            attributes["source_title"] = document.title
            updated.append(replace(citation, attributes=attributes))
        return updated

    # -- Stage 8 ------------------------------------------------------------ #

    def _build_ledger(
        self,
        citations: Sequence[Citation],
        verifications: Mapping[str, ValidationOutcome],
        fetched: Mapping[str, FetchedDocument],
        grounding: Mapping[str, Judgment[Citation, GroundingVerdict]],
        collector: EvidenceCollector,
    ) -> list[LedgerEntry]:
        """Build the Citation Ledger (Document 2, §6.3)."""
        entries: list[LedgerEntry] = []

        for citation in citations:
            verdict, severity, rationale = self._citation_state(
                citation, verifications, fetched, grounding
            )
            refs: list[str] = []
            if citation.source_span:
                refs.append(collector.output_span(citation.source_span).evidence_id)

            judgment = grounding.get(citation.citation_id)
            if judgment and judgment.rationale:
                refs.append(
                    collector.judge_rationale(judgment.rationale).evidence_id
                )

            entries.append(
                LedgerEntry(
                    entry_id=citation.citation_id,
                    unit=citation.text,
                    unit_type="Citation",
                    verdict=verdict,
                    severity=severity,
                    evidence_refs=refs,
                    rationale=rationale,
                    attributes={
                        "url": citation.url,
                        "doi": citation.doi,
                        "source_class": (
                            citation.source_class.value
                            if citation.source_class
                            else None
                        ),
                        "resolves": (
                            verifications[citation.citation_id].passed
                            if citation.citation_id in verifications
                            else None
                        ),
                        "mapped_claim_ids": citation.attributes.get(
                            "mapped_claim_ids", []
                        ),
                    },
                )
            )
        return entries

    def _citation_state(
        self,
        citation: Citation,
        verifications: Mapping[str, ValidationOutcome],
        fetched: Mapping[str, FetchedDocument],
        grounding: Mapping[str, Judgment[Citation, GroundingVerdict]],
    ) -> tuple[str, Severity | None, str]:
        """Summarize one citation's outcome across stages 4–6.

        Returns the ledger verdict, its severity, and a rationale. The order of
        the checks mirrors the pipeline: an unresolvable link makes grounding
        moot, so fabrication is reported before anything else.
        """
        if not citation.is_locatable_source:
            return (
                "Unlinked",
                None,
                "No URL or DOI accompanies this citation, so it could not be "
                "resolved or checked. This is not evidence of fabrication — an "
                "unlinked reference may be entirely genuine.",
            )

        verification = verifications.get(citation.citation_id)
        if verification is not None and not verification.passed:
            return (
                "Unresolvable",
                verification.severity or Severity.HIGH,
                f"The cited source could not be resolved. {verification.detail}",
            )

        document = fetched.get(citation.citation_id)
        if document is None:
            return (
                "Resolved",
                None,
                "The link resolves. The source was not retrieved, so its "
                "grounding was not checked.",
            )
        if not document.has_content:
            return (
                "Resolved",
                Severity.LOW,
                "The link resolves but no readable content could be extracted "
                "(a paywall or a script-rendered page), so grounding could not "
                "be checked.",
            )

        judgment = grounding.get(citation.citation_id)
        if judgment is None or judgment.verdict is None:
            return (
                "Resolved",
                None,
                "The source was retrieved but the grounding stage returned no "
                "verdict for it.",
            )
        severity = {
            GroundingVerdict.SUPPORTS: None,
            GroundingVerdict.PARTIAL: Severity.LOW,
            GroundingVerdict.UNRELATED: Severity.HIGH,
            GroundingVerdict.CONTRADICTS: Severity.HIGH,
        }[judgment.verdict]
        return judgment.verdict.value, severity, judgment.rationale

    # -- Stage 9 ------------------------------------------------------------ #

    def _detect_critical_findings(
        self,
        citations: Sequence[Citation],
        verifications: Mapping[str, ValidationOutcome],
        grounding: Mapping[str, Judgment[Citation, GroundingVerdict]],
        collector: EvidenceCollector,
        cfg,
    ) -> list[CriticalFinding]:
        """Raise findings for fabricated and misattributed citations.

        **Unlinked citations never raise a finding.** They are the single most
        important false positive to avoid: academic prose is full of "Smith et
        al. (2023)" references that are perfectly real and simply not
        hyperlinked. Reporting those as fabricated would gate trust to
        *Untrusted* on ordinary, honest writing.
        """
        findings: list[CriticalFinding] = []

        for citation in citations:
            if not citation.is_locatable_source:
                continue

            refs: list[str] = []
            if citation.source_span:
                refs.append(collector.output_span(citation.source_span).evidence_id)

            verification = verifications.get(citation.citation_id)
            if verification is not None and not verification.passed:
                probe = collector.validator_result(
                    check=verification.check,
                    detail=verification.detail,
                    source_ref=citation.url or citation.doi,
                )
                findings.append(
                    CriticalFinding(
                        finding_id=f"cf_{citation.citation_id}",
                        dimension=self.dimension,
                        type="Fabricated citation",
                        severity=cfg.fabrication_severity,
                        description=(
                            f"The citation {citation.text!r} points at a source "
                            f"that does not resolve. {verification.detail}"
                        ),
                        evidence_refs=[*refs, probe.evidence_id],
                        centrality=None,
                    )
                )
                continue

            judgment = grounding.get(citation.citation_id)
            if judgment is None or judgment.verdict is None:
                continue
            if judgment.verdict not in (
                GroundingVerdict.UNRELATED,
                GroundingVerdict.CONTRADICTS,
            ):
                continue

            rationale_item = collector.judge_rationale(
                judgment.rationale or "The source does not support the mapped claim."
            )
            kind = (
                "Misattributed citation"
                if judgment.verdict is GroundingVerdict.UNRELATED
                else "Contradicting citation"
            )
            findings.append(
                CriticalFinding(
                    finding_id=f"cf_{citation.citation_id}",
                    dimension=self.dimension,
                    type=kind,
                    severity=cfg.misattribution_severity,
                    description=(
                        f"The citation {citation.text!r} resolves, but the source "
                        f"{'is unrelated to' if judgment.verdict is GroundingVerdict.UNRELATED else 'contradicts'} "
                        f"the claim it is offered for. {judgment.rationale}".strip()
                    ),
                    evidence_refs=[*refs, rationale_item.evidence_id],
                    centrality=None,
                )
            )
        return findings

    # -- Stage 10 ----------------------------------------------------------- #

    def _score(
        self,
        citations: Sequence[Citation],
        verifications: Mapping[str, ValidationOutcome],
        fetched: Mapping[str, FetchedDocument],
        grounding: Mapping[str, Judgment[Citation, GroundingVerdict]],
    ) -> float:
        """Compute the Credibility score.

        Per-citation credit, averaged:

        * unresolvable → 0.0 (weight 1.0) — the source does not exist
        * Unrelated / Contradicts → 0.0 (weight 1.0) — misattributed
        * Partial → 0.5, Supports → 1.0
        * resolves but not grounded → 0.7 (weight 0.5) — the link is real and
          nothing disproves it; a lighter weight because less was established
        * unlinked → 0.6 (weight 0.3) — a real reference may simply lack a link;
          light weight so unlinked prose is not treated as a credibility failure

        The unlinked credit is the judgment call. Zero would brand ordinary
        academic writing untrustworthy; 1.0 would reward citations nobody can
        check. A middling value with low weight says what is true: this is
        weaker sourcing than a resolvable link, and it is not misconduct.
        """
        outcomes: list[tuple[float, float]] = []

        for citation in citations:
            if not citation.is_locatable_source:
                outcomes.append((0.6, 0.3))
                continue

            verification = verifications.get(citation.citation_id)
            if verification is not None and not verification.passed:
                outcomes.append((0.0, 1.0))
                continue

            judgment = grounding.get(citation.citation_id)
            if judgment is None or judgment.verdict is None:
                outcomes.append((0.7, 0.5))
                continue

            credit = {
                GroundingVerdict.SUPPORTS: 1.0,
                GroundingVerdict.PARTIAL: 0.5,
                GroundingVerdict.UNRELATED: 0.0,
                GroundingVerdict.CONTRADICTS: 0.0,
            }[judgment.verdict]
            outcomes.append((credit, 1.0))

        return weighted_mean(outcomes, default=1.0)

    # -- Stage 11 ----------------------------------------------------------- #

    def _confidence_signals(
        self,
        extraction,
        citations: Sequence[Citation],
        verifications: Mapping[str, ValidationOutcome],
        fetched: Mapping[str, FetchedDocument],
        grounding: Mapping[str, Judgment[Citation, GroundingVerdict]],
        mapping: CitationMapping,
    ) -> list[ConfidenceSignal]:
        """Report why Credibility is or is not confident in its own judgment."""
        total = len(citations)
        linked = sum(1 for c in citations if c.is_locatable_source)
        retrieved = sum(1 for d in fetched.values() if d.has_content)
        grounded = sum(1 for j in grounding.values() if j.is_judged)

        signals = [
            signal(
                "citations_linked",
                linked / total if total else 0.0,
                weight=3.0,
                rationale=(
                    f"{linked} of {total} citations carry a URL or DOI that "
                    "could be checked"
                ),
            ),
            signal(
                "sources_retrieved",
                retrieved / linked if linked else 0.0,
                weight=3.0,
                rationale=(
                    f"Readable content was retrieved for {retrieved} of {linked} "
                    "linked citations"
                ),
            ),
            signal(
                "grounding_judged",
                grounded / linked if linked else 0.0,
                weight=2.0,
                rationale=(
                    f"{grounded} of {linked} linked citations were checked "
                    "against their sources"
                ),
            ),
            signal(
                "citations_located",
                extraction.location_rate,
                weight=1.0,
                rationale=(
                    f"{extraction.located_count} of {len(extraction.units)} "
                    "citations were traced to a span of the output"
                ),
            ),
        ]

        hints = [j.confidence_hint for j in grounding.values() if j.confidence_hint]
        if hints:
            signals.append(
                signal(
                    "grounding_certainty",
                    sum(hints) / len(hints),
                    weight=2.0,
                    rationale=(
                        f"The grounding judge reported a mean certainty of "
                        f"{sum(hints) / len(hints):.0%}"
                    ),
                )
            )
        return signals

    # -- Stage 12 ----------------------------------------------------------- #

    def _recommendations(
        self,
        citations: Sequence[Citation],
        verifications: Mapping[str, ValidationOutcome],
        grounding: Mapping[str, Judgment[Citation, GroundingVerdict]],
        mapping: CitationMapping,
        collector: EvidenceCollector,
    ):
        """Produce recommendations for unresolvable, misattributed, and unlinked
        citations, and for factual claims that carry no source at all."""
        recommendations = []

        for citation in citations:
            refs = (
                [collector.output_span(citation.source_span).evidence_id]
                if citation.source_span
                else []
            )
            if not refs:
                continue

            verification = verifications.get(citation.citation_id)
            judgment = grounding.get(citation.citation_id)

            if verification is not None and not verification.passed:
                created = self.services.recommendations.create(
                    dimension=self.dimension,
                    text=(
                        f"Remove or replace the citation {citation.text!r}: its "
                        "source does not resolve."
                    ),
                    severity=Severity.HIGH,
                    evidence_refs=refs,
                )
            elif judgment and judgment.verdict in (
                GroundingVerdict.UNRELATED,
                GroundingVerdict.CONTRADICTS,
            ):
                created = self.services.recommendations.create(
                    dimension=self.dimension,
                    text=(
                        f"Re-cite {citation.text!r} against a source that "
                        "actually supports the claim it is attached to."
                    ),
                    severity=Severity.HIGH,
                    evidence_refs=refs,
                )
            elif not citation.is_locatable_source:
                created = self.services.recommendations.create(
                    dimension=self.dimension,
                    text=(
                        f"Add a resolvable link or DOI to {citation.text!r} so "
                        "the reader can verify it."
                    ),
                    severity=Severity.LOW,
                    evidence_refs=refs,
                )
            else:
                continue

            if created is not None:
                recommendations.append(created)

        return recommendations

    # -- Early exit --------------------------------------------------------- #

    async def _no_citations_result(
        self, context: SharedContext, collector: EvidenceCollector
    ) -> AuditResult:
        """Result for an output containing no citations.

        **Not automatically a failure.** Content that makes no factual claims
        needs no sources, and scoring it zero would penalize a poem for lacking
        a bibliography. But content that asserts checkable facts while citing
        nothing is a real transparency observation — so the two are separated
        here, using the shared claim extraction to tell which case this is.
        """
        claims = await self._factual_claims(context)
        if not claims:
            return AuditResult(
                score=1.0,
                confidence=0.5,
                ledger=[],
                evidence=[],
                recommendations=[],
                critical_findings=[],
                metadata=self.build_metadata(),
            )

        item = collector.validator_result(
            check="citations_present",
            detail=(
                f"The output makes {len(claims)} checkable factual claim(s) and "
                "cites no sources for any of them."
            ),
        )
        recommendation = self.services.recommendations.create(
            dimension=self.dimension,
            text=(
                "Cite sources for the factual claims in this output. It asserts "
                f"{len(claims)} checkable fact(s) without attributing any of them."
            ),
            severity=Severity.MEDIUM,
            evidence_refs=[item.evidence_id],
        )

        # Uncited factual content is unverifiable-by-construction rather than
        # wrong. A low score with real confidence says "this is poorly sourced",
        # which is exactly what was observed — no finding, because nothing here
        # shows a source was fabricated.
        return AuditResult(
            score=0.3,
            confidence=0.7,
            ledger=[],
            evidence=self.services.evidence.for_dimension(self.dimension),
            recommendations=[recommendation] if recommendation else [],
            critical_findings=[],
            metadata=self.build_metadata(),
        )
