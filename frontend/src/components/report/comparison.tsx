/** Comparative view — winner, ranking, and per-metric side-by-side comparison. */

import { motion } from 'framer-motion';
import { ArrowRight, Crown, TriangleAlert } from 'lucide-react';
import { cn } from '@/lib/cn';
import { Icon } from '@/lib/icons';
import {
  metricMeta,
  metricScore,
  pct,
  PRODUCER_STYLE,
  scoreBarColor,
  scoreToken,
} from '@/lib/format';
import type { ComparativeReport, OutputAudit } from '@/api/auditor-types';
import { Card, ScoreBar, stagger } from '../ui';
import { VerdictBadge } from './verdict';

const COMPARE_METRICS = [
  'Faithfulness',
  'Factual & Numeric Accuracy',
  'Coverage',
  'Meaning Preservation',
  'Readability & Coherence',
  'Conciseness / Non-Redundancy',
  'Bias / Objectivity',
];

function OutputColumn({
  audit,
  rank,
  isWinner,
  onOpen,
}: {
  audit: OutputAudit;
  rank: number;
  isWinner: boolean;
  onOpen: () => void;
}) {
  const producer = PRODUCER_STYLE[audit.producer];
  const gating = audit.findings.filter((f) => f.severity !== 'minor').length;
  return (
    <motion.div variants={stagger.item} className="min-w-0">
      <Card
        hover
        className={cn(
          'relative flex h-full flex-col p-5',
          isWinner && 'ring-1 ring-verdict-excellent/40',
        )}
      >
        {isWinner && (
          <span className="absolute -top-3 left-5 inline-flex items-center gap-1 rounded-full bg-verdict-excellent px-2.5 py-1 text-2xs font-bold text-white shadow-soft">
            <Crown size={11} /> Winner
          </span>
        )}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-elevated text-content-muted">
              <Icon name={producer.icon} size={17} />
            </span>
            <div>
              <p className="text-sm font-semibold text-content">{producer.label} output</p>
              <p className="text-2xs text-content-subtle">Rank #{rank} · {audit.output_id}</p>
            </div>
          </div>
        </div>

        <div className="mt-4">
          <VerdictBadge verdict={audit.verdict} size="lg" />
        </div>

        <div className="mt-5 space-y-2.5">
          {COMPARE_METRICS.map((id) => {
            const score = metricScore(audit, id);
            return (
              <div key={id}>
                <div className="mb-1 flex items-center justify-between text-2xs">
                  <span className="text-content-muted">{metricMeta(id).label}</span>
                  <span className={cn('font-semibold tabular-nums', scoreToken(score))}>{pct(score)}</span>
                </div>
                <ScoreBar value={score} color={scoreBarColor(score)} height="h-1.5" />
              </div>
            );
          })}
        </div>

        <div className="mt-4 flex items-center justify-between border-t border-border pt-3">
          <span className={cn('inline-flex items-center gap-1 text-2xs', gating ? 'text-severity-major' : 'text-content-subtle')}>
            {gating > 0 && <TriangleAlert size={12} />}
            {gating} gating finding{gating === 1 ? '' : 's'}
          </span>
          <button
            onClick={onOpen}
            className="inline-flex items-center gap-1 text-2xs font-medium text-brand transition-colors hover:brightness-110"
          >
            Full audit <ArrowRight size={12} />
          </button>
        </div>
      </Card>
    </motion.div>
  );
}

export function ComparisonView({
  report,
  onOpenOutput,
}: {
  report: ComparativeReport;
  onOpenOutput: (outputId: string) => void;
}) {
  const byId = new Map(report.outputs.map((o) => [o.output_id, o]));
  const ordered = report.comparison.ranking
    .map((id) => byId.get(id))
    .filter((o): o is OutputAudit => Boolean(o));
  const cols = ordered.length >= 4 ? 'lg:grid-cols-4' : ordered.length === 3 ? 'lg:grid-cols-3' : 'lg:grid-cols-2';

  return (
    <motion.div
      variants={stagger.container}
      initial="hidden"
      animate="show"
      className={cn('grid grid-cols-1 gap-4 sm:grid-cols-2', cols)}
    >
      {ordered.map((audit, i) => (
        <OutputColumn
          key={audit.output_id}
          audit={audit}
          rank={i + 1}
          isWinner={i === 0 && ordered.length > 1}
          onOpen={() => onOpenOutput(audit.output_id)}
        />
      ))}
    </motion.div>
  );
}
