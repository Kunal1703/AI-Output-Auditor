"""Relevance stage-7 deterministic override — the must_contain false-positive.

A semantic instruction ("report on the congestion pricing vote") is sometimes
classified as a literal ``must_contain`` constraint. A substring search then
fails on an article that reports the vote in other words ("the congestion
charge", "the 7-4 vote"), and before the fix that miss overrode the judge's
correct "Satisfied" into a trust-gating "Violated hard requirement" — a false
Untrusted verdict on good content. These tests hold that a must_contain miss
defers to the judge while genuinely deterministic checks still override.
"""

from __future__ import annotations

import pytest

from app.audit_engines.relevance import RelevanceAuditEngine
from app.shared.deterministic_validators import ValidationOutcome
from app.shared.evidence_pipeline import EvidenceCollector
from app.shared.extraction.models import Requirement
from app.shared.schemas import Severity
from app.shared.verification.base import Judgment
from app.shared.vocabularies import RequirementType, RequirementVerdict

pytestmark = pytest.mark.unit


def _engine(make_services):
    from tests.conftest import ScriptedLLM

    return RelevanceAuditEngine(make_services(ScriptedLLM()))


def _requirement(kind: str, value) -> Requirement:
    return Requirement(
        requirement_id="req_1",
        text="The response must report on the city council's congestion pricing vote.",
        requirement_type=RequirementType.HARD,
        attributes={"constraint_kind": kind, "constraint_value": value},
    )


def _judgment(req: Requirement, verdict: RequirementVerdict) -> Judgment:
    return Judgment(unit=req, verdict=verdict, rationale="The response explicitly reports it.",
                    evidence_refs=(), confidence_hint=0.9)


def test_must_contain_miss_does_not_override_a_satisfied_judgment(make_services):
    engine = _engine(make_services)
    collector = EvidenceCollector(engine.services.evidence, "Relevance")
    req = _requirement("must_contain", "congestion pricing vote")
    judgments = [_judgment(req, RequirementVerdict.SATISFIED)]
    checks = [ValidationOutcome(check="must_contain", passed=False,
                                detail="Required content 'congestion pricing vote' is absent.",
                                severity=Severity.HIGH, observed={"phrase": "congestion pricing vote"})]

    out = engine._apply_deterministic_overrides(judgments, checks, collector)

    # The judge's Satisfied stands — no false trust-gating Violated.
    assert out[0].verdict is RequirementVerdict.SATISFIED


def test_max_words_miss_still_overrides(make_services):
    """The genuinely-deterministic length check is unaffected by the fix."""
    engine = _engine(make_services)
    collector = EvidenceCollector(engine.services.evidence, "Relevance")
    req = _requirement("max_words", 200)
    judgments = [_judgment(req, RequirementVerdict.SATISFIED)]
    checks = [ValidationOutcome(check="max_words", passed=False,
                                detail="Requested at most 200 words; found 470.",
                                severity=Severity.MEDIUM, observed={"limit": 200, "actual": 470})]

    out = engine._apply_deterministic_overrides(judgments, checks, collector)

    # A word count is a fact, so it still overrides the judge.
    assert out[0].verdict is RequirementVerdict.VIOLATED


def test_must_not_contain_hit_still_overrides(make_services):
    """A present forbidden term is a definite fact and still overrides."""
    engine = _engine(make_services)
    collector = EvidenceCollector(engine.services.evidence, "Relevance")
    req = _requirement("must_not_contain", "confidential")
    judgments = [_judgment(req, RequirementVerdict.SATISFIED)]
    checks = [ValidationOutcome(check="must_not_contain", passed=False,
                                detail="Excluded content 'confidential' is present.",
                                severity=Severity.HIGH, observed={"phrase": "confidential"})]

    out = engine._apply_deterministic_overrides(judgments, checks, collector)

    assert out[0].verdict is RequirementVerdict.VIOLATED
