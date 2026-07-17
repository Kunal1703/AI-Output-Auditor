/**
 * TypeScript mirror of the backend's frozen contracts.
 *
 * These types correspond 1:1 to `backend/app/shared/schemas.py`. Keep them in
 * sync — the report shape is the seam between backend and frontend (Document 1,
 * §6), and the frontend depends on it and nothing else.
 *
 * Source of truth for each type is noted per declaration. The frontend never
 * computes a verdict or a score (Document 4, §5); it renders what the backend
 * decided. If a value you need is not here, it belongs in the report first.
 */

/** Graded impact of a finding or ledger item (Document 2, §3). */
export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info';

/** Trust / Quality / Hybrid classification (Document 2, §4.1). */
export type DimensionType = 'Trust' | 'Quality' | 'Hybrid';

/** Whether an engine may emit Critical Findings (Document 2, §4.1). */
export type CriticalFindingCapability = 'Yes' | 'No' | 'Conditional';

/** Recommendation priority tiers (Document 3, §10). */
export type RecommendationPriority = 'Critical' | 'High' | 'Medium' | 'Low';

/** The Trust Verdict vocabulary (Document 3, §6). */
export type TrustOutcome =
  | 'Trust-Pass'
  | 'Trust-Pass with caveats'
  | 'Untrusted'
  | 'Unable to Verify';

/** The Quality Verdict banding (Document 3, §7). */
export type QualityBand = 'High' | 'Adequate' | 'Low';

/** The fixed Overall Verdict set (Document 3, §11). */
export type OverallVerdict =
  | 'Trusted'
  | 'Trusted with Caveats'
  | 'Needs Revision'
  | 'Untrusted'
  | 'Unable to Verify';

/** How the audited content arrived (Document 4, §7). */
export type InputType = 'text' | 'url' | 'file';

/** Async audit job lifecycle (Document 4, §7). */
export type JobStatus = 'queued' | 'processing' | 'completed' | 'failed';

/**
 * A dimension score: a number in [0, 1], or the `'N/A'` sentinel.
 *
 * The union is not an inconvenience to be cast away — it is the type system
 * enforcing Document 3 §9. An inapplicable dimension must be *excluded*, never
 * scored as zero, so `'N/A'` has to be handled explicitly at every use. Reach
 * for `isScored()` in `client.ts` rather than a cast.
 */
export type Score = number | 'N/A';

/** One piece of located support behind a verdict or finding. */
export interface EvidenceItem {
  evidence_id: string;
  dimension: string;
  kind: string;
  content: string;
  locator: string | null;
  source_ref: string | null;
}

/** One row of an engine's per-unit evaluation record (Document 2, §6.3). */
export interface LedgerEntry {
  entry_id: string;
  unit: string;
  unit_type: string;
  verdict: string;
  severity: Severity | null;
  evidence_refs: string[];
  rationale: string | null;
  attributes: Record<string, unknown>;
}

/** An actionable improvement produced by an engine (Document 2, §5.11). */
export interface Recommendation {
  recommendation_id: string;
  dimension: string;
  text: string;
  severity: Severity;
  evidence_refs: string[];
}

/**
 * A high-severity issue surfaced separately from the score (Document 3, §5).
 *
 * Only Relevance, Accuracy, Coverage, and Credibility can emit these. One at or
 * above the configured blocking severity forces `Untrusted` regardless of any
 * other score — which is why Document 4 §8 requires these to be unmissable in
 * the UI.
 */
export interface CriticalFinding {
  finding_id: string;
  dimension: string;
  type: string;
  severity: Severity;
  description: string;
  evidence_refs: string[];
  centrality: number | null;
}

/** Engine descriptor and run metadata (Document 2, §6.5). */
export interface AuditResultMetadata {
  dimension: string;
  engine_id: string;
  dimension_type: DimensionType;
  critical_finding_capability: CriticalFindingCapability;
  supports_na: boolean;
  applicable: boolean;
  applicability_reason: string;
}

