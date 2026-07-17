/**
 * AuditPage — input selection and audit progress.
 *
 * Document 4 §8 steps: Input Selection → Audit Progress → Results Dashboard.
 *
 * Uses the **async create-and-poll** flow: `POST /audit/{text,url}` returns an
 * `audit_id` immediately, and the page polls `GET /audit/{id}/status` until the
 * report is ready. That is what lets `LoadingState` show real engine completion
 * rather than a decorative spinner (Document 4, §8: "Progress is real").
 *
 * The synchronous `POST /audit` still exists and is the right call for a
 * script. It is the wrong call for a browser: a full audit makes many LLM calls
 * and would hold the connection open for minutes with nothing to show.
 */

import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import InputPanel from '@/components/InputPanel';
import LoadingState from '@/components/LoadingState';
import {
  ApiError,
  auditFile,
  auditText,
  auditUrl,
  pollUntilComplete,
} from '@/api/client';
import type {
  AuditCreatedResponse,
  AuditRequest,
  AuditStatusResponse,
} from '@/api/types';

/** The audit submission page. */
export default function AuditPage() {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; auditId?: string } | null>(
    null,
  );
  const [status, setStatus] = useState<AuditStatusResponse | null>(null);
  const abort = useRef<AbortController | null>(null);

  // Stop polling if the user navigates away mid-audit. Without this the loop
  // keeps running and calls setState on an unmounted component.
  useEffect(() => () => abort.current?.abort(), []);

  /** Create the job, poll it to completion, and hand the report on. */
  async function run(create: () => Promise<AuditCreatedResponse>) {
    setBusy(true);
    setError(null);
    setStatus(null);

    const controller = new AbortController();
    abort.current = controller;

    try {
      const created = await create();
      const report = await pollUntilComplete(
        created.audit_id,
        setStatus,
        controller.signal,
      );

      // Hand the report to the Results page via router state rather than
      // refetching it there — the backend already sent it once, and the id is
      // in the URL for anyone who wants to reload.
      navigate(`/results/${created.audit_id}`, { state: { report } });
    } catch (cause) {
      if (cause instanceof ApiError && cause.code === 'aborted') {
        return; // the user navigated away; nothing to report
      }
      setError({
        message:
          cause instanceof ApiError
            ? cause.message
            : 'The audit failed for an unknown reason.',
        auditId:
          cause instanceof ApiError && cause.code === 'poll_timeout'
            ? status?.audit_id
            : undefined,
      });
    } finally {
      abort.current = null;
      setBusy(false);
    }
  }

  const handleSubmit = (request: AuditRequest) =>
    run(() => (request.url ? auditUrl(request) : auditText(request)));

  const handleSubmitFile = (file: File, prompt?: string, reference?: string) =>
    run(() => auditFile(file, prompt, reference));

  return (
    <div className="space-y-6">
      <header className="pt-4">
        <h1 className="text-2xl font-bold text-slate-100">New audit</h1>
        <p className="mt-1.5 text-sm text-slate-400">
          Submit AI-generated content as text, a URL, or a file. The optional
          prompt and reference source unlock dimensions that need them.
        </p>
      </header>

      {error && (
        <div
          role="alert"
          className="rounded-lg border border-verdict-untrusted/40 bg-verdict-untrusted/10 p-4"
        >
          <p className="text-sm font-medium text-verdict-untrusted">
            Audit failed
          </p>
          <p className="mt-1 text-sm text-slate-400">{error.message}</p>
          {error.auditId && (
            <p className="mt-2 font-mono text-xs text-slate-500">
              audit id: {error.auditId}
            </p>
          )}
        </div>
      )}

      {busy ? (
        <LoadingState
          enginesCompleted={status?.engines_completed ?? 0}
          enginesTotal={status?.engines_total ?? 8}
          message={
            status?.status === 'queued'
              ? 'Queued — preparing the run…'
              : 'Running the audit engines…'
          }
        />
      ) : (
        <InputPanel
          onSubmit={handleSubmit}
          onSubmitFile={handleSubmitFile}
          busy={busy}
        />
      )}
    </div>
  );
}
