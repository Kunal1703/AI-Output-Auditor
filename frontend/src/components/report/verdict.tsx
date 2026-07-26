/** Verdict presentation — badge and per-output hero. */

import { motion } from 'framer-motion';
import { cn } from '@/lib/cn';
import { VERDICTS } from '@/lib/format';
import type { VerdictBand } from '@/api/auditor-types';
import { Icon } from '@/lib/icons';

export function VerdictBadge({
  verdict,
  size = 'md',
}: {
  verdict: VerdictBand;
  size?: 'sm' | 'md' | 'lg';
}) {
  const v = VERDICTS[verdict];
  const pad = size === 'lg' ? 'px-3.5 py-1.5 text-sm' : size === 'sm' ? 'px-2 py-0.5 text-2xs' : 'px-2.5 py-1 text-xs';
  const icon = size === 'lg' ? 16 : 13;
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full font-semibold ring-1',
        v.soft,
        v.text,
        v.ring,
        pad,
      )}
    >
      <Icon name={v.icon} size={icon} />
      {v.label}
    </span>
  );
}

export function VerdictReasonBar({ verdict, reason }: { verdict: VerdictBand; reason: string }) {
  const v = VERDICTS[verdict];
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className={cn('flex items-start gap-3 rounded-xl border px-4 py-3', v.soft, v.ring, 'ring-1 border-transparent')}
    >
      <Icon name={v.icon} size={18} className={cn('mt-0.5 shrink-0', v.text)} />
      <p className="text-sm leading-relaxed text-content">{reason}</p>
    </motion.div>
  );
}
