/** Report — the comparative report: source meta, comparison, per-output detail. */

import { motion } from 'framer-motion';
import { useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Check, Copy, FileText, Hash, Layers, Sparkles } from 'lucide-react';
import { Icon } from '@/lib/icons';
import { useAudit } from '@/lib/store';
import { formatDate, PRODUCER_STYLE } from '@/lib/format';
import { Button, Card, SegmentedControl } from '@/components/ui';
import { EmptyState } from '@/components/states';
import { ComparisonView } from '@/components/report/comparison';
import { OutputAuditView } from '@/components/report/output-audit';
import { VerdictBadge } from '@/components/report/verdict';

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: string | number }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="grid h-9 w-9 place-items-center rounded-xl bg-elevated text-content-muted">{icon}</span>
      <div>
        <p className="text-sm font-semibold text-content">{value}</p>
        <p className="text-2xs text-content-subtle">{label}</p>
      </div>
    </div>
  );
}

export default function Report() {
  const { auditId } = useParams();
  const { getReport, getInputs } = useAudit();
  const detailRef = useRef<HTMLDivElement>(null);

  const report = auditId ? getReport(auditId) : null;
  const inputs = auditId ? getInputs(auditId) : null;

  const [selected, setSelected] = useState<string>(() => report?.comparison.ranking[0] ?? report?.outputs[0]?.output_id ?? '');
  const [copied, setCopied] = useState(false);

  const selectedAudit = useMemo(
    () => report?.outputs.find((o) => o.output_id === selected) ?? report?.outputs[0] ?? null,
    [report, selected],
  );

  if (!report) {
    return (
      <div className="py-10">
        <EmptyState
          title="Report not found"
          description="This audit isn’t in your local history. It may have been cleared, or the link is from another device."
          action={
            <Link to="/audit">
              <Button>
                <Sparkles size={15} /> Run a new audit
              </Button>
            </Link>
          }
        />
      </div>
    );
  }

  const multi = report.outputs.length > 1;
  const openOutput = (id: string) => {
    setSelected(id);
    detailRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <div className="space-y-8">
      {/* Header */}
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
        <Card className="p-6">
          <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-2xs text-content-subtle">
                <span>Audit {report.audit_id}</span>
                <span>·</span>
                <span>{formatDate(report.generated_at)}</span>
              </div>
              <h1 className="mt-1 truncate text-2xl font-bold tracking-tight text-content">
                {report.source.title ?? 'Comparative report'}
              </h1>
            </div>
            <button
              onClick={() => {
                navigator.clipboard?.writeText(window.location.href).then(() => {
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1400);
                });
              }}
              className="inline-flex items-center gap-2 self-start rounded-xl border border-border bg-elevated px-3 py-2 text-xs font-medium text-content-muted transition-colors hover:text-content"
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
              {copied ? 'Link copied' : 'Copy link'}
            </button>
          </div>
          <div className="mt-5 flex flex-wrap gap-x-8 gap-y-4 border-t border-border pt-5">
            <Stat icon={<FileText size={16} />} label="characters" value={report.source.char_count.toLocaleString()} />
            <Stat icon={<Hash size={16} />} label="sentences" value={report.source.sentence_count} />
            <Stat icon={<Layers size={16} />} label="key points" value={report.source.key_point_count} />
            <Stat icon={<Sparkles size={16} />} label="outputs audited" value={report.outputs.length} />
          </div>
        </Card>
      </motion.div>

      {/* Comparison */}
      {multi && (
        <section className="space-y-4">
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-bold tracking-tight text-content">Comparison</h2>
            <span className="text-xs text-content-subtle">ranked best to worst</span>
          </div>
          <ComparisonView report={report} onOpenOutput={openOutput} />
        </section>
      )}

      {/* Per-output detail */}
      <section ref={detailRef} className="space-y-4 scroll-mt-20">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-bold tracking-tight text-content">
            {multi ? 'Output detail' : 'Audit detail'}
          </h2>
          {multi && (
            <SegmentedControl
              value={selected}
              onChange={setSelected}
              options={report.outputs.map((o) => ({
                value: o.output_id,
                label: (
                  <span className="inline-flex items-center gap-1.5">
                    <Icon name={PRODUCER_STYLE[o.producer].icon} size={12} />
                    {PRODUCER_STYLE[o.producer].label}
                  </span>
                ),
              }))}
            />
          )}
        </div>
        {selectedAudit && (
          <div className="flex items-center gap-2">
            <VerdictBadge verdict={selectedAudit.verdict} size="sm" />
          </div>
        )}
        {selectedAudit && (
          <OutputAuditView
            key={selectedAudit.output_id}
            audit={selectedAudit}
            sourceText={inputs?.source ?? null}
            outputText={inputs?.outputs[selectedAudit.output_id] ?? null}
          />
        )}
      </section>
    </div>
  );
}
