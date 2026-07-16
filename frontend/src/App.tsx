/**
 * App — routing and the page shell.
 *
 * Document 4 §8 specifies a single-page app. Routes mirror its workflow:
 * landing → input/progress → results.
 *
 * `/results/:auditId` exists alongside `/results` so a finished report has a
 * shareable URL. Document 3 §11 routes *Unable to Verify* and *Needs Revision*
 * to human reviewers — that hand-off is a lot easier when a report can be
 * linked rather than described.
 */

import { Route, Routes } from 'react-router-dom';
import Navbar from '@/components/Navbar';
import Dashboard from '@/pages/Dashboard';
import AuditPage from '@/pages/AuditPage';
import ResultsPage from '@/pages/ResultsPage';

/** Fallback for an unknown route. */
function NotFound() {
  return (
    <div className="grid place-items-center py-24 text-center">
      <p className="text-2xl font-bold text-slate-300">404</p>
      <p className="mt-1 text-sm text-slate-500">This page does not exist.</p>
    </div>
  );
}

/** The application shell and route table. */
export default function App() {
  return (
    <div className="min-h-screen bg-slate-950">
      <Navbar />
      <main className="mx-auto max-w-6xl px-6 pb-20">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/audit" element={<AuditPage />} />
          <Route path="/results" element={<ResultsPage />} />
          <Route path="/results/:auditId" element={<ResultsPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
    </div>
  );
}
