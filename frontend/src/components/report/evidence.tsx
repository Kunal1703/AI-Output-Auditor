/**
 * Evidence explorer — synchronized source ⇄ output highlighting.
 *
 * Selecting a claim attribution or a finding highlights the matching span in
 * both the source and the output and scrolls each into view, so a reviewer can
 * see exactly where a verdict came from. Falls back to snippet cards when the
 * full text is unavailable (e.g. a URL input).
 */

import { motion } from 'framer-motion';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Check, Copy, FileText, MessageSquareText } from 'lucide-react';
import { cn } from '@/lib/cn';
import { SUPPORT_STYLE } from '@/lib/format';
import type { AttributionEntry, Finding, Span, SupportLabel } from '@/api/auditor-types';
import { Card } from '../ui';

type Tone = SupportLabel | 'finding';

interface HL {
  start: number;
  end: number;
  id: string;
  tone: Tone;
}

const TONE_BG: Record<Tone, string> = {
  supported: 'bg-verdict-excellent/20',
  partial: 'bg-verdict-unverified/25',
  not_found: 'bg-verdict-fail/20',
  finding: 'bg-severity-major/25',
};

const PRIORITY: Record<Tone, number> = { finding: 4, not_found: 3, partial: 2, supported: 1 };

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), 1400);
        } catch {
          /* clipboard blocked */
        }
      }}
      className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-2xs text-content-subtle transition-colors hover:text-content"
      aria-label="Copy text"
    >
      {done ? <Check size={12} /> : <Copy size={12} />}
      {done ? 'Copied' : 'Copy'}
    </button>
  );
}

/** Render text with layered highlights; the active id gets a ring + scroll. */
function HighlightedText({
  text,
  highlights,
  activeId,
  onSelect,
}: {
  text: string;
  highlights: HL[];
  activeId: string | null;
  onSelect: (id: string) => void;
}) {
  const activeRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [activeId]);

  const segments = useMemo(() => {
    const owner = new Int32Array(text.length).fill(-1);
    highlights.forEach((h, i) => {
      const s = Math.max(0, h.start);
      const e = Math.min(text.length, h.end);
      for (let c = s; c < e; c++) {
        const cur = owner[c];
        if (cur === -1 || PRIORITY[highlights[cur].tone] < PRIORITY[h.tone]) owner[c] = i;
      }
    });
    const segs: { text: string; hl: HL | null }[] = [];
    let c = 0;
    while (c < text.length) {
      const o = owner[c];
      let j = c + 1;
      while (j < text.length && owner[j] === o) j++;
      segs.push({ text: text.slice(c, j), hl: o === -1 ? null : highlights[o] });
      c = j;
    }
    return segs;
  }, [text, highlights]);

  return (
    <p className="whitespace-pre-wrap font-mono text-[0.8rem] leading-[1.7] text-content-muted">
      {segments.map((seg, i) =>
        seg.hl ? (
          <span
            key={i}
            ref={seg.hl.id === activeId ? activeRef : undefined}
            onClick={() => onSelect(seg.hl!.id)}
            className={cn(
              'cursor-pointer rounded px-0.5 text-content transition-shadow',
              TONE_BG[seg.hl.tone],
              seg.hl.id === activeId && 'shadow-[0_0_0_2px_rgb(var(--c-brand))]',
            )}
          >
            {seg.text}
          </span>
        ) : (
          <span key={i}>{seg.text}</span>
        ),
      )}
    </p>
  );
}

function SnippetList({ attribution }: { attribution: AttributionEntry[] }) {
  return (
    <div className="space-y-2">
      {attribution.map((a) => {
        const s = SUPPORT_STYLE[a.support];
        return (
          <Card key={a.output_unit_id} className="p-3">
            <div className="mb-2 flex items-center gap-2">
              <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-2xs font-semibold', s.soft, s.text)}>
                <span className={cn('h-1.5 w-1.5 rounded-full', s.dot)} />
                {s.label}
              </span>
              {a.nli_score !== null && (
                <span className="text-2xs text-content-subtle">NLI {Math.round(a.nli_score * 100)}%</span>
              )}
            </div>
            <p className="font-mono text-xs text-content">“{a.output_span.text}”</p>
            {a.source_span && (
              <p className="mt-1 border-l-2 border-border pl-2 font-mono text-2xs text-content-muted">
                ↳ {a.source_span.text}
              </p>
            )}
          </Card>
        );
      })}
    </div>
  );
}

