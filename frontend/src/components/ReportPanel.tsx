/**
 * ReportPanel — renders the Final Audit Report.
 *
 * Document 4 §8 sets five UX requirements that this component exists to honor,
 * and each one is a rendering constraint rather than a style preference:
 *
 * - **Verdict first, then reasons.** Lead with the Overall Verdict, then the
 *   separate Trust and Quality verdicts, then let the user drill down.
 * - **Two-axis clarity.** Trust and Quality are visually distinct and never a
 *   single blended number (Document 3, §7's separation guarantee).
 * - **Critical findings are unmissable.** Surfaced prominently, colored by
 *   severity — a fabricated citation must not be something you scroll past.
 * - **Everything is traceable.** Every score, finding, and recommendation is
 *   clickable through to its evidence.
 * - **Honest uncertainty is visible.** *Unable to Verify* and low-confidence
 *   dimensions are shown plainly, not hidden or rounded away.
 *
 * The panel renders; it never computes. Document 4 §5: the frontend "must NOT
 * compute verdicts or scores". Every value here was decided by the Decision
 * Engine.
 *
 * @remarks
 * The verdict banners, the dimension table, and the per-dimension rationale are
 * driven entirely by the report the Decision Engine produced. The Evidence
 * Viewer drill-through and report export land in Milestone 6.
 */

import { useState } from 'react';
import EvidenceViewer from '@/components/EvidenceViewer';
import { formatConfidence, formatScore } from '@/api/client';
import type {
  AuditReport,
  DimensionType,
  OverallVerdict,
  Severity,
} from '@/api/types';

/** What the Evidence Viewer is currently showing. */
interface EvidenceTarget {
  title: string;
  refs: string[];
}

interface ReportPanelProps {
  report: AuditReport;
}

/** Verdict → color. Semantic, not decorative (Document 3, §11). */
const VERDICT_STYLES: Record<OverallVerdict, string> = {
  Trusted: 'border-verdict-trusted/40 bg-verdict-trusted/10 text-verdict-trusted',
  'Trusted with Caveats':
    'border-verdict-caveats/40 bg-verdict-caveats/10 text-verdict-caveats',
  'Needs Revision':
    'border-verdict-revision/40 bg-verdict-revision/10 text-verdict-revision',
  Untrusted:
    'border-verdict-untrusted/40 bg-verdict-untrusted/10 text-verdict-untrusted',
  // Deliberately a different hue from Untrusted: "we could not check" is not
  // "we found a problem", and the two must never look alike.
  'Unable to Verify':
    'border-verdict-unverified/40 bg-verdict-unverified/10 text-verdict-unverified',
};

const SEVERITY_STYLES: Record<Severity, string> = {
  critical: 'bg-severity-critical/15 text-severity-critical border-severity-critical/30',
  high: 'bg-severity-high/15 text-severity-high border-severity-high/30',
  medium: 'bg-severity-medium/15 text-severity-medium border-severity-medium/30',
  low: 'bg-severity-low/15 text-severity-low border-severity-low/30',
  info: 'bg-severity-info/15 text-severity-info border-severity-info/30',
};

/** Priority → colour. Critical must not look like polish (Document 3, §10). */
const PRIORITY_STYLES: Record<string, string> = {
  Critical: 'border-severity-critical/40 bg-severity-critical/15 text-severity-critical',
  High: 'border-severity-high/40 bg-severity-high/15 text-severity-high',
  Medium: 'border-severity-medium/40 bg-severity-medium/15 text-severity-medium',
  Low: 'border-slate-700 bg-slate-800/50 text-slate-400',
};

const TYPE_STYLES: Record<DimensionType, string> = {
  Trust: 'bg-trust-900/40 text-trust-100 border-trust-700/50',
  Quality: 'bg-quality-700/20 text-quality-100 border-quality-700/50',
  Hybrid: 'bg-slate-700/40 text-slate-200 border-slate-600/50',
};

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
      <h3 className="mb-4 text-xs font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </h3>
      {children}
    </section>
  );
}

