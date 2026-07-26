/**
 * Audit store — the app's single source of truth for running audits and the
 * local history.
 *
 * `POST /audit/outputs` is synchronous, so `run()` awaits the real backend and
 * returns the `ComparativeReport`. Completed reports are persisted to
 * localStorage so the History page and shareable `/report/:id` links resolve
 * without a backend round-trip (there is no server-side report store yet).
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { ApiError, auditOutputs } from '@/api/auditor';
import type {
  AuditOutputsRequest,
  ComparativeReport,
  VerdictBand,
} from '@/api/auditor-types';

export interface HistoryItem {
  audit_id: string;
  generated_at: string;
  source_title: string;
  output_count: number;
  winner: string | null;
  verdicts: VerdictBand[];
}

/** Full source/output text, kept so the evidence explorer can highlight it. */
export interface AuditInputs {
  source: string | null;
  outputs: Record<string, string | null>; // output_id -> text
}

type Status = 'idle' | 'running' | 'done' | 'error';

interface AuditContextValue {
  status: Status;
  report: ComparativeReport | null;
  error: ApiError | null;
  history: HistoryItem[];
  run: (req: AuditOutputsRequest) => Promise<ComparativeReport>;
  getReport: (id: string) => ComparativeReport | null;
  getInputs: (id: string) => AuditInputs | null;
  clearHistory: () => void;
  reset: () => void;
}

const AuditContext = createContext<AuditContextValue | null>(null);

const HISTORY_KEY = 'veritas-history';
const REPORT_PREFIX = 'veritas-report-';
const INPUTS_PREFIX = 'veritas-inputs-';
const HISTORY_LIMIT = 20;

function loadHistory(): HistoryItem[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    return raw ? (JSON.parse(raw) as HistoryItem[]) : [];
  } catch {
    return [];
  }
}

function persist(report: ComparativeReport): HistoryItem[] {
  const item: HistoryItem = {
    audit_id: report.audit_id,
    generated_at: report.generated_at,
    source_title: report.source.title ?? 'Untitled source',
    output_count: report.outputs.length,
    winner: report.comparison.ranking[0] ?? null,
    verdicts: report.outputs.map((o) => o.verdict),
  };
  try {
    localStorage.setItem(REPORT_PREFIX + report.audit_id, JSON.stringify(report));
    const next = [item, ...loadHistory().filter((h) => h.audit_id !== item.audit_id)].slice(
      0,
      HISTORY_LIMIT,
    );
    localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
    return next;
  } catch {
    return loadHistory();
  }
}

export function AuditProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>('idle');
  const [report, setReport] = useState<ComparativeReport | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>(loadHistory);

  const run = useCallback(async (req: AuditOutputsRequest) => {
    setStatus('running');
    setError(null);
    try {
      const result = await auditOutputs(req);
      setReport(result);
      setHistory(persist(result));
      // Persist the full input text so the evidence explorer can highlight it
      // (the report itself carries only span snippets and source metadata).
      try {
        const inputs: AuditInputs = {
          source: req.source.text ?? null,
          outputs: Object.fromEntries(
            result.outputs.map((o, i) => [o.output_id, req.outputs[i]?.text ?? null]),
          ),
        };
        localStorage.setItem(INPUTS_PREFIX + result.audit_id, JSON.stringify(inputs));
      } catch {
        /* storage may be unavailable */
      }
      setStatus('done');
      return result;
    } catch (err) {
      const apiErr =
        err instanceof ApiError
          ? err
          : new ApiError('unknown', 'An unexpected error occurred.', 0);
      setError(apiErr);
      setStatus('error');
      throw apiErr;
    }
  }, []);

  const getReport = useCallback(
    (id: string): ComparativeReport | null => {
      if (report?.audit_id === id) return report;
      try {
        const raw = localStorage.getItem(REPORT_PREFIX + id);
        return raw ? (JSON.parse(raw) as ComparativeReport) : null;
      } catch {
        return null;
      }
    },
    [report],
  );

  const getInputs = useCallback((id: string): AuditInputs | null => {
    try {
      const raw = localStorage.getItem(INPUTS_PREFIX + id);
      return raw ? (JSON.parse(raw) as AuditInputs) : null;
    } catch {
      return null;
    }
  }, []);

  const clearHistory = useCallback(() => {
    try {
      loadHistory().forEach((h) => {
        localStorage.removeItem(REPORT_PREFIX + h.audit_id);
        localStorage.removeItem(INPUTS_PREFIX + h.audit_id);
      });
      localStorage.removeItem(HISTORY_KEY);
    } catch {
      /* ignore */
    }
    setHistory([]);
  }, []);

  const reset = useCallback(() => {
    setStatus('idle');
    setError(null);
  }, []);

  const value = useMemo(
    () => ({ status, report, error, history, run, getReport, getInputs, clearHistory, reset }),
    [status, report, error, history, run, getReport, getInputs, clearHistory, reset],
  );

  return <AuditContext.Provider value={value}>{children}</AuditContext.Provider>;
}

export function useAudit(): AuditContextValue {
  const ctx = useContext(AuditContext);
  if (!ctx) throw new Error('useAudit must be used within AuditProvider');
  return ctx;
}
