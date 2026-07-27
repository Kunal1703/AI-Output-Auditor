# AI Output Auditor

Audits one or more **outputs** (human- or LLM-written summaries and answers)
against a **source article**, and returns an evidence-backed **comparative
report**: which output is more trustworthy, why, and what to fix.

Every verdict traces to a source span. No external knowledge is used — the source
article is the only ground truth.

> **Add a `GROQ_API_KEY`** (in `backend/.env`) to run a real audit. Without one,
> claim extraction degrades and the audit returns *Unable to Verify* — the honest
> verdict for a system that could not check anything. The local NLI grounding and
> the deterministic checks (numeric accuracy, redundancy, bias) run regardless.

---

## What it does

As AI-generated text spreads, the hard problem is no longer producing content but
**knowing which output to trust**. Confident, fluent text can still be
hallucinated, misquote a figure, drop the key fact, or editorialize.

The auditor evaluates each output against the source across a **layered,
non-compensatory** framework — a grounding failure caps the verdict no matter how
well the output reads:

| Layer | Role | Metrics |
|---|---|---|
| **1 · Grounding** | Gating (non-compensatory) | Faithfulness · Numeric Accuracy · Hallucinations · Unsupported Claims · Contradictions |
| **2 · Information Quality** | Partial gating | Coverage · Missing Critical Facts · Meaning Preservation |
| **3 · Presentation** | Compensatory | Readability · Conciseness · Bias / Objectivity |

The verdict per output is one of **Excellent / Good / Needs Revision / Fail /
Unable to Verify**, and outputs are ranked side by side with a clear winner.

### How grounding works — cheap and reproducible

A **local NLI cross-encoder** (`cross-encoder/nli-deberta-v3-base`) does the
grounding: it retrieves candidate source spans per output claim and labels each
`supported / neutral / contradicted` on CPU, at **zero token cost**. The scarce
LLM budget is spent only on claim/key-point extraction, where a model is genuinely
needed. Numeric accuracy, conciseness, and bias are fully deterministic.

---

## Quick start

### With Docker (full stack)

```bash
cp backend/.env.example backend/.env      # add your GROQ_API_KEY
docker compose up --build
# frontend → http://localhost:5173
# backend  → http://localhost:8000/docs
```

The first build installs `torch` and bakes in the embedding + NLI models; expect
several minutes. Subsequent builds are cached.

### Local development

```bash
# Backend (from repo root)
cd backend
python -m venv .venv && source .venv/bin/activate   # or your preferred env
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8001          # matches the Vite dev proxy

# Frontend (in another terminal)
cd frontend
npm install
npm run dev                                         # http://localhost:5173
```

---

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/audit/outputs` | Audit `{ source, outputs[] }` → `ComparativeReport` (synchronous). |
| `GET` | `/health` | Liveness/readiness: provider, model availability, `nli_ready`. |

```jsonc
// POST /audit/outputs
{
  "source": { "text": "The company reported revenue of $5.2 billion in 2023. …" },
  "outputs": [
    { "producer": "human", "output_type": "summary", "text": "…" },
    { "producer": "llm",   "output_type": "summary", "text": "…" }
  ]
}
```

The response is a `ComparativeReport`: per-output `OutputAudit` (verdict, layered
metric results, findings, recommendations, confidence, and the attribution map)
plus a ranked `Comparison`. See `backend/app/shared/schemas.py`.

---

## Project structure

```
backend/app/
├── core/              config · logging · errors · metric matrix
├── shared/            LLM · embeddings · NLI · retrieval · evidence · extraction
│                      contexts (source/output) · schemas · deterministic validators
├── attribution/       retrieve-then-entail grounding substrate
├── evaluators/        the 7 metric evaluators (pure computation units)
├── orchestration/     Audit Orchestrator · layered Decision Engine · report assembly
├── preprocessing/     {source, outputs[]} → audit contexts
└── api/               FastAPI surface (/audit/outputs, /health)

config/
├── settings.yaml      thresholds & weights (all tunables)
└── prompts/           the 3 LLM prompt templates (claim & key-point extraction, salience)

frontend/              Veritas — the React SPA (see frontend/README.md)
```

---

## Configuration

All tunables live in `config/settings.yaml`; secrets and per-deployment overrides
come from `backend/.env` (see `.env.example`). Notable knobs:

- `nli.model` / `nli.entail_threshold` — the grounding backbone.
- `attribution.top_k` / `contradiction_threshold` — retrieval + NLI dials.
- `verdict.*` — verdict bands, minimum grounding confidence, per-metric weights.
- `numeric.*`, `coverage.*`, `meaning.*`, `bias.*` — per-evaluator thresholds.

The environment wins over YAML. Provider keys are per-provider (`GROQ_API_KEY`,
`OPENROUTER_API_KEY`).

---

The frontend is documented in [`frontend/README.md`](frontend/README.md).
