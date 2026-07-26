/**
 * Application shell — sidebar, topbar, breadcrumbs, footer, and a command
 * palette. Responsive: the sidebar becomes a slide-over drawer on mobile.
 */

import { AnimatePresence, motion } from 'framer-motion';
import {
  Clock,
  Command as CommandIcon,
  Github,
  Home,
  Menu,
  Search,
  Settings as SettingsIcon,
  Sparkles,
  X,
  type LucideIcon,
} from 'lucide-react';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { cn } from '@/lib/cn';
import { useAudit } from '@/lib/store';
import { getHealth } from '@/api/auditor';
import { Logo } from './brand';
import { ThemeToggle } from './brand';

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

const NAV: NavItem[] = [
  { to: '/', label: 'Home', icon: Home },
  { to: '/audit', label: 'New Audit', icon: Sparkles },
  { to: '/history', label: 'History', icon: Clock },
  { to: '/settings', label: 'Settings', icon: SettingsIcon },
];

const CRUMB_LABELS: Record<string, string> = {
  '': 'Home',
  audit: 'New Audit',
  history: 'History',
  settings: 'Settings',
  report: 'Report',
};

/* --------------------------------- Health ---------------------------------- */

function HealthDot() {
  const [state, setState] = useState<'checking' | 'ok' | 'down'>('checking');
  useEffect(() => {
    let alive = true;
    getHealth()
      .then((h) => alive && setState(h.status === 'ok' ? 'ok' : 'down'))
      .catch(() => alive && setState('down'));
    return () => {
      alive = false;
    };
  }, []);
  const color =
    state === 'ok' ? 'bg-verdict-excellent' : state === 'down' ? 'bg-verdict-fail' : 'bg-content-subtle';
  const label = state === 'ok' ? 'Backend online' : state === 'down' ? 'Backend offline' : 'Checking…';
  return (
    <span className="hidden items-center gap-2 rounded-full border border-border bg-elevated px-2.5 py-1 text-2xs font-medium text-content-muted sm:inline-flex">
      <span className={cn('relative h-1.5 w-1.5 rounded-full', color)}>
        {state === 'ok' && (
          <span className="absolute inset-0 animate-ping rounded-full bg-verdict-excellent opacity-60" />
        )}
      </span>
      {label}
    </span>
  );
}

/* ----------------------------- Command palette ----------------------------- */

