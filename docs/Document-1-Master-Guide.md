# Document 1 — AI Trust & Quality Auditor
## Master System Architecture & Engineering Guide

**Document type:** Master System Guide (read this first)
**Subject system:** AI Trust & Quality Auditor
**Status:** Master map over the frozen engineering source of truth
**Version:** 1.0
**Connects (frozen):** Document 2 — *Audit Engine Specifications*; Document 3 — *Auditor Intelligence & Decision Engine Specification*; Document 4 — *Implementation & Validation Specification*

> **Purpose of this document.** This is the single entry point to the project. It does not redesign anything and does not repeat the detailed metrics (Document 2), decision rules (Document 3), or implementation specifics (Document 4). It explains how the whole system fits together and points you to the right document for depth. If you are new to the project, read this document first.

---

## Table of Contents

1. [Vision](#1-vision)
2. [System Overview](#2-system-overview)
3. [System Components](#3-system-components)
4. [Runtime Execution Flow](#4-runtime-execution-flow)
5. [Data Flow](#5-data-flow)
6. [Internal Relationships](#6-internal-relationships)
7. [Document Relationship](#7-document-relationship)
8. [Build Roadmap](#8-build-roadmap)
9. [End-to-End Example](#9-end-to-end-example)
10. [Deployment Overview](#10-deployment-overview)
11. [Engineering Principles](#11-engineering-principles)
12. [Developer Onboarding](#12-developer-onboarding)

---

## 1. Vision

**What it is.** The AI Trust & Quality Auditor evaluates any AI-generated content — summaries, reports, articles, explanations, answers — and produces a complete, evidence-backed audit that says whether the content is trustworthy and of high quality, and *why*.

**Why it was built.** As AI-generated text spreads, the hard problem is no longer producing content but *knowing which output to trust*. Confident, fluent, well-formatted text can still be hallucinated, mis-sourced, off-instruction, or incomplete. Teams need a reliable way to separate good AI outputs from bad ones.

**What it solves.** It reliably distinguishes trustworthy content from untrustworthy content and explains the judgment: what the verdict is, what evidence supports it, how confident the auditor is, and what to fix.

**What makes it different.** Traditional evaluation returns a score. This system behaves like a **real auditor**. It is:

- **Evidence-first** — every conclusion traces to concrete evidence.
- **Non-compensatory for trust** — a single critical failure (e.g., a fabricated citation) cannot be averaged away by high scores elsewhere.
- **Confidence-aware** — it admits uncertainty and can return *Unable to Verify* instead of guessing.
- **Explainable** — every score and finding is traceable and human-reviewable.

The output is never just a number; it is a verdict with evidence, confidence, critical findings, and prioritized recommendations.

---

## 2. System Overview

At the highest level, the auditor is a pipeline of layers. Content enters, shared services power a framework of eight independent audit engines, a decision engine reasons across their results, and an explainable report is delivered to the user.

```
┌──────────────────────────────────────────────────────────────┐
│                    AI TRUST & QUALITY AUDITOR                 │
│                                                              │
│   Input Layer                                                │
│   (text | url | file  →  extracted & normalized content)     │
│        │                                                     │
│        ▼                                                     │
│   Shared Services                                            │
│   (LLM · Embedding · Retrieval · Prompts · Evidence ·        │
│    Recommendation · Confidence · Validators · Config)        │
│        │                                                     │
│        ▼                                                     │
│   Audit Engine Framework  (orchestrator + AuditResult contract)│
│        │                                                     │
│        ▼                                                     │
│   ┌───────────────── Eight Audit Engines ─────────────────┐  │
│   │  Trust:   Accuracy · Credibility                      │  │
│   │  Hybrid:  Relevance · Coverage                        │  │
│   │  Quality: Novelty · Readability · Engagement ·        │  │
│   │           Diversity (may return N/A)                  │  │
│   └───────────────────────────────────────────────────────┘  │
│        │  (eight AuditResults)                               │
│        ▼                                                     │
│   Decision Engine                                            │
│   (trust vs. quality · critical findings · confidence ·      │
│    verdict)                                                  │
│        │                                                     │
│        ▼                                                     │
│   Audit Report   (Trust + Quality verdicts, evidence,        │
│                   findings, recommendations, confidence)     │
│        │                                                     │
│        ▼                                                     │
│   Frontend       (dashboard · dimension cards · evidence ·   │
│                   export)                                    │
└──────────────────────────────────────────────────────────────┘
```

Layer detail lives in the frozen documents: engines in Document 2, the Decision Engine in Document 3, and the concrete implementation in Document 4.

---

## 3. System Components

Responsibilities only — no implementation detail (see Document 4 for that).

| Subsystem | Responsibility | Defined in |
|-----------|----------------|-----------|
| **Input Layer** | Accept text, URL, or file; extract and normalize it into the content the engines expect. | Document 4 (preprocessing, API) |
| **Shared Services** | Provide the reusable capabilities every engine uses — LLM access, embeddings, retrieval, prompt management, evidence collection, recommendation shaping, confidence utilities, deterministic validators, configuration, and the shared schemas. | Document 2 (§5), Document 4 (§4) |
| **Audit Engine Framework** | Orchestrate the eight engines, honor the frozen cross-engine ordering, and standardize every engine's output as an `AuditResult`. | Document 2, Document 4 |
| **Eight Audit Engines** | Each independently evaluates one dimension and returns an `AuditResult` (score, confidence, ledger, evidence, recommendations, critical findings, metadata). Two are Trust dimensions, two Hybrid, four Quality. | Document 2 |
| **Decision Engine** | Consume the eight `AuditResult`s and reason across them: separate trust from quality, apply critical-finding gates non-compensatorily, integrate confidence, handle N/A, and produce the Final Audit Report. | Document 3 |
| **API Layer** | Expose the auditor over REST, manage async audit jobs, and return the report. | Document 4 (§7) |
| **Frontend** | Collect input, show progress, and render the report so verdicts, evidence, and recommendations are explorable and exportable. | Document 4 (§8) |

The dividing line to remember: **engines measure; the Decision Engine decides; the frontend presents.**

---

## 4. Runtime Execution Flow

A complete audit, from submission to dashboard:

```
User submits input  (URL | text | file)
        │
        ▼
Content Extraction        (fetch + clean for URL/file)
        │
        ▼
Preprocessing             (normalize into engine input)
        │
        ▼
Shared Services ready      (LLM, Embedding, Retrieval, Prompts,
                            Validators, Config initialized)
        │
        ▼
Audit Engine Orchestrator
        │
        ▼
Eight Audit Engines execute
   (parallel wave, then Novelty after Coverage,
    then Engagement after Relevance/Coverage/Readability/Novelty)
        │
        ▼
AuditResults produced      (one per dimension)
        │
        ▼
Decision Engine            (validate → applicability → critical
                            findings → trust → quality → confidence
                            → recommendations → verdict)
        │
        ▼
Audit Report               (Trust + Quality verdicts, evidence,
                            findings, recommendations, confidence)
        │
        ▼
API Response               (report retrieved by audit_id)
        │
        ▼
Frontend Dashboard         (verdicts, dimension cards, evidence,
                            export)
```

The engine execution order and the Decision Engine stages shown here are the frozen behavior from Documents 2 and 3; this guide only maps their sequence.

---

## 5. Data Flow

The audit is a transformation of a few well-defined objects. Each is owned by one layer and consumed by the next.

```
AuditRequest
     │
     ▼
PreprocessedContent
     │
     ▼
AuditResult  ×8
     │
     ▼
DecisionResult
     │
     ▼
AuditReport
```

| Object | Represents | Produced by → Consumed by |
|--------|------------|---------------------------|
| **AuditRequest** | The incoming job: the content (or URL/file), optional prompt, optional reference source, and options. | API → Preprocessing |
| **PreprocessedContent** | Normalized, extracted content ready for evaluation. | Preprocessing → Audit Engines |
| **AuditResult** | One dimension's complete evaluation — the frozen contract: score, confidence, ledger, evidence, recommendations, critical findings, metadata. Eight are produced per audit. | Each Audit Engine → Decision Engine |
| **DecisionResult** | The Decision Engine's cross-dimensional outcome: Trust Verdict, Quality Verdict, overall verdict, integrated confidence, and prioritized recommendations. | Decision Engine → Report builder |
| **AuditReport** | The final, explainable, evidence-first deliverable presented to the user (the Final Audit Report of Document 3). | Report builder → API → Frontend |

The `AuditResult` and `AuditReport` shapes are frozen (Documents 2 and 3); this guide only shows how they move through the system.

---

## 6. Internal Relationships

Dependencies flow in one direction — from shared foundations up to the report. Understanding this graph is enough to know what to build first and what breaks what.

```
Configuration
     │  (thresholds, weights, models, prompts)
     ▼
Shared Services
     │  used by ALL engines (LLM, Embedding, Retrieval, Prompts,
     │  Evidence, Recommendation, Confidence, Validators, Schemas)
     ▼
Audit Engines  ×8
     │  each produces an AuditResult
     │  (frozen cross-engine inputs: Coverage → Novelty;
     │   Relevance/Coverage/Readability/Novelty → Engagement)
     ▼
Decision Engine
     │  consumes the eight AuditResults; produces the DecisionResult
     ▼
API Layer
     │  returns the AuditReport by audit_id
     ▼
Frontend
        renders verdicts, evidence, and recommendations
```

**Key dependency rules (all frozen upstream):**

- Every engine depends on Shared Services; **no engine calls a provider or performs IO directly.**
- Engines are independent of one another except the two frozen cross-engine inputs above.
- The Decision Engine depends only on the `AuditResult` contract — never on engine internals. This is the stable seam that lets engines evolve without touching decision logic.
- The API and Frontend depend only on the `AuditReport` contract.

---

## 7. Document Relationship

Four documents, one system. This guide is the map; the other three are the source of truth for their domain.

```
Document 1  — Master Guide (this document)
     │   "How does it all fit together? Where do I look?"
     │   ── points to ──►
     ├───────────────► Document 2 — Audit Engine Specifications
     │                    "How is each dimension measured?"
     │                    (engines, pipelines, ledgers, evidence,
     │                     confidence, AuditResult contract)
     │
     ├───────────────► Document 3 — Decision Engine Specification
     │                    "How are the results turned into a verdict?"
     │                    (workflow, critical findings, trust vs.
     │                     quality, confidence, verdict categories,
     │                     Final Audit Report)
     │
     └───────────────► Document 4 — Implementation & Validation
                          "How do we build, test, validate, and demo it?"
                          (tech stack, project structure, services,
                           API, frontend, testing, validation)
```

**How they connect.** Document 2 defines the measurement layer and the `AuditResult` contract that Document 3 consumes. Document 3 defines the decision layer and the `AuditReport` that Document 4 exposes and renders. Document 4 implements both. Document 1 (this document) links them so a reader always knows which document answers their question.

---

## 8. Build Roadmap

The recommended implementation order — a summary of Document 4's build order, presented here as the master roadmap. Build bottom-up so each layer is testable before the next depends on it.

```
Foundation            (repo, config, schemas / AuditResult model)
     │
     ▼
Shared Services       (LLM, Embedding, Retrieval, Prompts, Evidence,
     │                 Recommendation, Confidence, Validators)
     ▼
Audit Engine Framework (orchestrator + engine interface)
     │
     ▼
Trust Engines         (Accuracy, Credibility)  ── highest-risk first
     │
     ▼
Quality Engines       (Relevance, Coverage, Novelty, Readability,
     │                 Engagement, Diversity)
     ▼
Decision Engine       (Document 3 workflow)
     │
     ▼
API                   (async audit jobs + report retrieval)
     │
     ▼
Frontend              (dashboard, dimension cards, evidence, export)
     │
     ▼
Validation            (good / medium / poor + URL + text separation)
```

**Why this order.** Shared Services and the schema underpin everything, so they come first. Engines are thin once services exist; building the trust-critical ones first de-risks the core claim. The Decision Engine needs real engine outputs to test against. The API and Frontend layer onto a stable report contract, avoiding rework. Validation comes last, once there is an end-to-end system to prove separates good from bad. Full detail and the day-by-day mapping are in Document 4.

---

## 9. End-to-End Example

One complete audit, tying every layer together (behavior per the frozen documents):

```
Input
  │   A user pastes an AI-written article, or submits its URL.
  ▼
URL / Extraction
  │   The Input Layer fetches and cleans the article into
  │   PreprocessedContent.
  ▼
Audit Engines
  │   Shared Services power the eight engines. They run in parallel
  │   (with the frozen ordering for Novelty and Engagement). Each
  │   returns an AuditResult with a score, confidence, and evidence.
  │   Suppose Credibility finds a citation that does not exist.
  ▼
Evidence
  │   Credibility records a critical finding — "fabricated citation" —
  │   linked to the exact citation and the failed source lookup.
  │   Other engines attach their own evidence (claims, key points,
  │   redundancy spans, readability issues).
  ▼
Decision
  │   The Decision Engine processes critical findings before scoring.
  │   The fabricated-citation critical finding gates trust
  │   non-compensatorily → Trust Verdict: Untrusted — regardless of
  │   strong Readability or Relevance scores. Quality is still
  │   assessed and reported separately.
  ▼
Final Report
      Overall Verdict: Untrusted. The report shows the Trust and
      Quality verdicts, the critical finding with its evidence, the
      per-dimension results, prioritized recommendations (fix/remove
      the fabricated citation first), and confidence. The frontend
      renders it; the user can drill into evidence and export it.
```

This is the whole system in one pass: measure (engines) → decide (Decision Engine) → explain (report + frontend), with evidence at every step.

---

## 10. Deployment Overview

High level; specifics are in Document 4.

```
Local Development
     │   Run backend (FastAPI) and frontend directly; LLM via
     │   OpenAI API or a local Ollama; config via .env / YAML.
     ▼
Docker
     │   docker-compose brings up backend, frontend, and (optionally)
     │   a local model, for a reproducible demo environment.
     ▼
Production
         The same containers behind a health check, with providers
         and thresholds set by configuration. Fail-safe behavior
         (bias toward Unable to Verify / Untrusted) protects trust.
```

Deployment introduces no new behavior — it packages the frozen system.

---

## 11. Engineering Principles

The principles that govern the whole project (consistent across Documents 2–4):

- **Evidence-first** — every conclusion links to concrete evidence.
- **Explainable** — verdicts, scores, and findings are traceable and human-readable.
- **Non-compensatory trust** — a qualifying critical finding governs the trust verdict regardless of other scores.
- **Honest uncertainty** — the auditor returns *Unable to Verify* rather than assert trust it cannot support.
- **Modular** — engines, shared services, decision engine, API, and frontend are independent and separately testable.
- **Reusable** — all cross-cutting concerns live in Shared Services.
- **Configurable** — thresholds, weights, models, and prompts are configuration, not code.
- **Production-ready** — timeouts, retries, graceful degradation, health checks, and logging by default.
- **Human-review friendly** — outputs route uncertain or flawed content to reviewers with clear, prioritized actions.

---

## 12. Developer Onboarding

If you are joining the project, start here.

**1. Read in this order.**
- **This document (Document 1)** first — for the whole-system picture and where everything lives.
- **Document 2** — to understand how each dimension is measured and the `AuditResult` contract.
- **Document 3** — to understand how results become a trust/quality verdict.
- **Document 4** — to understand the stack, project structure, and how to build/test/validate.

**2. Understand these core ideas before coding.**
- The system **measures (engines), decides (Decision Engine), and presents (frontend)** — keep these separated.
- Every engine returns the same **`AuditResult`**; the Decision Engine depends only on that contract.
- **Trust is non-compensatory; quality is compensatory;** they are reported on two separate axes.
- The auditor is **evidence-first** and prefers **honest uncertainty** to a false verdict.

**3. Begin implementation.**
- Follow the **Build Roadmap** (§8): Foundation → Shared Services → Audit Engine Framework → Trust Engines → Quality Engines → Decision Engine → API → Frontend → Validation.
- Build against the **frozen contracts** (`AuditResult`, `AuditReport`); do not redesign engines, decision rules, or shared services.
- Use **Document 4's project structure, technology choices, and testing/validation strategy** as your concrete guide.
- Prove the system works by demonstrating that it **separates good from bad content** across text and URL inputs (Document 4, Validation).

Whenever you need depth, return to the document that owns that concern — this guide will always tell you which one that is.

---

*End of Master System Architecture & Engineering Guide — AI Trust & Quality Auditor (Document 1), Version 1.0.*
