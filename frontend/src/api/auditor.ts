/**
 * The AI Output Auditor API client — the single seam to the backend.
 *
 * Every network call goes through here. Errors always surface as {@link ApiError}
 * carrying the backend's frozen `{ error: { code, message } }` contract, so the
 * UI has exactly one error type to branch on.
 */

import type {
  AuditOutputsRequest,
  ComparativeReport,
  HealthResponse,
} from './auditor-types';

/** Backend base URL. Vite proxies `/api` to the backend in development. */
export const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? '/api';

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    });
  } catch {
    throw new ApiError(
      'network_error',
      'Could not reach the auditor backend. Is it running?',
      0,
    );
  }

  if (!response.ok) {
    let code = `http_${response.status}`;
    let message = response.statusText || 'Request failed.';
    try {
      const body = await response.json();
      if (body?.error?.code) {
        code = body.error.code;
        message = body.error.message;
      }
    } catch {
      /* non-JSON error body; keep defaults */
    }
    throw new ApiError(code, message, response.status);
  }
  return (await response.json()) as T;
}

/** Report backend, NLI, and LLM-provider health. */
export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/health');
}

/**
 * Audit one or more outputs against a source and return the comparative report.
 *
 * This is the finalized MB4 entry point (`POST /audit/outputs`). Synchronous:
 * the report comes back in the response.
 */
export function auditOutputs(
  body: AuditOutputsRequest,
  signal?: AbortSignal,
): Promise<ComparativeReport> {
  return request<ComparativeReport>('/audit/outputs', {
    method: 'POST',
    body: JSON.stringify(body),
    signal,
  });
}
