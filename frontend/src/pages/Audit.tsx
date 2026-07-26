/** Audit — paste a source, add outputs, run the real backend audit. */

import { AnimatePresence, motion } from 'framer-motion';
import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Bot, FileText, Link2, Play, Plus, Sparkles, Trash2, User } from 'lucide-react';
import { cn } from '@/lib/cn';
import { useAudit } from '@/lib/store';
import { SAMPLE_OUTPUTS, SAMPLE_SOURCE } from '@/lib/sample';
import type { OutputType, Producer } from '@/api/auditor-types';
import { Button, Card } from '@/components/ui';
import { LoadingReport, ErrorState } from '@/components/states';

interface OutputForm {
  key: string;
  producer: Producer;
  output_type: OutputType;
  text: string;
}

let idSeq = 0;
const newOutput = (producer: Producer = 'llm'): OutputForm => ({
  key: `o${idSeq++}`,
  producer,
  output_type: 'summary',
  text: '',
});

const PRODUCERS: { value: Producer; label: string; icon: typeof User }[] = [
  { value: 'human', label: 'Human', icon: User },
  { value: 'llm', label: 'LLM', icon: Bot },
];

const TYPES: OutputType[] = ['summary', 'answer', 'extraction', 'other'];

export default function Audit() {
  const navigate = useNavigate();
  const { run, status, error, reset } = useAudit();
  const [params] = useSearchParams();

  const [sourceMode, setSourceMode] = useState<'text' | 'url'>('text');
  const [source, setSource] = useState('');
  const [sourceUrl, setSourceUrl] = useState('');
  const [outputs, setOutputs] = useState<OutputForm[]>(() => [newOutput('human'), newOutput('llm')]);

  const loadExample = () => {
    setSourceMode('text');
    setSource(SAMPLE_SOURCE.text ?? '');
    setOutputs(
      SAMPLE_OUTPUTS.map((o) => ({
        key: `o${idSeq++}`,
        producer: o.producer,
        output_type: (o.output_type ?? 'summary') as OutputType,
        text: o.text ?? '',
      })),
    );
  };

  useEffect(() => {
    if (params.get('example')) loadExample();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sourceReady = sourceMode === 'text' ? source.trim().length > 0 : sourceUrl.trim().length > 0;
  const filledOutputs = outputs.filter((o) => o.text.trim().length > 0);
  const canRun = sourceReady && filledOutputs.length > 0 && status !== 'running';

  const submit = async () => {
    try {
      const report = await run({
        source: sourceMode === 'text' ? { text: source.trim() } : { url: sourceUrl.trim() },
        outputs: filledOutputs.map((o) => ({
          producer: o.producer,
          output_type: o.output_type,
          text: o.text.trim(),
        })),
      });
      navigate(`/report/${report.audit_id}`);
    } catch {
      /* error surfaced via store state */
    }
  };

  if (status === 'running') return <LoadingReport />;

  if (status === 'error' && error) {
    return (
      <div className="py-10">
        <ErrorState code={error.code} message={error.message} onRetry={reset} />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-content">New audit</h1>
            <p className="mt-1 text-sm text-content-muted">
              Audit one or more outputs against a single source article.
            </p>
          </div>
          <Button variant="secondary" size="sm" onClick={loadExample}>
            <Sparkles size={15} /> Load example
          </Button>
        </div>
      </motion.div>

      {/* Source */}
      <Card className="p-5">
        <div className="mb-3 flex items-center justify-between">
          <label className="text-sm font-semibold text-content">Source article</label>
          <div className="inline-flex rounded-lg border border-border bg-elevated p-0.5 text-xs">
            {(['text', 'url'] as const).map((m) => (
              <button
                key={m}
                onClick={() => setSourceMode(m)}
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 font-medium transition-colors',
                  sourceMode === m ? 'bg-surface text-content shadow-soft' : 'text-content-muted',
                )}
              >
                {m === 'text' ? <FileText size={13} /> : <Link2 size={13} />}
                {m === 'text' ? 'Text' : 'URL'}
              </button>
            ))}
          </div>
        </div>
        {sourceMode === 'text' ? (
          <textarea
            value={source}
            onChange={(e) => setSource(e.target.value)}
            placeholder="Paste the original article — the ground truth every output is checked against…"
            rows={7}
            className="w-full resize-y rounded-xl border border-border bg-canvas px-3.5 py-3 text-sm text-content outline-none transition-colors placeholder:text-content-subtle focus:border-brand/50"
          />
        ) : (
          <input
            value={sourceUrl}
            onChange={(e) => setSourceUrl(e.target.value)}
            placeholder="https://example.com/article"
            className="w-full rounded-xl border border-border bg-canvas px-3.5 py-2.5 text-sm text-content outline-none transition-colors placeholder:text-content-subtle focus:border-brand/50"
          />
        )}
        {sourceMode === 'text' && (
          <p className="mt-2 text-2xs text-content-subtle">{source.trim().split(/\s+/).filter(Boolean).length} words</p>
        )}
      </Card>

      {/* Outputs */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <label className="text-sm font-semibold text-content">Outputs to audit</label>
          <span className="text-2xs text-content-subtle">{filledOutputs.length} ready</span>
        </div>
        <AnimatePresence initial={false}>
          {outputs.map((o) => (
            <motion.div
              key={o.key}
              layout
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, height: 0, marginBottom: 0 }}
              transition={{ duration: 0.2 }}
            >
              <Card className="p-4">
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <div className="inline-flex rounded-lg border border-border bg-elevated p-0.5">
                    {PRODUCERS.map((p) => (
                      <button
                        key={p.value}
                        onClick={() =>
                          setOutputs((prev) => prev.map((x) => (x.key === o.key ? { ...x, producer: p.value } : x)))
                        }
                        className={cn(
                          'inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                          o.producer === p.value ? 'bg-surface text-content shadow-soft' : 'text-content-muted',
                        )}
                      >
                        <p.icon size={13} /> {p.label}
                      </button>
                    ))}
                  </div>
                  <select
                    value={o.output_type}
                    onChange={(e) =>
                      setOutputs((prev) =>
                        prev.map((x) => (x.key === o.key ? { ...x, output_type: e.target.value as OutputType } : x)),
                      )
                    }
                    className="rounded-lg border border-border bg-elevated px-2.5 py-1.5 text-xs text-content-muted outline-none focus:border-brand/50"
                    aria-label="Output type"
                  >
                    {TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                  <div className="flex-1" />
                  {outputs.length > 1 && (
                    <button
                      onClick={() => setOutputs((prev) => prev.filter((x) => x.key !== o.key))}
                      className="grid h-7 w-7 place-items-center rounded-lg text-content-subtle transition-colors hover:bg-verdict-fail/10 hover:text-verdict-fail"
                      aria-label="Remove output"
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>
                <textarea
                  value={o.text}
                  onChange={(e) =>
                    setOutputs((prev) => prev.map((x) => (x.key === o.key ? { ...x, text: e.target.value } : x)))
                  }
                  placeholder={`Paste the ${o.producer === 'human' ? 'human-written' : 'AI-generated'} ${o.output_type}…`}
                  rows={4}
                  className="w-full resize-y rounded-xl border border-border bg-canvas px-3.5 py-3 text-sm text-content outline-none transition-colors placeholder:text-content-subtle focus:border-brand/50"
                />
              </Card>
            </motion.div>
          ))}
        </AnimatePresence>
        <button
          onClick={() => setOutputs((prev) => [...prev, newOutput()])}
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-border py-3 text-sm font-medium text-content-muted transition-colors hover:border-brand/40 hover:text-content"
        >
          <Plus size={16} /> Add another output
        </button>
      </div>

      {/* Run bar */}
      <div className="sticky bottom-4 z-10">
        <Card className="glass flex items-center justify-between gap-4 p-3.5 shadow-lift">
          <p className="text-xs text-content-muted">
            {canRun
              ? `Ready to audit ${filledOutputs.length} output${filledOutputs.length === 1 ? '' : 's'}.`
              : 'Add a source and at least one output.'}
          </p>
          <Button onClick={submit} disabled={!canRun} size="lg">
            <Play size={16} /> Run audit
          </Button>
        </Card>
      </div>
    </div>
  );
}