export function EvidenceExplorer({
  sourceText,
  outputText,
  attribution,
  findings,
  selectedId,
  onSelectId,
}: {
  sourceText: string | null;
  outputText: string | null;
  attribution: AttributionEntry[];
  findings: Finding[];
  selectedId: string | null;
  onSelectId: (id: string | null) => void;
}) {
  const sourceHls = useMemo(() => collectHighlights('source', attribution, findings), [attribution, findings]);
  const outputHls = useMemo(() => collectHighlights('output', attribution, findings), [attribution, findings]);

  // Full-text explorer when we have the text; snippet fallback otherwise.
  const hasText = Boolean(sourceText && outputText);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        {(['supported', 'partial', 'not_found'] as SupportLabel[]).map((t) => (
          <span key={t} className="inline-flex items-center gap-1.5 text-2xs text-content-muted">
            <span className={cn('h-2.5 w-2.5 rounded', TONE_BG[t])} />
            {SUPPORT_STYLE[t].label}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5 text-2xs text-content-muted">
          <span className={cn('h-2.5 w-2.5 rounded', TONE_BG.finding)} />
          Finding
        </span>
      </div>

      {hasText ? (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card className="flex max-h-[28rem] flex-col overflow-hidden">
            <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
              <span className="inline-flex items-center gap-2 text-xs font-semibold text-content">
                <FileText size={14} className="text-brand" /> Source
              </span>
              <CopyButton text={sourceText ?? ''} />
            </div>
            <div className="overflow-y-auto px-4 py-3">
              <HighlightedText text={sourceText ?? ''} highlights={sourceHls} activeId={selectedId} onSelect={onSelectId} />
            </div>
          </Card>
          <Card className="flex max-h-[28rem] flex-col overflow-hidden">
            <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
              <span className="inline-flex items-center gap-2 text-xs font-semibold text-content">
                <MessageSquareText size={14} className="text-accent" /> Output
              </span>
              <CopyButton text={outputText ?? ''} />
            </div>
            <div className="overflow-y-auto px-4 py-3">
              <HighlightedText text={outputText ?? ''} highlights={outputHls} activeId={selectedId} onSelect={onSelectId} />
            </div>
          </Card>
        </div>
      ) : (
        <SnippetList attribution={attribution} />
      )}

      {/* Attribution index — click to sync both panels */}
      <div>
        <p className="mb-2 text-xs font-semibold text-content-muted">
          Claim attributions ({attribution.length})
        </p>
        <div className="grid max-h-72 grid-cols-1 gap-2 overflow-y-auto pr-1 md:grid-cols-2">
          {attribution.map((a) => {
            const id = `att:${a.output_unit_id}`;
            const s = SUPPORT_STYLE[a.support];
            const active = selectedId === id;
            return (
              <motion.button
                key={a.output_unit_id}
                onClick={() => onSelectId(active ? null : id)}
                whileHover={{ y: -1 }}
                className={cn(
                  'rounded-xl border p-2.5 text-left transition-colors',
                  active ? 'border-brand/50 bg-brand/5' : 'border-border bg-surface hover:border-hairline',
                )}
              >
                <span className={cn('inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-2xs font-medium', s.soft, s.text)}>
                  <span className={cn('h-1.5 w-1.5 rounded-full', s.dot)} />
                  {s.label}
                </span>
                <p className="mt-1.5 line-clamp-2 font-mono text-2xs text-content-muted">{a.output_span.text}</p>
              </motion.button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function collectHighlights(ref: 'source' | 'output', attribution: AttributionEntry[], findings: Finding[]): HL[] {
  const hls: HL[] = [];
  for (const a of attribution) {
    const span: Span | null = ref === 'source' ? a.source_span : a.output_span;
    if (span && span.ref === ref) hls.push({ start: span.start, end: span.end, id: `att:${a.output_unit_id}`, tone: a.support });
  }
  for (const f of findings) {
    const span: Span | null = ref === 'source' ? f.source_span : f.output_span;
    if (span && span.ref === ref) hls.push({ start: span.start, end: span.end, id: `find:${f.finding_id}`, tone: 'finding' });
  }
  return hls;
}
