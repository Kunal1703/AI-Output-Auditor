/**
 * ResultsPage — the Results Dashboard.
 *
 * Document 4 §8: Results Dashboard → Dimension Cards → Evidence Viewer →
 * Recommendations → Export Report.
 *
 * A report reaches this page one of two ways: handed over in router state by
 * `AuditPage` right after an audit, or fetched by `audit_id` from the URL
 * (`/results/:auditId`) so a report can be linked to and shared.
 */

import { useEffect, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import ReportPanel from '@/components/ReportPanel';
import LoadingState from '@/components/LoadingState';
import { ApiError, getReport } from '@/api/client';
import type { AuditReport } from '@/api/types';

/** The results dashboard. */
export default function ResultsPage() {
  const { auditId } = useParams<{ auditId?: string }>();
  const location = useLocation();
  const handedOver = (location.state as { report?: AuditReport } | null)?.report;

  const [report, setReport] = useState<AuditReport | null>(handedOver ?? null);
  const [loading, setLoading] = useState(Boolean(auditId) && !handedOver);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!auditId || handedOver) return;
    let cancelled = false;
    setLoading(true);
    getReport(auditId)
      .then((r) => !cancelled && setReport(r))
      .catch((cause) => {
        if (cancelled) return;
        setError(
          cause instanceof ApiError
            ? cause.message
            : 'Could not load the report.',
        );
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [auditId, handedOver]);

  if (loading) {
    return <div className="pt-4"><LoadingState message="Loading report…" /></div>;
  }

  if (error) {
    return (
      <div className="pt-4">
        <div className="rounded-lg border border-verdict-untrusted/40 bg-verdict-untrusted/10 p-5">
          <p className="text-sm font-medium text-verdict-untrusted">
            Report unavailable
          </p>
          <p className="mt-1 text-sm text-slate-400">{error}</p>
        </div>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="pt-4">
        <div className="grid place-items-center rounded-lg border border-dashed border-slate-800 py-20 text-center">
          <p className="text-sm text-slate-400">No report to show yet.</p>
          <p className="mt-1 text-xs text-slate-600">
            Run an audit, or open a report by id at{' '}
            <code className="font-mono">/results/&lt;audit_id&gt;</code>.
          </p>
          <Link
            to="/audit"
            className="mt-5 rounded bg-trust-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-trust-500"
          >
            Start an audit
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between pt-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Audit report</h1>
          <p className="mt-1 font-mono text-xs text-slate-600">
            {report.audit_id} · {new Date(report.generated_at).toLocaleString()}
          </p>
        </div>
        <button
          type="button"
          disabled
          title="Export lands in Milestone 2, with the evidence it exports."
          className="rounded border border-slate-800 px-4 py-2 text-sm text-slate-600"
        >
          Export report
        </button>
      </header>

      <ReportPanel report={report} />
    </div>
  );
}
