# AI Trust & Quality Auditor — Engineering Handoff

**Audience:** a senior engineer (or a fresh Claude Code session) with zero prior context.
**Status:** ✅ **Complete.** All six milestones done and verified. The system is production-ready; the only open item is running the validation corpus against a live Groq key (see §11).
**Purpose:** the single source of truth for continuing this build. You should not need any prior conversation.

**Read this document first, then Documents 1–4 in `docs/`.** This document tells you what exists and why; Documents 1–4 are the frozen specification and win any disagreement.

> ### ⚙️ Production hardening update (M7.1–M7.4)
>
> The body of this handoff is the original build record. These operational facts
> supersede it where they conflict (no architecture changed):
>
> - **LLM model is now `llama-3.3-70b-versatile`, not `qwen/qwen3-32b`.** Groq
>   retired qwen3-32b (completions 404'd). llama-3.3-70b is non-reasoning, so
>   `reasoning_format` and `reasoning_effort` are `null` (Groq 400s if either is
>   sent to a non-reasoning model). Closest reasoning successor if switching back:
>   `qwen/qwen3.6-27b` with `reasoning_format: hidden` + `reasoning_effort: none`.
> - **Startup model validation** (`ServiceContainer.verify_model`, called in the
>   app lifespan) fails fast if `llm.model` is not served; `/health` reports
>   `llm_model_available`.
> - **Free-tier pacing.** A client-side token limiter (`llm.tokens_per_minute`),
>   `max_tokens: 1024`, and `retry_after_cap_seconds` keep the eight-engine wave
>   under Groq's per-minute limit. The **per-day** limit (TPD ≈ 100k) caps usage
>   to ~3–6 reference-heavy audits/day; a full audit takes a few minutes by
>   design. A paid tier removes this (`tokens_per_minute: 0`).
> - **Two correctness fixes.** (1) An LLM judge may cite only evidence it was
>   shown (`shared/verification/base.py`), and an empty `{}` response is "no
>   records", not an error (`shared/llm_stage.py`). (2) A `must_contain` substring
>   *miss* no longer overrides a semantic "Satisfied" into a false trust-gating
>   "Violated" (`audit_engines/relevance.py`) — it was producing false *Untrusted*
>   verdicts on good content.
> - **Input validation.** File uploads strip YAML front matter; whitespace-only
>   text is rejected 422.
> - **Known boundary (by design):** content submitted **without a reference
>   source** routes to *Unable to Verify* — Coverage (trust-relevant, no N/A)
>   returns a verification gap and Accuracy can't verify claims without evidence.
>   Provide a `reference_source` (or enable external retrieval) for a definite
>   trust verdict.

---

## Table of contents

1. [Project overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [The four specification documents](#3-the-four-specification-documents)
4. [Implementation status](#4-implementation-status)
5. [Completed milestones](#5-completed-milestones)
6. [Engine implementations](#6-engine-implementations)
7. [Shared framework](#7-shared-framework)
8. [Configuration](#8-configuration)
9. [Important engineering decisions](#9-important-engineering-decisions)
10. [Verified behavior](#10-verified-behavior)
11. [Remaining work](#11-remaining-work)
12. [FROZEN ARCHITECTURE — do not change](#12-frozen-architecture--do-not-change)
13. [Continue from here](#13-continue-from-here)

---

## 1. Project overview

### Goal

Build a system that evaluates AI-generated content — summaries, reports, articles, answers — and returns a **complete, evidence-backed audit**: what the verdict is, what evidence supports it, how confident the auditor is, and what to fix.

### The problem it solves

As AI-generated text proliferates, producing content is no longer the hard part. **Knowing which output to trust is.** Confident, fluent, well-formatted text can still be hallucinated, mis-sourced, off-instruction, or incomplete. Every one of those failures is invisible to a reader who is not already an expert on the subject.

### Product vision

Not a score. A **verdict with evidence, confidence, critical findings, and prioritized recommendations** — the output of something behaving like a real auditor rather than a rubric.

The user pastes text (or a URL), and gets back:

- an **Overall Verdict** — Trusted / Trusted with Caveats / Needs Revision / Untrusted / Unable to Verify
- a **Trust Verdict** and a **Quality Verdict**, reported separately and never fused
- **Critical Findings** with the evidence that proves them
- **per-dimension results** — score, confidence, and a full ledger, drillable to the exact span
- **prioritized recommendations**, each bound to its evidence

### System philosophy — the four ideas everything else serves

These are not aspirations. They are the invariants the code is built to hold, and most of the non-obvious design decisions in this project exist to protect one of them.

1. **Evidence-first.** Every conclusion links to concrete evidence — a span, a passage, a source lookup. A finding with nothing to point at is not emitted.

2. **Non-compensatory trust.** One qualifying critical finding — a fabricated citation, a contradicted claim — gates the verdict to *Untrusted* regardless of every other score. **Trust is a floor, not an average.** Strengths never average a critical failure away.

3. **Honest uncertainty.** When the evidence cannot settle the question, the auditor returns *Unable to Verify* rather than guessing. **Undetermined is not the same as failed**, and neither is the same as passed. This is the axis most systems collapse, and collapsing it is the failure mode this project exists to prevent.

4. **Two-axis separation.** Trust (non-compensatory) and Quality (compensatory) are evaluated by *different logic* and reported *separately*. Content can be polished yet untrustworthy; accurate yet badly organized. Fusing them into one number destroys the distinction the system exists to draw.

### High-level workflow

```
User submits text | URL | file
        ↓
Preprocessing            normalize; extract clean content
        ↓
SharedContext            the single source of truth for one run
        ↓
8 Audit Engines          measure, in three dependency-ordered waves
        ↓
8 AuditResults           the frozen contract — score, confidence, ledger,
                         evidence, recommendations, critical findings, metadata
        ↓
Decision Engine          validate → applicability → critical findings → trust
                         → quality → confidence → recommendations → verdict
        ↓
AuditReport              the frozen deliverable
        ↓
API → Frontend           verdicts, dimension cards, evidence, export
```

### The dividing line to remember

> **Engines measure. The Decision Engine decides. The frontend presents.**

An engine never renders a verdict. The Decision Engine never re-measures. The frontend never computes. Keep these separate and the system stays testable; blur them and it does not.

---

## 2. Architecture

### Diagram

```
┌───────────────────────────────────────────────────────────────────────┐
│  FRONTEND  (React + Vite + TypeScript + Tailwind)                      │
│  pages: Dashboard · AuditPage · ResultsPage                            │
│  components: Navbar · InputPanel · ReportPanel · LoadingState          │
│  api/client.ts  ← the ONLY place the frontend calls the backend        │
│  api/types.ts   ← TypeScript mirror of the frozen contracts            │
└──────────────────────────────┬────────────────────────────────────────┘
                               │  HTTP  (Vite proxies /api → :8000)
┌──────────────────────────────▼────────────────────────────────────────┐
│  API LAYER   (FastAPI)   — thin; NO audit or decision logic            │
│  routes_audit · routes_report · routes_health · jobs · models          │
│  Error contract: { "error": { "code": ..., "message": ... } }          │
└──────────────────────────────┬────────────────────────────────────────┘
                               │
┌──────────────────────────────▼────────────────────────────────────────┐
│  PREPROCESSING     input_router · content_extractor                    │
│  text | url | file  →  PreprocessedContent  →  SharedContext           │
│  Normalizes. Never evaluates.                                          │
└──────────────────────────────┬────────────────────────────────────────┘
                               │
┌──────────────────────────────▼────────────────────────────────────────┐
│  SHAREDCONTEXT  — single source of truth, one per run                  │
│                                                                       │
│  Engine Input Contract (Doc 2 §6.1): ai_output · prompt ·             │
│                                       reference_source                 │
│  Lazy tier  (sync, memoized): sentences · paragraphs · statistics ·    │
│                                metadata · reference_* · prompt_*       │
│  Async tier (per-key locked): get_or_compute(key, factory)             │
│    SharedKeys.EXTRACTED_CLAIMS   ← Accuracy + Credibility share this   │
│    SharedKeys.REFERENCE_CHUNKS   ← Accuracy                            │
└──────────────────────────────┬────────────────────────────────────────┘
                               │  the SAME instance goes to every engine
┌──────────────────────────────▼────────────────────────────────────────┐
│  ENGINE ORCHESTRATOR  — frozen wave schedule (Doc 2 §8)                │
│                                                                       │
│   Wave 1 (parallel, asyncio.gather):                                   │
│     Relevance · Accuracy · Coverage · Credibility · Readability ·      │
│     Diversity                                                          │
│   Wave 2:  Novelty        ← needs Coverage (cross-check)               │
│   Wave 3:  Engagement     ← needs Relevance, Coverage, Readability,    │
│                             Novelty                                    │
│                                                                       │
│  validate_plan() asserts this at startup.                             │
│  Ordering is a DATA DEPENDENCY, not a performance choice.             │
└──────────────────────────────┬────────────────────────────────────────┘
                               │
┌──────────────────────────────▼────────────────────────────────────────┐
│  8 AUDIT ENGINES     (each returns the frozen AuditResult)             │
│                                                                       │
│   TRUST      Accuracy ✅        Credibility ✅                          │
│   HYBRID     Relevance ✅       Coverage ✅                             │
│   QUALITY    Novelty ✅  Readability ✅  Engagement ✅  Diversity ✅     │
│                                                     (Diversity: N/A-capable)│
│                                                                       │
│  Only Trust + Hybrid can emit Critical Findings → only they gate trust │
└──────────────────────────────┬────────────────────────────────────────┘
                               │  8 × AuditResult   ← THE STABLE SEAM
┌──────────────────────────────▼────────────────────────────────────────┐
│  DECISION ENGINE  ✅  (Doc 3 §4 — every stage implemented)             │
│  validate → applicability(N/A) → critical findings → trust → quality   │
│  → confidence → recommendations → verdict → report                     │
│  Depends ONLY on the AuditResult contract, never on engine internals.  │
│  PURE: no IO, no LLM, no engine imports. Deterministic given inputs.   │
└──────────────────────────────┬────────────────────────────────────────┘
                               │  AuditReport   ← THE OTHER STABLE SEAM
                               ▼
                        API → Frontend

┌───────────────────────────────────────────────────────────────────────┐
│  SHARED SERVICES   — every engine calls these; none reimplements them  │
│                                                                       │
│  schemas.py          AuditResult + AuditReport  (FROZEN CONTRACT)      │
│  vocabularies.py     the frozen verdict sets (Doc 2 §6.4)             │
│  llm_stage.py        render prompt → call → parse   (shared by ↓)      │
│    extraction/       §5.1  requirements · claims · key points ·        │
│                            citations                                   │
│    classification/   §5.2  hard/soft · claim type · centrality ·       │
│                            salience · category/severity · source class │
│    verification/     §5.4  the four judges                             │
│  mapping.py          Credibility stage 3 (claim → citation)            │
│  llm_service.py      retries · timeouts · JSON policy                  │
│  llm_providers/      base · groq (ACTIVE) · openrouter (commented out) │
│  embedding_service.py  local model + shared model-keyed cache          │
│  retrieval_service.py  chunk · embedding search · fetch                │
│  deterministic_validators.py  constraints · URL/DOI  (zero variance)   │
│  text_segmentation.py  sentences · paragraphs · locate_span            │
│  document_analysis.py  statistics · metadata  (facts, not verdicts)    │
│  evidence_store.py   storage + id minting                              │
│  evidence_pipeline.py  collector · verify_links · formatters           │
│  confidence_service.py  §5.10 weighted mean over explainable signals    │
│  recommendation_service.py  §5.11 shaping + evidence requirement       │
│  scoring.py          §5.9 shared arithmetic                            │
└───────────────────────────────────────────────────────────────────────┘

DEPENDENCY DIRECTION — one way only (Doc 1 §6):
  core/config → shared → audit_engines → decision_engine → api → frontend
  Nothing lower may import something higher. `shared/__init__.py` is
  deliberately import-free to avoid a core↔shared cycle.
```

### Backend architecture

Python 3.11+ / FastAPI / Pydantic v2 / Uvicorn. Layered strictly per Doc 1 §6.

**Composition root:** `backend/app/app.py` (`ServiceContainer`). Everything is constructed once at startup and **injected**. No module reaches for a global. Three scopes, deliberately separated:

| Scope | What lives there | Why |
|---|---|---|
| **Application** | LLM service + provider, embedding model **and cache**, retrieval, prompts, validators, all extraction/classification/verification stages, Decision Engine | Connection pools and the loaded model are shared; the embedding cache spans runs on purpose |
| **Run** | `EvidenceStore`, `RecommendationService` (via `container.engine_services(run_id)`) | They mint ids unique *within a run*; sharing them would let one audit's evidence resolve inside another's report |
| **Per audit** | `SharedContext` | Carries the content and its derivations |

**ASGI entry:** `backend/app/main.py` exposes `app = create_app()` so `uvicorn app.main:app` works from `backend/`.

### Frontend architecture

React 18 + Vite 5 + TypeScript (strict) + Tailwind 3.

- **`src/api/client.ts`** — the only place `fetch` is called. Every component goes through it, so a backend change breaks compilation here rather than surfacing as a blank panel.
- **`src/api/types.ts`** — a TypeScript mirror of the frozen contracts. Keep in sync with `shared/schemas.py`.
- **Routing:** `/` Dashboard · `/audit` AuditPage · `/results` and `/results/:auditId` ResultsPage.
- **The frontend never computes a verdict or score** (Doc 4 §5). It renders what the backend decided.
- Vite proxies `/api` → `http://127.0.0.1:8000`, so the browser sees one origin in dev.

### Data flow

```
AuditRequest  →  PreprocessedContent  →  SharedContext  →  AuditResult ×8
              →  DecisionResult  →  AuditReport
```

| Object | Produced by → Consumed by | Frozen? |
|---|---|---|
| `AuditRequest` | API → Preprocessing | Doc 4 §7 |
| `PreprocessedContent` | Preprocessing → Engines | Doc 2 §6.1 |
| `SharedContext` | Preprocessing → Engines | our design (M2) |
| **`AuditResult`** | each Engine → Decision Engine | **FROZEN — Doc 2 §6.5** |
| `DecisionResult` | Decision Engine → report builder | Doc 3 |
| **`AuditReport`** | report builder → API → Frontend | **FROZEN — Doc 3 §12** |

---

## 3. The four specification documents

Located in `docs/`. **They are frozen.** They win any disagreement with this handoff or with the code.

| Document | File | Owns |
|---|---|---|
| **1 — Master Guide** | `Document-1-Master-Guide.md` | How it all fits together; where to look |
| **2 — Audit Engine Specifications** | `Document-2-Audit-Engine-Specifications.md` | How each dimension is measured; the `AuditResult` contract |
| **3 — Decision Engine Specification** | `Document-3-Decision-Engine-Specification.md` | How results become a verdict; the `AuditReport` |
| **4 — Implementation & Validation** | `Document-4-Implementation-Validation.md` | Stack, structure, API, UI, testing, validation |

### Document 1 — Master Guide

The map. Defines the vision, the layer stack, the runtime flow, the data flow, and the **one-way dependency graph** (§6). **Frozen:** the engineering principles (§11) and the dependency rules. Notably: *"no engine calls a provider or performs IO directly"* and *"the Decision Engine depends only on the `AuditResult` contract."*

### Document 2 — Audit Engine Specifications (**status: Frozen implementation, design locked**)

The measurement layer. The most important document for Milestone 4.

- **§4.1 Dimension Classification & Capability Matrix** — the Trust/Quality/Hybrid types, critical-finding capability, and N/A support for all eight. **Transcribed verbatim into `core/constants.py`.**
- **§5 Shared Components** — §5.1 LLM Extraction · §5.2 Classification & Weighting · §5.3 Retrieval · §5.4 LLM Verification/Judge · §5.5 Embedding Analysis · §5.6 Deterministic Checks · §5.7 Evidence Collection · §5.8 Finding Detection · §5.9 Scoring · §5.10 Confidence Estimation · §5.11 Recommendation Generation. **Our `shared/` package maps 1:1 onto these.**
- **§6.1** Engine Input Contract · **§6.3** ledger names · **§6.4** verdict vocabularies · **§6.5** the `AuditResult` contract.
- **§7.1–§7.8** — the eight frozen pipelines, stage by stage. **Never reorder, merge, or skip a stage.**
- **§8 Cross-Engine Dependencies** — Coverage→Novelty; {Relevance, Coverage, Readability, Novelty}→Engagement. Nothing else.

**Explicitly out of scope (§2):** model selection, prompt text, thresholds, infrastructure, storage. **That is why prompts and thresholds are configuration and why scoring formulas were ours to choose.**

### Document 3 — Decision Engine Specification

The reasoning layer. **Milestone 5.** Defines the ordered workflow (§4), critical-finding processing (§5), trust evaluation (§6), quality evaluation (§7), confidence integration (§8), applicability/N/A (§9), recommendation prioritization (§10), the fixed verdict set and **deterministic resolution order** (§11), and the Final Audit Report (§12).

**Frozen:** the workflow order, the verdict set, the resolution order, and the rules — a qualifying critical finding gates trust; insufficient confidence blocks a Trusted verdict; N/A is excluded not penalized. **Thresholds are configuration.**

### Document 4 — Implementation & Validation

The blueprint. Tech stack (§2), project structure (§3), shared services (§4), module responsibilities and prohibitions (§5), execution flow (§6), API design (§7), frontend workflow (§8), build order (§9), testing (§10), validation (§11), performance/reliability (§12), demo checklist (§13).

**Two deviations from §3, both deliberate and both documented:**

1. Modules live under `backend/app/` rather than `backend/` so `uvicorn app.main:app` works from `backend/`. Every module name and responsibility is unchanged.
2. **LLM provider is Groq, not OpenAI/Ollama.** §2 recommends OpenAI; the user directed Groq. §2 is a *recommendation* ("Prefer the defaults; the alternatives are fallbacks only") and its actual requirement — *"a single provider-agnostic interface lets the team switch via config with no engine changes"* — is fully honored.

---

## 4. Implementation status

### Legend

✅ implemented and verified · 🟡 partial · ⬜ not started (with milestone)

### Folder structure

```
auditor/
├── README.md · .gitignore
├── docs/                                   Documents 1–4 + this handoff
├── config/
│   ├── settings.yaml                       ✅ all thresholds & weights
│   └── prompts/<engine>/<stage>.<version>.md   ✅ 27 templates, 8 dirs
├── datasets/{good,medium,poor}/            ✅ 12 labelled samples + expectations
├── tests/{unit,decision,api,e2e}/          ✅ 120 pytest tests · `pytest -m "not live"`
├── Dockerfile ×2 · docker-compose.yml      ✅ backend + frontend
├── frontend/                               ✅ polling · Evidence Viewer · export
└── backend/
    ├── requirements.txt                    ✅ runtime + sentence-transformers
    ├── requirements-m2.txt                 ✅ remaining audit-time libs
    ├── .env.example                        ✅
    └── app/
        ├── main.py                         ✅ ASGI entry
        ├── app.py                          ✅ ServiceContainer (composition root)
        ├── core/
        │   ├── config.py                   ✅ YAML + env; engines.* thresholds
        │   ├── constants.py                ✅ FROZEN dimension matrix + waves
        │   ├── errors.py                   ✅ taxonomy → wire contract
        │   └── logging.py                  ✅ structured; ids not content
        ├── shared/
        │   ├── schemas.py                  ✅ FROZEN AuditResult + AuditReport
        │   ├── vocabularies.py             ✅ FROZEN verdict sets (§6.4)
        │   ├── context.py                  ✅ SharedContext + SharedKeys
        │   ├── text_segmentation.py        ✅ TextSpan · segmenter · locate_span
        │   ├── document_analysis.py        ✅ statistics · metadata
        │   ├── llm_stage.py                ✅ shared LLM stage machinery
        │   ├── extraction/                 ✅ §5.1 — 5 (+ viewpoints)
        │   ├── classification/             ✅ §5.2 — 10 (+ readability ×2,
        │   │                                  diversity ×2)
        │   ├── verification/               ✅ §5.4 — 9 judges
        │   ├── mapping.py                  ✅ claim → citation
        │   ├── llm_service.py              ✅ retries · timeouts · JSON
        │   ├── llm_providers/              ✅ base · groq · openrouter(gated)
        │   ├── embedding_service.py        ✅ local model + shared cache
        │   ├── retrieval_service.py        ✅ chunk · search · fetch
        │   ├── deterministic_validators.py ✅ constraints · URL/DOI ·
        │   │                                  readability · manipulation
        │   ├── quality_units.py            ✅ M4 units (issue · candidate · …)
        │   ├── task_identification.py      ✅ Engagement stage 2
        │   ├── evidence_store.py           ✅
        │   ├── evidence_pipeline.py        ✅
        │   ├── confidence_service.py       ✅ §5.10
        │   ├── recommendation_service.py   ✅ §5.11
        │   └── scoring.py                  ✅ §5.9
        ├── audit_engines/
        │   ├── base.py                     ✅ AuditEngine + EngineServices
        │   ├── registry.py                 ✅
        │   ├── orchestrator.py             ✅ wave execution + validate_plan
        │   ├── accuracy.py                 ✅ TRUST
        │   ├── credibility.py              ✅ TRUST
        │   ├── relevance.py                ✅ HYBRID
        │   ├── coverage.py                 ✅ HYBRID
        │   ├── novelty.py                  ✅ QUALITY (wave 2)
        │   ├── readability.py              ✅ QUALITY
        │   ├── engagement.py               ✅ QUALITY (wave 3)
        │   └── diversity.py                ✅ QUALITY (N/A branch)
        ├── decision_engine/                ✅ M5 — Doc 3, every stage
        │   ├── workflow.py                 ✅ decide() + resolve_verdict()
        │   ├── applicability.py            ✅ §9 N/A partition
        │   ├── critical_findings.py        ✅ §5 dedupe · order · gate
        │   ├── trust_eval.py               ✅ §6 non-compensatory
        │   ├── quality_eval.py             ✅ §7 compensatory
        │   ├── confidence_integration.py   ✅ §8 assertability gate
        │   ├── recommendations.py          ✅ §10 tiers + evidence
        │   └── report_builder.py           ✅ §12 build_report()
        ├── evaluation/                    ✅ corpus loader + calibration runner
        │   ├── corpus.py                       labelled samples + expectations
        │   └── calibrate.py                    the Doc 4 §11 results table
        ├── preprocessing/
        │   ├── input_router.py             ✅ text · url · file
        │   └── content_extractor.py        ✅ trafilatura · pypdf · BeautifulSoup
        └── api/
            ├── main.py · dependencies.py   ✅
            ├── routes_audit.py             ✅ real audit wired in _run_audit
            ├── routes_report.py · routes_health.py · jobs.py · models.py  ✅
```

**94 Python modules · 27 prompt templates · 120 tests · 0 stray TODOs · 0 `NotImplementedError`.**
Nothing is stubbed. Every path a user can reach is implemented and verified.

### Module reference

#### `core/`

| Module | Purpose | Key API | Depends on |
|---|---|---|---|
| `config.py` | Configuration Manager. YAML under env; env wins. Per-provider API keys. | `Settings`, `load_settings()`, `LLMSettings`, `EngineSettings`, `DecisionSettings` | `shared.schemas` (Severity), `errors` |
| `constants.py` | **The frozen Doc 2 §4.1 matrix transcribed.** | `DIMENSION_SPECS`, `ALL_DIMENSIONS`, `TRUST_RELEVANT_DIMENSIONS`, `EXECUTION_WAVES`, `CROSS_ENGINE_INPUTS`, `spec_for()` | `shared.schemas` |
| `errors.py` | Error taxonomy → `{"error":{"code","message"}}`. | `AuditorError`, `ProviderError`, `ProviderTimeoutError`, `ConfigurationError` | — |
| `logging.py` | Structured logging. **Ids, never content** (Doc 4 §12). | `configure_logging()`, `get_logger()`, `bind()`, `log_duration()` | — |

#### `shared/` — contracts

| Module | Purpose | Key API |
|---|---|---|
| `schemas.py` | **THE FROZEN CONTRACT.** `AuditResult` (7 fields) + `AuditReport`. | `AuditResult`, `AuditReport`, `EvidenceItem`, `LedgerEntry`, `CriticalFinding`, `Recommendation`, `Severity`, `SEVERITY_ORDER`, `DimensionType`, `OverallVerdict`, `TrustOutcome`, `QualityBand`, `Score` (`float \| "N/A"`), `PreprocessedContent` |
| `vocabularies.py` | The frozen §6.4 verdict sets. | `ClaimType`, `ClaimVerdict`, `CoverageVerdict`, `GroundingVerdict`, `RequirementType`, `SourceClass`, `RequirementVerdict` *(**not** frozen — our choice)* |

`AuditResult.validate_contract()` returns violations rather than raising — an invalid result must reach the Decision Engine as a *verification gap* (Doc 3 §4 stage 2), not abort the run.

#### `shared/` — services

| Module | Purpose | Key API | Notes |
|---|---|---|---|
| `context.py` | **Single source of truth per run.** | `SharedContext`, `SharedKeys`, `.sentences`, `.statistics`, `.metadata`, `.get_or_compute()`, `.describe()` | Two caching tiers |
| `text_segmentation.py` | Sentences, paragraphs, span location. | `TextSpan`, `TextSegmenter`, `locate_span()`, `normalize_whitespace()` | `text[s:e] == span.text` invariant |
| `document_analysis.py` | Measured facts only. | `DocumentStatistics`, `DocumentMetadata`, `analyze_statistics()`, `analyze_metadata()`, `warm_language_detection()` | langdetect lazy + failure-tolerant |
| `llm_stage.py` | Shared machinery for §5.1/§5.2/§5.4. | `LLMStage`, `LLMStageError`, `index_by()` | `error_class` overridable |
| `llm_service.py` | Policy: retries, timeouts, JSON. | `LLMService`, `DefaultLLMService` | Raises; never swallows |
| `llm_providers/` | Provider seam. | `LLMProvider`, `GroqProvider`, `build_provider()`, `register_provider()` | OpenRouter commented out |
| `embedding_service.py` | Local model + shared cache. | `EmbeddingService`, `LocalEmbeddingService`, `relatedness()`, `cosine_similarity()`, `InMemoryEmbeddingCache`, `build_embedding_cache()` | **Use `relatedness()` for thresholds** |
| `retrieval_service.py` | §5.3. | `RetrievalService`, `DefaultRetrievalService`, `Chunk`, `RetrievedPassage`, `FetchedDocument` | `fetch()` never raises |
| `deterministic_validators.py` | §5.6. All four instantiations. | `DeterministicValidators`, `ValidationOutcome`, `URL_PATTERN`, `DOI_PATTERN` | `analyze_readability` takes the run's `sentences` (one sentence count per document); patterns use `\s+` (§9.21) |
| `quality_units.py` | The units the four Quality engines evaluate. | `ReadabilityAspect`, `READABILITY_ASPECTS`, `ReadabilityIssue`, `RedundancyCandidate`, `TaskContext`, `TaskCriterion`, `ManipulationCandidate`, `BiasItem` | Counterpart to `extraction/models.py`; classification fields default `None` |
| `task_identification.py` | Engagement stage 2. | `TaskIdentificationStage`, `TaskIdentificationError` | Returns `identified=False` with no prompt — never infers the goal from the output |
| `evidence_store.py` | Storage + id minting. | `EvidenceStore`, `InMemoryEvidenceStore` | Run-scoped |
| `evidence_pipeline.py` | Build/link/format. | `EvidenceCollector`, `EvidenceKind`, `verify_links()`, `format_for_prompt()`, `format_for_report()` | Per-dimension façade |
| `confidence_service.py` | §5.10. | `ConfidenceService`, `DefaultConfidenceService`, `ConfidenceSignal`, `signal()` | Weighted mean; empty ⇒ 0.0 |
| `recommendation_service.py` | §5.11. | `RecommendationService`, `DefaultRecommendationService` | Drops evidence-less recs |
| `scoring.py` | §5.9 arithmetic. | `weighted_mean()`, `importance_weighted_rate()`, `clamp()`, `apply_penalty()` | Pure |
| `mapping.py` | Credibility stage 3. | `ClaimCitationMapper`, `CitationMapping` | Also yields uncited claims |

#### `shared/extraction/` (§5.1)

`base.py` `LLMExtractionService` · `models.py` (`Requirement`, `Claim`, `KeyPoint`, `Citation`, **`Viewpoint`**, `ExtractionResult`) · `requirements.py` · `claims.py` · `key_points.py` · `citations.py` · **`viewpoints.py`**

**All classification fields default to `None`.** Extraction extracts; §5.2 classifies.

> **`viewpoints.py` extracts from the *question*, not the document** — including viewpoints the output never mentions, since a viewpoint that was never extracted can never be found missing. It is the one extraction service whose units are not all present in its source.

#### `shared/classification/` (§5.2)

`base.py` `LLMClassifier` + `coerce_enum()` + `coerce_unit_float()` + `render_units()` · `claims.py` (`ClaimClassifier`, `ClaimCentralityAssigner`) · `requirements.py` (`RequirementClassifier`) · `key_points.py` (`SalienceAssigner`, `CategorySeverityAssigner`) · `sources.py` (`SourceClassifier`, `domain_of()`) · **`readability.py`** (`IssueClassifier`, `IssueSeverityAssigner`) · **`diversity.py`** (`ApplicabilityClassifier`, `StanceContractDetector`)

> Diversity's two extend `LLMStage` directly, not `LLMClassifier`: their unit is the **document**, not a list of units. §5.2 catalogues what the stage *does* (assign a label), not the shape of the call.

#### `shared/verification/` (§5.4)

`base.py` `LLMJudge` + `Judgment` + **`build_judgments()`** · `claims.py` · `coverage.py` · `grounding.py` · `requirements.py` · **`readability.py`** (`ReadabilityReviewJudge.review()`) · **`novelty.py`** (`FunctionalRepetitionJudge`) · **`engagement.py`** (`TaskFitnessJudge`, `ManipulationVerificationJudge`) · **`diversity.py`** (`BalanceEvaluationJudge.evaluate()`, `BiasDetectionStage`)

> **`build_judgments()` is the reuse seam for stages whose frozen output is more than a verdict.** Readability's review returns aspect verdicts *and* issues; Diversity's balance evaluation returns verdicts *and* a legitimacy. Both call it rather than reimplementing id-matching and vocabulary enforcement — and `judge()` is unchanged for the seven judges that need only verdicts.

#### `decision_engine/` (Document 3) — **pure: no IO, no LLM, no engine imports**

| Module | Doc 3 | Purpose | Key API |
|---|---|---|---|
| `workflow.py` | §4, §11 | The ordered pipeline; the deterministic verdict resolution. | `DecisionEngine.decide()`, `resolve_verdict()`, `validate_results()` |
| `applicability.py` | §9 | Partition scored vs N/A. N/A out of numerator **and** denominator. | `partition()`, `ApplicabilityPartition` (`scored`, `excluded`, `reasons`, `failed`, `low_confidence()`) |
| `critical_findings.py` | §5 | Collect · dedupe · severity+trust-first order · gate. | `process()`, `CriticalFindingOutcome` (`findings`, `gating`, `trust_is_gated`) |
| `trust_eval.py` | §6 | Non-compensatory; the **weakest** governs. | `evaluate()`, `weakest()`, `requires_revision()`, `trust_dimensions()` |
| `quality_eval.py` | §7 | Compensatory; weight = `dim_weight × confidence`. | `evaluate()` |
| `confidence_integration.py` | §8 | Assertability gate; **reuses the shared §5.10 estimator**. | `integrate()`, `IntegratedConfidence` (`report`, `trust_assertable`, `trust_verdict`, `explanation`) |
| `recommendations.py` | §10 | Tiers, trust-first ordering, evidence requirement. | `prioritize()` |
| `report_builder.py` | §12 | Project the decision into the `AuditReport`. | `build_report()`, `build_placeholder_report()` *(retained, no longer wired)* |

> **The Decision Engine imports no engine and no engine module.** It reads
> `AuditResult` + `core.constants` (the frozen matrix) + `shared.scoring` /
> `shared.confidence_service` (arithmetic it reuses rather than duplicates).
> That is the stable seam of Doc 3 §13, and it is what makes the whole layer
> testable on synthetic results in milliseconds.

---

## 5. Completed milestones

### Milestone 1 — Foundation

**Built:** folder structure; `ServiceContainer`; Configuration Manager; structured logging; error taxonomy; **the frozen `AuditResult`/`AuditReport` contracts**; the provider seam; `AuditEngine` base + registry + orchestrator contract; the eight engines registered as placeholders carrying their frozen metadata; Decision Engine module skeleton; API (`POST /audit`, `/audit/{text,url,file}`, `GET /audit/{id}/status`, `/report/{id}`, `/health`); the React frontend.

**Decisions:**
- **Modules under `backend/app/`** so `uvicorn app.main:app` works. Names/responsibilities unchanged from Doc 4 §3.
- **`Score = float | Literal["N/A"]`** — encoding N/A in the *type* forces every consumer to honor Doc 3 §9's exclusion rule instead of letting a silent `0.0` depress the Quality Verdict.
- **The placeholder report returns *Unable to Verify*, and that is a safety property.** Nothing measured ⇒ trust genuinely undetermined. A scaffold returning *Trusted* would be a scaffold that lies — the one failure mode the system exists to prevent. **Do not "fix" this.**
- **Engine placeholders exist despite not being in the M1 list** — an empty registry is meaningless, and the frozen matrix needed a home.

**Verified:** `/health` → 8 engines; `POST /audit` → 8 dimensions; async lifecycle; error contract; frozen matrix; frontend build + live browser round-trip.

### Milestone 1.5 — Groq refinement

Replaced OpenRouter with Groq; **OpenRouter kept intact but commented out** in `llm_providers/registry.py` under `PAID PROVIDER` markers. Added flat env names (`GROQ_API_KEY`, `LLM_PROVIDER`, `LLM_MODEL`) resolved **per provider**, so adding a paid provider later is additive. Added `sentence-transformers` and the shared embedding cache. Introduced `SharedContext`.

**Decisions:** `reasoning_format: hidden` (Groq-only, config-driven) because qwen3-32b emits `<think>` blocks that corrupt structured JSON; Groq requests `json_object` not `json_schema` (most Groq models reject the latter); **renamed `EngineContext` → `EngineServices`** because `_execute(self, context: SharedContext)` alongside `self.context` was a trap.

### Milestone 2 — Shared framework

**Built:** preprocessing (sentence/paragraph segmentation with source offsets, statistics, metadata); `SharedContext` with two caching tiers; LLM Extraction (§5.1) for requirements + claims; the Prompt Manager (versioned, strict); the evidence pipeline; orchestrator wave execution + `validate_plan()`.

**Decisions:**
- **Extraction ≠ classification.** Doc 2 §5.1 and §5.2 are separate components run as separate stages. Extraction leaves `requirement_type`/`claim_type`/`centrality` as `None`.
- **Reversed M1's position on segmentation.** M1 argued preprocessing must not segment because Novelty owns "Text Segmentation" (§7.5 stage 2). The reconciling rule: **reuse of a mechanism is not relocation of a stage.** Novelty still segments at stage 2 — it reads `context.sentences` instead of carrying its own splitter.
- **Two caching tiers** — sync memoization for regex-cheap work (atomic on one event loop, no lock); async per-key locks for IO.
- **Extraction locates by the model's `quote`, not the unit text** — a requirement is a *restatement* and would never be found otherwise.

**Fixes found by verifying:**
1. **Latency bug in my own logging.** `describe()` forced language detection, and langdetect's first profile load costs **~576 ms on the event loop**, blocking wave 1. First audit measured **765 ms against a 150 ms floor**. Fixed: `describe()` reports language only if already derived; langdetect warms at boot. → **190 ms**.
2. **A misleading alias.** `ContentStats = DocumentStatistics` claimed backwards compatibility it did not have (the old type had `has_prompt`); it broke `routes_audit`. Removed rather than shipped.

### Milestone 3 — Trust & Hybrid engines

**Built:** all four Critical-Finding-capable engines (Accuracy, Credibility, Relevance, Coverage), each following its frozen pipeline stage by stage. Plus the shared components they required: Classification (§5.2), Verification (§5.4), Confidence (§5.10), Retrieval (chunk/search/fetch), Deterministic Validators (constraints, URL/DOI), the local embedding backend, `vocabularies.py`, `llm_stage.py`, `mapping.py`, `scoring.py`, and **15 prompt templates**.

**Order:** Accuracy first — it exercised the deepest path and forced the shared infrastructure into existence; the other three reused it.

**Fixes found by verifying:**
1. **Scope drift was dead code.** The `(cos+1)/2` remapping compressed all similarities into `[0.5, 0.9]`, so the `0.30` threshold **could never fire** — drift detection looked functional and detected nothing. Off-topic sentences scored 0.59; on-topic 0.70. Raw cosine separates cleanly (0.18 vs 0.40). Added `relatedness()`; switched every thresholded comparison.
2. **Confidence hit 1.000.** The judges returned certainty hints that were collected and never used — an absolute claim to correctness no LLM judgment earns. Wired in as a signal.
3. **Accuracy and Credibility didn't share claim extraction.** Both extract the same claims from the same output in the same wave. Added `SharedKeys` so the derivation is shared. **Verified: 1 call, not 2.**

### Milestone 4 — Quality engines

**Built:** the remaining four engines (Readability, Novelty, Engagement, Diversity), each following its frozen pipeline stage by stage. Plus: `analyze_readability` + `detect_manipulation_patterns` (§5.6), `quality_units.py`, `task_identification.py`, viewpoint extraction (§5.1), 4 new classifiers (§5.2), 5 new judges/stages (§5.4), 6 new vocabularies, and **12 prompt templates**.

**Order:** Readability first, per §13 — no cross-engine inputs, and the only substantial deterministic stage. Then Novelty (wave 2), Engagement (wave 3), Diversity (N/A branch) — dependency order, so each engine's cross-engine input already existed when it was verified.

**Decisions:**
- **`LLMJudge.build_judgments()` extracted** from `judge()` — a pure refactor, no behavior change. Two frozen stages produce *more than* a verdict per unit (Readability's review surfaces issues; Diversity's balance evaluation returns a legitimacy) and now reuse the id-matching and vocabulary enforcement instead of copying it.
- **Deterministic readability issues skip stages 4–5.** The check that raised one *is* its category, and its severity came from a rule. Re-asking a model to label "mean sentence length is 34 words" is asking what a regex already knows (§9.8). Reviewed issues go through both stages.
- **Readability's ledger carries the 3 aspects as well as the issues.** §6.3 names *Issue* as the unit and every issue is there; the aspect rows are additive because the score derives from them, and a ledger that could not explain its own score fails Doc 3 §13. Accuracy sets the precedent (it records non-factual claims it never verifies).
- **Novelty's Coverage cross-check only ever rescues.** It runs one way — it can turn Redundant into Functional, never the reverse. The cross-check exists to protect content, not to find more to delete. **The override is recorded in the ledger** (`review_verdict` retained), never silent, exactly as Relevance records its deterministic overrides.
- **Engagement weights its own judgment 3:1 over the reused four.** It must not collapse into an average of Relevance/Coverage/Readability/Novelty — it would then report nothing they don't already say, and could never find a document that is *well-made and useless*. Reuse is weighted by each engine's **confidence**, so a low-confidence measurement is not laundered into a fact (Doc 3 §8).
- **Engagement drops degraded priors rather than reading their `0.0` as a measurement.** Otherwise one engine's outage cascades into a second dimension's false quality signal.
- **Diversity's N/A returns `confidence=0.9`.** Not a contradiction: the engine is confident in the judgment it *made* (that the dimension doesn't apply). That is a real conclusion from a real stage, and it is a different thing from the score, which doesn't exist. Precisely why §5.10 reports the two separately.
- **No applicability *threshold*.** Whether Diversity applies is a judgment against its prompt's criteria, not a number — a configurable gate would let a deployment quietly switch the only N/A in the system on or off.

**Fixes found by verifying (all four were real):**
1. **The manipulation patterns missed anything that wrapped a line.** `"act now"` split across a newline never matched, because the patterns used literal spaces and prose wraps. So false-urgency detection *looked* functional and silently only caught phrases that happened not to wrap. Fixed with `_phrase()`, which compiles every literal space to `\s+`.
2. **Novelty's similarity threshold was miscalibrated and disabled the cross-check.** At 0.75 it missed genuine padding measured at **0.662** *and* the genuine recap at **0.720** — and a passage that never becomes a candidate can never be rescued, so the Coverage cross-check was unreachable. **Measured** on `all-MiniLM-L6-v2`: padding 0.66–0.94, recap 0.72, merely-same-topic ≤0.56. Retuned to **0.60**, where the separation actually sits. (The same class of bug as M3's `relatedness()` finding.)
3. **`sentence_termination` faulted every markdown document for being well-structured.** It flagged the heading `# How rate limiting works` as an unterminated sentence — headings, list items, and table rows legitimately carry no terminal punctuation. Narrowed to prose via `_is_structural_line`, and refocused on its real value: detecting truncated output.
4. **Diversity's "undisclosed stance" penalty was dead code.** It fired only on `Declared Advocacy AND NOT discloses` — self-contradictory, since "Declared" *means* disclosed. The `discloses` flag was also incoherent on the other branch: an encyclopedia article doesn't announce its neutrality, so it would have been penalized for good behavior. **Removed the flag and the penalty**: content that argues while posing as neutral is `Neutral` by stage 4's definition, so the strict credit table already catches it. Doc 2 §3 defines the stance contract as a binary; the extra field was mine and was redundant.

### Milestone 5 — Decision Engine

**Built:** every stage of Document 3 — applicability (§9), critical-finding processing (§5), trust evaluation (§6), quality evaluation (§7), confidence integration (§8), recommendation prioritization (§10), the ordered workflow (§4), the deterministic verdict (§11), and the Final Audit Report (§12). Wired into `app.py` and `routes_audit._run_audit`, replacing the placeholder.

**Order:** stages first, in Doc 3's own order, then the workflow that composes them, then the report. Each stage is pure and was verified on synthetic `AuditResult`s before the next depended on it.

**Decisions:**
- **The layer is pure and imports no engine.** `AuditResult` in, `DecisionResult` out. It reads the frozen matrix (`core.constants`) for routing and reuses `shared.scoring` / `shared.confidence_service` for arithmetic — never an engine module. That is Doc 3 §13's stable seam, and it is why the suite runs in milliseconds with no LLM.
- **Confidence integration reuses the §5.10 estimator** rather than reimplementing a weighted mean. A confidence figure in the report is combined by the same arithmetic that produced the per-dimension figures it combines, and `explain()` gives the human-readable rationale free.
- **A *failed* dimension stays in `scored`; only N/A is excluded.** Excluding a degraded dimension the way N/A is excluded would convert a verification gap into a non-event — and the gap is exactly what §8 needs to reach *Unable to Verify*. Its zero confidence then does the right thing everywhere: zero weight in the compensatory Quality aggregate, blocked assertability in Trust.
- **"Confident but weak" is *Needs Revision*, never *Untrusted*.** Doc 3 §6's table has no row for a trust dimension that scores 0.4 with high confidence and raises no finding — because §8 and §11 step 3 route exactly that to *Needs Revision*. *Untrusted* is reserved for a **disqualifying** failure (a qualifying Critical Finding). Reporting *Untrusted* for a low score would make the gate meaningless: every weak score would trip it, and "this is wrong" would stop being distinguishable from "this is weak".
- **"Tied to a Critical Finding" is decided by shared evidence refs**, not by wording or severity. It is checkable rather than inferred, so an engine cannot talk its way into the Critical tier and a finding's remedy cannot fall out of it.
- **Dedupe never merges across dimensions.** Accuracy's "contradicted claim" and Credibility's "misattributed citation" about the same sentence are two failures with two remedies. Within one dimension, duplicates merge with **unioned evidence** and the **higher** severity — a merge must never lose a pointer or un-gate trust.
- **Recommendations dedupe within a dimension only.** Two engines independently advising the same action is signal, not noise; merging would also force the report to misattribute it, since `PrioritizedRecommendation.dimension` is a single field in the frozen §12 report.
- **The one schema change:** `AuditReport.dimension_summaries`. Doc 3 §12's Dimension Results row explicitly requires a per-dimension **one-line rationale**, and the report had nowhere to carry it. Additive, defaulted, backward-compatible; `DimensionSummary` already existed. This is the "unless Document 3 explicitly requires them" carve-out, used once.

**Bugs found by verifying:**
1. **Quality reported a band without admitting how little voted.** With four of six quality dimensions degraded, the band was arithmetically correct (`High @ 1.00` over two voters) and rhetorically misleading — "Quality: High" over two voters read exactly like "Quality: High" over six. Fixed by naming the silent dimensions in `drivers`: *"…could not be measured and carried no weight — the band rests on 2 of 6"*. **The band did not change; only what the report admits about it.**
2. **The frontend told users the engines did not exist.** `AuditPage` still carried M1 copy — *"the audit engines are not yet implemented — every audit returns Unable to Verify with nothing measured"* — which had been false since M4 and was now actively misleading on a page rendering real verdicts. Replaced with what is true; the stale `Milestone 2` markers across four components were renumbered to M6.
3. **`sys.stdout` encoding broke a verification run on Windows.** A `→` in a check label raised `UnicodeEncodeError` under cp1252 and killed the suite mid-run. The harness now forces UTF-8 with `errors="replace"` — a test rig must never fail on its own label.

### Milestone 6 — Production (final)

**Built:** real Groq integration hardened · URL/file input · the validation corpus + calibration runner · frontend polish (async polling, Evidence Viewer, export) · Docker + Compose · 120 pytest tests · README rewrite.

**Decisions:**
- **`ProviderError` now carries its own classification** (`retryable`, `retry_after`, `status_code`). The *provider* knows a 401 from a 503; the *LLM Service* knows what to do about it. Additive and defaulted to `retryable=True`, so every existing raise site keeps its behavior.
- **429 stays retryable, and that is the important one.** Groq's free tier rate-limits a six-wide wave routinely, so treating it as permanent would degrade half the dimensions of a good audit. `Retry-After` is honoured as a floor — a limiter naming its own interval knows better than our curve.
- **`bind()` renames reserved `LogRecord` fields** instead of raising. A logging call must never be able to fail the operation it describes.
- **The corpus declares expectations as *ranges*, not point verdicts.** Doc 4 §11's criterion is that verdicts *track* quality and defects map to the right dimension — pinning an exact band would make the corpus a change-detector for prompt wording rather than a test of the claim.
- **Corpus samples are local, not live URLs.** A calibration corpus whose content changes under you measures the internet, not the auditor. The URL path is verified separately with mocked transport.
- **Export is JSON + Markdown, not PDF.** Doc 4 §2 puts PDF behind "optional"; these two cover archiving and pasting into a ticket without adding a rendering dependency to a frontend that has none.
- **`app/evaluation/` is a consumer, not part of the audit path.** Nothing in `audit_engines/` or `decision_engine/` imports it, so it may read anything without disturbing the one-way dependency graph.

**Bugs found by verifying (all four were real):**
1. **Permanent LLM failures were retried, turning a config error into a timeout.** A missing key cost **9.3s per call** — and ~19s through `complete_json`'s parse-retry — because `_complete_with_retries` retried *every* `ProviderError`. Across eight engines that is minutes of silence on the single most likely first-run misconfiguration. **Measured after the fix: ~0s.** A 401, 403, 400, or 404 now fails on the first attempt; 429/5xx/timeouts still retry.
2. **Every file upload crashed on its own log line.** `bind(filename=…)` hits a reserved `LogRecord` attribute and raises `KeyError: Attempt to overwrite 'filename'`, failing the audit from inside the telemetry. Caught by the API suite. Fixed systemically in `bind()` — `module`, `name`, `process`, and `args` were the same landmine waiting.
3. **`docker compose up` failed on a fresh clone.** `env_file` pointed at a `backend/.env` that does not exist until you make one, so the very first command in the README died with a file-not-found. Now `required: false`: the stack starts, `/health` reports `llm_configured: false`, and audits return *Unable to Verify* — the honest answer, and a far better first experience.
4. **The README and four frontend components still described a system that did not exist** — "Milestones 1–3", "every audit currently returns Unable to Verify", "Available in Milestone 2". All corrected.

---

## 6. Engine implementations

**Universal contract.** Subclasses implement `_execute(context, prior_results)`; callers invoke `run()`. `AuditEngine.run()` — **never override it** — applies three guarantees:

1. **Timeout** (`orchestrator.engine_timeout_seconds`)
2. **Degradation** — any failure becomes a zero-confidence `AuditResult`, never an exception
3. **Metadata correctness** — stamped from `core/constants.py`, so an engine cannot misdeclare its own `dimension_type`

`degraded_result()` reports `score=0.0, confidence=0.0` and **never a critical finding** — a dimension that could not measure has not *found* anything; forging one would gate trust on a gap.

---

### Accuracy (`ENG-ACCURACY`) — Trust — Doc 2 §7.2

| # | Stage | Kind | Implementation |
|---|---|---|---|
| 2 | Claim Extraction | LLM | `ClaimExtractionService` (shared via `SharedKeys.EXTRACTED_CLAIMS`) |
| 3 | Claim Classification | LLM | `ClaimClassifier` → Factual/Opinion/Non-verifiable |
| 4 | Centrality & Severity | LLM | `ClaimCentralityAssigner` (**factual only**) |
| 5 | Evidence Retrieval | **deterministic** | `RetrievalService.chunk` + `.search` (**reference-first**) |
| 6–7 | Claim Verification | LLM | `ClaimVerificationJudge` → Supported/Contradicted/Unverifiable |
| 8 | Evidence Collection | deterministic | `EvidenceCollector` |
| 9 | Critical Finding Detection | **deterministic** | Contradicted + severity ≥ threshold + has evidence |
| 10 | Confidence | deterministic | 6 signals |
| 11 | Score | deterministic | `importance_weighted_rate` |

**Reasoning flow:** extract every claim → keep only the *checkable* ones → weigh them → retrieve evidence from the reference → ask a judge, **evidence-only** → contradictions become findings; gaps become confidence loss.

**Score:** Supported → 1.0; Contradicted → 0.0; **Unverifiable → excluded from numerator *and* denominator**; weighted by centrality.

**Confidence signals:** `reference_available` (w3) · `evidence_retrieved` (w3) · `claims_judged` (w2) · **`verdicts_decisive` (w4 — heaviest)** · `claims_located` (w1) · `verifier_certainty` (w2).

> `verdicts_decisive` is heaviest because Unverifiable claims are excluded from the score — a score over 1 of 20 claims looks *identical* to one over all 20, and only this signal reveals the difference.

**Key decision — the load-bearing one in the whole engine.** *Unverifiable is excluded from the score, not scored zero.* The score answers "of what could be checked, how much held up?" A claim nothing was learned about has not failed. Scoring it zero would report **unverified content as inaccurate** — a false accusation. The cost lands on confidence → *Unable to Verify* (Doc 3 §8). **Measured:** no reference ⇒ score 1.0, **confidence 0.32**.

---

### Credibility (`ENG-CREDIBILITY`) — Trust — Doc 2 §7.4

| # | Stage | Kind | Implementation |
|---|---|---|---|
| 2 | Citation Extraction | LLM | `CitationExtractionService` (URL/DOI pulled by **regex**, never retyped) |
| 3 | Claim-to-Citation Mapping | LLM | `ClaimCitationMapper` (also yields **uncited claims** = transparency) |
| 4 | URL / DOI Verification | **deterministic** | `verify_url` / `verify_doi` — HEAD then GET, concurrent |
| 5 | Source Retrieval | deterministic | `RetrievalService.fetch` (only what resolved) |
| 6 | Grounding Verification | LLM | `GroundingVerificationJudge` → Supports/Partial/Contradicts/Unrelated |
| 7 | Source Classification | LLM | `SourceClassifier` (domain + title as hints) |
| 9 | Critical Finding Detection | **deterministic** | Fabricated / Misattributed |

**Three failures that look alike and are not:**

| Failure | Detected by | Finding |
|---|---|---|
| **Fabricated** — link doesn't resolve | stage 4 (deterministic) | `Fabricated citation` |
| **Misattributed** — resolves, but Unrelated/Contradicts | stage 6 (LLM) | `Misattributed`/`Contradicting citation` |
| **Unlinked** — "Smith et al. (2023)", no URL | stage 2 | **NONE** — low-severity recommendation only |

> **The unlinked case is the most important false positive to avoid.** Academic prose is full of real unlinked references. Reporting those as fabricated would gate trust to *Untrusted* on ordinary honest writing.

**Score:** unresolvable 0.0 (w1) · Unrelated/Contradicts 0.0 (w1) · Partial 0.5 · Supports 1.0 · resolves-but-ungrounded 0.7 (w0.5) · **unlinked 0.6 (w0.3)** — a judgment call: zero brands academic writing untrustworthy; 1.0 rewards uncheckable citations.

**Regex reads the URL from the citation's own text** — a model retyping a link could introduce a typo and trigger a fabrication finding against a correct URL.

---

### Relevance (`ENG-RELEVANCE`) — Hybrid — Doc 2 §7.1

| # | Stage | Kind | Implementation |
|---|---|---|---|
| 2 | Requirement Extraction | LLM | `RequirementExtractionService` |
| 3 | Hard/Soft Classification | LLM | `RequirementClassifier` (+ **machine-checkable constraint**) |
| 4 | Per-Requirement Evaluation | LLM | `RequirementEvaluationJudge` |
| 6 | Scope Drift Detection | **deterministic** | embeddings + `relatedness()` vs prompt |
| 7 | Deterministic Constraint Checks | **deterministic** | `check_constraints` — **overrides stage 4** |

**Stage 7 overrides stage 4.** A word count is a fact; a model's impression of length is a guess. **Verified:** judge said *"Satisfied — looks about right"* at 55 words against a 20-word limit; the counter said **Violated**, and the ledger records both.

**Critical findings:** only **violated + Hard + classified**. Soft never qualifies (§3 defines Hard as the blocking one); Partially Satisfied never qualifies (a shortfall is not a breach); unclassified never qualifies (trust must not be gated on an unanswered question).

**The judge is deliberately not shown the Hard/Soft type** — telling it the answer is trust-blocking invites it to soften a real violation. Stage 3 sets the stakes; stage 4 finds the facts.

**`RequirementVerdict` is NOT frozen.** Doc 2 §6.3 fixes no verdict set for Relevance. Ours: Satisfied / **Partially Satisfied** / Violated. The middle value stops "gave 3 examples when asked for 5" being reported as a hard-requirement breach → *Untrusted*.

---

### Coverage (`ENG-COVERAGE`) — Hybrid — Doc 2 §7.3

| # | Stage | Kind | Implementation |
|---|---|---|---|
| 2 | Key Point Extraction | LLM | `KeyPointExtractionService` (reads the **reference**, not the output) |
| 3 | Salience Assignment | LLM | `SalienceAssigner` |
| 4 | Category & Severity | LLM | `CategorySeverityAssigner` (sees stage-3 salience) |
| 5 | Coverage Verification | LLM | `CoverageVerificationJudge` → Present/Partial/Absent |
| 7 | Critical Omission Detection | **deterministic** | Absent + salience ≥ 0.70 + severity ≥ high + has evidence |

**"Without over-penalizing summarization" is the hardest constraint here.** A summary omits *by design*. Three mechanisms serve it: **salience weighting**, **partial credit**, and **a salience AND severity floor** on omissions.

**Verified:** a summary dropping the critical limitation → Critical Omission, score **0.53**. A *fair* summary dropping only funding/dates → **no findings**, score **0.83**.

**A missing reference is a verification gap, not a zero.** Coverage cannot return N/A (§4.1), so it returns **zero confidence** — never `score=0.0` with real confidence, which would assert the output *is* incomplete on the basis of never having looked.

---

### Readability (`ENG-READABILITY`) — Quality — Doc 2 §7.6

| # | Stage | Kind | Implementation |
|---|---|---|---|
| 2 | Deterministic Analysis | **deterministic** | `analyze_readability` — grammar · complexity · structure |
| 3 | LLM Readability Review | LLM | `ReadabilityReviewJudge.review()` → 3 aspect verdicts **+ issues** |
| 4 | Issue Classification | LLM | `IssueClassifier` (**reviewed issues only**) |
| 5 | Severity Assignment | LLM | `IssueSeverityAssigner` (**reviewed issues only**) |
| 7 | Score | deterministic | `weighted_mean([(aspects, 3), (deterministic_rate, 1)])` |

**The 3:1 weighting is the engine's whole argument.** Invert it and a document of short, disconnected sentences outscores a well-argued one with long sentences — exactly the mistake readability formulas make, and exactly why the review exists. Deterministic signals corroborate; they measure proxies.

**Score:** Clear → 1.0 · Acceptable → **0.65** · Unclear → 0.15 · unjudged → excluded. *Acceptable* sits near the top deliberately: prose a reader follows with some effort is ordinary competent writing, and 0.5 would report the median document as half-unreadable.

**Verified:** clean structured prose **0.964**; dense unstructured prose **0.345**.

---

### Novelty (`ENG-NOVELTY`) — Quality — Doc 2 §7.5 — **wave 2**

| # | Stage | Kind | Implementation |
|---|---|---|---|
| 2 | Text Segmentation | deterministic | reads `context.sentences` (no engine-local splitter) |
| 3–5 | Embedding · Duplicate Detection · Candidates | **deterministic** | `relatedness()` ≥ 0.60, or Jaccard ≥ 0.85; **each segment pairs with its single most similar predecessor** |
| 6 | Functional Repetition Review | LLM | `FunctionalRepetitionJudge` → Redundant candidate / Functional repetition |
| 7 | **Coverage Cross-check** | **deterministic** | `prior_results["Coverage"]` → **rescue only** |
| 8 | Score | deterministic | `1 − (redundant_words / total_words)` |

**Score by mass, not count.** A redundant 40-word paragraph wastes more of a reader's time than a redundant 6-word aside. Only *confirmed* redundancy counts; functional repetition and unjudged candidates are free.

**Verified:** padded prose **0.687** → 4 candidates; the salient recap **rescued** by the cross-check (`review_verdict` retained in the ledger); distinct prose **1.0 with no LLM call**.

---

### Engagement (`ENG-ENGAGEMENT`) — Quality — Doc 2 §7.7 — **wave 3**

| # | Stage | Kind | Implementation |
|---|---|---|---|
| 2 | Context & Task Identification | LLM | `TaskIdentificationStage` → task · goal · audience · **criteria** |
| 3 | **Reuse Prior Results** | deterministic | reads 4 `AuditResult`s — **never re-measures** |
| 4 | Task Fitness Evaluation | LLM | `TaskFitnessJudge` over the criteria → Met / Partially Met / Unmet |
| 5 | Manipulation Pattern Detection | **deterministic** | `detect_manipulation_patterns` — 6 families |
| 6 | Manipulation Verification | LLM | `ManipulationVerificationJudge` → Manipulative / Borderline / Legitimate |
| 8 | Score | deterministic | `wmean([(fitness,3),(reuse,1)])` **then penalty** |

**Manipulation is subtracted, never averaged.** Content that manipulates its reader has done something wrong that being useful does not excuse; averaging would let a high fitness score dilute it away.

**No prompt ⇒ no task ⇒ no fitness.** The stage returns `identified=False` rather than inferring the goal from the output — an output judged against a goal read off itself would grade its own homework and pass every time. Manipulation detection still runs.

**Verified:** useful+honest **0.963**; manipulative copy **≤0.5** across 4 families; **an article *reporting on* manipulation scores 0.9+** because the judge cleared the quoted patterns.

---

### Diversity (`ENG-DIVERSITY`) — Quality — Doc 2 §7.8 — **the only N/A engine**

| # | Stage | Kind | Implementation |
|---|---|---|---|
| 2 | Applicability Classification | LLM | `ApplicabilityClassifier` → **the gate** |
| 3 | **Branch** | — | **No ⇒ return N/A and terminate** |
| 4 | Stance Contract Detection | LLM | `StanceContractDetector` → Neutral / Declared Advocacy |
| 5 | Retrieval of Credible Perspectives | deterministic | reference-first; cited URLs only if `external_retrieval` |
| 6 | Viewpoint Extraction | LLM | `ViewpointExtractionService` — **extracts viewpoints the output omits** |
| 7 | Balance Evaluation | LLM | `BalanceEvaluationJudge.evaluate()` → verdict **+ legitimacy** |
| 8 | Bias & Loaded Language | LLM | `BiasDetectionStage` → located bias items |
| 10 | Score | deterministic | legitimacy-weighted balance rate − bias penalty |

**Legitimacy is the weight, and it is what prevents false balance.** Omitting a mainstream position costs heavily; omitting a fringe claim costs almost nothing. An unweighted rate would reward giving equal room to anything anyone ever said — the failure §7.8 names by name. **Verified: legitimacy 0.05 ⇒ 0.95; legitimacy 0.90 ⇒ 0.53.**

**The stance contract selects the credit table**, so an argument is not scored as a failed survey. *Misrepresented* costs the same under both — a strawman is dishonest whatever the stance. **Verified: a declared argument omitting a viewpoint scores 0.94 where a neutral survey doing the same scores 0.53**, and the argument is nudged (Low) rather than faulted (High).

> **Stage 5 and this deployment's retrieval.** The frozen stack (Doc 4 §2) has no search backend. So the engine retrieves from what it actually has — the reference source, plus cited URLs when opted in — and when it has neither it says so via a confidence signal rather than pretending the stage ran. Viewpoints then rest on the model's own knowledge, which is a weaker footing and is **reported as one**.

---

## 7. Shared framework

### SharedContext — the single source of truth

```python
context.ai_output / .prompt / .reference_source     # Doc 2 §6.1
context.sentences / .paragraphs / .statistics / .metadata     # lazy, memoized
context.reference_sentences / .reference_statistics / .prompt_sentences
await context.get_or_compute(SharedKeys.EXTRACTED_CLAIMS, factory)   # async
```

**Why two tiers.** Sync memoization for regex-cheap work — atomic on one event loop, no lock needed. Async per-key locks for IO — six engines in wave 1 genuinely race. Using the async path for a regex split costs more in lock overhead than the split; using the sync path for a network call blocks the loop six engines run on.

**The rule that keeps it evaluation-neutral:**

> Deriving **what the text is** — its sentences, word count, detected language — is infrastructure, identical for every engine, and lives here.
> Deciding **whether that is any good** is a frozen pipeline stage and lives in the engine.

### How the pieces interact — a real trace

```
routes_audit
  └─ input_router.from_text(audit_id, text, prompt, reference)
       └─ SharedContext.build(...)            ← nothing derived yet (lazy)

orchestrator.run(context)                     ← SAME instance to every engine
  │
  ├─ WAVE 1 (asyncio.gather)
  │   ├─ Accuracy._execute(context, {})
  │   │    ├─ get_or_compute(EXTRACTED_CLAIMS) ─┐  first caller pays
  │   │    ├─ ClaimClassifier.classify()        │
  │   │    ├─ ClaimCentralityAssigner           │
  │   │    ├─ get_or_compute(REFERENCE_CHUNKS)  │
  │   │    ├─ retrieval.search(claim, chunks)   │  → EmbeddingService → CACHE
  │   │    ├─ ClaimVerificationJudge.judge()    │
  │   │    └─ findings + confidence + score     │
  │   ├─ Credibility._execute(context, {})      │
  │   │    └─ get_or_compute(EXTRACTED_CLAIMS) ─┘  ← FREE (verified: 1 call)
  │   ├─ Relevance._execute → context.sentences ← memoized
  │   └─ Coverage._execute  → context.reference_sentences
  │
  ├─ WAVE 2: Novelty(context, {"Coverage": ...})
  └─ WAVE 3: Engagement(context, {Relevance, Coverage, Readability, Novelty})
```

Every LLM stage flows: `Engine → LLMStage → LLMService (retries) → LLMProvider (Groq) → HTTP`.
**No engine ever touches a provider.**

---

## 8. Configuration

**Two sources, layered. The environment always wins over YAML.**

### Environment (`backend/.env`, from `.env.example`)

```bash
GROQ_API_KEY=gsk_...              # https://console.groq.com/keys — REQUIRED for real audits
LLM_PROVIDER=groq
LLM_MODEL=qwen/qwen3-32b
# LLM_BASE_URL=                   # optional gateway override

AUDITOR_ENVIRONMENT=development   # production ⇒ missing key fails startup
AUDITOR_LOG_LEVEL=INFO
AUDITOR_LOG_FORMAT=text           # text | json
AUDITOR_CORS_ORIGINS=["http://localhost:5173","http://127.0.0.1:5173"]

# Paid provider (inactive — see llm_providers/registry.py PAID PROVIDER blocks)
# OPENROUTER_API_KEY=
```

**Two spellings.** Flat names (`GROQ_API_KEY`) map onto nested fields. `AUDITOR_*` with `__` reaches every field (`AUDITOR_DECISION__MIN_TRUST_CONFIDENCE=0.7`).

**The key resolves per provider** (`GROQ_API_KEY` for groq, `OPENROUTER_API_KEY` for openrouter) — adding a paid provider is additive, not a rename.

### Groq + Qwen specifics

| Setting | Value | Why |
|---|---|---|
| `llm.provider` | `groq` | Free tier; OpenAI-compatible; low latency for the 6-wide wave |
| `llm.model` | `qwen/qwen3-32b` | Strong structured output on Groq's free tier |
| **`llm.reasoning_format`** | **`hidden`** | **qwen3-32b is a reasoning model** — left alone it emits a `<think>` block that corrupts the JSON the pipelines parse. **Groq-only.** Set `null` for any other provider or non-reasoning model — they *reject* the parameter |
| `llm.temperature` | `0.0` | Reproducibility (Doc 4 §11) |
| response format | `json_object` (not `json_schema`) | Groq supports `json_schema` on only a subset of models and **rejects it on qwen3-32b**. OpenRouter's provider uses `json_schema`. This difference is exactly what the provider seam is for |

### Embedding

`all-MiniLM-L6-v2`, local, via `sentence-transformers`. Cache **application-scoped**, keyed by **model + text** (sha256). Lazy import → the backend boots in ~1 s and boots *without* torch installed.

### Thresholds (`config/settings.yaml` → `engines.*`)

All documented in-file. **These are reasoned defaults, not measured ones — Milestone 6 tunes them against the corpus.**

| Key | Default | Meaning |
|---|---|---|
| `accuracy.evidence_similarity_threshold` | 0.45 | **Raw cosine** floor for a passage to reach the judge |
| `accuracy.contradiction_blocking_severity` | high | Severity a contradiction must reach to become a finding |
| `credibility.max_sources_fetched` | 12 | Fetch ceiling per audit |
| `relevance.scope_drift_threshold` | 0.30 | **Raw cosine** floor vs the prompt |
| `relevance.scope_drift_tolerance` | 0.25 | Drift fraction tolerated before it scores |
| `coverage.critical_omission_salience` | 0.70 | **The summarization-fairness threshold** |
| `coverage.partial_credit` | 0.5 | Credit a Partial key point earns |
| `readability.max_mean_sentence_words` | 25 | Heuristic bound — a **measurement**, not a verdict |
| `readability.min_reading_ease` | 30.0 | Set low: technical prose is legitimately dense |
| `novelty.semantic_threshold` | **0.60** | **Raw cosine — measured, not guessed.** See §9.20 |
| `novelty.coverage_match_threshold` | 0.55 | Rescue floor; below `semantic_threshold` on purpose |
| `engagement.manipulation_penalty.high` | 0.25 | Penalty per **confirmed** item (subtracted, not averaged) |
| `diversity.perspective_similarity_threshold` | 0.35 | Deliberately loose — an opposing view *is* distant |
| `decision.min_trust_confidence` | 0.60 | Below this ⇒ *Unable to Verify* (M5) |
| `decision.trust_blocking_severity` | high | Doc 3 §5 gate |

> ⚠️ **Similarity thresholds are on the RAW-cosine scale** (`relatedness()`), not rescaled from `[-1,1]`. See §9. Rescaling would silently disable them.

---

## 9. Important engineering decisions

Each entry: **what**, **why**, **what breaks if reversed**.

### 9.1 Provider abstraction — transport vs policy

`LLMProvider` does transport only. `LLMService` owns retries, timeouts, JSON parsing. **Why:** a new provider inherits all policy free, and retry behavior does not depend on which backend is configured. **Reversed:** every provider reimplements backoff, and they drift.

### 9.2 OpenRouter commented, not deleted

Complete and ready in `llm_providers/openrouter.py`; wiring commented under `PAID PROVIDER` markers. **Why:** the user asked for a paid provider available later. Uncomment 3 blocks + set 2 env vars. **Never delete it.**

### 9.3 `reasoning_format` is configuration, not a constant

**Why:** it is Groq-only and **only valid on reasoning models** — a non-reasoning model *rejects* it. Hardcoding would break every non-qwen model. **Reversed:** `<think>` blocks corrupt structured JSON, or the provider 400s.

### 9.4 **Raw cosine, not rescaled** — the subtlest bug in the project

`relatedness()` = raw cosine clamped at 0. **NOT** `(cos+1)/2`.

**Why:** sentence-transformer embeddings of natural language essentially never produce negative cosines. Their useful range is ~`[0, 0.8]`, which rescaling squashes into `[0.5, 0.9]`. **Measured on this model:** two sentences on entirely different subjects score **0.59 rescaled** vs **0.18 raw**. Any threshold on the intuitive scale ("below 0.3 is unrelated") then **silently never fires**.

**This shipped as a real bug in M3** and was caught by verification: scope-drift detection computed correct similarities and reported nothing, because the espresso sentences scored 0.59 against a 0.30 threshold. **Reversed:** drift detection and evidence filtering both silently become no-ops while appearing to work.

### 9.5 Extraction ≠ classification

Doc 2 §5.1 and §5.2 are **separate components** run as **separate stages**. Extraction leaves `requirement_type`/`claim_type`/`centrality` as `None`. **Why:** a violated **Hard** requirement gates trust non-compensatorily while a missed **Soft** one does not. Deciding that inside extraction buries a trust gate in a prompt. **Reversed:** trust gates move into a stage the spec never gave one.

### 9.6 Unverifiable excluded from the score

See §6 Accuracy. **Reversed:** unverified content gets reported as *inaccurate* — a false accusation — and the Trust/Confidence axes collapse.

### 9.7 Coverage's missing reference ⇒ zero *confidence*, not zero *score*

**Why:** Coverage cannot return N/A (§4.1). `score=0.0` with real confidence would assert the output *is* incomplete on the basis of never having looked — levelled at every audit submitted without ground truth. **Reversed:** every reference-less audit falsely reports incompleteness.

### 9.8 Deterministic checks override the LLM

**Why:** a word count is a fact; a model's impression is a guess. Doc 4 §11 prefers the check that cannot vary. The override is **recorded in the ledger**, never silent. **Reversed:** the ledger misrepresents how the verdict was reached.

### 9.9 Verdicts match units by **id**, never position

**Why:** a model that drops one entry would, under positional matching, shift every subsequent verdict onto the wrong unit — marking a hallucinated claim *Supported* and an innocuous one *Contradicted*, **with nothing in the output to reveal it**. Unmatched units stay **unjudged**, never defaulted. **Reversed:** silent catastrophic misattribution of verdicts.

### 9.10 Embedding cache: application-scoped, keyed by model+text

**Why:** Relevance and Novelty embed the same sentences in *different waves*. Keying by text alone would return an `all-MiniLM` vector to a caller expecting another model's — **no error, just wrong similarity scores**, and therefore wrong Novelty and Relevance results.

### 9.11 Lazy computation + the `describe()` trap

Lazy properties compute on first access. **`describe()` deliberately does not force `metadata`** — langdetect's first load costs ~576 ms **on the event loop**. A log line has no business paying that. langdetect warms at boot instead. **Measured: 765 ms → 190 ms** first audit.

### 9.12 Wave execution — a data dependency

Coverage→Novelty and {Rel,Cov,Read,Nov}→Engagement are **frozen** (Doc 2 §8). Running Novelty before Coverage would not be *slower*, it would be **wrong** — the cross-check would have nothing to check against. `validate_plan()` asserts it at startup.

**Engines receive only the dimensions §8 names for them** — never the whole result set. Handing Accuracy the full map would let it quietly read Credibility.

### 9.13 `gather()` without `return_exceptions`

**Why:** `AuditEngine.run` is contractually *total* — it degrades rather than raises. An exception escaping is a framework bug and should surface loudly.

### 9.14 Confidence: weighted mean over explainable signals

**Why:** Doc 3 §13 wants decisions reconstructable. Every confidence value traces to its signals and can be re-derived by hand. A learned combiner could not. **Empty signals ⇒ 0.0**, not a neutral default — an engine that reported no reason to be confident has given none.

### 9.15 Judge certainty feeds confidence

**Why:** without it every signal can max out and the engine reports **1.000** — an absolute claim to correctness no LLM judgment earns.

### 9.16 Retrieval: reference-first, `fetch()` never raises

**Why (reference-first):** frozen (§7.2 stage 5). A claim *Unverifiable* because the reference didn't cover it is honest; one "verified" against an unsanctioned search result is not.
**Why (`fetch` never raises):** for Credibility an unreachable citation **is the finding**. Raising turns "this source does not exist" into "the audit crashed", losing the most important thing learned.

### 9.17 Fail-safe everywhere

- Degraded engine ⇒ `confidence=0.0`, **no forged findings**
- Contract-invalid result ⇒ degraded (reaches the Decision Engine as a gap, not as authority)
- `validate_contract()` **reports**, never raises
- Placeholder report ⇒ *Unable to Verify*
- Missing prompt/provider ⇒ warn at boot, degrade at runtime — **never a silent pass**

### 9.18 `shared/__init__.py` is import-free

**Why:** `core.config` imports `shared.schemas`. Re-exporting submodules creates a `core↔shared` cycle that only appears at startup. Import from the submodule directly.

### 9.19 Structured logs carry ids, not content

Doc 4 §12. The text under audit is the user's; it belongs in the report, not an aggregator.

### 9.20 Novelty's threshold was measured, not chosen — and 0.75 was silently wrong

**What:** `novelty.semantic_threshold = 0.60`, calibrated against measured pairs, not intuition.

**Why:** the first draft used 0.75, which *looked* reasonable and was not. Measured on `all-MiniLM-L6-v2`: genuine padding scores **0.662–0.936**, a genuine summary recap **0.720**, and sentences that merely share a topic **≤0.556**. At 0.75 the engine missed real padding at 0.662 — and, worse, missed the recap at 0.720, which meant **the Coverage cross-check was unreachable**: a passage that never becomes a candidate can never be rescued. An entire frozen stage was dead code behind a plausible-looking number.

**Reversed:** redundancy detection misses paraphrase-level restatement (the common case), and the cross-check that keeps Novelty from contradicting Coverage never fires.

> Same family as §9.4. Both are thresholds that *appear* to work while detecting nothing, and both were found only by measuring real pairs rather than reading the code. **When you tune a similarity threshold, print the actual scores first.**

### 9.21 Detection patterns must tolerate wrapped lines

**What:** `_phrase()` compiles every literal space in a manipulation pattern to `\s+`.

**Why:** prose wraps. `"act now"` split across a newline does not match `act now`. The engine looked like it was checking six pattern families and was only catching the phrases that happened not to wrap — invisible in the output, and it would have degraded quietly on exactly the long-form content the auditor exists to evaluate.

**Reversed:** false-urgency and clickbait detection become a coin flip on line-break position.

### 9.22 Provider errors classify themselves; the service acts on it

**What:** `ProviderError` carries `retryable` / `retry_after` / `status_code`. The provider sets them; `_complete_with_retries` obeys them.

**Why:** the provider is the only layer that knows a 401 from a 503, and the service is the only layer that decides what to do about it. Before this split the service retried *everything*: a missing key cost **9.3s per call**, and ~19s through `complete_json`'s parse-retry. Across eight engines that is minutes of silence on the misconfiguration a first-time user hits by definition — they have not set up their key yet. **Measured after: ~0s.**

The classification is not "4xx bad, 5xx good". **429 must retry** — Groq's free tier rate-limits this system's six-wide wave as a matter of course, and treating that as permanent would degrade half the dimensions of a perfectly good audit. `Retry-After` is honoured as a floor.

**Reversed:** every configuration error becomes a slow timeout, and every rate limit becomes a degraded dimension.

### 9.23 A logging call must never fail the operation it describes

**What:** `bind()` renames fields that collide with `LogRecord` attributes (`filename`, `module`, `name`, `process`, `args`, …) rather than letting logging raise.

**Why:** `bind(filename=…)` raises `KeyError: Attempt to overwrite 'filename' in LogRecord` — so every file upload crashed, from inside its own telemetry, on a line whose only job was to describe what was happening. The reserved list is full of words a caller naturally reaches for, so the guard belongs in the shared helper rather than in the memory of whoever writes the next log line.

**Reversed:** an audit is lost to the record of it, and the next one waits for someone to guess which field name was cursed.

---

## 10. Verified behavior

All offline and deterministic (scripted LLM per Doc 4 §10) with **real** embeddings, chunking, and validators.

### Consolidated M3 suite — **34/34 passing**

| Area | Verified |
|---|---|
| **Orchestrator** | All 8 dimensions returned · frozen ordering validated · all results contract-valid |
| **Engines** | Accuracy `conf=0.996` · Credibility `0.444` · Relevance `0.991` · Coverage `0.985` — all real |
| **Critical findings** | 4 raised across 3 dimensions; **every one carries resolvable evidence**; none unbacked |
| **Evidence** | 25 items; **zero dangling refs** |
| **Confidence** | All in `[0,1]` |
| **SharedContext reuse** | **claim extraction = 1 call** (Accuracy + Credibility) · async keys `(extracted_claims, reference_chunks)` · lazy keys `(paragraphs, sentences, statistics)` |
| **Frozen contracts** | All 8 `dimension_type` / `engine_id` / `critical_finding_capability` match `constants.py` |

### The pytest suite — **120 tests, all passing** (`pytest -m "not live"`, ~90s)

The permanent verification. No API key, no network, no flakiness.

| Suite | Verifies |
|---|---|
| `tests/unit/` | Groq provider + LLM Service (config, JSON, **retry classification**, timeouts, invalid key, error reporting) · content extraction (URL/file, boilerplate stripping, rejections) · `bind()`'s reserved-field guard |
| `tests/decision/` | The Decision Engine, **exhaustively** — the four quadrants, non-compensatory gating, honest uncertainty, N/A, dedupe/ordering, recommendation tiers, confidence, determinism, verdict reachability |
| `tests/api/` | `/health` · the frozen error contract · async job lifecycle with **real** progress · report shape · evidence traceability · upload rejection |
| `tests/e2e/` | Eight engines → Decision Engine → report, on the real stack. Wave ordering · SharedContext reuse (1 claim extraction, not 2) · **fabricated citation ⇒ Untrusted with Quality still High** |
| `-m live` | A real Groq audit. Deselected without a key. |

### Consolidated M5 suite — **106/106 passing** (Decision Engine)

Pure, offline, synthetic `AuditResult`s. No LLM, no embeddings, no engines — the
whole suite runs in milliseconds, which is exactly what Doc 4 §10 predicted for
this layer.

| Scenario | Verified |
|---|---|
| **1. High trust · high quality** | Trusted · Trust-Pass · High |
| **2. High trust · low quality** | Needs Revision — **trust still passes; quality never alters trust** |
| **3. Low trust · high quality** | **Untrusted + Quality High** — the two-axis separation, never fused |
| **4. Low trust · low quality** | Untrusted; both axes still reported |
| **5. Trust-critical failure** | **Untrusted despite every dimension scoring 1.0.** A LOW finding does *not* gate; two LOW findings do *not* add up |
| **6. Unable to Verify** | High score + low confidence ⇒ *Unable to Verify*, never Trusted, never Untrusted |
| **7. Diversity N/A** | Excluded, never penalized. **N/A scores strictly higher than the same dimension scored 0.0** |
| **8. Engine degradation** | Degraded *trust* engine ⇒ Unable to Verify. Degraded *quality* engine ⇒ band unmoved (zero weight), confidence drops. Total degradation ⇒ `score=None`, not 0.0 |
| **9. Conflicting recommendations** | Duplicate merged at the **higher** severity; trust-first ordering; unbacked recommendation dropped |
| **10. Evidence traceability** | Zero dangling refs; every finding and recommendation backed; full `AuditResult`s carried verbatim |
| **11. Confidence aggregation** | Falls with trust confidence; **a trust dimension's low confidence hurts more than a quality one's** |
| **12. Critical findings ordering** | severity → **Trust ahead of Hybrid** → centrality. Dedupe **unions evidence** and keeps the higher severity. Cross-dimension findings never merged. **A Quality dimension can never gate trust even if it emits a finding** |
| **13. Determinism** (§13) | Verdict, finding order, confidence, and summary identical across 5 runs |
| **14. Verdict reachability** (§11) | **All five Overall Verdicts reachable.** *Trusted* requires a clean run — one Low recommendation demotes it to Caveats |

### End-to-end — **18/18 passing**

Real orchestrator → real Decision Engine → real report builder; only the LLM is
scripted.

| Run | Result |
|---|---|
| Clean content | Needs Revision · Trust-Pass with caveats · Quality **High** · conf 0.893 — driven by Credibility 0.30 (see below) |
| **Planted fabricated citation** | **Untrusted** · Credibility critical finding · **Quality still High @ 0.97** — polished *and* untrustworthy, the whole point of two axes |

> ⚠️ **Observed threshold interaction, for M6 tuning — not a defect.** Citation-free
> content scores **Credibility 0.30**, which is below `trust_dimension_pass_threshold`
> (0.70), so *any* uncited text lands on **Needs Revision**. The Decision Engine is
> reading correctly and says so in the summary. Whether 0.30 is the right score for
> "cites nothing" is a Credibility/threshold question, and `engines.*` defaults are
> reasoned rather than measured — M6 tunes them against the corpus.

### Consolidated M4 suite — **260/260 passing**

| Script | Checks | Covers |
|---|---|---|
| `verify_readability.py` | 40 | clean vs dense prose · deterministic/reviewed split · too-short · degradation |
| `verify_novelty.py` | 59 | padding · **cross-check rescue** · no-Coverage · no-candidates · single sentence |
| `verify_engagement.py` | 58 | useful vs manipulative · **reporting-on-manipulation cleared** · no prompt · degraded prior dropped · doesn't average its priors |
| `verify_diversity.py` | 54 | **N/A branch** · balanced vs one-sided · advocacy vs neutral standard · **fringe vs serious omission** |
| `verify_integration.py` | 49 | all 8 through the orchestrator · wave ordering · contracts · evidence · reuse |

**All 8 dimensions, one run, real scores** (scripted LLM, real embeddings/validators/segmentation):

| Dimension | Score | Confidence | Ledger | Evidence |
|---|---|---|---|---|
| Relevance | 1.000 | 0.927 | 2 | 6 |
| Accuracy | 1.000 | 0.913 | 2 | 4 |
| Coverage | 1.000 | 0.919 | 3 | 4 |
| Credibility | 0.300 | 0.700 | 0 | 1 |
| Novelty | 1.000 | 0.933 | 1 | 3 |
| Readability | 1.000 | 0.844 | 3 | 3 |
| Engagement | 1.000 | 0.979 | 2 | 2 |
| **Diversity** | **N/A** | 0.900 | 0 | 0 |

**Quality-engine guarantees, verified on every run:** all four emit `critical_findings == []` · every evidence ref resolves (0 dangling across the whole run) · every recommendation carries evidence · all four degrade to `0.0` confidence with **no forged findings**.

### Per-engine scenarios

| Scenario | Result |
|---|---|
| Accuracy — planted "Berlin" + wrong stat | score **0.238**, 2 findings, opinion excluded |
| Accuracy — mostly unverifiable | score **1.000**, confidence **0.874** ← two axes |
| Accuracy — **no reference** | score 1.000, **confidence 0.323** ← *Unable to Verify* |
| Credibility — dead link | **Fabricated citation** |
| Credibility — live but unrelated | **Misattributed citation** |
| Credibility — unlinked "Smith et al." | **no finding** (low-sev rec only) ✅ |
| Relevance — deterministic override | judge "Satisfied" @55 words vs 20 → **Violated** |
| Relevance — scope drift | espresso 0.18/0.08 flagged; on-topic 0.64/0.40 kept |
| Coverage — drops critical limitation | **Critical omission**, score 0.53 |
| Coverage — **fair summary** | **no findings**, score **0.83** ✅ |
| Readability — clean structured prose | score **0.964**, no issues |
| Readability — dense, 1 monster sentence | score **0.345**; "the the" + 68-word sentence caught **deterministically** |
| Novelty — padded restatements | score **0.687**, 4 candidates confirmed |
| Novelty — **salient recap** | **rescued** by Coverage cross-check; no "delete your conclusion" advice ✅ |
| Novelty — distinct prose | score 1.0, **zero LLM calls** |
| Engagement — manipulative copy | ≤0.5 across 4 pattern families |
| Engagement — **article reporting on manipulation** | patterns matched, judge cleared them → **0.9+** ✅ |
| Engagement — 4 weak priors (0.20) | still **0.7+** — doesn't collapse into their average ✅ |
| Diversity — technical content | **N/A**, pipeline terminated after 1 LLM call ✅ |
| Diversity — **fringe omission** (legitimacy 0.05) | **0.95** — false balance avoided ✅ |
| Diversity — serious omission (legitimacy 0.90) | **0.53** |
| Diversity — declared argument vs neutral survey | **0.94 vs 0.53** on identical text ✅ |

### Infrastructure

Segmentation handles `approx.` / `i.e.` / `Dr.` / `7.8` with `text[s:e] == span.text` exact · `locate_span` recovers reflowed whitespace, returns `None` rather than fuzzy-matching · embedding cache: model+text keying, LRU eviction, in-batch dedupe, cross-call hits · config: flat env, env>YAML, per-provider keys, paid provider gated.

### Backend / API / Frontend

`/health` → `ok | groq | qwen/qwen3-32b | engines: 8 | prompts: 27` · `POST /audit` → a **real** report: 8 dimensions, two axes, per-dimension rationale · async lifecycle 8/8 with **real** engine progress from the orchestrator callback · error contract · **frontend typecheck + build clean** · **live browser round-trip verified end to end** — an audit submitted in the UI rendered the Decision Engine's verdict, the two axes, the dimension table with its *Why* column, and the confidence rationale.

### Verified in Milestone 6

| Area | Result |
|---|---|
| **Groq integration** | 55 checks: config resolution · provider init · `json_object` not `json_schema` · `reasoning_format` sent/omitted · **transient retries vs permanent fail-fast** · `Retry-After` honoured · missing/invalid key · timeouts · truncated errors · `health()` never raises · degradation reaches the engine |
| **URL / file input** | 44 checks: real trafilatura strips nav/cookie/newsletter/footer/script · 404/500/paywall/non-URL/network all raise · txt · md · html · **real PDF via pypdf** · BOM · oversize · corrupt · unsupported |
| **Corpus** | 12 labelled samples covering all 8 required categories |
| **Frontend** | typecheck + build clean · async polling wired · Evidence Viewer · export |
| **Docker** | Compose config validates on a **fresh clone with no `.env`** |

### Not yet verified

⬜ **A real Groq call.** No API key was available in this environment, so every LLM
   response to date is scripted. The Groq path is verified against mocked
   transport for every failure mode, and `tests/e2e -m live` + the calibration
   runner are written and waiting. **First real run may need prompt iteration.**
⬜ **A full `docker compose up`.** The Docker daemon would not start in this
   environment (Docker Desktop's WSL engine never came up). The Dockerfiles and
   compose file are written and `docker compose config` validates; the build
   itself is unrun.

---

## 11. Remaining work

**The build is complete.** All six milestones are done; nothing is stubbed.

### The one open item: calibration against a live key

Everything is verified **except a real Groq run over the corpus**, because this
environment never had a `GROQ_API_KEY`. The corpus, the runner, and the
expectations are written and ready:

```bash
cd backend
cp .env.example .env          # add GROQ_API_KEY=gsk_...
python -m app.evaluation.calibrate
```

That prints the Document 4 §11 results table — *sample → expected → observed →
pass/fail* — plus a separation summary by tier. It exits non-zero if any sample
misses its expectation.

**Expect to tune, and expect it to be prompts before thresholds.** Every LLM
call to date has been scripted; the first real run is the first time the prompts
meet the model. That is why prompts are versioned configuration
(`config/prompts/<engine>/<stage>.v1.md`) — add a `v2` and bump the `version`
attribute on the stage rather than editing in place.

Three interactions to settle with real data:

| Interaction | The question |
|---|---|
| **Credibility 0.30 for uncited content** vs `trust_dimension_pass_threshold` 0.70 | Any citation-free text lands on *Needs Revision*. Correct, or too strict? The corpus has citation-free samples on both tiers to decide it. |
| **`min_trust_confidence` 0.60** | The honesty dial. Too high and everything is *Unable to Verify*; too low and thin measurements get asserted. |
| **`novelty.semantic_threshold` 0.60** | Measured on `all-MiniLM-L6-v2`, not guessed (§9.20) — but measured on *my* samples. Re-check against the corpus. |

Every `engines.*` and `decision.*` default is a **reasoned** default, not a
measured one. This is where they earn their values.

### Nice-to-haves, deliberately not built

- **PDF export.** Doc 4 §2 marks it optional; JSON + Markdown cover the real need.
- **A live-URL corpus.** Deliberately excluded — content that changes under you measures the internet, not the auditor.
- Everything in Doc 4 §14 (more dimensions, fine-tuned models, SSO, streaming, multi-tenant storage, an external vector DB) remains out of scope by design.

---

## 12. FROZEN ARCHITECTURE — do not change

### Contracts

- **`AuditResult`** — the 7 fields (`score`, `confidence`, `ledger`, `evidence`, `recommendations`, `critical_findings`, `metadata`). Adding a field changes a contract Docs 2, 3, and 4 all depend on.
- **`AuditReport`** — Doc 3 §12.
- **`Score = float | "N/A"`** — do not widen to plain `float`.
- **The §6.4 verdict vocabularies** in `vocabularies.py`. *(Exception: `RequirementVerdict` is ours and documented as such.)*
- **The error contract** `{"error":{"code","message"}}`.

### The dimension matrix (`core/constants.py`)

Trust/Quality/Hybrid types · critical-finding capability · N/A support · engine ids · ledger names. **Transcribed from Doc 2 §4.1.** The dimension set is **closed** (Doc 4 §14).

### The pipelines

**All eight, stage by stage, in order.** Never reorder, merge, skip, or collapse a stage.

### Cross-engine dependencies

**Coverage→Novelty. {Relevance, Coverage, Readability, Novelty}→Engagement. Nothing else.** Never add one; never let an engine read another's result outside `prior_results`.

### Architectural rules

| Rule | Source |
|---|---|
| No engine calls a provider, HTTP client, or model directly | Doc 4 §4 |
| Decision Engine depends only on `AuditResult` — never engine internals | Doc 3 §13 |
| API contains no audit or decision logic | Doc 4 §5 |
| Frontend never computes a verdict or score | Doc 4 §5 |
| Preprocessing never evaluates | Doc 4 §5 |
| Prompts and thresholds are configuration, not code | Doc 4 §15 |
| One-way dependency: config → shared → engines → decision → api → frontend | Doc 1 §6 |
| Extraction never classifies | Doc 2 §5.1/§5.2 |
| **Trust is non-compensatory** | Doc 3 §5/§6 |
| **N/A excluded, never penalized** | Doc 3 §9 |
| **Insufficient confidence never becomes a favorable verdict** | Doc 3 §8 |
| **The Decision Engine never re-measures or overrides an engine score** | Doc 3 §1 |
| **The Decision Engine imports no engine module** — `AuditResult` only | Doc 3 §13 |
| **Trust and Quality never alter each other** | Doc 3 §7 |

### Behaviors that look like bugs and are not

- **Placeholder report ⇒ *Unable to Verify*.** Nothing measured ⇒ trust undetermined. **Do not "fix" to something friendlier.**
- **Accuracy: no reference ⇒ score 1.0, confidence 0.32.** The score says "of what was checked, all held up"; confidence says "almost nothing was checked."
- **Coverage: no reference ⇒ confidence 0.0.** A gap, not incompleteness.
- **Unlinked citations raise no finding.**
- **Degraded engines forge no findings.**
- **`relatedness()` not `(cos+1)/2`.**
- **`describe()` does not force `metadata`.**
- **Diversity's N/A carries `confidence=0.9`.** The engine is confident in the judgment it *made* — that the dimension does not apply. That is not the score, which does not exist.
- **Novelty scores 1.0 with zero LLM calls on distinct prose.** Every pair was embedded and compared; nothing crossed the threshold. A real measurement, not a skip.
- **Readability's deterministic issues never reach the LLM classifiers.** The check *is* the category (§9.8).
- **Engagement's manipulation candidates often come back `Legitimate`.** The regex is over-inclusive by design; stage 6 clears it. An article quoting a scam matches every pattern.
- **A declared argument scores far better than a neutral survey on identical text.** The stance contract selects the credit table. This is §7.8's "avoid false balance" working.
- **A trust dimension scoring 0.40 with high confidence is *Needs Revision*, not *Untrusted*.** *Untrusted* is reserved for a disqualifying failure — a qualifying Critical Finding. A low score is a weakness, not a disqualification (Doc 3 §8, §11 step 3).
- **Quality is still reported — with a real band and score — on content gated to *Untrusted*.** That is §7's separation guarantee, not a leak. Polished *and* untrustworthy is a real and common state.
- **Diversity's N/A scores strictly *higher* than the same dimension scored 0.0.** Excluded means excluded from the denominator too (§9).
- **Quality band `Low` with `score=None` is not a measurement.** It is the fail-safe default when nothing could be scored — the three-value enum has no "Unknown". Read the score, not just the band.
- **A degraded quality engine does not lower the quality band.** Its weight is `dim_weight × confidence` = 0, so it cannot vote. It lowers *confidence* instead, and `drivers` names it.
- **A 401 is not retried; a 429 is.** Retrying a rejected key cannot succeed and only spends the backoff. Groq's free tier rate-limits a six-wide wave routinely, so 429 is transient and must retry (§9.22).
- **`docker compose up` starts fine with no `.env`.** It reports `llm_configured: false` and returns *Unable to Verify*. That is the honest answer, not a broken container.
- **A paywalled URL raises rather than auditing what it scraped.** Unlike Credibility's source fetch — where an unreachable URL *is* the finding — the URL here *is* the content. No content, no audit.
- **`bind()` renames `filename` to `filename_`.** `LogRecord` owns the name; renaming beats crashing the audit from inside its own telemetry.

### Do not delete

`llm_providers/openrouter.py` and its commented registry blocks · `workflow.resolve_verdict()` · `orchestrator.validate_plan()` · `AuditEngine.run()`'s three guarantees · the Decision Engine's stage boundaries (each stage is separately testable *because* it is a separate function).

`report_builder.build_placeholder_report()` is **retained but no longer wired** — M5 replaced its call site. It documents the fail-safe report shape and costs nothing; delete it only deliberately.

---

## 13. Continue from here

### Setup (~5 min, plus a torch install)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate                    # Windows;  source .venv/bin/activate  elsewhere
pip install -r requirements.txt           # pulls torch — several minutes
pip install -r requirements-m2.txt        # pytest, trafilatura, textstat
cp .env.example .env                      # add GROQ_API_KEY for real runs (optional)
uvicorn app.main:app --reload             # → http://127.0.0.1:8000/docs

cd ../frontend && npm install && npm run dev     # → http://localhost:5173
```

**Sanity check:** `curl http://127.0.0.1:8000/health` should report
`"engines_registered": 8`, `"prompt_templates": 27`, `"llm_provider": "groq"`.

### Read, in this order

1. **This document.**
2. The specification document that owns whatever you are changing — §3 says which.
3. The module docstring. Every non-obvious decision in this codebase is explained where it lives, not here.

### The build is done — here is how to keep it honest

**Start with the calibration run** (§11). It is the one thing never done against
a real model, and it is the only remaining way to learn something the code
cannot tell you.

**Before changing anything, read §12.** The architecture is frozen. Most of the
non-obvious decisions exist to protect one of the four invariants, and §12 lists
the behaviors that look like bugs and are not — check that list before "fixing"
one of them.

**Run the suite.** `cd backend && pytest -m "not live"` — 120 tests, ~90s, no key
and no network. It is fast enough to run on every change and exhaustive enough
that a break means something.

**When you tune a threshold, print the actual numbers first.** §9.20 exists
because a plausible-looking 0.75 silently disabled an entire frozen stage, and
§9.4 because a plausible-looking rescale silently disabled another. Both were
found by measuring real pairs, not by reading code. Neither would have been
found by reasoning.

### Verification pattern

`tests/conftest.py` has the fixtures: `ScriptedLLM` routes by a marker in the
prompt, `make_services` wires a scripted LLM into otherwise-real services, and
`make_context` builds a `SharedContext` the way preprocessing does.

**Mock the LLM and the socket; keep everything else real.** Embeddings,
segmentation, validators, chunking, and the whole Decision Engine run for real
in the suite — which is why a passing run means the arithmetic under test is the
arithmetic that ships.

```bash
cd backend
pytest -m "not live"        # everything; no key, no network
pytest tests/decision -q    # the correctness core, in milliseconds
pytest -m live              # a real Groq audit; needs GROQ_API_KEY
```

**`assert_contract_valid()`** in `conftest.py` holds the universal guarantees so
a new engine test cannot forget them: contract-valid · confidence in `[0,1]` ·
Quality engines emit `critical_findings == []` · every evidence ref resolves.

### Reminders that will save you time

- **The Decision Engine is pure — keep it that way.** `AuditResult` in, `DecisionResult` out. No IO, no LLM, no engine imports. It is the cheapest layer in the project to test and the worst to get wrong.
- **Never re-measure or override an engine score** (Doc 3 §1). The Decision Engine interprets; it does not measure.
- **`score=0.0, confidence=0.0` means "not measured", not "measured badly".** Read the confidence. Collapsing those two is the failure this system exists to prevent.
- **Diversity really does return `score="N/A"`.** Handle the `float | "N/A"` union at every consumer; never widen it to `float`.
- **Quality engines can never emit Critical Findings.** Only 4 of 8 dimensions can gate trust.
- **The frontend never computes** (Doc 4 §5). Every value it shows was decided by the Decision Engine — including the per-dimension rationale, which comes from `report.dimension_summaries`.
- **`types.ts` mirrors `schemas.py`.** Keep them in sync; a drift shows up as a blank panel, not a compile error.
- **Prompts and thresholds are configuration.** No inline prompt strings, ever.
- **Similarity thresholds are raw cosine.** Use `relatedness()`.
- **When the spec and this document disagree, the spec wins.** Then fix this document.

---

*End of handoff. **All six milestones complete.** 94 modules · 27 prompts · **120 pytest tests + 465 verification checks** · 12 labelled corpus samples · 0 TODOs · 0 `NotImplementedError`.*

*Eight engines measure. The Decision Engine decides. The frontend presents. Text, URL, and file all work; the report is evidence-backed and two-axis; Docker packages it; and the auditor says **Unable to Verify** when it cannot check — which was the whole point.*

*One thing remains, and it needs a key rather than code: **run `python -m app.evaluation.calibrate` against a live Groq model** and tune what the corpus tells you to tune (§11).*
