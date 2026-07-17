"""Decision Engine suite (Document 3; Document 4, §10).

Document 4 §10: *"The Decision Engine suite must be exhaustive on gate logic —
it is the correctness core and is cheap to test because it is deterministic
given inputs."* This suite takes that literally.

Pure and offline: synthetic ``AuditResult``s in, ``DecisionResult`` out. No LLM,
no embeddings, no engines, no network. The whole file runs in milliseconds.
"""

from __future__ import annotations

import pytest

from app.core.constants import DIMENSION_SPECS
from app.decision_engine.report_builder import build_report
from app.decision_engine.workflow import DecisionEngine
from app.shared.schemas import (
    AuditResult,
    AuditResultMetadata,
    CriticalFinding,
    EvidenceItem,
    OverallVerdict,
    QualityBand,
    Recommendation,
    RecommendationPriority,
    Severity,
    TrustOutcome,
)

pytestmark = pytest.mark.decision


# --------------------------------------------------------------------------- #
# Fixtures — synthetic results shaped like the real engines produce
# --------------------------------------------------------------------------- #


def evidence(dimension: str, evidence_id: str) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        dimension=dimension,
        kind="output_span",
        content="the span the finding points at",
        locator="sentence[0]@0:10",
    )


def finding(
    dimension: str,
    finding_id: str,
    severity: Severity = Severity.HIGH,
    refs: list[str] | None = None,
    centrality: float | None = None,
    type_: str = "Contradicted claim",
    description: str = "A qualifying critical failure.",
) -> CriticalFinding:
    return CriticalFinding(
        finding_id=finding_id,
        dimension=dimension,
        type=type_,
        severity=severity,
        description=description,
        evidence_refs=refs or [f"ev_{dimension.lower()}_1"],
        centrality=centrality,
    )


def result(
    dimension: str,
    score,
    confidence: float,
    *,
    findings=None,
    recommendations=None,
    evidence_items=None,
    applicable: bool = True,
    applicability_reason: str = "",
) -> AuditResult:
    spec = DIMENSION_SPECS[dimension]
    items = evidence_items
    if items is None:
        items = (
            []
            if (confidence == 0.0 or not applicable)
            else [evidence(dimension, f"ev_{dimension.lower()}_1")]
        )
    return AuditResult(
        score=score,
        confidence=confidence,
        ledger=[],
        evidence=items,
        recommendations=recommendations or [],
        critical_findings=findings or [],
        metadata=AuditResultMetadata(
            dimension=spec.dimension,
            engine_id=spec.engine_id,
            dimension_type=spec.dimension_type,
            critical_finding_capability=spec.critical_finding_capability,
            supports_na=spec.supports_na,
            applicable=applicable,
            applicability_reason=applicability_reason,
        ),
    )


def degraded(dimension: str) -> AuditResult:
    """Exactly what ``AuditEngine.degraded_result()`` produces."""
    return result(dimension, 0.0, 0.0)


def na_diversity() -> AuditResult:
    return result(
        "Diversity",
        "N/A",
        0.9,
        applicable=False,
        applicability_reason=(
            "The content addresses a settled technical question with no "
            "legitimate opposing perspective."
        ),
    )


def all_eight(**overrides) -> list[AuditResult]:
    """A high-trust, high-quality result set, with any dimension overridable."""
    base = {
        "Relevance": result("Relevance", 0.95, 0.92),
        "Accuracy": result("Accuracy", 0.94, 0.91),
        "Coverage": result("Coverage", 0.92, 0.90),
        "Credibility": result("Credibility", 0.93, 0.88),
        "Novelty": result("Novelty", 0.96, 0.93),
        "Readability": result("Readability", 0.95, 0.84),
        "Engagement": result("Engagement", 0.94, 0.97),
        "Diversity": result("Diversity", 0.90, 0.80),
    }
    base.update(overrides)
    return [base[d] for d in DIMENSION_SPECS]


@pytest.fixture
def decide(settings):
    engine = DecisionEngine(settings)
    return engine.decide


# --------------------------------------------------------------------------- #
# The four score/verdict quadrants
# --------------------------------------------------------------------------- #


