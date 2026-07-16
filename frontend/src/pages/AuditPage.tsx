/**
 * AuditPage — input selection and audit progress.
 *
 * Document 4 §8 steps: Input Selection → Audit Progress → Results Dashboard.
 *
 * The page owns the submit-and-wait flow and hands the finished report to the
 * Results page. Today it uses the synchronous `POST /audit`; Milestone 2 swaps
 * in the async create-and-poll flow, at which point `LoadingState` receives
 * real `engines_completed` from `GET /audit/{id}/status`.
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import InputPanel from '@/components/InputPanel';
import LoadingState from '@/components/LoadingState';
import { ApiError, audit } from '@/api/client';
import type { AuditRequest } from '@/api/types';

/** The audit submission page. */
export default function AuditPage() {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(request: AuditRequest) {
    setBusy(true);
    setError(null);
    try {
      const report = await audit(request);
      // Hand the report to the Results page via router state rather than
      // refetching it there — the report is large, and the backend already
      // sent it once.
      navigate('/results', { state: { report } });
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : 'The audit failed for an unknown reason.',
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <header className="pt-4">
        <h1 className="text-2xl font-bold text-slate-100">New audit</h1>
        <p className="mt-1.5 text-sm text-slate-400">
          Submit AI-generated content as text or a URL. The optional prompt and
          reference source unlock dimensions that need them.
        </p>
      </header>

      {error && (
        <div className="rounded-lg border border-verdict-untrusted/40 bg-verdict-untrusted/10 p-4">
          <p className="text-sm font-medium text-verdict-untrusted">
            Audit failed
          </p>
          <p className="mt-1 text-sm text-slate-400">{error}</p>
        </div>
      )}

      {busy ? (
        <LoadingState message="Running the audit engines…" />
      ) : (
        <InputPanel onSubmit={handleSubmit} busy={busy} />
      )}

      <p className="text-xs text-slate-600">
        Milestone 1: the API contract and report shape are live, but the audit
        engines are not yet implemented — every audit returns{' '}
        <span className="text-slate-500">Unable to Verify</span> with nothing
        measured. That is the honest verdict for a system that has checked
        nothing, and it is what the engines will replace in Milestone 2.
      </p>
    </div>
  );
}
