"""End-to-end: eight engines → Decision Engine → Final Audit Report.

The real orchestrator, the real Decision Engine, the real report builder, real
embeddings, real validators. Only the model is scripted, so the run is
deterministic and offline while every other layer is the production path
(Document 4, §10).

The `live` test at the bottom makes real Groq calls and is deselected without a
key: `pytest -m "not live"`.
"""

from __future__ import annotations

import re

import pytest

from app.audit_engines.orchestrator import EngineOrchestrator
from app.audit_engines.registry import build_engines
from app.core.constants import ALL_DIMENSIONS, CROSS_ENGINE_INPUTS, EXECUTION_WAVES
from app.decision_engine.report_builder import build_report
from app.decision_engine.workflow import DecisionEngine
from app.shared.schemas import CriticalFindingCapability, OverallVerdict, TrustOutcome
from tests.conftest import ScriptedLLM

pytestmark = pytest.mark.e2e

PROMPT = "Summarise the trial findings for our clinical team. Keep it under 200 words."

AI_OUTPUT = """# Trial results

The trial found that the new treatment reduced hospital readmissions by 30%
across 500 patients. Researchers followed participants for eighteen months after
discharge.

An important limitation applies: participants were recruited from a single urban
hospital, so the result may not generalise to rural populations.

In summary, the treatment cut readmissions by 30% in a 500-patient trial, though
single-site recruitment limits how far the finding travels.
"""

REFERENCE = """A randomised controlled trial of 500 patients found the new
treatment reduced hospital readmissions by 30% over an eighteen-month follow-up
period. The effect was consistent across age groups.

The authors note an important limitation: all participants were recruited from a
single urban teaching hospital, which limits generalisability to rural
populations. The study was funded by a national research council grant.
"""

POISONED = AI_OUTPUT + (
    "\n\nThe protocol was independently validated by Halvorsen et al. (2021), "
    "available at https://example.invalid/halvorsen-2021-validation.\n"
)


def ids_in(prompt: str, prefix: str) -> list[str]:
    return list(dict.fromkeys(re.findall(rf'"({prefix}_\d+)"', prompt)))


def verdicts(prefix: str, verdict: str, extra: dict | None = None):
    def responder(prompt: str) -> dict:
        return {
            "verdicts": [
                {
                    "id": uid,
                    "verdict": verdict,
                    "rationale": "Scripted rationale for verification.",
                    "confidence": 0.85,
                    **(extra or {}),
                }
                for uid in ids_in(prompt, prefix)
            ]
        }

    return responder


