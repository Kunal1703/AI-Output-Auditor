"""Shared Pydantic models — the contract boundary of the whole system.

This module is the "Shared JSON Models" component of Document 2 §5 and the
``schemas.py`` of Document 4 §3/§4. It encodes, as typed Pydantic v2 models:

* the **Standard AuditResult Contract** (Document 2, §6.5) — the stable seam
  between the eight Audit Engines and the Decision Engine;
* the ledger, evidence, recommendation, and critical-finding shapes
  (Document 2, §6.2–§6.4);
* the **Final Audit Report** (Document 3, §12) — the stable seam between the
  Decision Engine and the API/Frontend;
* the verdict vocabularies (Document 3, §11).

Two rules govern edits here. First, the ``AuditResult`` field set is frozen at
seven fields; adding one changes a contract that Documents 2, 3, and 4 all
depend on. Second, thresholds never appear in this module — a schema describes
shape, and Document 3 treats every threshold as deployment configuration.

The Decision Engine depends only on these models, never on engine internals.
That is what lets an engine's pipeline evolve without touching decision logic
(Document 1, §6; Document 3, §13).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "Severity",
    "DimensionType",
    "CriticalFindingCapability",
    "RecommendationPriority",
    "TrustOutcome",
    "QualityBand",
    "OverallVerdict",
    "InputType",
    "JobStatus",
    "Score",
    "Confidence",
    "NOT_APPLICABLE",
    "SEVERITY_ORDER",
    "EvidenceItem",
    "LedgerEntry",
    "Recommendation",
    "CriticalFinding",
    "AuditResultMetadata",
    "AuditResult",
    "PreprocessedContent",
    "TrustVerdict",
    "QualityVerdict",
    "ConfidenceReport",
    "PrioritizedRecommendation",
    "DimensionSummary",
    "DecisionResult",
    "AuditReport",
    # --- AI Output Auditor — new evaluation-pipeline contracts (MB1) --------- #
    "SupportLabel",
    "VerdictBand",
    "FindingSeverity",
    "Layer",
    "GateRole",
    "Producer",
    "OutputType",
    "FindingType",
    "FINDING_SEVERITY_ORDER",
    "Span",
    "AttributionEntry",
    "Finding",
    "MetricResult",
    "LayerResults",
    "SourceMeta",
    "ComparisonRow",
    "Comparison",
    "OutputAudit",
    "ComparativeReport",
    "AuditOptions",
    "SourceInput",
    "OutputInput",
]


# --------------------------------------------------------------------------- #
# Vocabularies
# --------------------------------------------------------------------------- #


class Severity(str, Enum):
    """Graded impact assigned to a finding or ledger item (Document 2, §3).

    Severity is supplied by the emitting engine. The Decision Engine only
    orders and compares severities; it never reassigns them. Which severity
    gates trust is deployment configuration (``decision.trust_blocking_severity``
    in ``config/settings.yaml``), not a property of this enum.
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


#: Rank of each severity, ascending. Used for the severity ordering of Critical
#: Findings (Document 3, §5) and for comparing a finding against the configured
#: trust-blocking severity. Higher number means more severe.
SEVERITY_ORDER: dict[Severity, int] = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


class DimensionType(str, Enum):
    """Trust / Quality / Hybrid classification (Document 2, §4.1).

    The Decision Engine treats this as fixed input used to route a dimension to
    Trust Evaluation, Quality Evaluation, or both — it does not compute it
    (Document 3, §3).
    """

    TRUST = "Trust"
    QUALITY = "Quality"
    HYBRID = "Hybrid"


class CriticalFindingCapability(str, Enum):
    """Whether an engine may emit Critical Findings (Document 2, §4.1).

    This is what lets the Decision Engine distinguish an expected empty
    ``critical_findings`` array (capability ``NO``) from an anomalous one
    (capability ``YES`` with a structurally incomplete result).
    """

    YES = "Yes"
    NO = "No"
    CONDITIONAL = "Conditional"


class RecommendationPriority(str, Enum):
    """Priority tiers for the merged action list (Document 3, §10)."""

    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class TrustOutcome(str, Enum):
    """The Trust Verdict vocabulary (Document 3, §6).

    Reported on its own axis and never fused into the Quality Verdict
    (Document 3, §7 separation guarantee).
    """

    TRUST_PASS = "Trust-Pass"
    TRUST_PASS_WITH_CAVEATS = "Trust-Pass with caveats"
    UNTRUSTED = "Untrusted"
    UNABLE_TO_VERIFY = "Unable to Verify"


class QualityBand(str, Enum):
    """The Quality Verdict banding (Document 3, §7 and §12)."""

    HIGH = "High"
    ADEQUATE = "Adequate"
    LOW = "Low"


