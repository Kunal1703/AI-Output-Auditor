/**
 * LoadingState — progress display for a running audit.
 *
 * Document 4 §8: "Progress is real. The Audit Progress step reflects actual
 * engine completion from the status endpoint."
 *
 * That requirement deserves respect rather than compliance. A system whose
 * entire premise is refusing to overstate what it knows should not open by
 * animating a fake progress bar. `enginesCompleted` comes from
 * `GET /audit/{id}/status` and reflects engines that actually finished — so
 * when it sits still, it is telling the truth about a slow engine.
 */

interface LoadingStateProps {
  /** Engines finished so far, from the status endpoint. */
  enginesCompleted?: number;
  /** Engines in the run. Eight, per Document 2. */
  enginesTotal?: number;
  /** What is happening, in plain language. */
  message?: string;
}

/** The eight dimensions, in specification order (Document 2, §1). */
const DIMENSIONS = [
  'Relevance',
  'Accuracy',
  'Coverage',
  'Credibility',
  'Novelty',
  'Readability',
  'Engagement',
  'Diversity',
];

/**
 * Audit progress indicator.
 *
 * @remarks
 * Milestone 1 placeholder. It renders real progress when given real numbers;
 * Milestone 2 wires it to the polling loop in `AuditPage`.
 */
export default function LoadingState({
  enginesCompleted = 0,
  enginesTotal = 8,
  message = 'Auditing content…',
}: LoadingStateProps) {
  const pct = enginesTotal > 0 ? (enginesCompleted / enginesTotal) * 100 : 0;

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-8">
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-700 border-t-trust-500" />
          <span className="text-sm font-medium text-slate-200">{message}</span>
        </div>
        <span className="font-mono text-sm text-slate-400">
          {enginesCompleted}/{enginesTotal} engines
        </span>
      </div>

      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-slate-800"
        role="progressbar"
        aria-valuenow={enginesCompleted}
        aria-valuemin={0}
        aria-valuemax={enginesTotal}
        aria-label="Audit progress"
      >
        <div
          className="h-full rounded-full bg-trust-500 transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>

      <ul className="mt-6 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {DIMENSIONS.map((dimension, index) => {
          const done = index < enginesCompleted;
          return (
            <li
              key={dimension}
              className={`flex items-center gap-2 rounded border px-2.5 py-1.5 text-xs transition-colors ${
                done
                  ? 'border-trust-700/50 bg-trust-900/20 text-slate-300'
                  : 'border-slate-800 text-slate-500'
              }`}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  done ? 'bg-trust-500' : 'bg-slate-700'
                }`}
              />
              {dimension}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
