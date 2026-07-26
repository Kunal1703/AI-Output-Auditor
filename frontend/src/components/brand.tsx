/** Brand + chrome components: Logo, ThemeToggle, and the radial score Gauge. */

import { motion } from 'framer-motion';
import { Moon, Sun } from 'lucide-react';
import { cn } from '@/lib/cn';
import { useTheme } from '@/lib/theme';
import { Counter } from './ui';

/* ---------------------------------- Logo ----------------------------------- */

export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" aria-hidden>
      <defs>
        <linearGradient id="veritas-g" x1="8" y1="6" x2="56" y2="58" gradientUnits="userSpaceOnUse">
          <stop stopColor="rgb(var(--c-brand))" />
          <stop offset="1" stopColor="rgb(var(--c-accent))" />
        </linearGradient>
      </defs>
      <path
        d="M32 8L52 15V31C52 43.6 43.4 52.9 32 56C20.6 52.9 12 43.6 12 31V15L32 8Z"
        fill="url(#veritas-g)"
        fillOpacity="0.14"
        stroke="url(#veritas-g)"
        strokeWidth="2.5"
        strokeLinejoin="round"
      />
      <path
        d="M23 32.5L29.5 39L42 25.5"
        stroke="url(#veritas-g)"
        strokeWidth="4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function Logo({ collapsed = false }: { collapsed?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <LogoMark />
      {!collapsed && (
        <span className="flex flex-col leading-none">
          <span className="text-[0.95rem] font-bold tracking-tight text-content">Veritas</span>
          <span className="text-2xs font-medium text-content-subtle">Output Auditor</span>
        </span>
      )}
    </span>
  );
}

/* ------------------------------- ThemeToggle ------------------------------- */

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const dark = theme === 'dark';
  return (
    <button
      onClick={toggle}
      aria-label={`Switch to ${dark ? 'light' : 'dark'} theme`}
      className="relative grid h-9 w-9 place-items-center rounded-xl border border-border bg-elevated text-content-muted transition-colors hover:text-content"
    >
      <motion.span
        key={theme}
        initial={{ rotate: -90, opacity: 0, scale: 0.6 }}
        animate={{ rotate: 0, opacity: 1, scale: 1 }}
        transition={{ duration: 0.25 }}
      >
        {dark ? <Moon size={16} /> : <Sun size={16} />}
      </motion.span>
    </button>
  );
}

/* ---------------------------------- Gauge ---------------------------------- */

/** Animated radial gauge for a 0–1 score. */
export function Gauge({
  value,
  size = 132,
  stroke = 10,
  colorClass = 'text-brand',
  label,
  sublabel,
}: {
  value: number | null;
  size?: number;
  stroke?: number;
  colorClass?: string;
  label?: string;
  sublabel?: string;
}) {
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const clamped = value === null ? 0 : Math.max(0, Math.min(1, value));

  return (
    <div className="relative grid place-items-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          strokeWidth={stroke}
          className="stroke-elevated"
        />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          className={cn('stroke-current', colorClass)}
          strokeDasharray={circ}
          initial={{ strokeDashoffset: circ }}
          animate={{ strokeDashoffset: circ * (1 - clamped) }}
          transition={{ duration: 1.1, ease: [0.22, 1, 0.36, 1] }}
        />
      </svg>
      <div className="absolute inset-0 grid place-content-center text-center">
        {value === null ? (
          <span className="text-lg font-semibold text-content-subtle">N/A</span>
        ) : (
          <Counter
            value={clamped * 100}
            format={(v) => `${Math.round(v)}%`}
            className={cn('text-2xl font-bold tabular-nums', colorClass)}
          />
        )}
        {label && <span className="mt-0.5 text-2xs font-medium text-content-muted">{label}</span>}
        {sublabel && <span className="text-2xs text-content-subtle">{sublabel}</span>}
      </div>
    </div>
  );
}
