/** Loading, error, and empty states — the app's honest in-between screens. */

import { motion } from 'framer-motion';
import { useEffect, useState, type ReactNode } from 'react';
import { AlertTriangle, RefreshCw, SearchX, WifiOff } from 'lucide-react';
import { cn } from '@/lib/cn';
import { Button, Card, Skeleton } from './ui';
import { LogoMark } from './brand';

const STAGES = [
  'Segmenting the source & extracting key points',
  'Decomposing each output into atomic claims',
  'Retrieving candidate source spans',
  'Running local NLI entailment',
  'Deriving faithfulness & hallucinations',
  'Checking numbers, dates & quantities',
  'Scoring coverage & meaning preservation',
  'Assessing readability, conciseness & bias',
  'Assembling the comparative verdict',
];

export function LoadingReport() {
  const [stage, setStage] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setStage((s) => (s + 1) % STAGES.length), 1600);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="space-y-6">
      <Card className="overflow-hidden p-8">
        <div className="flex flex-col items-center gap-5 text-center">
          <motion.div
            animate={{ scale: [1, 1.06, 1], opacity: [0.85, 1, 0.85] }}
            transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
          >
            <LogoMark size={48} />
          </motion.div>
          <div>
            <p className="text-lg font-semibold text-content">Auditing your outputs</p>
            <p className="mt-1 text-sm text-content-muted">
              Every verdict is traced to a source span — this runs a real grounding pipeline.
            </p>
          </div>
          <div className="h-6 overflow-hidden">
            <motion.p
              key={stage}
              initial={{ y: 14, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              exit={{ y: -14, opacity: 0 }}
              className="text-sm font-medium text-brand"
            >
              {STAGES[stage]}
            </motion.p>
          </div>
          <div className="h-1.5 w-full max-w-sm overflow-hidden rounded-full bg-elevated">
            <motion.div
              className="h-full w-1/3 rounded-full bg-gradient-to-r from-brand to-accent"
              animate={{ x: ['-100%', '300%'] }}
              transition={{ duration: 1.6, repeat: Infinity, ease: 'easeInOut' }}
            />
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {[0, 1].map((i) => (
          <Card key={i} className="space-y-4 p-5">
            <div className="flex items-center gap-3">
              <Skeleton className="h-9 w-9 rounded-xl" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-3 w-24" />
                <Skeleton className="h-2.5 w-16" />
              </div>
            </div>
            <Skeleton className="h-7 w-20" />
            {[0, 1, 2, 3].map((j) => (
              <div key={j} className="space-y-1.5">
                <Skeleton className="h-2.5 w-full" />
                <Skeleton className="h-1.5 w-full rounded-full" />
              </div>
            ))}
          </Card>
        ))}
      </div>
    </div>
  );
}

export function StateShell({
  icon,
  title,
  description,
  children,
  tone = 'neutral',
}: {
  icon: ReactNode;
  title: string;
  description: ReactNode;
  children?: ReactNode;
  tone?: 'neutral' | 'error';
}) {
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
      <Card className="mx-auto max-w-md">
        <div className="flex flex-col items-center gap-4 p-10 text-center">
          <span
            className={cn(
              'grid h-14 w-14 place-items-center rounded-2xl',
              tone === 'error' ? 'bg-verdict-fail/10 text-verdict-fail' : 'bg-elevated text-content-muted',
            )}
          >
            {icon}
          </span>
          <div>
            <p className="text-base font-semibold text-content">{title}</p>
            <p className="mt-1.5 text-sm text-content-muted">{description}</p>
          </div>
          {children}
        </div>
      </Card>
    </motion.div>
  );
}

export function ErrorState({
  code,
  message,
  onRetry,
}: {
  code: string;
  message: string;
  onRetry?: () => void;
}) {
  const isNetwork = code === 'network_error';
  return (
    <StateShell
      tone="error"
      icon={isNetwork ? <WifiOff size={26} /> : <AlertTriangle size={26} />}
      title={isNetwork ? 'Backend unavailable' : 'Something went wrong'}
      description={
        <>
          {message}
          <span className="mt-2 block text-2xs text-content-subtle">Error code: {code}</span>
        </>
      }
    >
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          <RefreshCw size={15} /> Try again
        </Button>
      )}
    </StateShell>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <StateShell icon={<SearchX size={26} />} title={title} description={description}>
      {action}
    </StateShell>
  );
}