def build_llm(citations: list[dict] | None = None) -> ScriptedLLM:
    """Script every stage of all eight engines, routed by prompt marker."""
    return ScriptedLLM(
        [
            # Accuracy (§7.2)
            ("Extract every candidate factual claim", lambda p: {"claims": [
                {"text": "The treatment reduced hospital readmissions by 30% across 500 patients."},
                {"text": "Participants were recruited from a single urban hospital."},
            ]}),
            ("Classify each claim below by whether it can be checked", lambda p: {
                "classifications": [
                    {"id": c, "claim_type": "Factual", "rationale": "Checkable."}
                    for c in ids_in(p, "clm")
                ]}),
            ("judge how load-bearing it is", lambda p: {"assignments": [
                {"id": c, "centrality": 0.9, "severity": "high", "rationale": "Key."}
                for c in ids_in(p, "clm")
            ]}),
            ("Decide whether the evidence below supports", verdicts("clm", "Supported")),
            # Coverage (§7.3)
            ("Extract every important unit of information", lambda p: {"key_points": [
                {"text": "The treatment reduced readmissions by 30% across 500 patients."},
                {"text": "Participants came from a single urban hospital, limiting generalisability."},
                {"text": "The study was funded by a national research council grant."},
            ]}),
            ("judge how central it is to the source document", lambda p: {"assignments": [
                {"id": k, "salience": 0.9 if i < 2 else 0.2, "rationale": "x"}
                for i, k in enumerate(ids_in(p, "kpt"))
            ]}),
            ("name what kind of information it is", lambda p: {"assignments": [
                {"id": k, "category": "finding", "severity": "high", "rationale": "x"}
                for k in ids_in(p, "kpt")
            ]}),
            ("You are a completeness auditor", verdicts("kpt", "Present")),
            # Relevance (§7.1)
            ("Decompose the instruction below", lambda p: {"requirements": [
                {"text": "Summarise the trial findings.", "quote": "Summarise the trial findings"},
                {"text": "Keep the response under 200 words.", "quote": "Keep it under 200 words"},
            ]}),
            ("Classify each requirement as Hard or Soft", lambda p: {"classifications": [
                {"id": r, "requirement_type": "Hard", "rationale": "Explicit.",
                 **({"constraint": {"kind": "max_words", "value": 200}} if i == 1 else {})}
                for i, r in enumerate(ids_in(p, "req"))
            ]}),
            ("You are an instruction-following auditor", verdicts("req", "Satisfied")),
            # Credibility (§7.4)
            ("Extract every citation, reference, and source attribution",
             lambda p: {"citations": citations or []}),
            ("For each citation, identify which claims", lambda p: {"mappings": []}),
            ("decide whether the source it points at actually supports",
             lambda p: {"verdicts": []}),
            ("Classify what kind of source each citation points at",
             lambda p: {"classifications": []}),
            # Readability (§7.6)
            ("You are a readability auditor", lambda p: {"assessments": [
                {"id": a, "verdict": "Clear", "rationale": "Reads cleanly.",
                 "confidence": 0.9, "issues": []}
                for a in ("clarity", "coherence", "structure")
            ]}),
            ("You are classifying readability issues", lambda p: {"classifications": []}),
            ("You are assigning severity to readability issues", lambda p: {"assignments": []}),
            # Novelty (§7.5)
            ("You are an efficiency auditor", verdicts("red", "Redundant candidate")),
            # Engagement (§7.7)
            ("You are identifying what a user actually asked for", lambda p: {
                "task_type": "summarization",
                "goal": "Understand the trial findings quickly.",
                "audience": "Clinical team",
                "criteria": [
                    {"criterion": "States the headline result.", "importance": 0.9},
                    {"criterion": "States the key limitation.", "importance": 0.8},
                ]}),
            ("You are a usefulness auditor", verdicts("crt", "Met")),
            ("You are a communicative-integrity auditor", verdicts("man", "Legitimate")),
            # Diversity (§7.8)
            ('You are deciding whether "perspective balance"', lambda p: {
                "applicable": False,
                "reason": "The content summarises a clinical trial's findings. This "
                          "is a factual report, not a contested question; requiring "
                          "balance would mean manufacturing a controversy.",
                "topic": "Trial findings on readmission reduction"}),
        ]
    )


async def run_audit(llm, make_services, make_context, settings, output, audit_id):
    services = make_services(llm, audit_id)
    orchestrator = EngineOrchestrator(build_engines(services))
    context = make_context(output, prompt=PROMPT, reference_source=REFERENCE,
                           audit_id=audit_id)
    progress: list[str] = []
    results = await orchestrator.run(
        context, on_progress=lambda c, t, d: progress.append(d)
    )
    ordered = list(results.values())
    decision = DecisionEngine(settings, confidence=services.confidence).decide(ordered)
    return build_report(audit_id, decision, ordered), progress, results


