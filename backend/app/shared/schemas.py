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
    "RecommendationPriority",
    "Confidence",
    "EvidenceItem",
    "Recommendation",
    "ConfidenceReport",
    "PrioritizedRecommendation",
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


class RecommendationPriority(str, Enum):
    """Priority tiers for the merged action list (Document 3, §10)."""

    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


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


# --------------------------------------------------------------------------- #
# Preprocessing output (Document 1, §5)
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Decision Engine output (Document 3, §12)
# --------------------------------------------------------------------------- #


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