class OverallVerdict(str, Enum):
    """The fixed Overall Verdict set (Document 3, §11).

    Resolution order is deterministic and is implemented in
    ``decision_engine.workflow``: a qualifying Critical Finding yields
    ``UNTRUSTED``; insufficient trust confidence yields ``UNABLE_TO_VERIFY``;
    only then are favorable verdicts considered.
    """

    TRUSTED = "Trusted"
    TRUSTED_WITH_CAVEATS = "Trusted with Caveats"
    NEEDS_REVISION = "Needs Revision"
    UNTRUSTED = "Untrusted"
    UNABLE_TO_VERIFY = "Unable to Verify"


class InputType(str, Enum):
    """How the content under audit arrived (Document 4, §7)."""

    TEXT = "text"
    URL = "url"
    FILE = "file"


class JobStatus(str, Enum):
    """Async audit job lifecycle (Document 4, §7 status contract)."""

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


#: The sentinel a dimension reports instead of a numeric score when it does not
#: apply. Only legal when ``metadata.applicable`` is ``False``, which in turn is
#: only legal when ``metadata.supports_na`` is ``True`` — today, Diversity alone
#: (Document 2, §6.5; Document 3, §9).
NOT_APPLICABLE: Literal["N/A"] = "N/A"

#: A dimension score: a number in [0, 1], or the ``"N/A"`` sentinel.
#:
#: The union is deliberate. Document 3 §9 requires that an inapplicable
#: dimension be *excluded*, never scored as zero — encoding N/A in the type
#: forces every consumer to make that distinction explicitly instead of letting
#: a silent ``0.0`` depress the Quality Verdict.
Score = Union[Annotated[float, Field(ge=0.0, le=1.0)], Literal["N/A"]]

#: An engine's confidence in its own judgment, reported separately from the
#: score (Document 2, §5.10). Confidence gates assertability, and a high score
#: with low confidence is never upgraded to Trusted (Document 3, §8).
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


def _utc_now() -> datetime:
    """Return an aware UTC timestamp (naive datetimes cause silent bugs)."""
    return datetime.now(timezone.utc)