async def test_clean_audit_end_to_end(make_services, make_context, settings):
    report, progress, results = await run_audit(
        build_llm(), make_services, make_context, settings, AI_OUTPUT, "aud_clean"
    )

    assert len(progress) == 8
    assert len(report.dimension_results) == 8
    assert len(report.dimension_summaries) == 8
    assert all(row.rationale for row in report.dimension_summaries)
    # Rows follow the frozen matrix, not completion order.
    assert [r.metadata.dimension for r in report.dimension_results] == list(ALL_DIMENSIONS)
    assert report.summary and "scaffold" not in report.summary.lower()
    assert 0.0 <= report.confidence.overall <= 1.0

    # Every result is contract-valid, and every Quality engine stayed silent.
    for dimension, result in results.items():
        assert not result.validate_contract(), dimension
        spec_no = result.metadata.critical_finding_capability is CriticalFindingCapability.NO
        if spec_no:
            assert result.critical_findings == [], dimension

    # Diversity's N/A: excluded, never penalized.
    assert "Diversity" in report.quality_verdict.excluded_dimensions

    # Zero dangling references anywhere in the report.
    known = {e.evidence_id for r in report.dimension_results for e in r.evidence}
    for holder in (*report.critical_findings, *report.recommendations):
        assert set(holder.evidence_refs) <= known


async def test_wave_ordering_is_honoured(make_services, make_context, settings):
    """Coverage→Novelty and {Rel,Cov,Read,Nov}→Engagement (Document 2, §8)."""
    _, progress, _ = await run_audit(
        build_llm(), make_services, make_context, settings, AI_OUTPUT, "aud_waves"
    )
    for dimension, inputs in CROSS_ENGINE_INPUTS.items():
        for required in inputs:
            assert progress.index(required) < progress.index(dimension)
    assert EXECUTION_WAVES[1] == ("Novelty",)
    assert EXECUTION_WAVES[2] == ("Engagement",)


async def test_shared_context_reuse(make_services, make_context, settings):
    """Accuracy and Credibility share one claim extraction (SharedKeys)."""
    llm = build_llm()
    await run_audit(llm, make_services, make_context, settings, AI_OUTPUT, "aud_reuse")
    assert llm.call_count("Extract every candidate factual claim") == 1


async def test_fabricated_citation_gates_trust_but_not_quality(
    make_services, make_context, settings
):
    """The headline claim of the whole system, on the real stack."""
    llm = build_llm(citations=[{
        "text": "Halvorsen et al. (2021), https://example.invalid/halvorsen-2021-validation",
        "quote": "Halvorsen et al. (2021)",
    }])
    report, _, _ = await run_audit(
        llm, make_services, make_context, settings, POISONED, "aud_poisoned"
    )

    assert report.overall_verdict is OverallVerdict.UNTRUSTED
    assert report.trust_verdict.verdict is TrustOutcome.UNTRUSTED
    assert any(f.dimension == "Credibility" for f in report.critical_findings)
    assert report.trust_verdict.gating_finding_ids
    assert all(f.evidence_refs for f in report.critical_findings)

    # …and Quality is still reported independently. Polished AND untrustworthy.
    assert report.quality_verdict.score is not None
    assert report.recommendations
    assert report.recommendations[0].priority.value in ("Critical", "High")


@pytest.mark.live
async def test_live_groq_audit(make_context, settings):
    """A real audit against the real Groq API. Requires GROQ_API_KEY."""
    if not settings.llm_configured:
        pytest.skip("GROQ_API_KEY not configured")

    from app.app import build_container

    container = build_container()
    try:
        assert await container.llm.health(), "Groq is not reachable"
        audit_id = "aud_live"
        context = await container.input_router.from_text(
            audit_id=audit_id, text=AI_OUTPUT, prompt=PROMPT, reference_source=REFERENCE
        )
        results = await container.orchestrator(audit_id).run(context)
        ordered = list(results.values())
        report = build_report(
            audit_id, container.decision_engine.decide(ordered), ordered
        )

        assert len(report.dimension_results) == 8
        # A real run must actually measure something.
        assert any(r.confidence > 0.0 for r in ordered), "every engine degraded"
        for result in ordered:
            assert not result.validate_contract(), result.metadata.dimension
    finally:
        await container.aclose()
