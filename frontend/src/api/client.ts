/**
 * The shared API client — the single place the frontend talks to the backend.
 *
 * Every component goes through this module. Nothing else in the app should call
 * `fetch`. That keeps error handling, the base URL, and the request contracts in
 * one place, so a backend change breaks compilation here rather than surfacing
 * as a blank panel somewhere in the UI.
 *
 * Errors always arrive in the frozen contract (Document 4, §7):
 * `{ "error": { "code": "...", "message": "..." } }`. `ApiError` carries both
 * parts through so the UI can show the message and branch on the code.
 */

import type {
  AuditCreatedResponse,
  AuditReport,
  AuditRequest,
  AuditStatusResponse,
  HealthResponse,
  Score,
} from './types';

/**
 * Backend base URL. Defaults to `/api`, which Vite proxies to the backend in
 * development (see `vite.config.ts`).
 */
const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? '/api';

/** An error returned by the backend, in the frozen error contract. */
export class ApiError extends Error {
  /** Machine-readable code, e.g. `not_found`. Branch on this, not the message. */
  readonly code: string;
  /** HTTP status observed. */
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
  }
}

/**
 * Issue a request and parse the response, normalizing errors.
 *
 * @param path - Path relative to the base URL, e.g. `/health`.
 * @param init - Standard `fetch` options.
 * @returns The parsed JSON body.
 * @throws {ApiError} On a non-2xx response, or if the backend is unreachable.
 */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    });
  } catch (cause) {
    // A network failure has no error contract to parse — surface it as one
    // anyway so callers have exactly one error type to handle.
    throw new ApiError(
      'network_error',
      'Could not reach the auditor backend. Is it running on port 8000?',
      0,
    );
  }

  if (!response.ok) {
    let code = `http_${response.status}`;
    let message = response.statusText;
    try {
      const body = await response.json();
      if (body?.error?.code) {
        code = body.error.code;
        message = body.error.message;
      }
    } catch {
      // Non-JSON error body; keep the status-derived defaults.
    }
    throw new ApiError(code, message, response.status);
  }
  return (await response.json()) as T;
}

/** Report backend and LLM-provider health. */
export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/health');
}

/**
 * Audit content and return the report directly.
 *
 * @param body - Exactly one of `text` or `url`, plus optional prompt,
 *   reference source, and flags.
 * @returns The Final Audit Report.
 */
export function audit(body: AuditRequest): Promise<AuditReport> {
  return request<AuditReport>('/audit', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/**
 * Create an async audit job for raw text.
 *
 * @returns The `audit_id` to poll and retrieve by.
 */
export function auditText(body: AuditRequest): Promise<AuditCreatedResponse> {
  return request<AuditCreatedResponse>('/audit/text', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/**
 * Create an async audit job for a URL.
 *
 * @returns The `audit_id` to poll and retrieve by.
 */
export function auditUrl(body: AuditRequest): Promise<AuditCreatedResponse> {
  return request<AuditCreatedResponse>('/audit/url', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/** Poll a job's status and real engine progress. */
export function getStatus(auditId: string): Promise<AuditStatusResponse> {
  return request<AuditStatusResponse>(`/audit/${auditId}/status`);
}

/** Retrieve the Final Audit Report for a completed audit. */
export function getReport(auditId: string): Promise<AuditReport> {
  return request<AuditReport>(`/report/${auditId}`);
}

/**
 * Narrow a {@link Score} to a number.
 *
 * Use this instead of casting. Document 3 §9 requires an N/A dimension to be
 * excluded rather than scored as zero, and a cast is how a `'N/A'` quietly
 * becomes a `0` that drags a displayed average down.
 *
 * @returns True when the score is a real measurement.
 */
export function isScored(score: Score): score is number {
  return typeof score === 'number';
}

/**
 * Format a score for display.
 *
 * @param score - The score, possibly `'N/A'`.
 * @returns A percentage string, or `'N/A'`.
 */
export function formatScore(score: Score): string {
  return isScored(score) ? `${Math.round(score * 100)}%` : 'N/A';
}

/**
 * Format a confidence value for display.
 *
 * Confidence is always a real number, even for an N/A dimension — an engine
 * that declined to score still reports how sure it is about that.
 */
export function formatConfidence(confidence: number): string {
  return `${Math.round(confidence * 100)}%`;
}