def test_high_trust_high_quality(decide):
    d = decide(all_eight())
    assert d.overall_verdict is OverallVerdict.TRUSTED
    assert d.trust_verdict.verdict is TrustOutcome.TRUST_PASS
    assert d.quality_verdict.band is QualityBand.HIGH
    assert not d.critical_findings
    assert d.confidence.overall >= 0.75


def test_high_trust_low_quality_never_gates_trust(decide):
    """Quality must never alter Trust (Document 3, §7)."""
    d = decide(
        all_eight(
            Novelty=result("Novelty", 0.20, 0.90),
            Readability=result("Readability", 0.15, 0.90),
            Engagement=result("Engagement", 0.25, 0.90),
            Diversity=result("Diversity", 0.20, 0.90),
        )
    )
    assert d.quality_verdict.band is QualityBand.LOW
    assert d.trust_verdict.verdict is TrustOutcome.TRUST_PASS
    assert d.overall_verdict is OverallVerdict.NEEDS_REVISION
    assert d.overall_verdict is not OverallVerdict.UNTRUSTED


def test_low_trust_high_quality_reports_both_axes(decide):
    """Polished *and* untrustworthy — the two-axis separation (Document 3, §7)."""
    d = decide(
        all_eight(
            Credibility=result(
                "Credibility",
                0.10,
                0.90,
                evidence_items=[evidence("Credibility", "ev_fab")],
                findings=[
                    finding("Credibility", "cf_1", type_="Fabricated citation",
                            refs=["ev_fab"])
                ],
            )
        )
    )
    assert d.overall_verdict is OverallVerdict.UNTRUSTED
    assert d.trust_verdict.verdict is TrustOutcome.UNTRUSTED
    # Quality is untouched by the trust failure.
    assert d.quality_verdict.band is QualityBand.HIGH
    assert d.quality_verdict.score is not None
    assert d.trust_verdict.gating_finding_ids == ["cf_1"]
    assert "ev_fab" in d.trust_verdict.evidence_refs


def test_low_trust_low_quality(decide):
    d = decide(
        all_eight(
            Accuracy=result(
                "Accuracy", 0.15, 0.90,
                evidence_items=[evidence("Accuracy", "ev_a")],
                findings=[finding("Accuracy", "cf_a", refs=["ev_a"], centrality=0.9)],
            ),
            Novelty=result("Novelty", 0.2, 0.9),
            Readability=result("Readability", 0.2, 0.9),
            Engagement=result("Engagement", 0.2, 0.9),
            Diversity=result("Diversity", 0.2, 0.9),
        )
    )
    assert d.overall_verdict is OverallVerdict.UNTRUSTED
    assert d.quality_verdict.band is QualityBand.LOW


# --------------------------------------------------------------------------- #
# Non-compensatory trust — the core invariant
# --------------------------------------------------------------------------- #


def test_one_finding_beats_every_perfect_score(decide):
    """Trust is a floor, not an average (Document 3, §5/§6)."""
    perfect = {d: result(d, 1.0, 1.0) for d in DIMENSION_SPECS if d != "Accuracy"}
    d = decide(
        all_eight(
            **perfect,
            Accuracy=result(
                "Accuracy", 1.0, 1.0,  # a PERFECT score alongside a finding
                evidence_items=[evidence("Accuracy", "ev_h")],
                findings=[finding("Accuracy", "cf_h", refs=["ev_h"], centrality=1.0)],
            ),
        )
    )
    assert d.overall_verdict is OverallVerdict.UNTRUSTED
    assert d.quality_verdict.band is QualityBand.HIGH


@pytest.mark.parametrize(
    "severity, gates",
    [
        (Severity.CRITICAL, True),
        (Severity.HIGH, True),      # == the configured blocking severity
        (Severity.MEDIUM, False),
        (Severity.LOW, False),
        (Severity.INFO, False),
    ],
)
def test_gate_fires_on_severity_not_presence(decide, severity, gates):
    """The gate is on presence *and* severity (Document 3, §5)."""
    d = decide(
        all_eight(
            Accuracy=result(
                "Accuracy", 0.9, 0.9,
                evidence_items=[evidence("Accuracy", "ev_s")],
                findings=[finding("Accuracy", "cf_s", severity=severity, refs=["ev_s"])],
            )
        )
    )
    assert (d.overall_verdict is OverallVerdict.UNTRUSTED) is gates
    # Retained regardless — nothing is discarded (Document 3, §5).
    assert len(d.critical_findings) == 1


