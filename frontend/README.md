# Veritas — AI Output Auditor (frontend)

A premium single-page React app for the AI Output Auditor. It audits one or more
**outputs** (human- or LLM-written summaries/answers) against a **source
article** and renders the finalized `ComparativeReport` from the backend's
`POST /audit/outputs` endpoint (MB4) — verdicts, per-metric scores, findings,
recommendations, confidence, and a synchronized evidence explorer.

## Stack

- **React 18 + TypeScript** (strict), **Vite 5**
- **Tailwind CSS** with a CSS-variable design system (light/dark, no `dark:`
  variants — the tokens swap)
- **Framer Motion** for restrained, purposeful motion
- **lucide-react** icons
- **react-router-dom** with lazy-loaded, code-split routes

No mock data — every screen renders real backend responses.

## Run it

```bash
# 1. Start the backend (from repo root / backend/)
#    The dev proxy in vite.config.ts targets http://127.0.0.1:8001
cd backend && PYTHONPATH=. python -m uvicorn app.main:app --port 8001

# 2. Start the frontend
cd frontend
npm install
npm run dev            # http://localhost:5173
```

`npm run build` runs `tsc --noEmit` then `vite build`; `npm run typecheck`
type-checks only.

### Environment

Only `VITE_`-prefixed variables reach the browser. See `.env.example`:

- `VITE_API_BASE_URL` — defaults to `/api`, which Vite (dev) and nginx (Docker)
  proxy to the backend. Set an absolute URL to target a deployed backend.

## Architecture

```
src/
  api/            auditor-types.ts (contract mirror) · auditor.ts (client)
  lib/            theme · store (audit state + local history) · format · icons · cn · sample
  components/
    ui.tsx        primitives: Button, Card, Badge, ScoreBar, Counter, Disclosure, SegmentedControl, Tooltip, Skeleton
    brand.tsx     Logo, ThemeToggle, radial Gauge
    AppShell.tsx  sidebar · topbar · breadcrumbs · footer · ⌘K command palette · mobile drawer
    states.tsx    LoadingReport · ErrorState · EmptyState
    report/       verdict · metrics · findings · recommendations · evidence · comparison · output-audit
  pages/          Landing · Audit · Report · History · Settings · NotFound
```

### Design system

Semantic tokens live in `src/index.css` as RGB triplets and are mapped to
Tailwind colors in `tailwind.config.js` (`canvas`, `surface`, `content`,
`brand`, `verdict.*`, `severity.*`). Switching `data-theme` on `<html>` swaps
every color at once. The theme is set before first paint by an inline script in
`index.html` to avoid a flash.

### Data flow

1. **Audit** page collects a source + N outputs and calls `store.run()` →
   `POST /audit/outputs`.
2. The `ComparativeReport` is rendered on **Report**, and both the report and the
   raw input text are cached in `localStorage` (there is no server-side report
   store) so `/report/:id` links and **History** resolve offline.
3. The **evidence explorer** re-hydrates the source/output text to highlight the
   exact spans behind each attribution and finding.

## Notes

- The report carries span snippets + source metadata, not the full source text;
  the evidence explorer uses the locally-cached input text for full highlighting
  and falls back to snippet cards otherwise (e.g. URL inputs).
- Accessibility: keyboard-navigable, visible focus rings, ARIA roles on tabs /
  breadcrumbs / dialogs, and `prefers-reduced-motion` support.
