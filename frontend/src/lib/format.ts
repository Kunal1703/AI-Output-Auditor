/**
 * Display helpers — the single source of truth for how backend vocabulary is
 * rendered: labels, colors (semantic Tailwind tokens), icons, and descriptions.
 *
 * Keeping this here means a verdict color or a metric's friendly name is defined
 * once and every card, badge, and chart agrees.
 */

import type {
  FindingSeverity,
  FindingType,
  MetricResult,
  OutputAudit,
  Producer,
  RecommendationPriority,
  SupportLabel,
  VerdictBand,
} from '@/api/auditor-types';

/* ----------------------------- audit accessors ----------------------------- */

/** Every metric result on an output, in layer order. */
export function allMetrics(audit: OutputAudit): MetricResult[] {
  return [
    ...audit.layer_results.layer_1,
    ...audit.layer_results.layer_2,
    ...audit.layer_results.layer_3,
  ];
}

/** One metric's result on an output, by metric_id. */
export function findMetric(audit: OutputAudit, id: string): MetricResult | undefined {
  return allMetrics(audit).find((m) => m.metric_id === id);
}

/** One metric's score on an output, or null. */
export function metricScore(audit: OutputAudit, id: string): number | null {
  return findMetric(audit, id)?.score ?? null;
}

/* --------------------------------- verdicts -------------------------------- */

export interface VerdictStyle {
  label: string;
  /** Tailwind text-color token, e.g. `text-verdict-fail`. */
  text: string;
  /** Tailwind bg token for soft fills. */
  soft: string;
  ring: string;
  dot: string;
  /** lucide icon name key (mapped in components). */
  icon: 'check-circle' | 'thumbs-up' | 'pencil' | 'x-octagon' | 'help-circle';
  blurb: string;
}

export const VERDICTS: Record<VerdictBand, VerdictStyle> = {
  Excellent: {
    label: 'Excellent',
    text: 'text-verdict-excellent',
    soft: 'bg-verdict-excellent/10',
    ring: 'ring-verdict-excellent/30',
    dot: 'bg-verdict-excellent',
    icon: 'check-circle',
    blurb: 'Faithful, complete, and well-presented.',
  },
  Good: {
    label: 'Good',
    text: 'text-verdict-good',
    soft: 'bg-verdict-good/10',
    ring: 'ring-verdict-good/30',
    dot: 'bg-verdict-good',
    icon: 'thumbs-up',
    blurb: 'Solid, with minor room to improve.',
  },
  'Needs Revision': {
    label: 'Needs Revision',
    text: 'text-verdict-revision',
    soft: 'bg-verdict-revision/10',
    ring: 'ring-verdict-revision/30',
    dot: 'bg-verdict-revision',
    icon: 'pencil',
    blurb: 'A grounding or coverage gap caps the verdict.',
  },
  Fail: {
    label: 'Fail',
    text: 'text-verdict-fail',
    soft: 'bg-verdict-fail/10',
    ring: 'ring-verdict-fail/30',
    dot: 'bg-verdict-fail',
    icon: 'x-octagon',
    blurb: 'A critical grounding failure — not trustworthy.',
  },
  'Unable to Verify': {
    label: 'Unable to Verify',
    text: 'text-verdict-unverified',
    soft: 'bg-verdict-unverified/10',
    ring: 'ring-verdict-unverified/30',
    dot: 'bg-verdict-unverified',
    icon: 'help-circle',
    blurb: 'Grounding could not be established with confidence.',
  },
};

/* -------------------------------- severity --------------------------------- */

export interface SeverityStyle {
  label: string;
  text: string;
  soft: string;
  border: string;
  dot: string;
}

export const SEVERITIES: Record<FindingSeverity, SeverityStyle> = {
  critical: {
    label: 'Critical',
    text: 'text-severity-critical',
    soft: 'bg-severity-critical/10',
    border: 'border-severity-critical/30',
    dot: 'bg-severity-critical',
  },
  major: {
    label: 'Major',
    text: 'text-severity-major',
    soft: 'bg-severity-major/10',
    border: 'border-severity-major/30',
    dot: 'bg-severity-major',
  },
  minor: {
    label: 'Minor',
    text: 'text-severity-minor',
    soft: 'bg-severity-minor/10',
    border: 'border-severity-minor/30',
    dot: 'bg-severity-minor',
  },
};

export const SEVERITY_ORDER: FindingSeverity[] = ['critical', 'major', 'minor'];

/* ------------------------------ recommendations ---------------------------- */

export const PRIORITY_STYLE: Record<
  RecommendationPriority,
  { text: string; soft: string; dot: string }
> = {
  Critical: { text: 'text-severity-critical', soft: 'bg-severity-critical/10', dot: 'bg-severity-critical' },
  High: { text: 'text-severity-major', soft: 'bg-severity-major/10', dot: 'bg-severity-major' },
  Medium: { text: 'text-verdict-good', soft: 'bg-verdict-good/10', dot: 'bg-verdict-good' },
  Low: { text: 'text-content-subtle', soft: 'bg-content-subtle/10', dot: 'bg-content-subtle' },
};