def test_two_low_findings_do_not_add_up(decide):
    """Two low-severity findings never sum into a block (Document 3, §5)."""
    d = decide(
        all_eight(
            Accuracy=result(
                "Accuracy", 0.9, 0.9,
                evidence_items=[evidence("Accuracy", "ev_a"), evidence("Accuracy", "ev_b")],
                findings=[
                    finding("Accuracy", "cf_a", Severity.LOW, ["ev_a"], type_="Minor A"),
                    finding("Accuracy", "cf_b", Severity.LOW, ["ev_b"], type_="Minor B"),
                ],
            )
        )
    )
    assert d.overall_verdict is not OverallVerdict.UNTRUSTED
    assert len(d.critical_findings) == 2


def test_quality_dimension_can_never_gate_trust(decide):
    """A Quality engine's finding is dropped, not honoured (Document 3, §5)."""
    rogue = result(
        "Readability", 0.5, 0.9, evidence_items=[evidence("Readability", "ev_r")]
    )
    object.__setattr__(
        rogue,
        "critical_findings",
        [finding("Readability", "cf_rogue", Severity.CRITICAL, ["ev_r"], type_="Unclear")],
    )
    d = decide(all_eight(Readability=rogue))
    assert d.overall_verdict is not OverallVerdict.UNTRUSTED
    assert not any(f.dimension == "Readability" for f in d.critical_findings)


def test_weakest_trust_dimension_governs(decide):
    """Not the mean (Document 3, §6)."""
    d = decide(all_eight(Credibility=result("Credibility", 0.40, 0.90)))
    assert d.overall_verdict is OverallVerdict.NEEDS_REVISION
    # A weakness is not a disqualification (Document 3, §8; §11 step 3).
    assert d.trust_verdict.verdict is not TrustOutcome.UNTRUSTED


# --------------------------------------------------------------------------- #
# Honest uncertainty
# --------------------------------------------------------------------------- #


def test_high_score_low_confidence_is_never_asserted(decide):
    """Document 3 §8: never upgraded to Trusted on unverified strength."""
    d = decide(all_eight(Accuracy=result("Accuracy", 1.0, 0.32)))
    assert d.overall_verdict is OverallVerdict.UNABLE_TO_VERIFY
    assert d.overall_verdict is not OverallVerdict.TRUSTED
    assert d.overall_verdict is not OverallVerdict.UNTRUSTED  # undetermined ≠ failed
    assert d.confidence.unable_to_verify_rationale is not None
    assert "Accuracy" in d.confidence.low_confidence_dimensions
    assert "undetermined" in d.summary.lower()


def test_degraded_trust_engine_is_a_gap_not_a_failure(decide):
    d = decide(all_eight(Accuracy=degraded("Accuracy")))
    assert d.overall_verdict is OverallVerdict.UNABLE_TO_VERIFY
    assert d.overall_verdict is not OverallVerdict.UNTRUSTED


def test_degraded_quality_engine_cannot_move_the_band(decide):
    """Zero confidence ⇒ zero weight ⇒ no vote (Document 3, §7/§8)."""
    clean = decide(all_eight())
    d = decide(all_eight(Readability=degraded("Readability")))
    assert d.trust_verdict.verdict is TrustOutcome.TRUST_PASS
    assert d.quality_verdict.band is QualityBand.HIGH
    assert d.confidence.overall < clean.confidence.overall
    # …and the report admits how little voted.
    assert any("could not be measured" in driver for driver in d.quality_verdict.drivers)


def test_total_degradation_reports_no_quality_score(decide):
    d = decide([degraded(dimension) for dimension in DIMENSION_SPECS])
    assert d.overall_verdict is OverallVerdict.UNABLE_TO_VERIFY
    # None, not 0.0 — "not measured" is not "measured as bad".
    assert d.quality_verdict.score is None


