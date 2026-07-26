/** Metric cards — interactive, animated, with hover detail and expandable info. */

import { motion } from 'framer-motion';
import { useState } from 'react';
import { ChevronDown, Info, TriangleAlert } from 'lucide-react';
import { cn } from '@/lib/cn';
import { Icon } from '@/lib/icons';
import {
  LAYER_NAMES,
  metricMeta,
  pct,
  scoreBarColor,
  scoreToken,
} from '@/lib/format';
import type { MetricResult } from '@/api/auditor-types';
import { Card, Collapsible, Counter, ScoreBar, stagger } from '../ui';

function MetricCard({ metric, index }: { metric: MetricResult; index: number }) {
  const [open, setOpen] = useState(false);
  const meta = metricMeta(metric.metric_id);
  const scored = metric.applicable && metric.score !== null;
  const findingCount = metric.findings.length;

  return (
    <motion.div variants={stagger.item}>
      <Card hover className="group h-full p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <span
              className={cn(
                'grid h-9 w-9 place-items-center rounded-xl bg-elevated',
                scoreToken(metric.score),
              )}
            >
              <Icon name={meta.icon} size={17} />
            </span>
            <div>
              <p className="text-sm font-semibold text-content">{meta.label}</p>
              <p className="text-2xs text-content-subtle">Layer {meta.layer} · {LAYER_NAMES[meta.layer]}</p>
            </div>
          </div>
          {findingCount > 0 && (
            <span className="inline-flex items-center gap-1 rounded-full bg-severity-major/10 px-2 py-0.5 text-2xs font-medium text-severity-major">
              <TriangleAlert size={11} />
              {findingCount}
            </span>
          )}
        </div>

        <div className="mt-4 flex items-end justify-between">
          {scored ? (
            <Counter
              value={(metric.score ?? 0) * 100}
              format={(v) => `${Math.round(v)}%`}
              className={cn('text-3xl font-bold tabular-nums', scoreToken(metric.score))}
            />
          ) : (
            <span className="text-2xl font-bold text-content-subtle">N/A</span>
          )}
          <span className="mb-1 text-2xs text-content-subtle">
            conf <span className="font-medium text-content-muted">{pct(metric.confidence)}</span>
          </span>
        </div>

        <ScoreBar
          value={scored ? metric.score : null}
          color={scoreBarColor(metric.score)}
          className="mt-2.5"
          delay={0.1 + index * 0.04}
        />

        <button
          onClick={() => setOpen((o) => !o)}
          className="mt-3 flex w-full items-center justify-between text-2xs text-content-subtle transition-colors hover:text-content-muted"
          aria-expanded={open}
        >
          <span className="inline-flex items-center gap-1">
            <Info size={11} /> What this measures
          </span>
          <ChevronDown size={13} className={cn('transition-transform', open && 'rotate-180')} />
        </button>
        <Collapsible open={open}>
          <p className="pt-2 text-xs leading-relaxed text-content-muted">{meta.blurb}</p>
          {!metric.applicable && metric.applicability_reason && (
            <p className="pt-1.5 text-2xs text-content-subtle">{metric.applicability_reason}</p>
          )}
        </Collapsible>
      </Card>
    </motion.div>
  );
}

export function MetricGrid({ metrics }: { metrics: MetricResult[] }) {
  return (
    <motion.div
      variants={stagger.container}
      initial="hidden"
      animate="show"
      className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3"
    >
      {metrics.map((m, i) => (
        <MetricCard key={m.metric_id} metric={m} index={i} />
      ))}
    </motion.div>
  );
}