/* --------------------------------- metrics --------------------------------- */

export interface MetricMeta {
  label: string;
  short: string;
  /** lucide icon name key (mapped in components). */
  icon: string;
  layer: 1 | 2 | 3;
  blurb: string;
}

/** Friendly metadata for each metric_id the backend emits. */
export const METRICS: Record<string, MetricMeta> = {
  Faithfulness: {
    label: 'Faithfulness',
    short: 'Faithful',
    icon: 'shield-check',
    layer: 1,
    blurb: 'Every claim is supported by the source, with nothing fabricated.',
  },
  'Factual & Numeric Accuracy': {
    label: 'Numeric Accuracy',
    short: 'Numeric',
    icon: 'hash',
    layer: 1,
    blurb: 'Figures, dates, and quantities match the source exactly.',
  },
  Coverage: {
    label: 'Coverage',
    short: 'Coverage',
    icon: 'layers',
    layer: 2,
    blurb: 'The output captures the source’s important information.',
  },
  'Meaning Preservation': {
    label: 'Meaning',
    short: 'Meaning',
    icon: 'git-compare',
    layer: 2,
    blurb: 'The source’s overall meaning and emphasis are preserved.',
  },
  'Readability & Coherence': {
    label: 'Readability',
    short: 'Readability',
    icon: 'book-open',
    layer: 3,
    blurb: 'Clear, coherent, and fluent for its reader.',
  },
  'Conciseness / Non-Redundancy': {
    label: 'Conciseness',
    short: 'Concise',
    icon: 'scissors',
    layer: 3,
    blurb: 'Efficient — free of unnecessary repetition.',
  },
  'Bias / Objectivity': {
    label: 'Objectivity',
    short: 'Objectivity',
    icon: 'scale',
    layer: 3,
    blurb: 'No slant or framing introduced beyond the source.',
  },
};

export function metricMeta(id: string): MetricMeta {
  return (
    METRICS[id] ?? {
      label: id,
      short: id,
      icon: 'circle-dot',
      layer: 3,
      blurb: '',
    }
  );
}

export const LAYER_NAMES: Record<1 | 2 | 3, string> = {
  1: 'Grounding',
  2: 'Information Quality',
  3: 'Presentation',
};

/* ------------------------------- finding types ----------------------------- */

export const FINDING_LABELS: Record<FindingType, string> = {
  intrinsic_hallucination: 'Intrinsic hallucination',
  extrinsic_hallucination: 'Extrinsic hallucination',
  numeric_error: 'Numeric error',
  contradiction: 'Contradiction',
  unsupported_claim: 'Unsupported claim',
  unsupported_inference: 'Unsupported inference',
  missing_critical_fact: 'Missing critical fact',
  meaning_distortion: 'Meaning distortion',
  context_loss: 'Context loss',
  introduced_bias: 'Introduced bias',
  redundancy: 'Redundancy',
  readability_issue: 'Readability issue',
  structure_issue: 'Structure issue',
};

/* -------------------------------- support ---------------------------------- */

export const SUPPORT_STYLE: Record<
  SupportLabel,
  { label: string; text: string; soft: string; dot: string }
> = {
  supported: { label: 'Supported', text: 'text-verdict-excellent', soft: 'bg-verdict-excellent/10', dot: 'bg-verdict-excellent' },
  partial: { label: 'Partial', text: 'text-verdict-unverified', soft: 'bg-verdict-unverified/10', dot: 'bg-verdict-unverified' },
  not_found: { label: 'Not found', text: 'text-verdict-fail', soft: 'bg-verdict-fail/10', dot: 'bg-verdict-fail' },
};

/* -------------------------------- producer --------------------------------- */

export const PRODUCER_STYLE: Record<
  Producer,
  { label: string; icon: 'user' | 'bot' | 'circle-help' }
> = {
  human: { label: 'Human', icon: 'user' },
  llm: { label: 'LLM', icon: 'bot' },
  unknown: { label: 'Unknown', icon: 'circle-help' },
};

/* --------------------------------- numbers --------------------------------- */

export function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return `${Math.round(value * 100)}%`;
}

/** Map a 0–1 score to a semantic color token for bars/gauges. */
export function scoreToken(score: number | null | undefined): string {
  if (score === null || score === undefined) return 'text-content-subtle';
  if (score >= 0.85) return 'text-verdict-excellent';
  if (score >= 0.65) return 'text-verdict-good';
  if (score >= 0.4) return 'text-verdict-revision';
  return 'text-verdict-fail';
}

export function scoreBarColor(score: number | null | undefined): string {
  if (score === null || score === undefined) return 'bg-content-subtle';
  if (score >= 0.85) return 'bg-verdict-excellent';
  if (score >= 0.65) return 'bg-verdict-good';
  if (score >= 0.4) return 'bg-verdict-revision';
  return 'bg-verdict-fail';
}

export function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}