# --------------------------------------------------------------------------- #
# Applicability (Document 3, §9)
# --------------------------------------------------------------------------- #


def test_na_is_excluded_never_penalized(decide):
    with_na = decide(all_eight(Diversity=na_diversity()))
    scored = decide(all_eight(Diversity=result("Diversity", 0.90, 0.80)))
    as_zero = decide(all_eight(Diversity=result("Diversity", 0.0, 0.80)))

    assert "Diversity" in with_na.quality_verdict.excluded_dimensions
    # Excluded from the denominator too, so it cannot drag the band down.
    assert with_na.quality_verdict.score >= scored.quality_verdict.score
    # The decisive test: N/A behaves like absence, not like a zero.
    assert with_na.quality_verdict.score > as_zero.quality_verdict.score
    assert with_na.trust_verdict.verdict is TrustOutcome.TRUST_PASS


def test_na_reason_is_carried_for_the_report(decide):
    d = decide(all_eight(Diversity=na_diversity()))
    row = next(s for s in d.dimension_summaries if s.dimension == "Diversity")
    assert not row.applicable
    assert "not applicable" in row.rationale.lower()
    # An N/A dimension still reports its own confidence.
    assert d.confidence.per_dimension["Diversity"] == 0.9


# --------------------------------------------------------------------------- #
# Critical findings: dedupe and ordering (Document 3, §5)
# --------------------------------------------------------------------------- #


def test_findings_order_severity_then_trust_then_centrality(decide):
    d = decide(
        all_eight(
            Coverage=result(
                "Coverage", 0.4, 0.9,
                evidence_items=[evidence("Coverage", "ev_c")],
                findings=[finding("Coverage", "cf_cov", Severity.CRITICAL, ["ev_c"],
                                  centrality=0.8, type_="Critical omission")],
            ),
            Accuracy=result(
                "Accuracy", 0.4, 0.9,
                evidence_items=[evidence("Accuracy", "ev_a")],
                findings=[finding("Accuracy", "cf_acc", Severity.HIGH, ["ev_a"],
                                  centrality=0.5)],
            ),
            Relevance=result(
                "Relevance", 0.4, 0.9,
                evidence_items=[evidence("Relevance", "ev_r")],
                findings=[finding("Relevance", "cf_rel", Severity.HIGH, ["ev_r"],
                                  centrality=0.9, type_="Violated hard requirement")],
            ),
        )
    )
    order = [f.finding_id for f in d.critical_findings]
    assert order[0] == "cf_cov"                       # CRITICAL before HIGH
    assert order.index("cf_acc") < order.index("cf_rel")  # Trust before Hybrid
    assert len(d.critical_findings) == 3


def test_dedupe_unions_evidence_and_keeps_higher_severity(decide):
    d = decide(
        all_eight(
            Accuracy=result(
                "Accuracy", 0.4, 0.9,
                evidence_items=[evidence("Accuracy", "ev_p"), evidence("Accuracy", "ev_q")],
                findings=[
                    finding("Accuracy", "cf_1", Severity.MEDIUM, ["ev_p"],
                            description="Same issue."),
                    finding("Accuracy", "cf_2", Severity.HIGH, ["ev_q"],
                            description="Same issue."),
                ],
            )
        )
    )
    assert len(d.critical_findings) == 1
    # A merge must never lose a pointer…
    assert set(d.critical_findings[0].evidence_refs) == {"ev_p", "ev_q"}
    # …and must never un-gate trust.
    assert d.critical_findings[0].severity is Severity.HIGH


def test_findings_from_different_engines_are_never_merged(decide):
    """Two dimensions, two failures, two remedies (Document 3, §5)."""
    d = decide(
        all_eight(
            Accuracy=result(
                "Accuracy", 0.4, 0.9,
                evidence_items=[evidence("Accuracy", "ev_s")],
                findings=[finding("Accuracy", "cf_x", refs=["ev_s"],
                                  description="Same issue.")],
            ),
            Credibility=result(
                "Credibility", 0.4, 0.9,
                evidence_items=[evidence("Credibility", "ev_t")],
                findings=[finding("Credibility", "cf_y", refs=["ev_t"],
                                  description="Same issue.")],
            ),
        )
    )
    assert len(d.critical_findings) == 2