class _Base(BaseModel):
    """Base model for every schema in the contract.

    ``extra="forbid"`` is the important setting: an engine that invents a field
    should fail loudly at the contract boundary rather than have it silently
    dropped before the Decision Engine ever sees it.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=False)


# --------------------------------------------------------------------------- #
# AuditResult constituents (Document 2, §6.2–§6.4)
# --------------------------------------------------------------------------- #


class EvidenceItem(_Base):
    """One piece of located support behind a verdict or finding.

    Evidence is the backbone of the evidence-first principle: every conclusion
    in the Final Audit Report resolves to one of these via ``evidence_id``
    (Document 1, §11; Document 3, §13). The Decision Engine reads evidence but
    never creates it (Document 3, §1).
    """

    evidence_id: str = Field(
        description="Run-unique id, e.g. 'ev_12'. Referenced by ledger entries, "
        "critical findings, and recommendations."
    )
    dimension: str = Field(description="The dimension whose engine collected this.")
    kind: str = Field(
        description="Evidence class, e.g. 'output_span', 'reference_passage', "
        "'retrieved_source', 'validator_result'."
    )
    content: str = Field(description="The located text — the span or passage itself.")
    locator: str | None = Field(
        default=None,
        description="Where the content sits in its source, e.g. a character "
        "range or section anchor, so the UI can highlight it.",
    )
    source_ref: str | None = Field(
        default=None,
        description="Origin of the evidence — a URL, DOI, or reference-document "
        "id. None for spans taken from the AI Output itself.",
    )


class LedgerEntry(_Base):
    """One row of an engine's per-unit evaluation record (Document 2, §6.3).

    The ledger is deliberately generic across engines. Each engine names its own
    ledger and evaluates its own unit (Requirement, Claim, Key Point, Citation,
    text segment, issue, viewpoint) against its own verdict vocabulary
    (Document 2, §6.4) — but all of them serialize into this shape so the
    Decision Engine and report builder can traverse them uniformly.
    """

    entry_id: str = Field(description="Run-unique id for this ledger row.")
    unit: str = Field(description="The evaluated unit's text, e.g. the claim itself.")
    unit_type: str = Field(
        description="What kind of unit this is, e.g. 'Claim', 'Requirement', "
        "'Key Point', 'Citation'."
    )
    verdict: str = Field(
        description="The per-unit outcome, drawn from this engine's frozen "
        "verdict vocabulary (Document 2, §6.4), e.g. 'Supported'."
    )
    severity: Severity | None = Field(
        default=None, description="Graded impact, where the engine assigns one."
    )
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="``EvidenceItem.evidence_id`` values supporting this verdict.",
    )
    rationale: str | None = Field(
        default=None, description="One-line human-readable justification."
    )
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Engine-specific labels that do not generalize across "
        "engines — e.g. Accuracy's claim_type and centrality, Coverage's "
        "salience, Credibility's source_class, Relevance's requirement_type.",
    )


class Recommendation(_Base):
    """An actionable improvement produced by an engine (Document 2, §5.11).

    Engines produce these; the Decision Engine orders them and binds them to
    evidence but never rewrites or invents them (Document 3, §10).
    """

    recommendation_id: str = Field(description="Run-unique id.")
    dimension: str = Field(description="The emitting dimension.")
    text: str = Field(description="The recommended action, in plain language.")
    severity: Severity = Field(
        description="Source severity, used to assign the priority tier and to "
        "order within a tier (Document 3, §10)."
    )
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="Evidence and/or ledger ids that motivated this. Document 3 "
        "§10 forbids emitting a recommendation with no traceable evidence, so "
        "an entry with an empty list is dropped during prioritization.",
    )


class CriticalFinding(_Base):
    """A high-severity issue surfaced separately from the numeric score.

    Only the four capable engines emit these — Relevance, Accuracy, Coverage
    (as Critical Omissions), and Credibility. Quality dimensions never do, which
    is precisely why they can never gate trust (Document 3, §5).

    A single unresolved finding at or above the configured trust-blocking
    severity forces the Trust Verdict to Untrusted regardless of any other
    dimension's score. That non-compensatory rule is fixed; only the severity
    threshold is configuration.
    """

    finding_id: str = Field(description="Run-unique id.")
    dimension: str = Field(description="The emitting dimension.")
    type: str = Field(
        description="Finding class, e.g. 'Fabricated citation', 'Contradicted "
        "claim', 'Violated hard requirement', 'Critical omission'."
    )
    severity: Severity = Field(
        description="Severity as supplied by the emitting engine. The Decision "
        "Engine compares this against the configured blocking severity; it "
        "never reassigns it."
    )
    description: str = Field(description="What is wrong, in plain language.")
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="Evidence backing the finding. A finding with no evidence "
        "cannot be justified in the report.",
    )
    centrality: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="How load-bearing the affected unit is, where the source "
        "engine supplies it. Used as the third tiebreaker when ordering "
        "findings (Document 3, §5).",
    )


class AuditResultMetadata(_Base):
    """Engine descriptor and run metadata (Document 2, §6.5).

    This is how the Decision Engine routes and interprets a result without
    knowing anything about the engine that produced it: ``dimension_type``
    drives Trust vs. Quality routing, ``critical_finding_capability`` tells it
    whether an empty findings array is expected, and ``applicable`` /
    ``applicability_reason`` drive exclusion-with-transparency.
    """

    dimension: str = Field(description="e.g. 'Relevance'.")
    engine_id: str = Field(description="e.g. 'ENG-RELEVANCE'.")
    dimension_type: DimensionType = Field(
        description="Routing class consumed by the Decision Engine."
    )
    critical_finding_capability: CriticalFindingCapability = Field(
        description="Whether this engine may emit Critical Findings."
    )
    supports_na: bool = Field(
        description="Whether this engine may legitimately return 'N/A'."
    )
    applicable: bool = Field(
        default=True,
        description="Runtime applicability. May only be False when "
        "``supports_na`` is True (Document 2, §6.5).",
    )
    applicability_reason: str = Field(
        default="",
        description="Why the dimension was excluded. Surfaced verbatim in the "
        "report so every exclusion is auditable (Document 3, §9).",
    )


class AuditResult(_Base):
    """The standardized result object returned by every Audit Engine.

    This is the **frozen seven-field contract** of Document 2 §6.5 and the
    stable seam of the entire system. Every engine returns this shape
    regardless of dimension, and the Decision Engine consumes only this — never
    engine internals (Document 3, §13).

    Field population rules (Document 2, §6.5), enforced by
    :meth:`validate_contract`:

    * ``score`` — always present; ``"N/A"`` only when ``metadata.applicable``
      is False.
    * ``confidence`` — always present, and always separate from the score. A
      high score with low confidence is not assertable (Document 3, §8).
    * ``ledger`` — the engine's named ledger; empty for Diversity when N/A.
    * ``evidence`` — always present; may be empty when there are no findings.
    * ``recommendations`` — empty when no issues are detected.
    * ``critical_findings`` — populated only by capable engines; an empty array
      is valid and expected for the four Quality engines.
    * ``metadata`` — always present.
    """

    score: Score = Field(
        description="Numeric dimension score in [0, 1], or 'N/A' when the "
        "dimension does not apply."
    )
    confidence: Confidence = Field(
        description="How well-supported the engine's own judgment is. Reported "
        "separately from the score and never folded into it."
    )
    ledger: list[LedgerEntry] = Field(
        default_factory=list, description="Per-unit evaluation record."
    )
    evidence: list[EvidenceItem] = Field(
        default_factory=list, description="Located support behind verdicts."
    )
    recommendations: list[Recommendation] = Field(
        default_factory=list, description="Actionable improvements."
    )
    critical_findings: list[CriticalFinding] = Field(
        default_factory=list,
        description="High-severity findings; always empty for engines with "
        "capability = No.",
    )
    metadata: AuditResultMetadata = Field(description="Engine and run descriptor.")

    def validate_contract(self) -> list[str]:
        """Check the population rules Pydantic's type system cannot express.

        Document 3 §4 Stage 2 requires the Decision Engine to confirm each
        result conforms to the contract before interpreting it, and to treat a
        structurally invalid Trust or Hybrid result as a verification gap that
        pushes the run toward *Unable to Verify* — never toward a silent pass.

        This method reports rather than raises. A malformed result must
        influence the verdict through that documented path, not abort the run.

        Returns:
            Human-readable violations; empty means the result conforms.
        """
        problems: list[str] = []
        meta = self.metadata

        if self.score == NOT_APPLICABLE and meta.applicable:
            problems.append(
                f"{meta.dimension}: score is 'N/A' but metadata.applicable is True. "
                "An N/A score is always paired with applicable=False."
            )
        if not meta.applicable:
            if not meta.supports_na:
                problems.append(
                    f"{meta.dimension}: applicable=False but supports_na=False. "
                    "Only N/A-capable dimensions may be inapplicable."
                )
            if self.score != NOT_APPLICABLE:
                problems.append(
                    f"{meta.dimension}: applicable=False but score is "
                    f"{self.score!r}. An inapplicable dimension must not carry "
                    "a numeric score."
                )
            if not meta.applicability_reason.strip():
                problems.append(
                    f"{meta.dimension}: applicable=False requires an "
                    "applicability_reason so the exclusion is auditable."
                )
        if (
            meta.critical_finding_capability is CriticalFindingCapability.NO
            and self.critical_findings
        ):
            problems.append(
                f"{meta.dimension}: emitted {len(self.critical_findings)} critical "
                "finding(s) but its capability is No. A Quality dimension must "
                "never be able to gate trust."
            )

        known_evidence = {item.evidence_id for item in self.evidence}
        for finding in self.critical_findings:
            dangling = set(finding.evidence_refs) - known_evidence
            if dangling:
                problems.append(
                    f"{meta.dimension}: critical finding {finding.finding_id} "
                    f"references unknown evidence {sorted(dangling)}."
                )
        for rec in self.recommendations:
            dangling = set(rec.evidence_refs) - known_evidence
            if dangling:
                problems.append(
                    f"{meta.dimension}: recommendation {rec.recommendation_id} "
                    f"references unknown evidence {sorted(dangling)}."
                )
        return problems


# --------------------------------------------------------------------------- #
# Preprocessing output (Document 1, §5)
# --------------------------------------------------------------------------- #


class PreprocessedContent(_Base):
    """Normalized content ready for evaluation (Document 1, §5).

    Produced by Preprocessing and consumed by the Audit Engines. It carries the
    Engine Input Contract of Document 2 §6.1: ``ai_output`` for every engine,
    ``prompt`` for Relevance/Engagement/Diversity, and ``reference_source``
    for Accuracy (optional) and Coverage (required to score).
    """

    content_id: str = Field(description="Run-unique id for the normalized content.")
    ai_output: str = Field(description="The AI-generated content under audit.")
    prompt: str | None = Field(
        default=None,
        description="The user's original instruction. Used by Relevance, "
        "Engagement, and Diversity.",
    )
    reference_source: str | None = Field(
        default=None,
        description="Ground-truth document. Optional for Accuracy; Coverage "
        "requires it in order to score.",
    )
    input_type: InputType = Field(description="How the content arrived.")
    source_uri: str | None = Field(
        default=None, description="Original URL or filename, when applicable."
    )
    options: dict[str, Any] = Field(
        default_factory=dict, description="Request flags, e.g. external_retrieval."
    )
    extraction_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Provenance of the extraction — extractor used, detected "
        "language, character counts, title.",
    )


# --------------------------------------------------------------------------- #
# Decision Engine output (Document 3, §12)
# --------------------------------------------------------------------------- #


class TrustVerdict(_Base):
    """The trust axis of the report (Document 3, §6 and §12).

    Always carries its specific reason: the gating Critical Finding, or the
    confidence gap that produced *Unable to Verify*. A verdict without a stated
    reason would violate the explainability principle.
    """

    verdict: TrustOutcome = Field(description="The trust outcome.")
    reason: str = Field(description="Why — the gating finding or confidence gap.")
    evidence_refs: list[str] = Field(
        default_factory=list, description="Evidence backing the trust outcome."
    )
    gating_finding_ids: list[str] = Field(
        default_factory=list,
        description="Critical findings that gated trust. Empty unless the "
        "verdict is Untrusted.",
    )


class QualityVerdict(_Base):
    """The quality axis of the report (Document 3, §7 and §12).

    Reported alongside — never fused into — the Trust Verdict. Content can be
    high-quality yet Untrusted, and trustworthy yet low-quality; preserving both
    axes is a guarantee of Document 3 §7.
    """

    band: QualityBand = Field(description="High / Adequate / Low.")
    score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="The confidence-weighted aggregate behind the band. None "
        "when no quality dimension could be scored.",
    )
    drivers: list[str] = Field(
        default_factory=list, description="The main contributors to the band."
    )
    excluded_dimensions: list[str] = Field(
        default_factory=list,
        description="Dimensions excluded as N/A, removed from both numerator "
        "and denominator (Document 3, §9).",
    )


class ConfidenceReport(_Base):
    """Per-dimension and overall confidence state (Document 3, §12)."""

    overall: Confidence = Field(description="Integrated confidence for the run.")
    per_dimension: dict[str, Confidence] = Field(
        default_factory=dict, description="Confidence by dimension name."
    )
    unable_to_verify_rationale: str | None = Field(
        default=None,
        description="Why trust could not be asserted. Present exactly when the "
        "run resolves to Unable to Verify (Document 3, §8).",
    )
    low_confidence_dimensions: list[str] = Field(
        default_factory=list,
        description="Dimensions below the configured minimum. Surfaced plainly "
        "rather than rounded away.",
    )


class PrioritizedRecommendation(_Base):
    """One entry in the merged, ordered action list (Document 3, §10)."""

    priority: RecommendationPriority = Field(description="Critical/High/Medium/Low.")
    dimension: str = Field(description="The originating dimension.")
    text: str = Field(description="The recommended action, verbatim from the engine.")
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="Evidence pointers. Never empty — Document 3 §10 forbids "
        "emitting a recommendation without traceable evidence.",
    )
    source_severity: Severity = Field(description="Severity from the emitting engine.")


class DimensionSummary(_Base):
    """One row of the Dimension Results table (Document 3, §12).

    A flat projection of an ``AuditResult`` for display. N/A dimensions appear
    explicitly as excluded with their reason rather than being hidden.
    """

    dimension: str
    dimension_type: DimensionType
    score: Score
    confidence: Confidence
    rationale: str = Field(description="One-line explanation of the score.")
    applicable: bool = True
    applicability_reason: str = ""


class DecisionResult(_Base):
    """The Decision Engine's cross-dimensional outcome (Document 1, §5).

    Produced by the decision workflow and consumed by the report builder. It
    holds the reasoning outcome; :class:`AuditReport` is its presentation.
    """

    overall_verdict: OverallVerdict
    trust_verdict: TrustVerdict
    quality_verdict: QualityVerdict
    summary: str = Field(description="Plain-language statement for a decision-maker.")
    confidence: ConfidenceReport
    critical_findings: list[CriticalFinding] = Field(
        default_factory=list,
        description="The full severity-ordered list. All findings are retained "
        "— none are discarded or collapsed (Document 3, §5).",
    )
    recommendations: list[PrioritizedRecommendation] = Field(default_factory=list)
    dimension_summaries: list[DimensionSummary] = Field(default_factory=list)


class AuditReport(_Base):
    """The Final Audit Report — the system's deliverable (Document 3, §12).

    The stable seam between the backend and the frontend. Its guarantees:

    * **Two-axis clarity.** ``trust_verdict`` and ``quality_verdict`` are always
      separate and are never fused into a single number.
    * **Traceability.** Every claim links back to an ``AuditResult`` field via
      the full ``dimension_results`` carried here.
    * **Honest uncertainty.** Where confidence is insufficient, the report says
      so rather than presenting an unearned verdict.
    """

    audit_id: str = Field(description="The id the report is retrieved by.")
    generated_at: datetime = Field(default_factory=_utc_now)
    overall_verdict: OverallVerdict
    trust_verdict: TrustVerdict
    quality_verdict: QualityVerdict
    summary: str
    confidence: ConfidenceReport
    critical_findings: list[CriticalFinding] = Field(default_factory=list)
    dimension_results: list[AuditResult] = Field(
        default_factory=list,
        description="The complete AuditResult per dimension, carried through "
        "verbatim so the frontend can drill from any verdict into the ledger "
        "and evidence that produced it.",
    )
    dimension_summaries: list[DimensionSummary] = Field(
        default_factory=list,
        description="The flat per-dimension rows of Document 3 §12's Dimension "
        "Results section: dimension, type, score (or N/A with reason), "
        "confidence, and a one-line rationale. Carried alongside "
        "``dimension_results`` rather than derived from it because the rationale "
        "is the Decision Engine's one-line reading of what the engine reported, "
        "and §12 requires the report to state it. N/A dimensions appear here "
        "explicitly as excluded rather than being omitted.",
    )
    recommendations: list[PrioritizedRecommendation] = Field(default_factory=list)
    input_type: InputType = InputType.TEXT
    source_uri: str | None = None


# =========================================================================== #
# AI Output Auditor — new evaluation-pipeline contracts (MB1)
# =========================================================================== #
#
# These are the contracts of the *new* AI Output Auditor pipeline, which audits
# one or more outputs against a mandatory source article across three metric
# layers (Grounding / Information Quality / Presentation). They are added
# **alongside** the frozen ``AuditResult``/``AuditReport`` contracts above, which
# the currently-shipping application still depends on. The migration that retires
# the legacy contracts happens in MB4, once the new pipeline is complete.
#
# Naming note: the new grounding-finding severity vocabulary is
# ``FindingSeverity{CRITICAL, MAJOR, MINOR}``. It is intentionally *not* the
# frozen ``Severity{CRITICAL…INFO}`` above — that enum is used pervasively by the
# legacy engines, config, and Decision Engine and must not change while both
# pipelines coexist.


class SupportLabel(str, Enum):
    """How an output unit stands relative to the source (Attribution).

    The three grounding states the design distinguishes, produced by the
    Attribution substrate (MB2) from the local NLI labels
    (entailed → SUPPORTED, neutral → PARTIAL, contradicted → NOT_FOUND is *not*
    the mapping — see below). Concretely, Attribution maps an output claim to:

    * ``SUPPORTED`` — a source span entails it.
    * ``PARTIAL`` — a source span partially supports it (weak / hedged entail).
    * ``NOT_FOUND`` — no source span supports it (neutral or contradicted; the
      contradiction case is additionally surfaced as a Contradiction finding).
    """

    SUPPORTED = "supported"
    PARTIAL = "partial"
    NOT_FOUND = "not_found"


class VerdictBand(str, Enum):
    """The per-output overall verdict (Evaluation Framework §6).

    Resolved non-compensatorily by the Decision Engine (MB4): a Layer-1
    grounding failure caps at ``FAIL``; a critical Layer-2 omission caps at
    ``NEEDS_REVISION``; grounding that cannot be established with confidence
    yields ``UNABLE_TO_VERIFY``; otherwise a confidence-weighted compensatory
    band.
    """

    EXCELLENT = "Excellent"
    GOOD = "Good"
    NEEDS_REVISION = "Needs Revision"
    FAIL = "Fail"
    UNABLE_TO_VERIFY = "Unable to Verify"


class FindingSeverity(str, Enum):
    """Graded impact of a Layer-1/Layer-2 finding (Evaluation Framework §6).

    Derived by the emitting evaluator from ``support-label × centrality/salience``
    and read directly by the grounding gate: ``CRITICAL`` gates the verdict,
    ``MAJOR`` caps it, ``MINOR`` only modulates.
    """

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


#: Rank of each finding severity, ascending. Higher means more severe.
FINDING_SEVERITY_ORDER: dict[FindingSeverity, int] = {
    FindingSeverity.MINOR: 0,
    FindingSeverity.MAJOR: 1,
    FindingSeverity.CRITICAL: 2,
}


class Layer(str, Enum):
    """Which evaluation layer a metric or finding belongs to (§1)."""

    L1_GROUNDING = "L1_Grounding"
    L2_INFO = "L2_InformationQuality"
    L3_PRESENTATION = "L3_Presentation"
    CROSS = "CrossCutting"


class GateRole(str, Enum):
    """How a metric participates in the verdict (§1 role-in-verdict column)."""

    GATING = "gating"
    PARTIAL_GATING = "partial_gating"
    COMPENSATORY = "compensatory"
    MECHANISM = "mechanism"


class Producer(str, Enum):
    """Who produced an output under audit (§6 side-by-side comparison)."""

    HUMAN = "human"
    LLM = "llm"
    UNKNOWN = "unknown"


class OutputType(str, Enum):
    """The kind of output, which narrows some metrics (e.g. Compression N/A)."""

    SUMMARY = "summary"
    ANSWER = "answer"
    EXTRACTION = "extraction"
    OTHER = "other"


class FindingType(str, Enum):
    """The specific defect a finding records.

    Spans all three layers. The intrinsic/extrinsic hallucination split mirrors
    the NLI contradiction/neutral split (Metric Research §2); the remaining types
    name the design's per-metric finding vocabularies.
    """

    INTRINSIC_HALLUCINATION = "intrinsic_hallucination"
    EXTRINSIC_HALLUCINATION = "extrinsic_hallucination"
    NUMERIC_ERROR = "numeric_error"
    CONTRADICTION = "contradiction"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    UNSUPPORTED_INFERENCE = "unsupported_inference"
    MISSING_CRITICAL_FACT = "missing_critical_fact"
    MEANING_DISTORTION = "meaning_distortion"
    CONTEXT_LOSS = "context_loss"
    INTRODUCED_BIAS = "introduced_bias"
    REDUNDANCY = "redundancy"
    READABILITY_ISSUE = "readability_issue"
    STRUCTURE_ISSUE = "structure_issue"


class Span(_Base):
    """A located run of text in either the source or an output.

    The atomic evidence unit of the new pipeline: every finding and attribution
    entry points at source and/or output spans so the report can highlight the
    exact text (Evaluation Framework §5.2).
    """

    text: str = Field(description="The span's text, verbatim.")
    start: int = Field(ge=0, description="Character offset of the first character.")
    end: int = Field(ge=0, description="Character offset one past the last character.")
    ref: Literal["source", "output"] = Field(
        description="Which document the offsets index into."
    )
    locator: str | None = Field(
        default=None,
        description="Optional human-readable anchor, e.g. 'sentence 4' or a "
        "section id, for display.",
    )


class AttributionEntry(_Base):
    """One output unit mapped to its supporting source location, or 'absent'.

    Produced by the Attribution substrate (MB2) — the per-claim
    retrieve-then-entail map that every Layer-1 metric is derived from
    (Evaluation Framework §5.1). Present in the contracts now so ``OutputAudit``
    can carry it; populated in MB2.
    """

    output_unit_id: str = Field(description="Id of the output claim/sentence.")
    output_span: Span = Field(description="The output text being attributed.")
    support: SupportLabel = Field(description="Supported / partial / not-found.")
    source_span: Span | None = Field(
        default=None,
        description="The best supporting source span, or None when not found.",
    )
    nli_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="The entailment probability from the NLI backend, when the "
        "support decision came from it.",
    )
    confidence: Confidence = Field(
        default=0.0, description="Confidence in this attribution decision."
    )


class Finding(_Base):
    """One defect surfaced by an evaluator, bound to located evidence.

    The new pipeline's analogue of a legacy ``CriticalFinding``/ledger issue,
    generalized across all three layers and typed by ``FindingType``. Severity is
    the new ``FindingSeverity`` and drives the grounding gate (MB4).
    """

    finding_id: str = Field(description="Run-unique id, e.g. 'fnd_3'.")
    metric: str = Field(description="The metric that raised it, e.g. 'Faithfulness'.")
    layer: Layer = Field(description="The layer the metric belongs to.")
    type: FindingType = Field(description="The specific defect class.")
    severity: FindingSeverity = Field(description="Critical / major / minor.")
    note: str = Field(description="What is wrong, in plain language.")
    output_span: Span | None = Field(
        default=None, description="The offending output span, when locatable."
    )
    source_span: Span | None = Field(
        default=None,
        description="The relevant source span, when one exists (e.g. the correct "
        "value for a numeric error, or 'absent' by being None).",
    )
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="``EvidenceItem.evidence_id`` values backing this finding.",
    )
    centrality: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="How load-bearing the affected unit is, when the evaluator "
        "supplies it. Feeds severity and finding ordering.",
    )


class MetricResult(_Base):
    """The standardized result one metric evaluator returns (per output).

    The new pipeline's counterpart to the legacy ``AuditResult``, shaped for the
    metric/layer model: internal ``score`` stays a 0–1 float (or None when the
    metric is inapplicable / could not be scored), and the 1–5 ``band`` is a
    report-layer projection carried alongside it.
    """

    metric_id: str = Field(description="The metric name, e.g. 'Faithfulness'.")
    layer: Layer = Field(description="The metric's layer.")
    gate_role: GateRole = Field(description="Gating / partial / compensatory / mechanism.")
    score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Internal 0–1 score, or None when inapplicable or unscored. "
        "Reported separately from confidence and never fused with it.",
    )
    band: int | None = Field(
        default=None,
        ge=1,
        le=5,
        description="Optional 1–5 presentation band projected from ``score``.",
    )
    confidence: Confidence = Field(
        default=0.0, description="How well-supported this metric's judgment is."
    )
    applicable: bool = Field(
        default=True,
        description="False when the metric does not apply to this output (e.g. "
        "Compression on a non-compression). An inapplicable metric carries no "
        "score and is excluded from aggregation.",
    )
    applicability_reason: str = Field(
        default="",
        description="Why the metric was excluded. Surfaced verbatim so every "
        "exclusion is auditable.",
    )
    findings: list[Finding] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LayerResults(_Base):
    """The per-output metric results grouped by layer (§6 layer_results)."""

    layer_1: list[MetricResult] = Field(default_factory=list)
    layer_2: list[MetricResult] = Field(default_factory=list)
    layer_3: list[MetricResult] = Field(default_factory=list)


class SourceMeta(_Base):
    """Descriptive facts about the source article (§6 report header)."""

    title: str | None = Field(default=None)
    char_count: int = Field(ge=0, description="Character length of the source.")
    sentence_count: int = Field(ge=0, description="Sentence count of the source.")
    key_point_count: int = Field(
        default=0, ge=0, description="Extracted key-point count (populated in MB2)."
    )


class OutputAudit(_Base):
    """The complete audit of one output against the source (§6).

    Faithfulness is carried explicitly as the headline Layer-1 metric; the full
    per-layer results, findings, confidence, recommendations, and the attribution
    evidence map are all present so the report can drill from any verdict into
    the evidence that produced it.
    """

    output_id: str = Field(description="Run-unique id for this output.")
    producer: Producer = Field(description="Human / LLM / unknown.")
    output_type: OutputType = Field(default=OutputType.OTHER)
    verdict: VerdictBand = Field(description="The per-output overall verdict.")
    verdict_reason: str = Field(
        default="", description="Why — the gating finding or confidence gap."
    )
    layer_results: LayerResults = Field(default_factory=LayerResults)
    faithfulness: MetricResult | None = Field(
        default=None,
        description="The headline Layer-1 metric, surfaced directly. None until "
        "Faithfulness runs (MB2).",
    )
    confidence: ConfidenceReport | None = Field(
        default=None, description="Per-metric and overall confidence for this output."
    )
    findings: list[Finding] = Field(
        default_factory=list, description="All findings, severity-ordered."
    )
    recommendations: list[PrioritizedRecommendation] = Field(default_factory=list)
    attribution: list[AttributionEntry] = Field(
        default_factory=list, description="The output→source evidence map."
    )


class ComparisonRow(_Base):
    """One output's headline profile in the side-by-side comparison (§6)."""

    output_id: str
    producer: Producer
    verdict: VerdictBand
    faithfulness_score: float | None = Field(default=None, ge=0.0, le=1.0)
    coverage_score: float | None = Field(default=None, ge=0.0, le=1.0)
    meaning_score: float | None = Field(default=None, ge=0.0, le=1.0)
    gating_finding_count: int = Field(default=0, ge=0)


