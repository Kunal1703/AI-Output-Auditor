/**
 * Navbar — top-level navigation and backend health indicator.
 *
 * The health dot is not decoration. When the backend cannot reach its LLM
 * provider, every trust dimension degrades to zero confidence and every report
 * comes back *Unable to Verify* — correct behavior, but baffling if you cannot
 * see why. The dot makes the cause visible before the user files a bug against
 * the auditor's judgment.
 */

import { useEffect, useState } from 'react';
import { NavLink } from 'react-router-dom';
import { getHealth } from '@/api/client';
import type { HealthResponse } from '@/api/types';

const LINKS = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/audit', label: 'New Audit', end: false },
  { to: '/results', label: 'Results', end: false },
];

/** Backend health indicator: a colored dot plus the provider name. */
function HealthDot() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getHealth()
      .then((h) => !cancelled && setHealth(h))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, []);

  if (failed) {
    return (
      <span className="flex items-center gap-2 text-xs text-slate-400">
        <span className="h-2 w-2 rounded-full bg-verdict-untrusted" />
        Backend offline
      </span>
    );
  }
  if (!health) {
    return (
      <span className="flex items-center gap-2 text-xs text-slate-400">
        <span className="h-2 w-2 animate-pulse rounded-full bg-slate-500" />
        Checking…
      </span>
    );
  }

  // Three states worth distinguishing: fully ready, up but no provider key,
  // and up with a key that is not answering.
  const ready = health.llm_configured && health.llm_reachable;
  const color = ready
    ? 'bg-verdict-trusted'
    : health.llm_configured
      ? 'bg-verdict-unverified'
      : 'bg-slate-500';
  const label = ready
    ? health.llm_provider
    : health.llm_configured
      ? `${health.llm_provider} unreachable`
      : 'No LLM key';

  return (
    <span
      className="flex items-center gap-2 text-xs text-slate-400"
      title={[
        `Provider: ${health.llm_provider}`,
        `Model: ${health.llm_model ?? '—'}`,
        `Engines: ${health.engines_registered ?? '—'}/8`,
        `Embeddings: ${health.embedding_model ?? '—'}`,
      ].join(' · ')}
    >
      <span className={`h-2 w-2 rounded-full ${color}`} />
      {label}
    </span>
  );
}

/** The application navigation bar. */
export default function Navbar() {
  return (
    <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur">
      <nav className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-6">
        <NavLink to="/" className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded bg-trust-600 text-sm font-bold text-white">
            A
          </span>
          <span className="text-sm font-semibold text-slate-100">
            AI Trust &amp; Quality Auditor
          </span>
        </NavLink>

        <div className="flex flex-1 items-center gap-1">
          {LINKS.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.end}
              className={({ isActive }) =>
                `rounded px-3 py-1.5 text-sm transition-colors ${
                  isActive
                    ? 'bg-slate-800 text-slate-100'
                    : 'text-slate-400 hover:text-slate-200'
                }`
              }
            >
              {link.label}
            </NavLink>
          ))}
        </div>

        <HealthDot />
      </nav>
    </header>
  );
}
