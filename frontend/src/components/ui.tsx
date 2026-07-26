/**
 * Veritas UI primitives — the reusable building blocks of the design system.
 *
 * One coherent visual language: soft surfaces, hairline borders, restrained
 * motion. Every component themes itself via the CSS-variable tokens.
 */

import {
  animate,
  AnimatePresence,
  motion,
  useMotionValue,
  useTransform,
} from 'framer-motion';
import {
  useEffect,
  useId,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type ReactNode,
} from 'react';
import { ChevronDown, Loader2 } from 'lucide-react';
import { cn } from '@/lib/cn';

/* --------------------------------- Button ---------------------------------- */

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
type ButtonSize = 'sm' | 'md' | 'lg';

const BTN_BASE =
  'inline-flex items-center justify-center gap-2 rounded-xl font-medium transition-all duration-150 ' +
  'focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:opacity-50 select-none';

const BTN_VARIANT: Record<ButtonVariant, string> = {
  primary:
    'bg-brand text-brand-contrast shadow-soft hover:shadow-glow hover:brightness-110 active:brightness-95',
  secondary:
    'bg-elevated text-content border border-border hover:border-hairline hover:bg-surface',
  ghost: 'text-content-muted hover:text-content hover:bg-elevated',
  danger: 'bg-verdict-fail text-white hover:brightness-110',
};

const BTN_SIZE: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-xs',
  md: 'h-10 px-4 text-sm',
  lg: 'h-12 px-6 text-[0.95rem]',
};

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}) {
  return (
    <button
      className={cn(BTN_BASE, BTN_VARIANT[variant], BTN_SIZE[size], className)}
      disabled={loading || props.disabled}
      {...props}
    >
      {loading && <Loader2 size={16} className="animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

/* ---------------------------------- Card ----------------------------------- */

export function Card({
  className,
  children,
  hover = false,
  as: As = 'div',
}: {
  className?: string;
  children: ReactNode;
  hover?: boolean;
  as?: 'div' | 'section' | 'article';
}) {
  return (
    <As
      className={cn(
        'rounded-2xl border border-border bg-surface shadow-card',
        hover && 'transition-all duration-200 hover:-translate-y-0.5 hover:border-hairline hover:shadow-lift',
        className,
      )}
    >
      {children}
    </As>
  );
}

/* ---------------------------------- Badge ---------------------------------- */

export function Badge({
  children,
  className,
  dot,
  icon,
}: {
  children: ReactNode;
  className?: string;
  dot?: string;
  icon?: ReactNode;
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium',
        className,
      )}
    >
      {dot && <span className={cn('h-1.5 w-1.5 rounded-full', dot)} aria-hidden />}
      {icon}
      {children}
    </span>
  );
}

/* -------------------------------- ScoreBar --------------------------------- */

export function ScoreBar({
  value,
  color = 'bg-brand',
  className,
  delay = 0,
  height = 'h-2',
}: {
  value: number | null;
  color?: string;
  className?: string;
  delay?: number;
  height?: string;
}) {
  const width = value === null ? 0 : Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className={cn('w-full overflow-hidden rounded-full bg-elevated', height, className)}>
      <motion.div
        className={cn('h-full rounded-full', color)}
        initial={{ width: 0 }}
        animate={{ width: `${width}%` }}
        transition={{ duration: 0.9, delay, ease: [0.22, 1, 0.36, 1] }}
      />
    </div>
  );
}

/* --------------------------------- Counter --------------------------------- */

export function Counter({
  value,
  format = (v) => Math.round(v).toString(),
  className,
  duration = 1,
}: {
  value: number;
  format?: (v: number) => string;
  className?: string;
  duration?: number;
}) {
  const mv = useMotionValue(0);
  const text = useTransform(mv, (v) => format(v));
  useEffect(() => {
    const controls = animate(mv, value, { duration, ease: [0.22, 1, 0.36, 1] });
    return () => controls.stop();
  }, [value, duration, mv]);
  return <motion.span className={className}>{text}</motion.span>;
}

/* -------------------------------- Skeleton --------------------------------- */

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('skeleton', className)} />;
}

/* ------------------------------- Collapsible ------------------------------- */

export function Collapsible({
  open,
  children,
}: {
  open: boolean;
  children: ReactNode;
}) {
  return (
    <AnimatePresence initial={false}>
      {open && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
          className="overflow-hidden"
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** A self-contained expandable disclosure with an animated chevron. */
export function Disclosure({
  title,
  defaultOpen = false,
  children,
  right,
  className,
}: {
  title: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
  right?: ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <div className={className}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={id}
        className="flex w-full items-center justify-between gap-3 text-left"
      >
        <span className="min-w-0 flex-1">{title}</span>
        <span className="flex items-center gap-2">
          {right}
          <ChevronDown
            size={16}
            className={cn('shrink-0 text-content-subtle transition-transform', open && 'rotate-180')}
            aria-hidden
          />
        </span>
      </button>
      <div id={id}>
        <Collapsible open={open}>{children}</Collapsible>
      </div>
    </div>
  );
}

/* ----------------------------- SegmentedControl ---------------------------- */

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  className,
}: {
  options: { value: T; label: ReactNode }[];
  value: T;
  onChange: (v: T) => void;
  className?: string;
}) {
  const groupId = useId();
  return (
    <div
      role="tablist"
      className={cn('inline-flex rounded-xl border border-border bg-elevated p-1', className)}
    >
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(opt.value)}
            className={cn(
              'relative rounded-lg px-3 py-1.5 text-xs font-medium transition-colors',
              active ? 'text-content' : 'text-content-muted hover:text-content',
            )}
          >
            {active && (
              <motion.span
                layoutId={`seg-${groupId}`}
                className="absolute inset-0 rounded-lg bg-surface shadow-soft"
                transition={{ type: 'spring', stiffness: 400, damping: 32 }}
              />
            )}
            <span className="relative z-10">{opt.label}</span>
          </button>
        );
      })}
    </div>
  );
}

/* --------------------------------- Tooltip --------------------------------- */

export function Tooltip({
  content,
  children,
  side = 'top',
}: {
  content: ReactNode;
  children: ReactNode;
  side?: 'top' | 'bottom';
}) {
  const [show, setShow] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  return (
    <span
      ref={ref}
      className="relative inline-flex"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
      onFocus={() => setShow(true)}
      onBlur={() => setShow(false)}
    >
      {children}
      <AnimatePresence>
        {show && (
          <motion.span
            role="tooltip"
            initial={{ opacity: 0, y: side === 'top' ? 4 : -4, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, scale: 0.96 }}
            transition={{ duration: 0.14 }}
            className={cn(
              'pointer-events-none absolute left-1/2 z-50 w-max max-w-xs -translate-x-1/2 rounded-lg border border-hairline bg-elevated px-2.5 py-1.5 text-2xs font-medium text-content shadow-lift',
              side === 'top' ? 'bottom-full mb-2' : 'top-full mt-2',
            )}
          >
            {content}
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  );
}

/* --------------------------------- Motion ---------------------------------- */

/** Staggered reveal container + item, used across lists and grids. */
export const stagger = {
  container: {
    hidden: {},
    show: { transition: { staggerChildren: 0.06, delayChildren: 0.05 } },
  },
  item: {
    hidden: { opacity: 0, y: 12 },
    show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: [0.22, 1, 0.36, 1] } },
  },
};