class Comparison(_Base):
    """The cross-output comparison (§6).

    MVP is the side-by-side ``rows`` table; ``ranking`` (an ordered list of
    output ids) is the advanced human-vs-LLM ranking, left empty until built.
    """

    rows: list[ComparisonRow] = Field(default_factory=list)
    ranking: list[str] = Field(
        default_factory=list,
        description="Output ids best-first. Empty in the MVP (advanced feature).",
    )


class ComparativeReport(_Base):
    """The system deliverable — every output audited against one source (§6).

    The stable seam between the new backend pipeline and the frontend. Each
    output is audited independently against the same source and presented side by
    side.
    """

    audit_id: str = Field(description="The id the report is retrieved by.")
    generated_at: datetime = Field(default_factory=_utc_now)
    source: SourceMeta = Field(description="Facts about the source article.")
    outputs: list[OutputAudit] = Field(
        default_factory=list, description="One audit per supplied output."
    )
    comparison: Comparison = Field(default_factory=Comparison)


# --------------------------------------------------------------------------- #
# New input contract — mandatory source + N outputs (MB1)
# --------------------------------------------------------------------------- #


class AuditOptions(_Base):
    """Per-request options for the new audit pipeline.

    Distinct from ``app.api.models.AuditOptions`` (the legacy transport shape);
    this is the domain-level options object the Input Router and evaluators read.
    """

    self_consistency_k: int = Field(
        default=1,
        ge=1,
        description="Number of judge samples for gate-only self-consistency "
        "(budget-gated; used by MB2+ gating judges).",
    )
    external_retrieval: bool = Field(
        default=False,
        description="Reserved: allow evidence retrieval beyond the source. The "
        "auditor is source-only by design; off by default.",
    )


