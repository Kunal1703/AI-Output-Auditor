/** OutputAuditView — the full audit of one output, with tabbed detail. */

import { AnimatePresence, motion } from 'framer-motion';
import { useState } from 'react';
import { ShieldQuestion } from 'lucide-react';
import { cn } from '@/lib/cn';
import { Icon } from '@/lib/icons';
import { allMetrics, findMetric, PRODUCER_STYLE, VERDICTS } from '@/lib/format';
import type { Finding, OutputAudit } from '@/api/auditor-types';
import { Card, SegmentedControl } from '../ui';
import { Gauge } from '../brand';
import { VerdictBadge, VerdictReasonBar } from './verdict';
import { MetricGrid } from './metrics';
import { FindingsList } from './findings';
import { RecommendationsList } from './recommendations';
import { EvidenceExplorer } from './evidence';

type Tab = 'metrics' | 'findings' | 'recommendations' | 'evidence';

export function OutputAuditView({
  audit,
  sourceText,
  outputText,
}: {
  audit: OutputAudit;
  sourceText: string | null;
  outputText: string | null;
}) {
  const [tab, setTab] = useState<Tab>('metrics');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const producer = PRODUCER_STYLE[audit.producer];
  const faith = audit.faithfulness ?? findMetric(audit, 'Faithfulness');
  const confidence = audit.confidence?.overall ?? null;

  const onFindingSelect = (f: Finding) => {
    setSelectedId(`find:${f.finding_id}`);
    setTab('evidence');
  };

  const tabs: { value: Tab; label: string; count?: number }[] = [
    { value: 'metrics', label: 'Metrics' },
    { value: 'findings', label: 'Findings', count: audit.findings.length },
    { value: 'recommendations', label: 'Fixes', count: audit.recommendations.length },
    { value: 'evidence', label: 'Evidence', count: audit.attribution.length },
  ];

  const v = VERDICTS[audit.verdict];

  return (
    <div className="space-y-6">
      {/* Hero */}
      <Card className={cn('overflow-hidden')}>
        <div className={cn('flex flex-col gap-6 p-6 sm:flex-row sm:items-center', v.soft)}>
          <div className="flex items-center gap-4">
            <Gauge
              value={faith?.score ?? null}
              colorClass={v.text}
              label="Faithfulness"
              size={124}
            />
          </div>
          <div className="min-w-0 flex-1 space-y-3">
            <div className="flex flex-wrap items-center gap-2.5">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 py-1 text-xs font-medium text-content-muted">
                <Icon name={producer.icon} size={13} /> {producer.label}
              </span>
              <VerdictBadge verdict={audit.verdict} size="lg" />
              {confidence !== null && (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 py-1 text-xs text-content-muted">
                  <ShieldQuestion size={13} /> {Math.round(confidence * 100)}% confidence
                </span>
              )}
            </div>
            <VerdictReasonBar verdict={audit.verdict} reason={audit.verdict_reason} />
            {audit.confidence?.unable_to_verify_rationale && (
              <p className="text-xs text-content-muted">{audit.confidence.unable_to_verify_rationale}</p>
            )}
          </div>
        </div>
      </Card>

      {/* Tabs */}
      <div className="flex items-center justify-between">
        <SegmentedControl
          value={tab}
          onChange={setTab}
          options={tabs.map((t) => ({
            value: t.value,
            label: (
              <span className="inline-flex items-center gap-1.5">
                {t.label}
                {t.count !== undefined && t.count > 0 && (
                  <span className="rounded-full bg-elevated px-1.5 text-2xs text-content-subtle">{t.count}</span>
                )}
              </span>
            ),
          }))}
        />
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={tab}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.22 }}
        >
          {tab === 'metrics' && <MetricGrid metrics={allMetrics(audit)} />}
          {tab === 'findings' && <FindingsList findings={audit.findings} onSelect={onFindingSelect} />}
          {tab === 'recommendations' && <RecommendationsList recs={audit.recommendations} />}
          {tab === 'evidence' && (
            <EvidenceExplorer
              sourceText={sourceText}
              outputText={outputText}
              attribution={audit.attribution}
              findings={audit.findings}
              selectedId={selectedId}
              onSelectId={setSelectedId}
            />
          )}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