/** Renders a complete Final Audit Report. */
export default function ReportPanel({ report }: ReportPanelProps) {
  const [evidence, setEvidence] = useState<EvidenceTarget | null>(null);

  return (
    <div className="space-y-5">
      {/* Verdict first (Document 4, §8). */}
      <div
        className={`rounded-lg border p-6 ${VERDICT_STYLES[report.overall_verdict]}`}
      >
        <p className="text-xs font-semibold uppercase tracking-wide opacity-70">
          Overall verdict
        </p>
        <p className="mt-1 text-3xl font-bold">{report.overall_verdict}</p>
        <p className="mt-3 max-w-3xl text-sm leading-relaxed text-slate-300">
          {report.summary}
        </p>
      </div>

      {/* Two axes, side by side and never fused (Document 3, §7). */}
      <div className="grid gap-5 md:grid-cols-2">
        <Section title="Trust verdict · non-compensatory">
          <p className="text-xl font-semibold text-slate-100">
            {report.trust_verdict.verdict}
          </p>
          <p className="mt-2 text-sm leading-relaxed text-slate-400">
            {report.trust_verdict.reason}
          </p>
          {report.trust_verdict.gating_finding_ids.length > 0 && (
            <p className="mt-3 text-xs text-verdict-untrusted">
              Gated by {report.trust_verdict.gating_finding_ids.length} critical
              finding(s).
            </p>
          )}
        </Section>

        <Section title="Quality verdict · compensatory">
          <div className="flex items-baseline gap-3">
            <p className="text-xl font-semibold text-slate-100">
              {report.quality_verdict.band}
            </p>
            {report.quality_verdict.score !== null && (
              <span className="font-mono text-sm text-slate-500">
                {Math.round(report.quality_verdict.score * 100)}%
              </span>
            )}
          </div>
          {report.quality_verdict.drivers.length > 0 ? (
            <ul className="mt-2 space-y-1 text-sm text-slate-400">
              {report.quality_verdict.drivers.map((d) => (
                <li key={d}>· {d}</li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-slate-500">No drivers reported.</p>
          )}
          {report.quality_verdict.excluded_dimensions.length > 0 && (
            <p className="mt-3 text-xs text-slate-500">
              Excluded as N/A: {report.quality_verdict.excluded_dimensions.join(', ')}
            </p>
          )}
        </Section>
      </div>

      {/* Critical findings must be unmissable (Document 4, §8). */}
      {report.critical_findings.length > 0 && (
        <Section title={`Critical findings · ${report.critical_findings.length}`}>
          <ul className="space-y-3">
            {report.critical_findings.map((finding) => (
              <li
                key={finding.finding_id}
                className={`rounded border p-3 ${SEVERITY_STYLES[finding.severity]}`}
              >
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold">{finding.type}</span>
                  <span className="rounded bg-black/20 px-1.5 py-0.5 text-[10px] font-medium uppercase">
                    {finding.severity}
                  </span>
                  <span className="text-xs opacity-70">{finding.dimension}</span>
                </div>
                <p className="mt-1.5 text-sm text-slate-300">
                  {finding.description}
                </p>
                <button
                  type="button"
                  onClick={() =>
                    setEvidence({
                      title: `${finding.dimension} — ${finding.type}`,
                      refs: finding.evidence_refs,
                    })
                  }
                  className="mt-2 text-xs underline decoration-dotted opacity-80 transition hover:opacity-100"
                >
                  Show the evidence ({finding.evidence_refs.length})
                </button>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* Per-dimension results. N/A shown explicitly, never hidden. */}
      <Section title="Dimension results">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="pb-2 pr-4 font-medium">Dimension</th>
                <th className="pb-2 pr-4 font-medium">Type</th>
                <th className="pb-2 pr-4 font-medium">Score</th>
                <th className="pb-2 pr-4 font-medium">Confidence</th>
                <th className="pb-2 font-medium">Why</th>
              </tr>
            </thead>
            <tbody>
              {report.dimension_results.map((result) => {
                const meta = result.metadata;
                // Document 3 §12 requires a one-line rationale per row. It is
                // decided by the Decision Engine, never derived here — the
                // frontend renders what the backend concluded (Document 4 §5).
                const summary = report.dimension_summaries.find(
                  (s) => s.dimension === meta.dimension,
                );
                return (
                  <tr
                    key={meta.engine_id}
                    className="border-b border-slate-800/60 last:border-0"
                  >
                    <td className="py-2.5 pr-4 text-slate-200">
                      {meta.dimension}
                      {!meta.applicable && (
                        <span
                          className="ml-2 text-xs text-slate-500"
                          title={meta.applicability_reason}
                        >
                          not applicable
                        </span>
                      )}
                    </td>
                    <td className="py-2.5 pr-4">
                      <span
                        className={`rounded border px-1.5 py-0.5 text-[10px] font-medium ${TYPE_STYLES[meta.dimension_type]}`}
                      >
                        {meta.dimension_type}
                      </span>
                    </td>
                    <td className="py-2.5 pr-4 font-mono text-slate-300">
                      {formatScore(result.score)}
                    </td>
                    <td className="py-2.5 pr-4 font-mono text-slate-400">
                      {formatConfidence(result.confidence)}
                    </td>
                    <td className="py-2.5 text-xs text-slate-500">
                      {summary?.rationale ?? ''}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Section>

      {/* Honest uncertainty, stated plainly (Document 3, §8). */}
      <Section title="Confidence">
        <div className="flex items-baseline gap-3">
          <span className="text-xl font-semibold text-slate-100">
            {formatConfidence(report.confidence.overall)}
          </span>
          <span className="text-xs text-slate-500">overall</span>
        </div>
        {report.confidence.unable_to_verify_rationale && (
          <p className="mt-3 rounded border border-verdict-unverified/30 bg-verdict-unverified/10 p-3 text-sm text-slate-300">
            {report.confidence.unable_to_verify_rationale}
          </p>
        )}
        {report.confidence.low_confidence_dimensions.length > 0 && (
          <p className="mt-3 text-xs text-slate-500">
            Low confidence: {report.confidence.low_confidence_dimensions.join(', ')}
          </p>
        )}
      </Section>

      {/* Prioritized action list (Document 3, §10). */}
      <Section title="Recommendations">
        {report.recommendations.length > 0 ? (
          <ol className="space-y-2">
            {report.recommendations.map((rec, index) => (
              <li
                key={`${rec.dimension}-${index}`}
                className="flex flex-wrap items-start gap-x-3 gap-y-1.5 rounded border border-slate-800 p-3"
              >
                <span
                  className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase ${PRIORITY_STYLES[rec.priority]}`}
                >
                  {rec.priority}
                </span>
                <span className="min-w-0 flex-1 text-sm text-slate-300">
                  {rec.text}
                </span>
                <span className="text-xs text-slate-600">{rec.dimension}</span>
                <button
                  type="button"
                  onClick={() =>
                    setEvidence({
                      title: `${rec.dimension} — ${rec.priority} recommendation`,
                      refs: rec.evidence_refs,
                    })
                  }
                  className="basis-full text-left text-xs text-slate-500 underline decoration-dotted transition hover:text-slate-300"
                >
                  Show the evidence ({rec.evidence_refs.length})
                </button>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-sm text-slate-500">No recommendations.</p>
        )}
      </Section>

      {evidence && (
        <EvidenceViewer
          report={report}
          evidenceRefs={evidence.refs}
          title={evidence.title}
          onClose={() => setEvidence(null)}
        />
      )}
    </div>
  );
}
