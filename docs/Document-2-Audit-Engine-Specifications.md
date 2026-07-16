# AI Trust & Quality Auditor — Software Design Specification (SDS)

**Document type:** Software Design Specification
**Subject system:** AI Trust & Quality Auditor — Dimension Audit Engines
**Status:** Frozen implementation (design locked)
**Version:** 1.1 — implementation-metadata enrichment (no implementation changes)
**Audience:** Engineering, evaluation, and integration teams building and consuming the audit engines

> **Version note.** Version 1.1 adds engineering metadata only — Dimension Classification, Critical Finding Capability, Applicability, the Standard AuditResult Contract, and per-engine Shared Components. No audit engine, metric, pipeline, model, ledger, evidence logic, confidence methodology, recommendation logic, or shared workflow has been modified. All Section 7 pipelines and outputs remain frozen and verbatim from v1.0.

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Scope](#2-scope)
3. [Terminology & Glossary](#3-terminology--glossary)
4. [System Overview](#4-system-overview)
   - 4.1 [Dimension Classification & Capability Matrix](#41-dimension-classification--capability-matrix)
5. [Common Architecture & Shared Components](#5-common-architecture--shared-components)
6. [Shared Data Models & Contracts](#6-shared-data-models--contracts)
   - 6.5 [Standard AuditResult Contract](#65-standard-auditresult-contract)
7. [Audit Engine Specifications](#7-audit-engine-specifications)
   - 7.1 [Relevance Audit Engine](#71-relevance-audit-engine)
   - 7.2 [Accuracy Audit Engine](#72-accuracy-audit-engine)
   - 7.3 [Coverage Audit Engine](#73-coverage-audit-engine)
   - 7.4 [Credibility Audit Engine](#74-credibility-audit-engine)
   - 7.5 [Novelty Audit Engine](#75-novelty-audit-engine)
   - 7.6 [Readability Audit Engine](#76-readability-audit-engine)
   - 7.7 [Engagement Audit Engine](#77-engagement-audit-engine)
   - 7.8 [Diversity Audit Engine](#78-diversity-audit-engine)
8. [Cross-Engine Dependencies](#8-cross-engine-dependencies)
9. [Aggregation Layer (Downstream, Out of Scope)](#9-aggregation-layer-downstream-out-of-scope)
10. [Document Conventions](#10-document-conventions)

---

## 1. Introduction

The AI Trust & Quality Auditor evaluates AI-generated content and determines whether it is trustworthy and of high quality. Rather than returning a single opaque score, the auditor produces a structured audit for each quality dimension, and every evaluation yields a score, supporting evidence, a confidence estimate, recommendations, and — where applicable — critical findings.

The auditor is composed of eight independent **Audit Engines**, one per quality dimension:

| # | Dimension | Audit Engine | Governing Question |
|---|-----------|--------------|--------------------|
| 1 | Relevance | Relevance Audit Engine | Does the output satisfy the user's instruction and intent without off-topic content? |
| 2 | Accuracy | Accuracy Audit Engine | Is every factual claim supported, contradicted, or unverifiable against available evidence? |
| 3 | Coverage | Coverage Audit Engine | Does the output include all important information from the reference source without over-penalizing summarization? |
| 4 | Credibility | Credibility Audit Engine | Are factual claims supported by trustworthy, correctly cited, verifiable sources? |
| 5 | Novelty | Novelty Audit Engine | Does the output communicate efficiently, minimizing unnecessary repetition while preserving important content? |
| 6 | Readability | Readability Audit Engine | Is the content easy for its intended audience to understand (clarity, coherence, structure)? |
| 7 | Engagement | Engagement Audit Engine | Does the content help the user achieve their goal without manipulative or misleading communication? |
| 8 | Diversity | Diversity Audit Engine | Where appropriate, does the content fairly represent legitimate perspectives while avoiding false balance? |

This document specifies the frozen implementation of each engine: its purpose, inputs, processing pipeline, and outputs, plus (v1.1) the engineering metadata needed by developers and by the downstream Decision Engine.

---

## 2. Scope

**In scope.** This SDS documents the eight Audit Engines as frozen implementations. For each engine it defines the purpose, the input contract, the ordered processing pipeline, and the output contract. It additionally documents the shared components and data models common to multiple engines, the dependencies between engines, and (v1.1) per-engine implementation metadata: dimension classification, critical-finding capability, applicability, shared-component usage, and the common result contract.

**Out of scope.** This document does not define the cross-dimension aggregation layer (the Decision Engine) that combines the eight engine outputs into a final audit verdict; that layer is downstream and is referenced only as a consumer of engine outputs (see Section 9). This document does not prescribe model selection, prompt text, thresholds, infrastructure, or storage, except where such a step is an explicit stage of a frozen pipeline.

**Design freeze.** The pipelines in Section 7 are locked. This document is an organizational, formatting, and metadata artifact only; it records the decisions as given and does not modify, optimize, or extend them.

---

## 3. Terminology & Glossary

| Term | Definition |
|------|------------|
| **Audit Engine** | A self-contained evaluation pipeline responsible for a single quality dimension. |
| **Dimension** | One of the eight quality axes evaluated by the auditor. |
| **Dimension Type** | Classification of a dimension as Trust, Quality, or Hybrid, consumed by the Decision Engine. |
| **Trust Dimension** | A dimension whose findings bear on whether content can be trusted; capable of gating the trust verdict via Critical Findings. |
| **Quality Dimension** | A dimension whose findings modulate quality; does not gate the trust verdict. |
| **Hybrid Dimension** | A dimension carrying both trust-gating capability (Critical Findings) and quality-modulating signals. |
| **AI Output** | The AI-generated content under audit; the primary subject of evaluation. |
| **Prompt** | The user's original instruction/request associated with the AI Output. |
| **Reference Source** | A source document provided as ground truth for verification (used by Accuracy and Coverage; optional for Accuracy). |
| **Requirement** | An atomic instruction or expectation extracted from the Prompt (Relevance). |
| **Hard Requirement** | A requirement whose violation is treated as a critical/blocking issue (Relevance). |
| **Soft Requirement** | A requirement representing intent or preference rather than a strict constraint (Relevance). |
| **Claim** | An atomic, independently checkable statement extracted from the AI Output (Accuracy). |
| **Key Point** | An atomic unit of important information extracted from the Reference Source (Coverage). |
| **Citation** | A reference, URL, DOI, or attribution present in the AI Output (Credibility). |
| **Verdict** | The per-item evaluation outcome (e.g., Supported / Contradicted / Unverifiable; Present / Partial / Absent; Supports / Partial / Contradicts / Unrelated). |
| **Salience** | The assessed importance of a key point (Coverage). |
| **Centrality** | The degree to which a claim is load-bearing to the AI Output's message (Accuracy). |
| **Severity** | The graded impact assigned to a finding or item. |
| **Ledger** | The itemized, per-unit record of evaluation results produced by an engine (e.g., Claim Verification Ledger, Coverage Ledger, Citation Ledger). |
| **Evidence** | The located support (spans, retrieved passages, matched sources) justifying a verdict or finding. |
| **Critical Finding** | A high-severity issue surfaced separately from the numeric score. |
| **Critical Finding Capability** | Whether an engine can emit Critical Findings (Yes / No / Conditional), per its frozen output contract. |
| **Critical Omission** | A high-severity missing key point (Coverage's critical finding class). |
| **Confidence** | The engine's estimate of how well-supported its own judgment is, reported separately from the score. |
| **Recommendation** | An actionable improvement generated by an engine when issues are found. |
| **Applicability (N/A support)** | Whether an engine may legitimately return N/A instead of a score. |
| **Scope Drift** | Content in the AI Output that departs from the Prompt's topic/scope (Relevance). |
| **Stance Contract** | Whether the AI Output presents itself as neutral/objective or as declared advocacy (Diversity). |
| **AuditResult** | The standardized result object returned by every engine (see Section 6.5). |
| **LLM-as-a-Judge** | Use of an LLM to render a structured, evidence-bearing evaluation. |
| **NLI** | Natural Language Inference; entailment-style verification of a statement against evidence. |

---

## 4. System Overview

The auditor evaluates a single AI Output by running it through the applicable Audit Engines. Each engine operates independently and produces a standardized result package (the AuditResult, Section 6.5). Engines share a common execution shape:

```
Input  →  Extraction / Segmentation  →  Classification & Scoring  →
Verification / Evidence  →  Finding Detection  →  Score  →  Confidence  →  Recommendations  →  Output
```

Engines differ in their inputs (some require the Prompt, some require a Reference Source, some operate on the AI Output alone), in their unit of evaluation (Requirement, Claim, Key Point, Citation, text segment, viewpoint), and in the verdict vocabulary applied to those units. Two engines have distinguishing control characteristics:

- **Engagement** reuses the results of other engines rather than recomputing overlapping signals (see Sections 7.7 and 8).
- **Diversity** begins with an applicability decision and returns **N/A** without scoring when the dimension does not apply (see Section 7.8).

Every engine emits, at minimum: **Score**, **Confidence**, **Evidence**, and **Recommendations**. Most engines additionally emit a per-unit **Ledger** and a **Critical Findings** section. The full per-engine output contracts are given in Section 7, and the common result object in Section 6.5.

### 4.1 Dimension Classification & Capability Matrix

This matrix consolidates the v1.1 metadata for consumption by the Decision Engine. It is a documentation summary of finalized behavior; it introduces no new logic.

| Engine | Dimension Type | Critical Finding Capability | Applicability (N/A) |
|--------|----------------|-----------------------------|---------------------|
| Relevance | **Hybrid Dimension** | **Yes** (Critical Findings) | Does Not Support N/A |
| Accuracy | **Trust Dimension** | **Yes** (Critical Findings) | Does Not Support N/A |
| Coverage | **Hybrid Dimension** | **Yes** (Critical Omissions) | Does Not Support N/A |
| Credibility | **Trust Dimension** | **Yes** (Critical Findings) | Does Not Support N/A |
| Novelty | **Quality Dimension** | **No** | Does Not Support N/A |
| Readability | **Quality Dimension** | **No** | Does Not Support N/A |
| Engagement | **Quality Dimension** | **No** | Does Not Support N/A |
| Diversity | **Quality Dimension** (applicability-gated) | **No** | **Supports N/A** |

**Classification anchor (documentation note).** Dimension Type is aligned to the finalized Critical Finding Capability defined by each engine's frozen output contract in Section 7: engines that emit Critical Findings (Relevance, Accuracy, Coverage, Credibility) are trust-gating and are therefore typed Trust or Hybrid; engines that do not emit Critical Findings (Novelty, Readability, Engagement, Diversity) are quality-modulating and are typed Quality. Trust vs. Hybrid distinguishes engines dedicated to trust verification (Accuracy, Credibility) from engines that combine a trust-gating capability with substantial quality signals (Relevance, Coverage). Diversity is a Quality Dimension that is additionally applicability-gated (it may return N/A). This anchoring is descriptive; it does not alter any frozen decision.

---

## 5. Common Architecture & Shared Components

The following components recur across multiple engines. They are documented once here and referenced by the per-engine specifications (see each engine's **Shared Components Used**). Their presence and ordering within any given engine are defined by that engine's frozen pipeline in Section 7.

For the purpose of the per-engine **Shared Components Used** lists (v1.1), the shared components are catalogued under the following service names:

| Shared Component | Backing Capability (from §5.1–§5.11) |
|------------------|--------------------------------------|
| **Shared LLM Service** | LLM Extraction (§5.1) and LLM Verification / Judge (§5.4) |
| **Shared Retrieval Service** | Retrieval (§5.3) |
| **Shared Embedding Service** | Embedding Analysis (§5.5) |
| **Shared Deterministic Validators** | Deterministic Checks (§5.6) |
| **Shared Evidence Store** | Evidence Collection (§5.7) |
| **Shared Confidence Estimator** | Confidence Estimation (§5.10) |
| **Shared Recommendation Generator** | Recommendation Generation (§5.11) |
| **Shared Prompt Templates** | Prompt definitions backing LLM Extraction / Verification |
| **Shared JSON Models** | Structured schemas for ledgers, evidence, and the AuditResult |

### 5.1 LLM Extraction

LLM-based decomposition of an input into atomic units of evaluation. Instantiated as:
- **Requirement Extraction** (Relevance) — extracts requirements from the Prompt.
- **Claim Extraction** (Accuracy) — extracts factual claims from the AI Output.
- **Key Point Extraction** (Coverage) — extracts important information units from the Reference Source.
- **Citation Extraction** (Credibility) — extracts citations/references from the AI Output.

### 5.2 Classification & Weighting

Assignment of type and/or importance labels to extracted units. Instantiated as:
- **Hard / Soft Requirement Classification** (Relevance).
- **Claim Classification** (Factual / Opinion / Non-verifiable) and **Centrality & Severity Assignment** (Accuracy).
- **Salience Assignment** and **Category & Severity Assignment** (Coverage).
- **Source Classification** (Primary / Secondary / Government / Academic) (Credibility).
- **Issue Classification** and **Severity Assignment** (Readability).
- **Applicability Classification** and **Stance Contract Detection** (Diversity).

### 5.3 Retrieval

Acquisition of evidence against which the AI Output is evaluated. Instantiated as:
- **Evidence Retrieval** — Reference Document first; external retrieval optional (Accuracy).
- **Source Retrieval** — fetching cited sources (Credibility).
- **Retrieval of Credible Perspectives** (Diversity).

### 5.4 LLM Verification / Judge

LLM-based rendering of a per-unit verdict against evidence or criteria. Instantiated as:
- **Per-Requirement Evaluation** (Relevance).
- **Claim Verification** → Supported / Contradicted / Unverifiable (Accuracy).
- **Coverage Verification** → Present / Partial / Absent (Coverage).
- **Grounding Verification** → Supports / Partial / Contradicts / Unrelated (Credibility).
- **Functional Repetition Review** (Novelty).
- **Readability Review** — Clarity, Coherence, Structure (Readability).
- **Task Fitness Evaluation** and **Manipulation Verification** (Engagement).
- **Balance Evaluation** and **Bias & Loaded Language Detection** (Diversity).

### 5.5 Embedding Analysis

Vector-representation analysis of text. Instantiated as:
- **Sentence Embedding-based Scope Drift Detection** (Relevance).
- **Sentence Embedding Generation** and **Semantic & Literal Duplicate Detection** (Novelty).

### 5.6 Deterministic Checks

Rule-based, non-model verification. Instantiated as:
- **Deterministic Constraint Checks** — format, language, length, etc. (Relevance).
- **URL / DOI Verification** (Credibility).
- **Deterministic Analysis** — grammar, sentence complexity, structure heuristics (Readability).
- **Manipulation Pattern Detection** (Engagement).

### 5.7 Evidence Collection

Assembly of the located support behind each verdict/finding into the engine's Evidence output. Present in all engines.

### 5.8 Finding Detection

Identification of high-severity issues surfaced separately from the score. Instantiated as **Critical Finding Detection** (Accuracy, Credibility), **Critical Omission Detection** (Coverage), and **Critical Findings** output (Relevance).

### 5.9 Scoring

Production of the dimension **Score** from the per-unit results and findings.

### 5.10 Confidence Estimation

Production of the **Confidence** value, reported separately from the Score.

### 5.11 Recommendation Generation

Production of actionable **Recommendations** when issues are detected.

---

## 6. Shared Data Models & Contracts

The following logical contracts standardize engine inputs and outputs. Field availability per engine is defined by that engine's specification in Section 7.

### 6.1 Engine Input Contract

| Field | Description | Used by |
|-------|-------------|---------|
| `ai_output` | The AI-generated content under audit. | All engines |
| `prompt` | The user's instruction/request. | Relevance, Engagement, Diversity |
| `reference_source` | Ground-truth source document. Optional for Accuracy; required for Coverage. | Accuracy (optional), Coverage |
| `prior_audit_results` | Results from previously executed engines. | Engagement |

### 6.2 Engine Output Contract

| Field | Description | Notes |
|-------|-------------|-------|
| `score` | The dimension score. | May be `N/A` for Diversity when not applicable. |
| `confidence` | Confidence in the engine's judgment, reported separately from the score. | All engines |
| `evidence` | Located support behind verdicts and findings. | All engines |
| `ledger` | Per-unit evaluation record. | Named per engine (see below). |
| `critical_findings` | High-severity issues surfaced separately from the score. | Relevance, Accuracy, Credibility; Coverage uses `critical_omissions`. |
| `recommendations` | Actionable improvements. | All engines |
| `applicable` / `applicability_reason` | Applicability decision and rationale. | Diversity only |

### 6.3 Ledger Naming by Engine

| Engine | Ledger Name | Unit | Verdict Vocabulary |
|--------|-------------|------|--------------------|
| Relevance | Requirement Checklist | Requirement | Per-requirement evaluation (Hard / Soft classified) |
| Accuracy | Claim Verification Ledger | Claim | Supported / Contradicted / Unverifiable |
| Coverage | Coverage Ledger | Key Point | Present / Partial / Absent |
| Credibility | Citation Ledger | Citation | Supports / Partial / Contradicts / Unrelated |
| Novelty | Redundancy Ledger | Text segment | Redundant candidate / Functional repetition |
| Readability | Readability Ledger | Issue | Classified & severity-assigned issue |
| Engagement | Engagement Ledger | Task-fitness / manipulation item | Task fitness + manipulation verdict |
| Diversity | Diversity Ledger | Viewpoint / bias item | Balance & bias evaluation |

### 6.4 Common Verdict Vocabularies

| Vocabulary | Values | Engine |
|------------|--------|--------|
| Claim verification | Supported / Contradicted / Unverifiable | Accuracy |
| Coverage presence | Present / Partial / Absent | Coverage |
| Grounding | Supports / Partial / Contradicts / Unrelated | Credibility |
| Claim type | Factual / Opinion / Non-verifiable | Accuracy |
| Source class | Primary / Secondary / Government / Academic | Credibility |
| Requirement type | Hard / Soft | Relevance |
| Applicability | Applicable (Yes) / Not Applicable (No) | Diversity |

### 6.5 Standard AuditResult Contract

Every Audit Engine returns the same standardized result object, `AuditResult`, so that the Decision Engine consumes a uniform shape regardless of dimension. Individual engines may leave optional fields empty when not applicable, but the contract remains consistent across all engines.

```
AuditResult
{
    score,               // numeric dimension score, or "N/A" (Diversity when not applicable)
    confidence,          // confidence value, reported separately from score
    ledger,              // per-unit evaluation record (engine-specific ledger; see §6.3)
    evidence,            // located support behind verdicts and findings
    recommendations,     // actionable improvements (may be empty when no issues)
    critical_findings,   // high-severity findings; empty array for engines with Capability = No
    metadata             // engine descriptor and run metadata (see below)
}
```

**Field population rules (documentation of finalized behavior).**

| Field | Population rule |
|-------|-----------------|
| `score` | Always present. `N/A` only for Diversity when `metadata.applicable = No`. |
| `confidence` | Always present. |
| `ledger` | Present using the engine's named ledger (§6.3). Empty for Diversity when not applicable. |
| `evidence` | Always present; may be empty when there are no findings. |
| `recommendations` | Present; empty when no issues are detected. |
| `critical_findings` | Populated by engines with Critical Finding Capability = Yes (Relevance, Accuracy, Credibility, and Coverage — where the field carries Critical Omissions). Empty array for engines with Capability = No (Novelty, Readability, Engagement, Diversity). |
| `metadata` | Always present (see below). |

**`metadata` object.** Carries the v1.1 engine descriptors and the runtime applicability values, keeping the seven-field contract uniform across engines:

```
metadata
{
    dimension,                    // e.g., "Relevance"
    engine_id,                    // e.g., "ENG-RELEVANCE"
    dimension_type,               // "Trust" | "Quality" | "Hybrid"
    critical_finding_capability,  // "Yes" | "No" | "Conditional"
    supports_na,                  // true | false
    applicable,                   // runtime: true | false  (false only when supports_na = true)
    applicability_reason          // runtime: rationale string, or empty
}
```

**Mapping of engine-specific outputs onto the contract.**
- **Coverage.** The frozen `Critical Omissions` output is carried in `critical_findings` (Coverage's critical-finding class).
- **Diversity.** The frozen `Applicable (Yes/No)` and `Applicability Reason` outputs are carried in `metadata.applicable` and `metadata.applicability_reason`; `score` is `N/A` when `applicable = No`.
- All other frozen outputs map one-to-one onto the like-named contract fields.

---

## 7. Audit Engine Specifications

Each engine below is specified as: **Purpose**, **Inputs**, **Classification & Capability** (v1.1 metadata), **Processing Pipeline** (ordered stages, preserving the frozen pipeline), **Outputs**, and **Shared Components Used** (v1.1 metadata).

### 7.1 Relevance Audit Engine

**Engine ID:** `ENG-RELEVANCE`

**Purpose.** Determine whether the AI-generated output satisfies the user's instruction and intent while avoiding irrelevant or off-topic content.

**Inputs.** Prompt + AI Output.

**Classification & Capability.**
- **Type:** Hybrid Dimension
- **Critical Finding Capability:** Yes
- **Applicability:** Does Not Support N/A

**Processing Pipeline.**

1. Input (Prompt + AI Output)
2. LLM-based Requirement Extraction
3. Hard / Soft Requirement Classification
4. Per-Requirement Evaluation
5. Evidence Generation
6. Sentence Embedding-based Scope Drift Detection
7. Deterministic Constraint Checks (format, language, length, etc.)
8. Final Relevance Score
9. Confidence Score
10. Recommendations

**Outputs.**
- Score
- Confidence
- Evidence
- Requirement Checklist
- Critical Findings
- Recommendations

**Shared Components Used.**
- Shared LLM Service
- Shared Embedding Service
- Shared Deterministic Validators
- Shared Evidence Store
- Shared Confidence Estimator
- Shared Recommendation Generator
- Shared Prompt Templates
- Shared JSON Models

---

### 7.2 Accuracy Audit Engine

**Engine ID:** `ENG-ACCURACY`

**Purpose.** Determine whether every factual claim generated by the AI is supported, contradicted, or unverifiable using the available evidence.

**Inputs.** AI Output + Reference Source (if available).

**Classification & Capability.**
- **Type:** Trust Dimension
- **Critical Finding Capability:** Yes
- **Applicability:** Does Not Support N/A

**Processing Pipeline.**

1. Input (AI Output + Reference Source if available)
2. LLM-based Claim Extraction
3. Claim Classification (Factual / Opinion / Non-verifiable)
4. Claim Centrality & Severity Assignment
5. Evidence Retrieval (Reference Document first; external retrieval optional)
6. LLM-based Claim Verification
7. Verdict per Claim (Supported / Contradicted / Unverifiable)
8. Evidence Collection
9. Critical Finding Detection
10. Confidence Estimation
11. Final Accuracy Score

**Outputs.**
- Score
- Confidence
- Claim Verification Ledger
- Critical Findings
- Evidence
- Recommendations

**Shared Components Used.**
- Shared LLM Service
- Shared Retrieval Service
- Shared Evidence Store
- Shared Confidence Estimator
- Shared Recommendation Generator
- Shared Prompt Templates
- Shared JSON Models

---

### 7.3 Coverage Audit Engine

**Engine ID:** `ENG-COVERAGE`

**Purpose.** Determine whether the AI-generated output includes all important information from the reference source without penalizing appropriate summarization.

**Inputs.** Reference Source + AI Output.

**Classification & Capability.**
- **Type:** Hybrid Dimension
- **Critical Finding Capability:** Yes (Critical Omissions)
- **Applicability:** Does Not Support N/A

**Processing Pipeline.**

1. Input (Reference Source + AI Output)
2. LLM Key Point Extraction
3. Salience Assignment
4. Category & Severity Assignment
5. Coverage Verification (Present / Partial / Absent)
6. Evidence Collection
7. Critical Omission Detection
8. Coverage Score
9. Confidence
10. Recommendations

**Outputs.**
- Score
- Confidence
- Coverage Ledger
- Critical Omissions
- Evidence
- Recommendations

**Shared Components Used.**
- Shared LLM Service
- Shared Evidence Store
- Shared Confidence Estimator
- Shared Recommendation Generator
- Shared Prompt Templates
- Shared JSON Models

---

### 7.4 Credibility Audit Engine

**Engine ID:** `ENG-CREDIBILITY`

**Purpose.** Determine whether factual claims are supported by trustworthy, correctly cited, and verifiable sources.

**Inputs.** AI Output.

**Classification & Capability.**
- **Type:** Trust Dimension
- **Critical Finding Capability:** Yes
- **Applicability:** Does Not Support N/A

**Processing Pipeline.**

1. Input (AI Output)
2. LLM Citation Extraction
3. Claim-to-Citation Mapping
4. URL / DOI Verification
5. Source Retrieval
6. Grounding Verification (Supports / Partial / Contradicts / Unrelated)
7. Source Classification (Primary / Secondary / Government / Academic)
8. Evidence Collection
9. Critical Finding Detection
10. Credibility Score
11. Confidence
12. Recommendations

**Outputs.**
- Score
- Confidence
- Citation Ledger
- Critical Findings
- Evidence
- Recommendations

**Shared Components Used.**
- Shared LLM Service
- Shared Retrieval Service
- Shared Deterministic Validators
- Shared Evidence Store
- Shared Confidence Estimator
- Shared Recommendation Generator
- Shared Prompt Templates
- Shared JSON Models

---

### 7.5 Novelty Audit Engine

**Engine ID:** `ENG-NOVELTY`

**Purpose.** Determine whether the AI-generated output communicates information efficiently by minimizing unnecessary repetition while preserving important content.

**Inputs.** AI Output.

**Classification & Capability.**
- **Type:** Quality Dimension
- **Critical Finding Capability:** No
- **Applicability:** Does Not Support N/A

**Processing Pipeline.**

1. Input (AI Output)
2. Text Segmentation
3. Sentence Embedding Generation
4. Semantic & Literal Duplicate Detection
5. Candidate Redundancy Identification
6. LLM-based Functional Repetition Review
7. Coverage Cross-check
8. Novelty Score
9. Confidence
10. Recommendations

**Outputs.**
- Score
- Confidence
- Redundancy Ledger
- Evidence
- Recommendations

**Shared Components Used.**
- Shared Embedding Service
- Shared LLM Service
- Shared Evidence Store
- Shared Confidence Estimator
- Shared Recommendation Generator
- Shared Prompt Templates
- Shared JSON Models
- *Cross-engine input:* consumes Coverage results for the Coverage Cross-check (see §8)

---

### 7.6 Readability Audit Engine

**Engine ID:** `ENG-READABILITY`

**Purpose.** Determine whether the AI-generated content is easy for its intended audience to understand by evaluating clarity, coherence, and document structure.

**Inputs.** AI Output.

**Classification & Capability.**
- **Type:** Quality Dimension
- **Critical Finding Capability:** No
- **Applicability:** Does Not Support N/A

**Processing Pipeline.**

1. Input (AI Output)
2. Deterministic Analysis (Grammar, sentence complexity, structure heuristics)
3. LLM Readability Review (Clarity, Coherence, Structure)
4. Issue Classification
5. Severity Assignment
6. Evidence Collection
7. Readability Score
8. Confidence
9. Recommendations

**Outputs.**
- Score
- Confidence
- Readability Ledger
- Evidence
- Recommendations

**Shared Components Used.**
- Shared Deterministic Validators
- Shared LLM Service
- Shared Evidence Store
- Shared Confidence Estimator
- Shared Recommendation Generator
- Shared Prompt Templates
- Shared JSON Models

---

### 7.7 Engagement Audit Engine

**Engine ID:** `ENG-ENGAGEMENT`
**Alternate title:** Usefulness & Communicative Integrity

**Purpose.** Determine whether the AI-generated content effectively helps the user achieve their goal while avoiding manipulative, sensational, or misleading communication.

**Inputs.** Prompt + AI Output. Also consumes prior audit results (see Cross-Engine Dependencies, Section 8).

**Classification & Capability.**
- **Type:** Quality Dimension
- **Critical Finding Capability:** No
- **Applicability:** Does Not Support N/A

**Processing Pipeline.**

1. Input (Prompt + AI Output)
2. Context & Task Identification
3. Reuse Previous Audit Results (Relevance, Coverage, Readability, Novelty)
4. LLM-based Task Fitness Evaluation
5. Manipulation Pattern Detection
6. LLM Manipulation Verification
7. Evidence Collection
8. Engagement Score
9. Confidence
10. Recommendations

**Outputs.**
- Score
- Confidence
- Engagement Ledger
- Evidence
- Recommendations

**Shared Components Used.**
- Shared LLM Service
- Shared Deterministic Validators
- Shared Evidence Store
- Shared Confidence Estimator
- Shared Recommendation Generator
- Shared Prompt Templates
- Shared JSON Models
- *Cross-engine input:* consumes prior audit results from Relevance, Coverage, Readability, Novelty (see §8)

---

### 7.8 Diversity Audit Engine

**Engine ID:** `ENG-DIVERSITY`

**Purpose.** Determine whether AI-generated content fairly represents legitimate perspectives when diversity is appropriate, while avoiding false balance for factual or technical content.

**Inputs.** Prompt + AI Output.

**Classification & Capability.**
- **Type:** Quality Dimension (applicability-gated)
- **Critical Finding Capability:** No
- **Applicability:** Supports N/A

**Processing Pipeline.**

1. Input (Prompt + AI Output)
2. Applicability Classification
3. **Applicability branch:**
   - **No →** Return N/A (terminate; no score produced).
   - **Yes →** proceed to the evaluation branch below.
4. Stance Contract Detection
5. Retrieval of Credible Perspectives
6. Viewpoint Extraction
7. Balance Evaluation
8. Bias & Loaded Language Detection
9. Evidence Collection
10. Diversity Score
11. Confidence
12. Recommendations

**Control flow (as frozen):**

```
Input (Prompt + AI Output)
        ↓
Applicability Classification
        ↓
   Applicable?
   /        \
  No         Yes
  ↓           ↓
Return N/A   Stance Contract Detection
                ↓
             Retrieval of Credible Perspectives
                ↓
             Viewpoint Extraction
                ↓
             Balance Evaluation
                ↓
             Bias & Loaded Language Detection
                ↓
             Evidence Collection
                ↓
             Diversity Score
                ↓
             Confidence
                ↓
             Recommendations
```

**Outputs.**
- Applicable (Yes/No)
- Applicability Reason
- Score (or N/A)
- Confidence
- Diversity Ledger
- Evidence
- Recommendations

**Shared Components Used.**
- Shared LLM Service
- Shared Retrieval Service
- Shared Evidence Store
- Shared Confidence Estimator
- Shared Recommendation Generator
- Shared Prompt Templates
- Shared JSON Models

---

## 8. Cross-Engine Dependencies

The engines are independently executable, with the following defined dependencies:

- **Engagement → Relevance, Coverage, Readability, Novelty.** The Engagement engine's pipeline explicitly reuses previous audit results from the Relevance, Coverage, Readability, and Novelty engines (Stage 3, "Reuse Previous Audit Results"). These four engines must therefore complete before Engagement executes, and their outputs must be available to Engagement as `prior_audit_results`.
- **Novelty → Coverage.** The Novelty engine's pipeline includes a "Coverage Cross-check" (Stage 7), relating its redundancy findings to coverage information.
- **Diversity → Retrieval.** On the Applicable=Yes branch, the Diversity engine performs "Retrieval of Credible Perspectives" (Stage 5) as part of its evaluation.

Engines not listed above (Relevance, Accuracy, Coverage, Credibility, Readability) operate without dependencies on other engines' outputs, per their frozen pipelines.

**Implied execution ordering.** Because Engagement consumes Relevance, Coverage, Readability, and Novelty results, and Novelty performs a Coverage cross-check, a valid ordering completes Coverage before Novelty, and completes Relevance, Coverage, Readability, and Novelty before Engagement. Accuracy, Credibility, and Diversity have no cross-engine input dependencies.

---

## 9. Aggregation Layer (Downstream, Out of Scope)

Each Audit Engine emits a standardized result package — the AuditResult (Section 6.5) — carrying Score, Confidence, Evidence, Ledger, Critical Findings (where applicable), Recommendations, and metadata. These per-dimension results are consumed by a downstream aggregation layer (the Decision Engine) that produces the overall audit verdict for the AI Output. The design of that aggregation layer is **out of scope for this SDS** and is referenced here only to identify the engines' outputs as its inputs.

The v1.1 metadata is provided specifically to support that downstream consumption: `metadata.dimension_type` identifies Trust / Quality / Hybrid engines, `metadata.critical_finding_capability` and the `critical_findings` field identify trust-gating signals, and `metadata.supports_na` / `metadata.applicable` identify the Diversity engine's non-scoring `N/A` result, which the aggregation layer must accommodate.

---

## 10. Document Conventions

- **Terminology.** Terms defined in Section 3 are used consistently throughout. Ledger names, verdict vocabularies, and classification label sets are used exactly as defined in Sections 3 and 6.
- **Pipelines.** Each engine's Processing Pipeline in Section 7 preserves the frozen stage sequence. Stage names are reproduced as specified.
- **Outputs.** Each engine's Outputs list reproduces the frozen output contract for that engine.
- **Metadata (v1.1).** The Classification & Capability blocks, Shared Components Used lists, the Dimension Classification & Capability Matrix (§4.1), and the Standard AuditResult Contract (§6.5) are engineering metadata added for implementation and Decision-Engine consumption. They document finalized behavior and introduce no implementation change.
- **Frozen status.** This document is organizational and descriptive only. It records the frozen implementation decisions and introduces no design changes, optimizations, or alternatives to any engine, metric, pipeline, model, ledger, evidence logic, confidence methodology, recommendation logic, or shared workflow.
- **Engine identifiers.** `ENG-*` identifiers are naming conventions introduced by this document for reference within the specification and downstream artifacts; they do not alter any frozen decision.

---

*End of Software Design Specification — AI Trust & Quality Auditor, Version 1.1.*
