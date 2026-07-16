# AI Trust & Quality Auditor

Evaluates AI-generated content and returns a complete, evidence-backed audit: **what** the verdict is, **what evidence** supports it, **how confident** the auditor is, and **what to fix**.

The output is never just a number. It is a verdict with evidence, confidence, critical findings, and prioritized recommendations.

> **Milestone 1 — engineering foundation.** The full architecture, every contract, and the runnable stack are in place. The eight audit engines and the Decision Engine workflow land in Milestone 2, so **every audit currently returns `Unable to Verify` with nothing measured**. That is the honest verdict for a system that has checked nothing — see [Milestone status](#milestone-status).

---

## Contents

- [What it does](#what-it-does)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Architecture](#architecture)
- [Project structure](#project-structure)
- [API](#api)
- [Milestone status](#milestone-status)
- [Specification documents](#specification-documents)

---

## What it does

As AI-generated text spreads, the hard problem is no longer producing content but **knowing which output to trust**. Confident, fluent, well-formatted text can still be hallucinated, mis-sourced, off-instruction, or incomplete.

Eight independent audit engines each measure one dimension:

| Dimension | Type | Governing question |
|---|---|---|
| **Relevance** | Hybrid | Does the output satisfy the user's instruction and intent? |
| **Accuracy** | Trust | Is every factual claim supported, contradicted, or unverifiable? |
| **Coverage** | Hybrid | Does it include all important information from the reference source? |
| **Credibility** | Trust | Are claims backed by trustworthy, correctly cited, verifiable sources? |
| **Novelty** | Quality | Does it communicate efficiently, without unnecessary repetition? |
| **Readability** | Quality | Is it clear, coherent, and well structured? |
| **Engagement** | Quality | Does it help the user without manipulative communication? |
| **Diversity** | Quality (N/A-capable) | Where appropriate, are legitimate perspectives fairly represented? |

### The four ideas that shape the whole design

- **Evidence-first.** Every conclusion links to concrete evidence — a span, a passage, a source lookup.
- **Non-compensatory trust.** One qualifying critical finding — a fabricated citation, a contradicted claim — gates the verdict to *Untrusted* regardless of every other score. Trust is a floor, not an average.
- **Honest uncertainty.** When the evidence cannot settle the question, the auditor returns *Unable to Verify* rather than guessing. Undetermined is not the same as failed.
- **Two-axis separation.** Trust and Quality are evaluated by different logic (non-compensatory vs. compensatory) and reported **separately** — never fused into one number. Content can be polished yet untrustworthy, or accurate yet badly organized.

---

## Quick start

**Prerequisites:** Python 3.11+ and Node 18+.

### Backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt   # pulls torch via sentence-transformers; a few minutes

cp .env.example .env      # then add your Groq key (optional in Milestone 1)

uvicorn app.main:app --reload
```

Backend runs at **http://127.0.0.1:8000** — interactive API docs at **/docs**.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at **http://localhost:5173** and proxies `/api` to the backend.

### Verify

```bash
curl http://127.0.0.1:8000/health
```

```json
{ "status": "ok", "llm_provider": "groq", "llm_model": "qwen/qwen3-32b",
  "version": "1.0", "llm_configured": false, "llm_reachable": false,
  "engines_registered": 8, "embedding_model": "all-MiniLM-L6-v2",
  "embedding_cache_enabled": true, "embedding_cache_hit_rate": 0.0 }
```

`engines_registered: 8` confirms all eight engines registered at startup. `llm_configured: false` is expected until you add a key — the Navbar shows this as a status dot, because a backend that cannot reach its provider will degrade every trust dimension and return *Unable to Verify* for everything. That is correct behavior, but you should be able to see *why*.

---

## Configuration

Two layered sources. **The environment wins over YAML**, so a deployment can retune without editing files.

| Source | Holds | Committed? |
|---|---|---|
| `config/settings.yaml` | Thresholds, weights, model and provider selection | Yes |
| `backend/.env` | Secrets and per-deployment overrides | **No** |

Two environment spellings, both supported:

- **Flat, documented names** — what `.env.example` sets and most deployments use.
- **Prefixed names** — `AUDITOR_*` with `__` for nesting (`AUDITOR_DECISION__MIN_TRUST_CONFIDENCE`). These reach every field, including ones with no flat alias.

```bash
GROQ_API_KEY=gsk_...          # https://console.groq.com/keys
LLM_PROVIDER=groq
LLM_MODEL=qwen/qwen3-32b
```

Thresholds and weights are **configuration, not code**. Retuning one moves where a line sits; it can never change the rules themselves — a qualifying critical finding always gates trust, and insufficient confidence always blocks a *Trusted* verdict.

### LLM provider

**Groq is active** (`app/shared/llm_providers/groq.py`), on the free tier. The default model `qwen/qwen3-32b` is a reasoning model, so `llm.reasoning_format: hidden` in `settings.yaml` suppresses its `<think>` block — without that it corrupts the structured JSON the engine pipelines parse.

The API key is resolved **per provider** (`GROQ_API_KEY` for Groq, `OPENROUTER_API_KEY` for OpenRouter), so adding a paid provider later means adding its key alongside the one you already have, not renaming it.

#### Enabling the paid provider (OpenRouter)

The OpenRouter provider is fully written and ships **commented out**:

1. Uncomment the two `PAID PROVIDER` blocks in `app/shared/llm_providers/registry.py`.
2. Uncomment `OPENROUTER_API_KEY` / `LLM_PROVIDER` / `LLM_MODEL` in `backend/.env` and add your key.
3. Set `reasoning_format: null` in `config/settings.yaml` — it is Groq-specific.

No engine, service, or Decision Engine code changes. That is the provider seam doing its job.

#### Adding another provider

Two steps, touching **no engine**: implement `LLMProvider` in `app/shared/llm_providers/`, register it in `registry.py`, then set `LLM_PROVIDER=<key>`. Engines call the Shared LLM Service, which resolves the provider from config — they never see a provider SDK.

### Embedding cache

Relevance and Novelty both embed sentences of the same AI Output, in different waves. Without a cache the same text is encoded twice per audit. The cache is **application-scoped**, so it also spans runs: re-auditing the same content, or two texts sharing boilerplate, costs one encode.

It is keyed by **model and text together** — vectors from different models are not comparable, and returning the wrong one would not error, it would silently produce wrong similarity scores. `embedding_cache_hit_rate` on `/health` makes effectiveness observable; a rate near zero usually means the model id is changing between calls.

Tune with `embedding.cache_enabled` and `embedding.cache_max_entries` in `settings.yaml`.

---

## Architecture

```
Configuration          (thresholds, weights, models, prompts)
     │
     ▼
Shared Services        (LLM · Embedding · Retrieval · Prompts · Evidence ·
     │                  Recommendation · Confidence · Validators · Schemas)
     ▼
Audit Engines ×8       each produces an AuditResult
     │                 (cross-engine inputs: Coverage → Novelty;
     │                  {Rel, Cov, Read, Nov} → Engagement)
     ▼
Decision Engine        consumes the eight AuditResults → DecisionResult
     │
     ▼
API Layer              returns the AuditReport by audit_id
     │
     ▼
Frontend               renders verdicts, evidence, recommendations
```

**The dividing line:** engines *measure*; the Decision Engine *decides*; the frontend *presents*.

Two contracts are the stable seams of the system:

- **`AuditResult`** — every engine returns the same seven-field shape. The Decision Engine depends only on this, never on engine internals, which is what lets engines evolve without touching decision logic.
- **`AuditReport`** — the API and frontend depend only on this.

### SharedContext

Preprocessing produces a **`SharedContext`** (`app/shared/context.py`) — the single source of truth for one run, passed to every engine. It carries the Engine Input Contract (`ai_output`, `prompt`, `reference_source`) and owns every derivation of it that more than one engine needs.

**Two caching tiers, chosen by cost:**

| Tier | For | Why |
|---|---|---|
| Lazy properties — `sentences`, `paragraphs`, `statistics`, `metadata` | Pure CPU, milliseconds | Sync, so no two engines can interleave mid-computation on one event loop; no lock needed |
| `await get_or_compute(key, factory)` | Expensive or IO-bound — embeddings, chunks, fetches | Per-key async lock, because engines in the same wave genuinely race |

```python
for sentence in context.sentences:          # lazy, memoized, offsets included
    ...

chunks = await context.get_or_compute(       # computed once even under a race
    "reference_chunks",
    lambda: retrieval.chunk(context.reference_source),
)
```

Using the async path for a regex split would cost more in lock overhead than the split; using the sync path for a network fetch would block the loop six engines are running on. Hence two tiers.

**The rule that keeps it evaluation-neutral:**

> Deriving *what the text is* — its sentences, its word count, its detected language — is infrastructure, identical for every engine, and lives here. Deciding *whether that is any good* is a frozen pipeline stage and lives in the engine.

Novelty still performs "Text Segmentation" at its stage 2; it reads `context.sentences` instead of carrying its own splitter. Relevance still performs its Deterministic Constraint Checks at stage 7; it reads `context.metadata.language` rather than re-detecting. **Reuse of a mechanism is not relocation of a stage** — that distinction is what makes this spec-compliant rather than a redesign.

### Shared framework (Milestone 2)

Every engine reuses these; none reimplements them.

| Component | Module | Responsibility |
|---|---|---|
| **Text segmentation** | `shared/text_segmentation.py` | Sentences, paragraphs, and `locate_span`. Every span carries source offsets, so `text[span.start:span.end] == span.text` — the invariant the Evidence Viewer depends on. |
| **Document analysis** | `shared/document_analysis.py` | Statistics and metadata. Measured facts only: "470 words, reads as English" is a fact; "violates the 200-word limit" is Relevance's judgment. |
| **LLM Extraction** (§5.1) | `shared/extraction/` | Requirements, Claims, Key Points, Citations — one base class, four instantiations. |
| **Classification** (§5.2) | `shared/classification/` | Hard/Soft, Factual/Opinion, centrality, salience, category/severity, source class. |
| **Verification** (§5.4) | `shared/verification/` | The four judges and their frozen verdict vocabularies. |
| **Confidence** (§5.10) | `shared/confidence_service.py` | Weighted mean over explicit, individually-explainable signals. |
| **Retrieval** (§5.3) | `shared/retrieval_service.py` | Chunking, embedding search, source fetching. |
| **Validators** (§5.6) | `shared/deterministic_validators.py` | Constraint checks, URL/DOI resolution. Zero model variability. |
| **Prompt Manager** | `shared/prompt_manager.py` | Versioned templates from `config/prompts/<engine>/<stage>.<version>.md`. Strict rendering: a missing variable raises *before* the model is called. |
| **Evidence pipeline** | `shared/evidence_pipeline.py` | `EvidenceCollector` (per-dimension façade), `verify_links`, and formatters for the two consumers — an LLM judge and a human reader. |
| **Orchestrator** | `audit_engines/orchestrator.py` | Wave execution with `asyncio.gather`, real progress, and `validate_plan()` asserting the frozen ordering at startup. |

**Extraction extracts; it does not classify.** Document 2 keeps LLM Extraction (§5.1) and Classification & Weighting (§5.2) as *separate* shared components, and the frozen pipelines run them as separate stages. So every `Requirement` comes back from extraction with `requirement_type=None` and every `Claim` with `claim_type=None, centrality=None` — the engine fills them at the stage that owns them. A violated **hard** requirement gates trust non-compensatorily while a missed **soft** one does not; deciding that inside extraction would move a trust gate into a stage the specification never gave one.

### The two axes, in the engines

The clearest expression of Document 3 §8's design is Accuracy's treatment of an unverifiable claim:

| Case | Score | Confidence | Decision Engine reads it as |
|---|---|---|---|
| Claim contradicted by evidence | **low** | high | *Untrusted* — a confident negative, with a Critical Finding |
| Claim unverifiable (no evidence) | **high** | **low** | *Unable to Verify* — honest uncertainty |
| No reference source supplied | 1.0 | **0.32** | *Unable to Verify* — nothing was checked |

Unverifiable claims are **excluded from the score, not scored as zero.** The score answers "of what could be checked, how much held up?" — scoring an unchecked claim zero would report unverified content as *inaccurate*, which is a false accusation. The cost lands on confidence instead. Coverage does the same for a missing reference: zero confidence, not a zero score, because "we never looked" is not "the output is incomplete."

### Engine execution order

Not a performance choice — a data dependency. Running Novelty before Coverage would not be slower, it would be *wrong*:

| Wave | Engines | Why |
|---|---|---|
| 1 (parallel) | Relevance, Accuracy, Coverage, Credibility, Readability, Diversity | No cross-engine inputs |
| 2 | Novelty | Performs a Coverage cross-check |
| 3 | Engagement | Reuses Relevance, Coverage, Readability, Novelty results |

---

## Project structure

```
auditor/
├── backend/
│   ├── app/
│   │   ├── main.py                 # ASGI entry: uvicorn app.main:app
│   │   ├── app.py                  # service container / dependency injection
│   │   ├── core/
│   │   │   ├── config.py           # Configuration Manager (YAML + env)
│   │   │   ├── constants.py        # frozen dimension matrix + execution waves
│   │   │   ├── errors.py           # error taxonomy → wire contract
│   │   │   └── logging.py          # structured logging (ids, not content)
│   │   ├── shared/
│   │   │   ├── schemas.py          # AuditResult + AuditReport — the contract
│   │   │   ├── context.py          # SharedContext — single source of truth
│   │   │   ├── text_segmentation.py# sentences, paragraphs, locatable spans
│   │   │   ├── document_analysis.py# statistics + metadata (facts, not verdicts)
│   │   │   ├── vocabularies.py     # Doc 2 §6.4 — the frozen verdict sets
│   │   │   ├── llm_stage.py        # shared: render prompt → call → parse
│   │   │   ├── extraction/         # §5.1 — requirements · claims · key points · citations
│   │   │   ├── classification/     # §5.2 — hard/soft · claim type · centrality
│   │   │   │                       #        salience · category/severity · source class
│   │   │   ├── verification/       # §5.4 — the four judges
│   │   │   ├── mapping.py          # Credibility stage 3 — claim → citation
│   │   │   ├── scoring.py          # §5.9 — shared scoring arithmetic
│   │   │   ├── evidence_pipeline.py# collector · link check · formatters
│   │   │   ├── llm_service.py      # retries, timeouts, JSON policy
│   │   │   ├── llm_providers/      # base · groq (active) · openrouter (gated)
│   │   │   ├── embedding_service.py# + shared, model-keyed embedding cache
│   │   │   ├── retrieval_service.py
│   │   │   ├── prompt_manager.py   # versioned templates from config/prompts/
│   │   │   ├── evidence_store.py
│   │   │   ├── recommendation_service.py
│   │   │   ├── confidence_service.py
│   │   │   └── deterministic_validators.py
│   │   ├── audit_engines/
│   │   │   ├── base.py             # AuditEngine ABC (timeout + degradation)
│   │   │   ├── registry.py         # dimension → engine class
│   │   │   ├── orchestrator.py     # frozen wave schedule
│   │   │   └── {relevance,accuracy,coverage,credibility,
│   │   │       novelty,readability,engagement,diversity}.py
│   │   ├── decision_engine/
│   │   │   ├── workflow.py         # ordered pipeline + verdict resolution
│   │   │   ├── applicability.py    # Stage 3 — N/A exclusion
│   │   │   ├── critical_findings.py# Stage 4 — non-compensatory gating
│   │   │   ├── trust_eval.py       # Stage 5 — worst-case trust
│   │   │   ├── quality_eval.py     # Stage 6 — compensatory quality
│   │   │   ├── confidence_integration.py  # Stage 7 — assertability
│   │   │   ├── recommendations.py  # Stage 8 — prioritization
│   │   │   └── report_builder.py   # Stage 10 — Final Audit Report
│   │   ├── preprocessing/
│   │   │   ├── input_router.py     # text / url / file → SharedContext
│   │   │   └── content_extractor.py
│   │   └── api/
│   │       ├── main.py             # app factory, CORS, error contract
│   │       ├── routes_audit.py     # POST /audit, /audit/{text,url,file}, status
│   │       ├── routes_report.py    # GET /report/{id}
│   │       ├── routes_health.py    # GET /health
│   │       ├── jobs.py             # async job store
│   │       ├── models.py           # request/response models
│   │       └── dependencies.py     # FastAPI DI providers
│   ├── requirements.txt            # runtime + sentence-transformers
│   ├── requirements-m2.txt         # remaining audit-time libraries
│   └── .env.example
├── frontend/
│   └── src/
│       ├── App.tsx                 # routing
│       ├── api/
│       │   ├── client.ts           # the shared API client
│       │   └── types.ts            # TypeScript mirror of the contracts
│       ├── pages/                  # Dashboard, AuditPage, ResultsPage
│       └── components/             # Navbar, InputPanel, ReportPanel, LoadingState
├── config/
│   ├── settings.yaml               # thresholds, weights, models
│   └── prompts/                    # one dir per engine; <stage>.<version>.md
│       ├── accuracy/              # extraction · classification · centrality · verification
│       ├── credibility/           # extraction · mapping · grounding · source class
│       ├── relevance/             # extraction · classification · evaluation
│       ├── coverage/              # extraction · salience · category/severity · verification
│       └── {novelty,readability,engagement,diversity}/   # Milestone 4
├── datasets/                       # validation fixtures (good/medium/poor)
└── docs/                           # Documents 1–4
```

**Note on layout.** Document 4 §3 specifies `backend/audit_engines/`, `backend/shared/`, and so on. Those modules live under `backend/app/` so that `uvicorn app.main:app` works from `backend/`. Every module name and responsibility is unchanged.

---

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/audit` | Audit text or a URL; returns the report directly |
| `POST` | `/audit/text` | Audit raw text (async → `audit_id`) |
| `POST` | `/audit/url` | Fetch, extract, audit a URL (async) |
| `POST` | `/audit/file` | Upload txt/md/pdf, extract, audit (async) |
| `GET` | `/audit/{id}/status` | Poll job status and **real** engine progress |
| `GET` | `/report/{id}` | Retrieve the Final Audit Report |
| `GET` | `/health` | Liveness and readiness |

Auditing is asynchronous because a run makes many LLM calls. `POST /audit` is the synchronous convenience path; the type-specific endpoints create a job and let the client poll.

```bash
curl -X POST http://127.0.0.1:8000/audit \
  -H "Content-Type: application/json" \
  -d '{"text": "...AI output under audit...", "prompt": "...original instruction..."}'
```

**The two optional fields matter more than they look:**

- `prompt` — Relevance, Engagement, and Diversity measure the output *against stated intent*. Without it, those three have nothing to compare to.
- `reference_source` — optional for Accuracy, but **Coverage requires it to score**: completeness is meaningless without something to be complete with respect to.

**Error contract.** Every non-2xx returns `{ "error": { "code": "...", "message": "..." } }`.

---

## Milestone status

### Done — Milestone 1 (foundation)

Folder structure, configuration, logging, the frozen `AuditResult` / `AuditReport` contracts, the provider seam, the engine registry and base class, the API surface, and the React frontend.

### Done — Milestone 2 (shared framework)

The infrastructure every engine reuses, so no engine reimplements it: preprocessing (segmentation with source offsets, statistics, metadata), `SharedContext` with two-tier lazy caching, LLM Extraction (§5.1), the Prompt Manager, the evidence pipeline, and the orchestrator's wave execution.

### Done — Milestone 3 (Trust and Hybrid engines)

All four **Critical-Finding-capable** engines, each following its frozen pipeline stage by stage:

| Engine | Type | Detects | Critical Finding |
|---|---|---|---|
| **Accuracy** | Trust | Contradicted claims against retrieved evidence | Contradicted claim |
| **Credibility** | Trust | Citations that don't resolve, or resolve to the wrong thing | Fabricated / Misattributed citation |
| **Relevance** | Hybrid | Unmet instructions, scope drift, constraint violations | Violated hard requirement |
| **Coverage** | Hybrid | Salient information dropped from the source | Critical omission |

Plus the shared components they required: Classification & Weighting (§5.2), LLM Verification / Judge (§5.4), the Confidence Estimator (§5.10), Retrieval (chunking, embedding search, fetching), Deterministic Validators (constraints, URL/DOI), the local embedding backend, and 15 prompt templates.

### Why every audit still says *Unable to Verify*

`POST /audit` returns a placeholder report from `report_builder.build_placeholder_report`. **Its verdict is a safety property, not a filler value.** The engines now measure, but the **Decision Engine that turns eight `AuditResult`s into a verdict is Milestone 4** — so nothing yet interprets them, and trust remains genuinely undetermined.

The orchestrator is complete and verified, but is **not yet wired into the route**: without the Decision Engine it would run eight engines and discard the results. The seam is one call in `routes_audit._run_audit`.

### Milestone 4 — Quality engines, Decision Engine, validation

1. **Novelty, Readability, Engagement, Diversity** (Document 2 §7.5–§7.8). The shared framework is in place: subclass `LLMJudge` / `LLMClassifier`, add a prompt. Two shared validators remain — `analyze_readability` and `detect_manipulation_patterns`.
2. **Decision Engine workflow** (Document 3 §4) — the stage modules, then `DecisionEngine.decide` and `build_report`. `resolve_verdict` is already done and is the correctness core.
3. **Swap the placeholder** — replace the `build_placeholder_report` call in `routes_audit._run_audit` with the orchestrator + Decision Engine. No route signatures change.
4. **URL and file input** — `content_extractor.from_url` / `from_file`, and the matching `input_router` paths.
5. **Finish the frontend** — Evidence Viewer drill-through, dimension cards, async polling, report export.
6. **Tests** (Document 4 §10) — `tests/{unit,engines,decision,api,e2e}/`. The Decision Engine suite must be exhaustive on gate logic: it is deterministic given inputs, so it is both the correctness core and cheap to test.
7. **Validation** (Document 4 §11) — the good/medium/poor corpus, proving the auditor separates good content from bad. **This is where the engine thresholds get tuned** — `config/settings.yaml` `engines.*` — against real samples rather than reasoning.
8. **Packaging** — `Dockerfile` and `docker-compose.yml`.

---

## Specification documents

The frozen source of truth. Read Document 1 first.

| Document | Answers |
|---|---|
| **1 — Master Guide** | How does it all fit together? Where do I look? |
| **2 — Audit Engine Specifications** | How is each dimension measured? (`AuditResult` contract) |
| **3 — Decision Engine Specification** | How do results become a verdict? (`AuditReport`) |
| **4 — Implementation & Validation** | How do we build, test, validate, and demo it? |

Build against the frozen contracts. Do not redesign engines, decision rules, or shared services.