function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [q, setQ] = useState('');
  const navigate = useNavigate();
  const { history } = useAudit();

  const results = useMemo(() => {
    const nav = NAV.map((n) => ({ kind: 'nav' as const, ...n }));
    const hist = history.map((h) => ({
      kind: 'history' as const,
      to: `/report/${h.audit_id}`,
      label: h.source_title,
      icon: Clock,
    }));
    const all = [...nav, ...hist];
    if (!q.trim()) return all;
    const needle = q.toLowerCase();
    return all.filter((r) => r.label.toLowerCase().includes(needle));
  }, [q, history]);

  useEffect(() => {
    if (!open) setQ('');
  }, [open]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[60] grid place-items-start justify-center bg-black/50 p-4 pt-[12vh] backdrop-blur-sm"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, y: -12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.98 }}
            transition={{ duration: 0.18 }}
            className="w-full max-w-lg overflow-hidden rounded-2xl border border-hairline bg-surface shadow-lift"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-3 border-b border-border px-4">
              <Search size={16} className="text-content-subtle" />
              <input
                autoFocus
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search pages and past audits…"
                className="h-12 flex-1 bg-transparent text-sm text-content outline-none placeholder:text-content-subtle"
                aria-label="Search"
              />
              <kbd className="rounded-md border border-border px-1.5 py-0.5 text-2xs text-content-subtle">
                Esc
              </kbd>
            </div>
            <ul className="max-h-72 overflow-y-auto p-2">
              {results.length === 0 && (
                <li className="px-3 py-6 text-center text-sm text-content-subtle">No matches.</li>
              )}
              {results.map((r) => (
                <li key={`${r.kind}-${r.to}-${r.label}`}>
                  <button
                    onClick={() => {
                      navigate(r.to);
                      onClose();
                    }}
                    className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm text-content-muted transition-colors hover:bg-elevated hover:text-content"
                  >
                    <r.icon size={15} className="text-content-subtle" />
                    <span className="flex-1 truncate">{r.label}</span>
                    <span className="text-2xs text-content-subtle">
                      {r.kind === 'nav' ? 'Page' : 'Report'}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/* --------------------------------- Sidebar --------------------------------- */

function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex flex-1 flex-col gap-1 px-3 py-4" aria-label="Primary">
      {NAV.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === '/'}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors',
              isActive
                ? 'bg-elevated text-content'
                : 'text-content-muted hover:bg-elevated/60 hover:text-content',
            )
          }
        >
          {({ isActive }) => (
            <>
              {isActive && (
                <motion.span
                  layoutId="nav-active"
                  className="absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-brand"
                  transition={{ type: 'spring', stiffness: 400, damping: 32 }}
                />
              )}
              <item.icon size={17} className="shrink-0" />
              {item.label}
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
}

/* ------------------------------- Breadcrumbs ------------------------------- */

function Breadcrumbs() {
  const { pathname } = useLocation();
  const parts = pathname.split('/').filter(Boolean);
  const crumbs = [{ label: 'Home', to: '/' }];
  let acc = '';
  for (const p of parts) {
    acc += `/${p}`;
    crumbs.push({ label: CRUMB_LABELS[p] ?? p, to: acc });
  }
  return (
    <nav aria-label="Breadcrumb" className="hidden items-center gap-1.5 text-xs md:flex">
      {crumbs.map((c, i) => (
        <span key={c.to} className="flex items-center gap-1.5">
          {i > 0 && <span className="text-content-subtle">/</span>}
          {i === crumbs.length - 1 ? (
            <span className="font-medium text-content">{c.label}</span>
          ) : (
            <NavLink to={c.to} className="text-content-muted transition-colors hover:text-content">
              {c.label}
            </NavLink>
          )}
        </span>
      ))}
    </nav>
  );
}

/* --------------------------------- Shell ----------------------------------- */

export default function AppShell({ children }: { children: ReactNode }) {
  const [drawer, setDrawer] = useState(false);
  const [palette, setPalette] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPalette((p) => !p);
      }
      if (e.key === 'Escape') {
        setPalette(false);
        setDrawer(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <div className="min-h-screen bg-canvas">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-64 flex-col border-r border-border bg-surface lg:flex">
        <div className="flex h-16 items-center border-b border-border px-5">
          <NavLink to="/" aria-label="Veritas home">
            <Logo />
          </NavLink>
        </div>
        <SidebarNav />
        <div className="border-t border-border p-4">
          <a
            href="https://github.com"
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-2 rounded-lg px-2 py-2 text-2xs text-content-subtle transition-colors hover:text-content-muted"
          >
            <Github size={14} /> Local NLI · zero token cost
          </a>
        </div>
      </aside>

      {/* Mobile drawer */}
      <AnimatePresence>
        {drawer && (
          <motion.div
            className="fixed inset-0 z-50 bg-black/50 lg:hidden"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setDrawer(false)}
          >
            <motion.aside
              className="flex h-full w-64 flex-col border-r border-border bg-surface"
              initial={{ x: -280 }}
              animate={{ x: 0 }}
              exit={{ x: -280 }}
              transition={{ type: 'spring', stiffness: 380, damping: 36 }}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex h-16 items-center justify-between border-b border-border px-5">
                <Logo />
                <button onClick={() => setDrawer(false)} aria-label="Close menu" className="text-content-muted">
                  <X size={18} />
                </button>
              </div>
              <SidebarNav onNavigate={() => setDrawer(false)} />
            </motion.aside>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Main column */}
      <div className="lg:pl-64">
        <header className="glass sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-border px-4 md:px-6">
          <button
            className="grid h-9 w-9 place-items-center rounded-xl border border-border bg-elevated text-content-muted lg:hidden"
            onClick={() => setDrawer(true)}
            aria-label="Open menu"
          >
            <Menu size={16} />
          </button>
          <Breadcrumbs />
          <div className="flex-1" />
          <button
            onClick={() => setPalette(true)}
            className="flex h-9 items-center gap-2 rounded-xl border border-border bg-elevated px-3 text-xs text-content-subtle transition-colors hover:text-content-muted"
            aria-label="Open search"
          >
            <Search size={14} />
            <span className="hidden sm:inline">Search</span>
            <kbd className="hidden items-center gap-0.5 rounded border border-border px-1 py-0.5 text-2xs sm:inline-flex">
              <CommandIcon size={9} />K
            </kbd>
          </button>
          <HealthDot />
          <ThemeToggle />
        </header>

        <main className="mx-auto min-h-[calc(100vh-4rem)] w-full max-w-7xl px-4 py-6 md:px-8 md:py-10">
          {children}
        </main>

        <footer className="border-t border-border px-4 py-6 md:px-8">
          <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-3 text-2xs text-content-subtle sm:flex-row">
            <div className="flex items-center gap-2">
              <Logo collapsed />
              <span>Veritas — evidence-backed AI output auditing.</span>
            </div>
            <span>Every verdict traces to a source span. No external knowledge.</span>
          </div>
        </footer>
      </div>

      <CommandPalette open={palette} onClose={() => setPalette(false)} />
    </div>
  );
}
