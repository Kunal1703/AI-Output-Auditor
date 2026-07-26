/**
 * App — the routed shell.
 *
 * Pages are code-split with `React.lazy`, and route changes fade through
 * `AnimatePresence` for smooth transitions. Landing is eager (it's the first
 * paint); the rest load on demand.
 */

import { lazy, Suspense } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Route, Routes, useLocation } from 'react-router-dom';
import AppShell from '@/components/AppShell';
import Landing from '@/pages/Landing';
import { LogoMark } from '@/components/brand';

const Audit = lazy(() => import('@/pages/Audit'));
const Report = lazy(() => import('@/pages/Report'));
const History = lazy(() => import('@/pages/History'));
const Settings = lazy(() => import('@/pages/Settings'));
const NotFound = lazy(() => import('@/pages/NotFound'));

function PageFallback() {
  return (
    <div className="grid min-h-[50vh] place-items-center">
      <motion.div animate={{ opacity: [0.4, 1, 0.4] }} transition={{ duration: 1.4, repeat: Infinity }}>
        <LogoMark size={36} />
      </motion.div>
    </div>
  );
}

export default function App() {
  const location = useLocation();
  return (
    <AppShell>
      <AnimatePresence mode="wait">
        <motion.div
          key={location.pathname.split('/')[1] || 'home'}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
        >
          <Suspense fallback={<PageFallback />}>
            <Routes location={location}>
              <Route path="/" element={<Landing />} />
              <Route path="/audit" element={<Audit />} />
              <Route path="/report/:auditId" element={<Report />} />
              <Route path="/history" element={<History />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </Suspense>
        </motion.div>
      </AnimatePresence>
    </AppShell>
  );
}
