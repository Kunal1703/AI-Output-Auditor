/** Settings — theme, backend health, and about. */

import { motion } from 'framer-motion';
import { useEffect, useState } from 'react';
import { Activity, Cpu, Moon, Server, Sun } from 'lucide-react';
import { cn } from '@/lib/cn';
import { useTheme, type Theme } from '@/lib/theme';
import { BASE_URL, getHealth } from '@/api/auditor';
import type { HealthResponse } from '@/api/auditor-types';
import { Card, SegmentedControl } from '@/components/ui';

function HealthRow({ label, value, ok }: { label: string; value: string; ok?: boolean | null }) {
  return (
    <div className="flex items-center justify-between border-b border-border py-2.5 last:border-0">
      <span className="text-sm text-content-muted">{label}</span>
      <span className="flex items-center gap-2">
        {ok !== undefined && ok !== null && (
          <span className={cn('h-1.5 w-1.5 rounded-full', ok ? 'bg-verdict-excellent' : 'bg-verdict-fail')} />
        )}
        <span className="font-mono text-xs text-content">{value}</span>
      </span>
    </div>
  );
}

export default function Settings() {
  const { theme, setTheme } = useTheme();
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [state, setState] = useState<'loading' | 'ok' | 'down'>('loading');

  useEffect(() => {
    let alive = true;
    getHealth()
      .then((h) => {
        if (!alive) return;
        setHealth(h);
        setState('ok');
      })
      .catch(() => alive && setState('down'));
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-content">Settings</h1>
        <p className="mt-1 text-sm text-content-muted">Appearance and backend status.</p>
      </div>

      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
        <Card className="p-5">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold text-content">Theme</p>
              <p className="mt-0.5 text-xs text-content-muted">Choose light or dark. Saved to this browser.</p>
            </div>
            <SegmentedControl<Theme>
              value={theme}
              onChange={setTheme}
              options={[
                { value: 'light', label: <span className="inline-flex items-center gap-1.5"><Sun size={13} /> Light</span> },
                { value: 'dark', label: <span className="inline-flex items-center gap-1.5"><Moon size={13} /> Dark</span> },
              ]}
            />
          </div>
        </Card>
      </motion.div>

      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
        <Card className="p-5">
          <div className="mb-3 flex items-center gap-2">
            <Server size={16} className="text-brand" />
            <p className="text-sm font-semibold text-content">Backend</p>
            <span
              className={cn(
                'ml-auto inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-2xs font-medium',
                state === 'ok' ? 'bg-verdict-excellent/10 text-verdict-excellent' : state === 'down' ? 'bg-verdict-fail/10 text-verdict-fail' : 'bg-elevated text-content-muted',
              )}
            >
              <Activity size={11} />
              {state === 'ok' ? 'Online' : state === 'down' ? 'Offline' : 'Checking…'}
            </span>
          </div>
          {state === 'down' ? (
            <p className="text-sm text-content-muted">
              Could not reach the backend at <span className="font-mono text-xs">{BASE_URL}</span>. Start it and reload.
            </p>
          ) : health ? (
            <div>
              <HealthRow label="API base" value={BASE_URL} />
              <HealthRow label="Version" value={health.version} />
              <HealthRow label="LLM provider" value={health.llm_provider} />
              {health.llm_model && <HealthRow label="LLM model" value={health.llm_model} ok={health.llm_model_available} />}
              {health.nli_model && <HealthRow label="NLI model" value={health.nli_model} ok={health.nli_ready} />}
              {health.embedding_model && <HealthRow label="Embeddings" value={health.embedding_model} />}
            </div>
          ) : (
            <div className="space-y-2">
              {[0, 1, 2].map((i) => (
                <div key={i} className="skeleton h-4 w-full" />
              ))}
            </div>
          )}
        </Card>
      </motion.div>

      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
        <Card className="flex items-start gap-3 p-5">
          <Cpu size={18} className="mt-0.5 shrink-0 text-accent" />
          <div>
            <p className="text-sm font-semibold text-content">How Veritas works</p>
            <p className="mt-1 text-sm leading-relaxed text-content-muted">
              A local NLI cross-encoder grounds every output claim against the source at zero token cost. The scarce
              LLM budget is spent only where a model is genuinely needed. Verdicts are non-compensatory: grounding
              failures cap the result, and presentation quality can only shape it within that ceiling.
            </p>
          </div>
        </Card>
      </motion.div>
    </div>
  );
}
