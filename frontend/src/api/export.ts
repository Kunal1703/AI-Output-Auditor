/**
 * Report export — JSON and Markdown (Document 4, §8: "Export Report").
 *
 * Both formats are projections of the report the backend produced. **Nothing
 * here computes or re-derives a verdict** (Document 4, §5) — the Markdown is
 * the same facts in a form you can paste into a review, and the JSON is the
 * report verbatim.
 *
 * Document 4 §2 puts server-side PDF behind "optional ... via existing doc
 * tooling". JSON and Markdown cover the actual need — archiving a result and
 * pasting it into a ticket — without adding a rendering dependency to a
 * frontend that has none.
 */

import { formatConfidence, formatScore } from './client';
import type { AuditReport } from './types';

/** Trigger a browser download of `content` as `filename`. */
function download(filename: string, content: string, mime: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  // Revoking immediately can cancel the download in some browsers; a tick is
  // enough for the click to have been handled.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** Export the report as JSON — the complete contract, verbatim. */
export function exportJson(report: AuditReport): void {
  download(
    `audit-${report.audit_id}.json`,
    JSON.stringify(report, null, 2),
    'application/json',
  );
}

/**
 * Render the report as Markdown.
 *
 * Ordered the way the report reads: verdict → reasons → evidence → actions
 * (Document 3, §12). Trust and Quality stay in separate sections, because
 * fusing them in the export would undo the guarantee the whole system is built
 * to hold.
 */
export function toMarkdown(report: AuditReport): string {
  const lines: string[] = [];

  lines.push(`# Audit report — ${report.overall_verdict}`);
  lines.push('');
  lines.push(`- **Audit id:** \`${report.audit_id}\``);
  lines.push(`- **Generated:** ${new Date(report.generated_at).toISOString()}`);
  lines.push(`- **Input:** ${report.input_type}${report.source_uri ? ` — ${report.source_uri}` : ''}`);
  lines.push(`- **Overall confidence:** ${formatConfidence(report.confidence.overall)}`);
  lines.push('');
  lines.push(report.summary);
  lines.push('');

  lines.push('## Trust verdict (non-compensatory)');
  lines.push('');
  lines.push(`**${report.trust_verdict.verdict}**`);
  lines.push('');
  lines.push(report.trust_verdict.reason);
  if (report.trust_verdict.gating_finding_ids.length > 0) {
    lines.push('');
    lines.push(
      `Gated by: ${report.trust_verdict.gating_finding_ids.join(', ')}`,
    );
  }
  lines.push('');

  lines.push('## Quality verdict (compensatory)');
  lines.push('');
  const band = report.quality_verdict.score !== null
    ? `**${report.quality_verdict.band}** (${Math.round(report.quality_verdict.score * 100)}%)`
    : `**${report.quality_verdict.band}** — no quality dimension could be scored`;
  lines.push(band);
  if (report.quality_verdict.drivers.length > 0) {
    lines.push('');
    for (const driver of report.quality_verdict.drivers) lines.push(`- ${driver}`);
  }
  if (report.quality_verdict.excluded_dimensions.length > 0) {
    lines.push('');
    lines.push(
      `Excluded as not applicable: ${report.quality_verdict.excluded_dimensions.join(', ')}`,
    );
  }
  lines.push('');

  if (report.critical_findings.length > 0) {
    lines.push(`## Critical findings (${report.critical_findings.length})`);
    lines.push('');
    for (const finding of report.critical_findings) {
      lines.push(
        `### ${finding.type} — ${finding.severity} (${finding.dimension})`,
      );
      lines.push('');
      lines.push(finding.description);
      lines.push('');
      lines.push(`Evidence: ${finding.evidence_refs.join(', ') || 'none'}`);
      lines.push('');
    }
  }

  lines.push('## Dimension results');
  lines.push('');
  lines.push('| Dimension | Type | Score | Confidence | Why |');
  lines.push('|---|---|---|---|---|');
  for (const result of report.dimension_results) {
    const meta = result.metadata;
    const summary = report.dimension_summaries.find(
      (s) => s.dimension === meta.dimension,
    );
    const why = (summary?.rationale ?? '').replace(/\|/g, '\\|');
    lines.push(
      `| ${meta.dimension} | ${meta.dimension_type} | ${formatScore(result.score)} | ` +
        `${formatConfidence(result.confidence)} | ${why} |`,
    );
  }
  lines.push('');

  if (report.recommendations.length > 0) {
    lines.push('## Recommendations');
    lines.push('');
    for (const rec of report.recommendations) {
      lines.push(
        `- **${rec.priority}** (${rec.dimension}) — ${rec.text} ` +
          `_[evidence: ${rec.evidence_refs.join(', ')}]_`,
      );
    }
    lines.push('');
  }

  lines.push('## Evidence');
  lines.push('');
  for (const result of report.dimension_results) {
    if (result.evidence.length === 0) continue;
    lines.push(`### ${result.metadata.dimension}`);
    lines.push('');
    for (const item of result.evidence) {
      const where = item.locator ? ` _(${item.locator})_` : '';
      const source = item.source_ref ? ` — source: ${item.source_ref}` : '';
      lines.push(`- \`${item.evidence_id}\` **${item.kind}**${where}${source}`);
      lines.push(`  > ${item.content.replace(/\n/g, '\n  > ')}`);
    }
    lines.push('');
  }

  lines.push('## Confidence');
  lines.push('');
  for (const [dimension, value] of Object.entries(report.confidence.per_dimension)) {
    lines.push(`- ${dimension}: ${formatConfidence(value)}`);
  }
  if (report.confidence.unable_to_verify_rationale) {
    lines.push('');
    lines.push(`**Unable to verify:** ${report.confidence.unable_to_verify_rationale}`);
  }
  lines.push('');
  lines.push('---');
  lines.push('');
  lines.push('_Generated by the AI Trust & Quality Auditor._');

  return lines.join('\n');
}

/** Export the report as Markdown. */
export function exportMarkdown(report: AuditReport): void {
  download(`audit-${report.audit_id}.md`, toMarkdown(report), 'text/markdown');
}