# --------------------------------------------------------------------------- #
# Recommendations (Document 3, §10)
# --------------------------------------------------------------------------- #


def test_recommendation_tiers_and_trust_first_ordering(decide):
    d = decide(
        all_eight(
            Credibility=result(
                "Credibility", 0.1, 0.9,
                evidence_items=[evidence("Credibility", "ev_fab")],
                findings=[finding("Credibility", "cf_1", type_="Fabricated citation",
                                  refs=["ev_fab"])],
                recommendations=[
                    Recommendation(recommendation_id="r1", dimension="Credibility",
                                   text="Remove the fabricated citation.",
                                   severity=Severity.HIGH, evidence_refs=["ev_fab"])
                ],
            ),
            Novelty=result(
                "Novelty", 0.6, 0.9,
                evidence_items=[evidence("Novelty", "ev_n")],
                recommendations=[
                    Recommendation(recommendation_id="r2", dimension="Novelty",
                                   text="Trim the repeated passage.",
                                   severity=Severity.LOW, evidence_refs=["ev_n"])
                ],
            ),
        )
    )
    # Tied to a critical finding by shared evidence ⇒ Critical tier, listed first.
    assert d.recommendations[0].priority is RecommendationPriority.CRITICAL
    assert d.recommendations[0].dimension == "Credibility"
    assert d.recommendations[-1].priority is RecommendationPriority.LOW


def test_duplicate_recommendations_merge_at_higher_severity(decide):
    d = decide(
        all_eight(
            Accuracy=result(
                "Accuracy", 0.5, 0.9,
                evidence_items=[evidence("Accuracy", "ev_r")],
                recommendations=[
                    Recommendation(recommendation_id="r1", dimension="Accuracy",
                                   text="Cite a source for the claim.",
                                   severity=Severity.HIGH, evidence_refs=["ev_r"]),
                    Recommendation(recommendation_id="r2", dimension="Accuracy",
                                   text="Cite a source for the claim.",
                                   severity=Severity.MEDIUM, evidence_refs=["ev_r"]),
                ],
            )
        )
    )
    merged = [r for r in d.recommendations if r.text.startswith("Cite")]
    assert len(merged) == 1
    assert merged[0].source_severity is Severity.HIGH


def test_unbacked_recommendation_is_never_emitted(decide):
    """Document 3 §10: no traceable evidence ⇒ not emitted."""
    d = decide(
        all_eight(
            Novelty=result(
                "Novelty", 0.6, 0.9,
                evidence_items=[evidence("Novelty", "ev_n")],
                recommendations=[
                    Recommendation(recommendation_id="r1", dimension="Novelty",
                                   text="Unbacked advice.", severity=Severity.LOW,
                                   evidence_refs=[]),
                ],
            )
        )
    )
    assert not any(r.text == "Unbacked advice." for r in d.recommendations)


def test_every_recommendation_names_its_originating_engine(decide):
    d = decide(
        all_eight(
            Novelty=result(
                "Novelty", 0.6, 0.9,
                evidence_items=[evidence("Novelty", "ev_n")],
                recommendations=[
                    Recommendation(recommendation_id="r1", dimension="Novelty",
                                   text="Trim it.", severity=Severity.LOW,
                                   evidence_refs=["ev_n"]),
                ],
            )
        )
    )
    assert all(r.dimension for r in d.recommendations)
    assert d.recommendations[0].dimension == "Novelty"


# --------------------------------------------------------------------------- #
# Confidence integration (Document 3, §8)
# --------------------------------------------------------------------------- #


def test_overall_confidence_tracks_trust_confidence(decide):
    high = decide(all_eight())
    low = decide(
        all_eight(
            Accuracy=result("Accuracy", 0.9, 0.30),
            Credibility=result("Credibility", 0.9, 0.30),
        )
    )
    assert low.confidence.overall < high.confidence.overall
    assert 0.0 <= high.confidence.overall <= 1.0
    assert len(high.confidence.per_dimension) == 8
    # The engines' own values, unmodified — the Decision Engine never re-measures.
    assert high.confidence.per_dimension["Readability"] == 0.84


