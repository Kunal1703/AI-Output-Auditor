/**
 * EvidenceViewer — drill from a finding or recommendation to the evidence.
 *
 * Document 4 §8: "Everything is traceable. Every score, finding, and
 * recommendation is clickable through to its evidence in the Evidence Viewer."
 *
 * This component is where the system's first principle stops being an
 * architectural claim and becomes something a reader can check. The backend
 * guarantees every finding carries resolvable `evidence_refs`; this resolves
 * them against the report's own `dimension_results` and shows what they point
 * at. Nothing is computed here — the evidence was collected by the engines and
 * carried through the report verbatim.
 *
 * A ref that does not resolve is shown as a broken pointer rather than hidden.
 * Silently dropping it would turn a traceability defect into an invisible one,
 * and the whole point of this panel is that the reader can tell.
 */

import { useMemo } from 'react';
import type { AuditReport, EvidenceItem } from '@/api/types';

interface EvidenceViewerProps {
  /** The report to resolve refs against. */
  report: AuditReport;
  /** The evidence ids to show. */
  evidenceRefs: string[];
  /** What the evidence supports, for the panel heading. */
  title: string;
  /** Close handler. */
  onClose: () => void;
}

/** Human labels for the evidence kinds the engines record. */
const KIND_LABELS: Record<string, string> = {
  output_span: 'Span of the audited output',
  reference_passage: 'Passage from the reference source',
  retrieved_source: 'Retrieved source',
  validator_result: 'Deterministic check',
  prompt_span: 'Span of the prompt',
  judge_rationale: "Judge's reasoning",
};

/** Parse `kind[i]@start:end` into a readable range. */
function formatLocator(locator: string | null): string | null {
  if (!locator) return null;
  const at = locator.indexOf('@');
  if (at === -1) return locator;
  return `characters ${locator.slice(at + 1)}`;
}

/** A modal panel showing the evidence behind one finding or recommendation. */
export default function EvidenceViewer({
  report,
  evidenceRefs,
  title,
  onClose,
}: EvidenceViewerProps) {
  // Index every evidence item in the report once, then resolve. The report
  // carries the full AuditResults precisely so this is possible client-side.
  const { resolved, dangling } = useMemo(() => {
    const index = new Map<string, EvidenceItem>();
    for (const result of report.dimension_results) {
      for (const item of result.evidence) index.set(item.evidence_id, item);
    }
    const found: EvidenceItem[] = [];
    const missing: string[] = [];
    for (const ref of evidenceRefs) {
      const item = index.get(ref);
      if (item) found.push(item);
      else missing.push(ref);
    }
    return { resolved: found, dangling: missing };
  }, [report, evidenceRefs]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 sm:p-8"
      role="dialog"
      aria-modal="true"
      aria-label={`Evidence for ${title}`}
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl rounded-lg border border-slate-700 bg-slate-900 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-4 border-b border-slate-800 p-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Evidence
            </p>
            <h3 className="mt-1 text-sm font-medium text-slate-200">{title}</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close evidence viewer"
            className="rounded border border-slate-700 px-2.5 py-1 text-xs text-slate-400 transition hover:border-slate-600 hover:text-slate-200"
          >
            Close
          </button>
        </header>

        <div className="space-y-4 p-5">
          {resolved.length === 0 && dangling.length === 0 && (
            <p className="text-sm text-slate-500">
              No evidence was attached. The backend drops findings and
              recommendations that carry none, so this should not happen.
            </p>
          )}

          {resolved.map((item) => (
            <article
              key={item.evidence_id}
              className="rounded border border-slate-800 bg-slate-950 p-4"
            >
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                  {item.evidence_id}
                </span>
                <span className="text-xs font-medium text-slate-300">
                  {KIND_LABELS[item.kind] ?? item.kind}
                </span>
                <span className="text-xs text-slate-600">·</span>
                <span className="text-xs text-slate-500">{item.dimension}</span>
              </div>

              <blockquote className="whitespace-pre-wrap border-l-2 border-trust-700 pl-3 text-sm leading-relaxed text-slate-300">
                {item.content}
              </blockquote>

              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
                {formatLocator(item.locator) && (
                  <span>{formatLocator(item.locator)}</span>
                )}
                {item.source_ref && (
                  <span className="truncate">
                    source:{' '}
                    {item.source_ref.startsWith('http') ? (
                      <a
                        href={item.source_ref}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="text-trust-400 underline decoration-dotted hover:text-trust-300"
                      >
                        {item.source_ref}
                      </a>
                    ) : (
                      item.source_ref
                    )}
                  </span>
                )}
              </div>
            </article>
          ))}

          {dangling.length > 0 && (
            <div className="rounded border border-verdict-untrusted/40 bg-verdict-untrusted/10 p-3">
              <p className="text-xs font-medium text-verdict-untrusted">
                {dangling.length} evidence reference
                {dangling.length === 1 ? '' : 's'} could not be resolved
              </p>
              <p className="mt-1 font-mono text-xs text-slate-500">
                {dangling.join(', ')}
              </p>
              <p className="mt-1.5 text-xs text-slate-500">
                This is a traceability defect, shown rather than hidden.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