/** The frozen seven-field AuditResult contract (Document 2, §6.5). */
export interface AuditResult {
  score: Score;
  confidence: number;
  ledger: LedgerEntry[];
  evidence: EvidenceItem[];
  recommendations: Recommendation[];
  critical_findings: CriticalFinding[];
  metadata: AuditResultMetadata;
}

/** The trust axis, always carrying its reason (Document 3, §6 and §12). */
export interface TrustVerdict {
  verdict: TrustOutcome;
  reason: string;
  evidence_refs: string[];
  gating_finding_ids: string[];
}

/** The quality axis, reported independently of trust (Document 3, §7). */
export interface QualityVerdict {
  band: QualityBand;
  score: number | null;
  drivers: string[];
  excluded_dimensions: string[];
}

/** Per-dimension and overall confidence state (Document 3, §12). */
export interface ConfidenceReport {
  overall: number;
  per_dimension: Record<string, number>;
  unable_to_verify_rationale: string | null;
  low_confidence_dimensions: string[];
}

/** One entry in the merged, ordered action list (Document 3, §10). */
export interface PrioritizedRecommendation {
  priority: RecommendationPriority;
  dimension: string;
  text: string;
  evidence_refs: string[];
  source_severity: Severity;
}

/**
 * The Final Audit Report (Document 3, §12) — the frontend's only contract.
 *
 * Note that `trust_verdict` and `quality_verdict` are separate fields and must
 * stay separate in the UI. Document 3 §7 guarantees two-axis clarity: content
 * can be high-quality yet Untrusted, and blending them into one number would
 * destroy the distinction the whole system exists to draw.
 */
/**
 * One row of Document 3 §12's Dimension Results section: the flat projection of
 * an AuditResult, plus the Decision Engine's one-line reading of it.
 *
 * N/A dimensions appear here explicitly as excluded, never omitted.
 */
export interface DimensionSummary {
  dimension: string;
  dimension_type: DimensionType;
  score: Score;
  confidence: number;
  rationale: string;
  applicable: boolean;
  applicability_reason: string;
}

export interface AuditReport {
  audit_id: string;
  generated_at: string;
  overall_verdict: OverallVerdict;
  trust_verdict: TrustVerdict;
  quality_verdict: QualityVerdict;
  summary: string;
  confidence: ConfidenceReport;
  critical_findings: CriticalFinding[];
  dimension_results: AuditResult[];
  dimension_summaries: DimensionSummary[];
  recommendations: PrioritizedRecommendation[];
  input_type: InputType;
  source_uri: string | null;
}

/** Optional request flags (Document 4, §7). */
export interface AuditOptions {
  external_retrieval?: boolean;
}

/** `POST /audit` — exactly one of `text` or `url`. */
export interface AuditRequest {
  text?: string;
  url?: string;
  prompt?: string | null;
  reference_source?: string | null;
  options?: AuditOptions;
}

/** Async creation response (Document 4, §7). */
export interface AuditCreatedResponse {
  audit_id: string;
  status: JobStatus;
}

/** `GET /audit/{id}/status` (Document 4, §7). */
export interface AuditStatusResponse {
  audit_id: string;
  status: JobStatus;
  engines_completed: number;
  engines_total: number;
  error: string | null;
}

/** `GET /health` (Document 4, §7). */
export interface HealthResponse {
  status: string;
  llm_provider: string;
  version: string;
  llm_model?: string | null;
  llm_configured?: boolean | null;
  llm_reachable?: boolean | null;
  engines_registered?: number | null;
  embedding_model?: string | null;
  embedding_cache_enabled?: boolean | null;
  embedding_cache_hit_rate?: number | null;
}

/** The frozen error contract (Document 4, §7). */
export interface ErrorResponse {
  error: { code: string; message: string };
}