def test_trust_confidence_outweighs_quality_confidence(decide):
    trust_hit = decide(all_eight(Accuracy=result("Accuracy", 0.9, 0.1)))
    quality_hit = decide(all_eight(Novelty=result("Novelty", 0.9, 0.1)))
    assert trust_hit.confidence.overall < quality_hit.confidence.overall


# --------------------------------------------------------------------------- #
# Determinism and verdict reachability (Document 3, §11/§13)
# --------------------------------------------------------------------------- #


def test_decision_is_deterministic(decide):
    fixture = all_eight(
        Accuracy=result(
            "Accuracy", 0.5, 0.9,
            evidence_items=[evidence("Accuracy", "ev_d")],
            findings=[finding("Accuracy", "cf_d", refs=["ev_d"])],
        )
    )
    runs = [decide(fixture) for _ in range(5)]
    assert len({r.overall_verdict for r in runs}) == 1
    assert len({tuple(f.finding_id for f in r.critical_findings) for r in runs}) == 1
    assert len({round(r.confidence.overall, 9) for r in runs}) == 1
    assert len({r.summary for r in runs}) == 1


@pytest.mark.parametrize("verdict", list(OverallVerdict))
def test_every_verdict_is_reachable(decide, verdict):
    """A verdict the engine can never emit is a verdict that does not exist."""
    reachable = {
        decide(all_eight()).overall_verdict,
        decide(all_eight(Coverage=result("Coverage", 0.80, 0.90))).overall_verdict,
        decide(
            all_eight(
                Novelty=result("Novelty", 0.2, 0.9),
                Readability=result("Readability", 0.2, 0.9),
                Engagement=result("Engagement", 0.2, 0.9),
                Diversity=result("Diversity", 0.2, 0.9),
            )
        ).overall_verdict,
        decide(all_eight(Accuracy=result("Accuracy", 1.0, 0.2))).overall_verdict,
        decide(
            all_eight(
                Accuracy=result(
                    "Accuracy", 0.9, 0.9,
                    evidence_items=[evidence("Accuracy", "ev_v")],
                    findings=[finding("Accuracy", "cf_v", refs=["ev_v"])],
                )
            )
        ).overall_verdict,
    }
    assert verdict in reachable


def test_trusted_requires_a_clean_run(decide):
    """One Low recommendation is enough to demote to Caveats."""
    d = decide(
        all_eight(
            Novelty=result(
                "Novelty", 0.96, 0.93,
                evidence_items=[evidence("Novelty", "ev_t")],
                recommendations=[
                    Recommendation(recommendation_id="r1", dimension="Novelty",
                                   text="Trim a repeated line.", severity=Severity.LOW,
                                   evidence_refs=["ev_t"]),
                ],
            )
        )
    )
    assert d.overall_verdict is OverallVerdict.TRUSTED_WITH_CAVEATS


# --------------------------------------------------------------------------- #
# Report projection (Document 3, §12)
# --------------------------------------------------------------------------- #


def test_report_is_traceable_and_ordered(decide):
    results = all_eight(
        Credibility=result(
            "Credibility", 0.1, 0.9,
            evidence_items=[evidence("Credibility", "ev_fab")],
            findings=[finding("Credibility", "cf_1", type_="Fabricated citation",
                              refs=["ev_fab"])],
            recommendations=[
                Recommendation(recommendation_id="r1", dimension="Credibility",
                               text="Remove it.", severity=Severity.HIGH,
                               evidence_refs=["ev_fab"]),
            ],
        )
    )
    report = build_report("aud_x", decide(results), results)

    known = {e.evidence_id for r in report.dimension_results for e in r.evidence}
    for holder in (*report.critical_findings, *report.recommendations):
        assert holder.evidence_refs
        assert set(holder.evidence_refs) <= known
    assert set(report.trust_verdict.evidence_refs) <= known

    # Rows follow the frozen matrix, not completion order — a report whose rows
    # move between runs is a report nobody can diff.
    assert [r.metadata.dimension for r in report.dimension_results] == list(DIMENSION_SPECS)
    assert len(report.dimension_summaries) == 8
    assert all(s.rationale for s in report.dimension_summaries)