class SourceInput(_Base):
    """The mandatory ground-truth source article for an audit (MB1).

    Exactly one of ``text`` or ``url`` is supplied. File upload arrives via the
    multipart route in MB4.
    """

    text: str | None = Field(default=None, description="The source article text.")
    url: str | None = Field(default=None, description="A URL to fetch and extract.")

    @model_validator(mode="after")
    def _exactly_one(self) -> "SourceInput":
        if bool(self.text and self.text.strip()) == bool(self.url and self.url.strip()):
            raise ValueError("SourceInput requires exactly one of 'text' or 'url'.")
        return self


class OutputInput(_Base):
    """One output to be audited against the source (MB1).

    Exactly one of ``text`` or ``url`` is supplied. ``producer`` labels who wrote
    it so the report can compare human vs. LLM outputs.
    """

    output_id: str | None = Field(
        default=None, description="Optional caller id; assigned if absent."
    )
    producer: Producer = Field(
        default=Producer.UNKNOWN, description="Human / LLM / unknown."
    )
    output_type: OutputType = Field(default=OutputType.OTHER)
    task_prompt: str | None = Field(
        default=None,
        description="The instruction that produced this output, when known. Used "
        "by task-narrowed metrics (MB2+).",
    )
    text: str | None = Field(default=None, description="The output text.")
    url: str | None = Field(default=None, description="A URL to fetch and extract.")

    @model_validator(mode="after")
    def _exactly_one(self) -> "OutputInput":
        if bool(self.text and self.text.strip()) == bool(self.url and self.url.strip()):
            raise ValueError("OutputInput requires exactly one of 'text' or 'url'.")
        return self
