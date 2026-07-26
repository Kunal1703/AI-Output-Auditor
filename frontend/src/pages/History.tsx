/** History — past audits from local storage (there is no server-side store). */

import { motion } from 'framer-motion';
import { Link } from 'react-router-dom';
import { ArrowRight, Clock, Sparkles, Trash2 } from 'lucide-react';
import { useAudit } from '@/lib/store';
import { formatDate } from '@/lib/format';
import { Button, Card, stagger } from '@/components/ui';
import { EmptyState } from '@/components/states';
import { VerdictBadge } from '@/components/report/verdict';

export default function History() {
  const { history, clearHistory } = useAudit();

  if (history.length === 0) {
    return (
      <div className="py-10">
        <EmptyState
          title="No audits yet"
          description="Your audits are stored locally in this browser. Run one to see it here."
          action={
            <Link to="/audit">
              <Button>
                <Sparkles size={15} /> Run an audit
              </Button>
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-content">History</h1>
          <p className="mt-1 text-sm text-content-muted">Stored locally · {history.length} audit{history.length === 1 ? '' : 's'}</p>
        </div>
        <Button variant="ghost" size="sm" onClick={clearHistory}>
          <Trash2 size={14} /> Clear
        </Button>
      </div>

      <motion.div variants={stagger.container} initial="hidden" animate="show" className="space-y-3">
        {history.map((h) => (
          <motion.div key={h.audit_id} variants={stagger.item}>
            <Link to={`/report/${h.audit_id}`}>
              <Card hover className="flex items-center gap-4 p-4">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-elevated text-content-muted">
                  <Clock size={17} />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-content">{h.source_title}</p>
                  <p className="text-2xs text-content-subtle">
                    {formatDate(h.generated_at)} · {h.output_count} output{h.output_count === 1 ? '' : 's'}
                  </p>
                </div>
                <div className="hidden flex-wrap items-center gap-1.5 sm:flex">
                  {h.verdicts.slice(0, 3).map((v, i) => (
                    <VerdictBadge key={i} verdict={v} size="sm" />
                  ))}
                </div>
                <ArrowRight size={16} className="shrink-0 text-content-subtle" />
              </Card>
            </Link>
          </motion.div>
        ))}
      </motion.div>
    </div>
  );
}
