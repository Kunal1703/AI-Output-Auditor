/** Recommendations — prioritized, evidence-linked action list. */

import { motion } from 'framer-motion';
import { ListChecks, Sparkles } from 'lucide-react';
import { cn } from '@/lib/cn';
import { metricMeta, PRIORITY_STYLE } from '@/lib/format';
import type { PrioritizedRecommendation } from '@/api/auditor-types';
import { Card, stagger } from '../ui';

function RecCard({ rec, index }: { rec: PrioritizedRecommendation; index: number }) {
  const style = PRIORITY_STYLE[rec.priority];
  const meta = metricMeta(rec.dimension);
  return (
    <motion.div variants={stagger.item}>
      <Card hover className="flex items-start gap-3.5 p-4">
        <span className={cn('mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg text-2xs font-bold', style.soft, style.text)}>
          {index + 1}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-2xs font-semibold', style.soft, style.text)}>
              <span className={cn('h-1.5 w-1.5 rounded-full', style.dot)} />
              {rec.priority}
            </span>
            <span className="text-2xs font-medium text-content-muted">{meta.label}</span>
          </div>
          <p className="mt-1.5 text-sm leading-relaxed text-content">{rec.text}</p>
          <p className="mt-1.5 text-2xs text-content-subtle">
            Backed by {rec.evidence_refs.length} evidence reference{rec.evidence_refs.length === 1 ? '' : 's'}
          </p>
        </div>
      </Card>
    </motion.div>
  );
}

export function RecommendationsList({ recs }: { recs: PrioritizedRecommendation[] }) {
  if (recs.length === 0) {
    return (
      <Card className="grid place-items-center gap-2 p-10 text-center">
        <Sparkles size={30} className="text-verdict-excellent" />
        <p className="text-sm font-medium text-content">Nothing to fix</p>
        <p className="text-xs text-content-subtle">This output produced no actionable recommendations.</p>
      </Card>
    );
  }
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-xs text-content-subtle">
        <ListChecks size={14} />
        {recs.length} recommendation{recs.length === 1 ? '' : 's'}, most important first
      </div>
      <motion.div variants={stagger.container} initial="hidden" animate="show" className="space-y-2.5">
        {recs.map((r, i) => (
          <RecCard key={`${r.dimension}-${i}`} rec={r} index={i} />
        ))}
      </motion.div>
    </div>
  );
}
