/**
 * TypeScript mirror of the AI Output Auditor's finalized contracts (MB1–MB4).
 *
 * 1:1 with `backend/app/shared/schemas.py`. The frontend renders what the
 * backend decided — it never computes a verdict or a score.
 */

export type SupportLabel = 'supported' | 'partial' | 'not_found';

export type VerdictBand =
  | 'Excellent'
  | 'Good'
  | 'Needs Revision'
  | 'Fail'
  | 'Unable to Verify';

export type FindingSeverity = 'critical' | 'major' | 'minor';

export type Layer =
  | 'L1_Grounding'
  | 'L2_InformationQuality'
  | 'L3_Presentation'
  | 'CrossCutting';

export type GateRole = 'gating' | 'partial_gating' | 'compensatory' | 'mechanism';

export type Producer = 'human' | 'llm' | 'unknown';

export type OutputType = 'summary' | 'answer' | 'extraction' | 'other';

export type FindingType =
  | 'intrinsic_hallucination'
  | 'extrinsic_hallucination'
  | 'numeric_error'
  | 'contradiction'
  | 'unsupported_claim'
  | 'unsupported_inference'
  | 'missing_critical_fact'
  | 'meaning_distortion'
  | 'context_loss'
  | 'introduced_bias'
  | 'redundancy'
  | 'readability_issue'
  | 'structure_issue';

export type RecommendationPriority = 'Critical' | 'High' | 'Medium' | 'Low';

/** A located run of text in either the source or an output. */
export interface Span {
  text: string;
  start: number;
  end: number;
  ref: 'source' | 'output';
  locator: string | null;
}

/** One output unit mapped to its supporting source location, or "absent". */
export interface AttributionEntry {
  output_unit_id: string;
  output_span: Span;
  support: SupportLabel;
  source_span: Span | null;
  nli_score: number | null;
  confidence: number;
}

/** One located piece of evidence. */
export interface EvidenceItem {
  evidence_id: string;
  dimension: string;
  kind: string;
  content: string;
  locator: string | null;
  source_ref: string | null;
}

/** One defect surfaced by an evaluator, bound to located evidence. */
export interface Finding {
  finding_id: string;
  metric: string;
  layer: Layer;
  type: FindingType;
  severity: FindingSeverity;
  note: string;
  output_span: Span | null;
  source_span: Span | null;
  evidence_refs: string[];
  centrality: number | null;
}

/** Engine-level recommendation carried inside a MetricResult. */
export interface Recommendation {
  recommendation_id: string;
  dimension: string;
  text: string;
  severity: string;
  evidence_refs: string[];
}

/** The standardized result one metric evaluator returns (per output). */
export interface MetricResult {
  metric_id: string;
  layer: Layer;
  gate_role: GateRole;
  score: number | null;
  band: number | null;
  confidence: number;
  applicable: boolean;
  applicability_reason: string;
  findings: Finding[];
  recommendations: Recommendation[];
  evidence: EvidenceItem[];
  metadata: Record<string, unknown>;
}

export interface LayerResults {
  layer_1: MetricResult[];
  layer_2: MetricResult[];
  layer_3: MetricResult[];
}

export interface SourceMeta {
  title: string | null;
  char_count: number;
  sentence_count: number;
  key_point_count: number;
}

export interface ConfidenceReport {
  overall: number;
  per_dimension: Record<string, number>;
  unable_to_verify_rationale: string | null;
  low_confidence_dimensions: string[];
}

export interface PrioritizedRecommendation {
  priority: RecommendationPriority;
  dimension: string;
  text: string;
  evidence_refs: string[];
  source_severity: string;
}

/** The complete audit of one output against the source. */
export interface OutputAudit {
  output_id: string;
  producer: Producer;
  output_type: OutputType;
  verdict: VerdictBand;
  verdict_reason: string;
  layer_results: LayerResults;
  faithfulness: MetricResult | null;
  confidence: ConfidenceReport | null;
  findings: Finding[];
  recommendations: PrioritizedRecommendation[];
  attribution: AttributionEntry[];
}

export interface ComparisonRow {
  output_id: string;
  producer: Producer;
  verdict: VerdictBand;
  faithfulness_score: number | null;
  coverage_score: number | null;
  meaning_score: number | null;
  gating_finding_count: number;
}

export interface Comparison {
  rows: ComparisonRow[];
  ranking: string[];
}

/** The system deliverable — every output audited against one source. */
export interface ComparativeReport {
  audit_id: string;
  generated_at: string;
  source: SourceMeta;
  outputs: OutputAudit[];
  comparison: Comparison;
}

/* -------------------------------- requests -------------------------------- */

export interface SourceInput {
  text?: string;
  url?: string;
}

export interface OutputInput {
  output_id?: string;
  producer: Producer;
  output_type?: OutputType;
  task_prompt?: string | null;
  text?: string;
  url?: string;
}

export interface AuditOptions {
  self_consistency_k?: number;
  external_retrieval?: boolean;
}

export interface AuditOutputsRequest {
  source: SourceInput;
  outputs: OutputInput[];
  options?: AuditOptions;
}

/** `GET /health`. */
export interface HealthResponse {
  status: string;
  version: string;
  llm_provider: string;
  llm_model?: string | null;
  llm_configured?: boolean | null;
  llm_reachable?: boolean | null;
  llm_model_available?: boolean | null;
  engines_registered?: number | null;
  embedding_model?: string | null;
  embedding_cache_enabled?: boolean | null;
  embedding_cache_hit_rate?: number | null;
  prompt_templates?: number | null;
  nli_model?: string | null;
  nli_ready?: boolean | null;
}
