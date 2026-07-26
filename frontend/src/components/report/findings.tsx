/** Findings — grouped by severity, expandable cards with evidence links. */

import { motion } from 'framer-motion';
import { useMemo, useState } from 'react';
import { ArrowUpRight, ChevronDown, CircleCheck } from 'lucide-react';
import { cn } from '@/lib/cn';
import {
  FINDING_LABELS,
  metricMeta,
  SEVERITIES,
  SEVERITY_ORDER,
} from '@/lib/format';
import type { Finding, FindingSeverity } from '@/api/auditor-types';
import { Card, Collapsible, stagger } from '../ui';

function SpanQuote({ label, text }: { label: string; text: string }) {
  return (
    <div className="min-w-0">
      <p className="mb-1 text-2xs font-medium uppercase tracking-wide text-content-subtle">{label}</p>
      <p className="rounded-lg border border-border bg-canvas px-3 py-2 font-mono text-xs leading-relaxed text-content-muted">
        “{text}”
      </p>
    </div>
  );
}

function FindingCard({
  finding,
  onSelect,
}: {
  finding: Finding;
  onSelect?: (f: Finding) => void;
}) {
  const [open, setOpen] = useState(false);
  const sev = SEVERITIES[finding.severity];
  const meta = metricMeta(finding.metric);

  return (
    <motion.div variants={stagger.item}>
      <Card className={cn('overflow-hidden border-l-4', sev.border)} hover>
        <button
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="flex w-full items-start gap-3 p-3.5 text-left"
        >
          <span className={cn('mt-1 h-2 w-2 shrink-0 rounded-full', sev.dot)} aria-hidden />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className={cn('rounded-md px-1.5 py-0.5 text-2xs font-semibold', sev.soft, sev.text)}>
                {sev.label}
              </span>
              <span className="text-2xs font-medium text-content-muted">{FINDING_LABELS[finding.type]}</span>
              <span className="text-2xs text-content-subtle">· {meta.label}</span>
            </div>
            <p className="mt-1.5 line-clamp-2 text-sm text-content">{finding.note}</p>
          </div>
          <ChevronDown
            size={16}
            className={cn('mt-1 shrink-0 text-content-subtle transition-transform', open && 'rotate-180')}
          />
        </button>
        <Collapsible open={open}>
          <div className="space-y-3 border-t border-border p-3.5">
            {finding.output_span && <SpanQuote label="In the output" text={finding.output_span.text} />}
            {finding.source_span && <SpanQuote label="In the source" text={finding.source_span.text} />}
            <div className="flex items-center justify-between pt-1">
              <span className="text-2xs text-content-subtle">
                {finding.evidence_refs.length} evidence reference
                {finding.evidence_refs.length === 1 ? '' : 's'}
              </span>
              {onSelect && (
                <button
                  onClick={() => onSelect(finding)}
                  className="inline-flex items-center gap-1 rounded-lg bg-elevated px-2.5 py-1 text-2xs font-medium text-content-muted transition-colors hover:text-content"
                >
                  Show in evidence <ArrowUpRight size={12} />
                </button>
              )}
            </div>
          </div>
        </Collapsible>
      </Card>
    </motion.div>
  );
}

export function FindingsList({
  findings,
  onSelect,
}: {
  findings: Finding[];
  onSelect?: (f: Finding) => void;
}) {
  const [filter, setFilter] = useState<FindingSeverity | 'all'>('all');

  const counts = useMemo(() => {
    const c: Record<string, number> = { critical: 0, major: 0, minor: 0 };
    findings.forEach((f) => (c[f.severity] = (c[f.severity] ?? 0) + 1));
    return c;
  }, [findings]);

  if (findings.length === 0) {
    return (
      <Card className="grid place-items-center gap-2 p-10 text-center">
        <CircleCheck size={32} className="text-verdict-excellent" />
        <p className="text-sm font-medium text-content">No findings</p>
        <p className="text-xs text-content-subtle">This output raised no grounding, quality, or presentation issues.</p>
      </Card>
    );
  }

  const shown = filter === 'all' ? findings : findings.filter((f) => f.severity === filter);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <FilterChip active={filter === 'all'} onClick={() => setFilter('all')} label="All" count={findings.length} />
        {SEVERITY_ORDER.map((s) =>
          counts[s] ? (
            <FilterChip
              key={s}
              active={filter === s}
              onClick={() => setFilter(s)}
              label={SEVERITIES[s].label}
              count={counts[s]}
              dot={SEVERITIES[s].dot}
            />
          ) : null,
        )}
      </div>
      <motion.div variants={stagger.container} initial="hidden" animate="show" className="space-y-2.5">
        {shown.map((f) => (
          <FindingCard key={f.finding_id} finding={f} onSelect={onSelect} />
        ))}
      </motion.div>
    </div>
  );
}

function FilterChip({
  active,
  onClick,
  label,
  count,
  dot,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
  dot?: string;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
        active
          ? 'border-brand/40 bg-brand/10 text-content'
          : 'border-border bg-elevated text-content-muted hover:text-content',
      )}
    >
      {dot && <span className={cn('h-1.5 w-1.5 rounded-full', dot)} />}
      {label}
      <span className="text-content-subtle">{count}</span>
    </button>
  );
}
