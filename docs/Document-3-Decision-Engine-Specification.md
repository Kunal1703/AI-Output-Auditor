# AI Trust & Quality Auditor
## Auditor Intelligence & Decision Engine Specification (Document 3)

**Document type:** Software Design Specification — Intelligence & Decision Layer
**Subject system:** AI Trust & Quality Auditor — Decision Engine
**Status:** Design (implementation-ready)
**Version:** 1.0
**Source of truth:** Document 2 — *Audit Engine Specifications* (frozen). This document consumes Document 2; it does not modify any Audit Engine, metric, pipeline, model, ledger, evidence logic, confidence methodology, recommendation logic, shared component, or the AuditResult schema.

> **Boundary statement.** The eight Audit Engines define **how each dimension is measured**. This document defines **how the auditor reasons over completed measurements to reach an overall decision**. It sits between the Audit Engines and the Final Audit Report. It introduces no new metrics and reuses the frozen dimension classifications, capabilities, and the AuditResult contract from Document 2.

---

## Table of Contents

1. [Purpose](#1-purpose)
2. [Responsibilities](#2-responsibilities)
3. [Inputs](#3-inputs)
4. [Decision Workflow](#4-decision-workflow)
5. [Critical Finding Processing](#5-critical-finding-processing)
6. [Trust Evaluation](#6-trust-evaluation)
7. [Quality Evaluation](#7-quality-evaluation)
8. [Confidence Integration](#8-confidence-integration)
9. [Applicability Handling](#9-applicability-handling)
10. [Recommendation Prioritization](#10-recommendation-prioritization)
11. [Verdict Categories](#11-verdict-categories)
12. [Final Audit Report](#12-final-audit-report)
13. [Engineering Principles](#13-engineering-principles)

---

## 1. Purpose

The Decision Engine is the reasoning layer — the "brain" — of the AI Trust & Quality Auditor. Its responsibility is to consume the completed `AuditResult` objects produced by the eight Audit Engines and to produce a single, explainable, evidence-backed audit decision for the content under review.

**Measurement vs. decision-making.** The two layers have strictly separated responsibilities:

| Layer | Responsibility | Output |
|-------|----------------|--------|
| **Audit Engines** (Document 2) | *Measurement.* Evaluate one dimension each, producing per-dimension scores, ledgers, evidence, confidence, critical findings, and recommendations. | Eight `AuditResult` objects |
| **Decision Engine** (this document) | *Decision-making.* Interpret, weigh, and combine those measurements into an overall trust and quality determination, resolve conflicts, honor uncertainty, and assemble the Final Audit Report. | One Final Audit Report with Trust Verdict, Quality Verdict, and prioritized recommendations |

The Decision Engine never re-measures a dimension, never overrides an engine's per-dimension score, and never generates new evidence. It only **interprets** what the engines produced. Every determination it makes must trace back to `AuditResult` fields supplied by the engines.

---

## 2. Responsibilities

The Decision Engine is responsible for, and only for, the following:

1. **Consuming AuditResults.** Ingest all eight `AuditResult` objects and validate their structural completeness.
2. **Handling applicability.** Detect and correctly exclude dimensions that return `N/A` so they do not distort the outcome (Section 9).
3. **Processing Critical Findings.** Collect, deduplicate, and severity-order all Critical Findings emitted by capable engines, and apply non-compensatory gating (Section 5).
4. **Separating Trust and Quality.** Route dimensions to the Trust evaluation and the Quality evaluation according to the frozen `dimension_type` metadata (Sections 6–7).
5. **Integrating confidence.** Interpret per-dimension confidence to decide when a verdict can be asserted and when the auditor must declare *Unable to Verify* (Section 8).
6. **Resolving conflicts.** Reconcile disagreements between dimensions (e.g., a high score alongside a Critical Finding) using the precedence rules in Sections 5–6.
7. **Producing final verdicts.** Emit a Trust Verdict, a Quality Verdict, and an Overall Verdict drawn from the fixed verdict set (Section 11).
8. **Prioritizing recommendations.** Merge and order all engine recommendations by severity into a single evidence-backed action list (Section 10).
9. **Producing the Final Audit Report.** Assemble the complete, explainable, evidence-first report (Section 12).

Everything outside this list — measurement, prompt design, model selection, engine internals — belongs to Document 2 and is out of scope.

---

## 3. Inputs

The Decision Engine receives exactly the eight `AuditResult` objects defined by the frozen AuditResult Contract (Document 2, §6.5). No other input is required. Each object supplies:

| Field | Consumed for |
|-------|--------------|
| `score` | Trust and Quality evaluation; may be `N/A` (Diversity when not applicable). |
| `confidence` | Confidence integration; gating of assertable verdicts. |
| `ledger` | Traceability and evidence linkage in the report (per-unit detail). |
| `evidence` | Evidence-first justification of every conclusion. |
| `recommendations` | Recommendation prioritization. |
| `critical_findings` | Critical Finding processing and non-compensatory trust gating. |
| `metadata.dimension` / `metadata.engine_id` | Identification and report labeling. |
| `metadata.dimension_type` | Routing to Trust vs. Quality evaluation (`Trust` / `Quality` / `Hybrid`). |
| `metadata.critical_finding_capability` | Determining whether an empty `critical_findings` is expected or anomalous. |
| `metadata.supports_na` / `metadata.applicable` | Applicability handling. |
| `metadata.applicability_reason` | Report transparency for excluded dimensions. |

**Fixed dimension routing (from Document 2, §4.1).** The Decision Engine treats the following classification as fixed input, not as something it computes:

| Dimension | `dimension_type` | Critical Finding Capable | Supports N/A |
|-----------|------------------|--------------------------|--------------|
| Relevance | Hybrid | Yes | No |
| Accuracy | Trust | Yes | No |
| Coverage | Hybrid | Yes (Critical Omissions) | No |
| Credibility | Trust | Yes | No |
| Novelty | Quality | No | No |
| Readability | Quality | No | No |
| Engagement | Quality | No | No |
| Diversity | Quality (applicability-gated) | No | Yes |

---

## 4. Decision Workflow

The Decision Engine executes a fixed, ordered pipeline. The ordering is deliberate: applicability and critical findings are resolved **before** any scoring is interpreted, so that a disqualifying condition short-circuits the rest of the reasoning.

```
Receive AuditResults
        ↓
Validate Results
        ↓
Handle Applicability (N/A)
        ↓
Process Critical Findings
        ↓
Trust Evaluation
        ↓
Quality Evaluation
        ↓
Confidence Integration
        ↓
Recommendation Prioritization
        ↓
Generate Final Verdict
        ↓
Generate Audit Report
```

**Stage 1 — Receive AuditResults.** Collect the eight `AuditResult` objects for the content under review.

**Stage 2 — Validate Results.** Confirm each object conforms to the AuditResult Contract: required fields present, `metadata` populated, and `critical_findings` present as an array (empty is valid for engines with `critical_finding_capability = No`). A structurally invalid or missing result for a Trust or Hybrid dimension is treated as a verification gap and pushes the run toward *Unable to Verify* (Section 8), because trust cannot be asserted on incomplete measurement.

**Stage 3 — Handle Applicability (N/A).** Partition dimensions into *scored* and *N/A* sets using `metadata.applicable`. N/A dimensions are removed from all downstream aggregation and denominators, and recorded for the report (Section 9).

**Stage 4 — Process Critical Findings.** Gather every `critical_findings` entry from the four capable engines, severity-order them, and evaluate the non-compensatory gate (Section 5). This stage can set a provisional *Untrusted* outcome that later stages will not override.

**Stage 5 — Trust Evaluation.** Evaluate the Trust and Hybrid dimensions non-compensatorily to produce the Trust Verdict (Section 6).

**Stage 6 — Quality Evaluation.** Evaluate the Quality dimensions (and the quality contribution of Hybrid dimensions) compensatorily to produce the Quality Verdict (Section 7).

**Stage 7 — Confidence Integration.** Overlay per-dimension confidence on the Trust and Quality outcomes to decide whether each verdict is assertable, or whether the run must be marked *Unable to Verify* (Section 8).

**Stage 8 — Recommendation Prioritization.** Merge all engine recommendations, bind each to its evidence, and order by severity (Section 10).

**Stage 9 — Generate Final Verdict.** Combine Trust Verdict, Quality Verdict, and confidence state into the Overall Verdict from the fixed set (Section 11).

**Stage 10 — Generate Audit Report.** Assemble the Final Audit Report (Section 12).

---

## 5. Critical Finding Processing

**Definition.** A Critical Finding is a high-severity issue that an Audit Engine surfaced separately from its numeric score, as defined in Document 2. Only four engines can emit them (`critical_finding_capability = Yes`): **Relevance**, **Accuracy**, **Coverage** (as *Critical Omissions*), and **Credibility**. Quality dimensions never emit Critical Findings, so they can never gate trust.

**Why they are special.** Critical Findings encode failures that make content untrustworthy *regardless of how well it scores elsewhere* — for example, a contradicted claim, a fabricated or misattributed citation, a violated hard requirement, or a critical omission. The Decision Engine therefore treats them as **non-compensatory**: they cannot be averaged away by strong scores on other dimensions.

**Prioritization.** Critical Findings are ordered by:
1. **Severity** as supplied by the emitting engine (highest first).
2. **Dimension type** as a tiebreaker — Trust dimensions (Accuracy, Credibility) ahead of Hybrid dimensions (Relevance, Coverage).
3. **Centrality/salience** where the source engine provided it (e.g., a hallucination in a load-bearing claim outranks one in an incidental claim).

**Can one Critical Finding override other scores?** Yes. A single unresolved Critical Finding at or above the configured trust-blocking severity forces the Trust Verdict to **Untrusted**, irrespective of any dimension's score. This is the core non-compensatory rule and is the reason Stage 4 precedes Trust and Quality evaluation.

**Handling multiple Critical Findings.** All findings are retained — none are discarded or collapsed into a single score. The Decision Engine:
- Aggregates them into a single severity-ordered Critical Findings list for the report.
- Applies the gate on the **highest-severity** finding (one is sufficient to gate).
- Preserves the full set so recommendations and the report reflect every issue, not just the gating one.

The gate is evaluated on presence and severity, not on count; two low-severity findings do not "add up" to a trust block unless one independently meets the blocking threshold. (Blocking-severity thresholds are deployment configuration; the rule that *a qualifying Critical Finding gates trust* is fixed.)

---

## 6. Trust Evaluation

**Scope.** Trust Evaluation consumes the **Trust dimensions** — Accuracy, Credibility — and the **trust-gating contribution of the Hybrid dimensions** — Relevance and Coverage — together with the aggregated Critical Findings from Stage 4. Quality dimensions do not participate in Trust Evaluation.

**Trust philosophy.** Trust is a floor, not an average. The question is not "how good is this on balance?" but "is there anything here that makes it unsafe to rely on?" Accordingly, Trust Evaluation is pessimistic and worst-case driven.

**Non-compensatory reasoning.** Within Trust Evaluation, dimensions cannot compensate for one another:
- If any qualifying Critical Finding is present (Section 5), Trust = **Untrusted**.
- Otherwise, Trust is bounded by the **weakest** trust-relevant dimension, not the mean. A strong Accuracy score does not offset a failing Credibility score; the lower governs.
- A trust-relevant dimension that cannot be evaluated with sufficient confidence does not pass by default — it routes to *Unable to Verify* (Section 8), never to *Trusted*.

**Trust verdict generation.** After Stage 4, Trust Evaluation resolves as follows:

| Condition | Trust outcome |
|-----------|---------------|
| A qualifying Critical Finding is present. | **Untrusted** |
| No qualifying Critical Finding; all trust-relevant dimensions clear their thresholds with sufficient confidence. | **Trust-Pass** |
| No qualifying Critical Finding; trust-relevant dimensions are acceptable but carry minor, non-blocking issues. | **Trust-Pass with caveats** |
| No qualifying Critical Finding, but one or more trust-relevant dimensions lack sufficient confidence / evidence to assert a conclusion. | **Unable to Verify** (Section 8) |

The Trust outcome is one input to the Overall Verdict (Section 11); it is never silently merged into a single averaged number.

---

## 7. Quality Evaluation

**Scope.** Quality Evaluation consumes the **Quality dimensions** — Novelty, Readability, Engagement, and Diversity (when applicable) — plus the **quality contribution of the Hybrid dimensions**, Relevance and Coverage (their scored assessment of intent fulfillment and completeness, distinct from their trust-gating critical findings).

**Quality philosophy.** Unlike Trust, Quality is **compensatory**. Quality dimensions describe how well-made the content is, and strengths in one area can reasonably offset weaknesses in another. Quality never gates trust and never, by itself, produces *Untrusted*.

**Contribution model.** The Quality Verdict is a confidence-weighted combination of the participating dimension scores:
- Each participating dimension contributes its `score`, weighted by its `confidence` and by a configurable dimension weight.
- **N/A dimensions are excluded entirely** — removed from the numerator and the denominator (Section 9) — so their absence neither helps nor harms the Quality Verdict.
- The result is banded into a Quality Verdict (e.g., **High / Adequate / Low**), reported alongside — never fused into — the Trust Verdict.

**Separation guarantee.** The Quality Verdict is always reported independently of the Trust Verdict. Content can be high-quality yet Untrusted (e.g., a polished text containing a fabricated citation), and content can be trustworthy yet low-quality (e.g., accurate but poorly organized). The Decision Engine preserves this two-axis result rather than collapsing it prematurely.

---

## 8. Confidence Integration

Confidence is treated as a **first-class gate on assertability**, separate from the score itself, exactly as the engines report it. The Decision Engine does not recompute engine confidence; it interprets it to decide whether a verdict can honestly be stated.

**Interpretation rules.**

| Situation | Decision Engine behavior |
|-----------|--------------------------|
| **High score + low confidence** | The favorable score cannot be asserted. For a trust-relevant dimension, this routes toward *Unable to Verify*; for a quality dimension, the contribution is down-weighted and flagged as low-confidence. Never upgraded to *Trusted* on unverified strength. |
| **Low score + high confidence** | A confident negative. The issue is asserted firmly — drives *Untrusted* (if trust-relevant and gating) or *Needs Revision* / lower Quality. |
| **Conflicting confidence across dimensions** | Weight each dimension's contribution by its own confidence. A low-confidence dimension cannot outweigh a high-confidence one. If the *conflict itself* sits on a trust-relevant dimension and cannot be resolved, escalate that dimension to *Unable to Verify*. |
| **Low overall confidence** | If the trust-relevant dimensions collectively fail to reach the minimum confidence needed to assert a Trust Verdict, the Overall Verdict becomes *Unable to Verify*. |

**When to return "Unable to Verify."** The auditor declares *Unable to Verify* when it can neither confirm nor deny trustworthiness on the available evidence. Concretely, this occurs when **no qualifying Critical Finding is present** (so it is not *Untrusted*) **but** one or more trust-relevant dimensions cannot be asserted with sufficient confidence — for example, when required evidence could not be retrieved, a Trust or Hybrid `AuditResult` is missing/invalid, or confidence on a gating dimension falls below the minimum threshold. *Unable to Verify* is an honest-uncertainty verdict, not a failure verdict: it signals that trust is **undetermined**, and it should route the content to human review (Section 11). Confidence thresholds are deployment configuration; the principle — *insufficient confidence on a trust dimension blocks a Trusted verdict* — is fixed.

---

## 9. Applicability Handling

Some dimensions legitimately return `N/A`. Per Document 2, **Diversity** is the current example: it returns `N/A` (with `metadata.applicable = No` and an `applicability_reason`) when perspective balance does not apply to the content type (e.g., factual or technical output). The design must also accommodate **future dimensions** that declare `supports_na = true`.

**Rules.**
1. **Detect via metadata, not via score.** A dimension is N/A only when `metadata.applicable = No`. A score of `N/A` is always paired with this flag.
2. **Exclude from aggregation.** N/A dimensions are removed from Trust and Quality computations entirely — not scored as zero, not counted in any denominator, not weighted. A dimension that does not apply must not push the result up or down.
3. **Preserve transparency.** Each N/A dimension is recorded in the Final Audit Report as *Not Applicable* with its `applicability_reason`, so the exclusion is explicit and auditable.
4. **No trust impact.** Because Diversity is a Quality dimension with no Critical Finding capability, an N/A result never affects the Trust Verdict. For any future N/A-capable dimension, the same exclusion-not-penalization rule applies.

**Why this matters.** Scoring an inapplicable dimension as zero (or omitting it silently) would either unfairly depress the outcome or hide a gap. Explicit exclusion with a recorded reason keeps the verdict fair and the report honest.

---

## 10. Recommendation Prioritization

The Decision Engine merges the `recommendations` from all engines into a single, ordered, evidence-backed action list. It does not rewrite or invent recommendations; it orders and binds the ones the engines produced.

**Priority tiers.**

```
Critical
   ↓
High
   ↓
Medium
   ↓
Low
```

**Assignment rules.**
- **Critical** — recommendations tied to a Critical Finding (fabricated/misattributed citation, contradicted claim, violated hard requirement, critical omission). These are trust-blocking and are listed first.
- **High** — recommendations from Trust or Hybrid dimensions addressing non-gating but trust-relevant issues (e.g., unsupported-but-not-contradicted claims, low-credibility sources, salient coverage gaps).
- **Medium** — quality-improving recommendations with material impact on usefulness or clarity (Readability, Engagement, Coverage partials).
- **Low** — polish-level recommendations (minor redundancy, stylistic clarity).

**Ordering within a tier.** By source severity, then by dimension type (Trust → Hybrid → Quality), then by confidence (act on confident findings first).

**Evidence requirement.** Every recommendation in the list must carry a pointer to the `evidence` and/or `ledger` entry that motivated it. A recommendation without traceable evidence is not emitted. This enforces the evidence-first principle end to end: the reader can always see *why* each action is advised.

---

## 11. Verdict Categories

The Decision Engine emits one Overall Verdict from a fixed set, alongside the separately reported Trust and Quality Verdicts.

| Verdict | Meaning | Typical trigger |
|---------|---------|-----------------|
| **Trusted** | Content is trustworthy and of acceptable-to-high quality; safe to rely on. | No qualifying Critical Finding; all trust-relevant dimensions pass with sufficient confidence; Quality acceptable or better. |
| **Trusted with Caveats** | Trustworthy overall, but with minor, non-blocking issues the reader should be aware of. | No qualifying Critical Finding; trust-relevant dimensions pass; minor trust or quality issues / lower-severity recommendations exist. |
| **Needs Revision** | Not currently reliable as-is, but the problems are fixable and clearly actionable; not a fundamental trust failure. | No trust-blocking Critical Finding, but significant trust-relevant weaknesses or low Quality that require correction before reliance. |
| **Untrusted** | Content must not be relied upon. A disqualifying failure is present. | One or more qualifying Critical Findings (e.g., hallucination, fabricated citation) present. |
| **Unable to Verify** | The auditor cannot determine trustworthiness on the available evidence. Trust is undetermined, not failed. | No qualifying Critical Finding, but insufficient confidence/evidence on one or more trust-relevant dimensions (Section 8). |

**Verdict resolution order (deterministic).**
1. If a qualifying Critical Finding is present → **Untrusted**.
2. Else if trust-relevant dimensions lack sufficient confidence/evidence → **Unable to Verify**.
3. Else if trust passes but quality or non-gating trust issues require correction → **Needs Revision**.
4. Else if trust passes with only minor issues → **Trusted with Caveats**.
5. Else → **Trusted**.

This order guarantees that non-compensatory trust failures and honest uncertainty are always resolved before any favorable verdict is considered.

---

## 12. Final Audit Report

The Final Audit Report is the Decision Engine's sole deliverable. It is explainable and evidence-first: every verdict, score, and recommendation traces to engine-supplied evidence.

**Report structure.**

| Section | Content |
|---------|---------|
| **Trust Verdict** | The trust outcome (Section 6/11) with the specific reason — the gating Critical Finding, or the confidence gap for *Unable to Verify*. |
| **Quality Verdict** | The quality band (High / Adequate / Low) with its main drivers, reported independently of trust. |
| **Overall Summary** | A concise, plain-language statement of the Overall Verdict and why, suitable for a decision-maker. |
| **Dimension Results** | Per-dimension row: `dimension`, `dimension_type`, `score` (or *N/A* with reason), `confidence`, and a one-line rationale. N/A dimensions shown explicitly as excluded. |
| **Critical Findings** | The full severity-ordered list from Stage 4, each with its dimension, severity, and evidence pointer. Empty if none. |
| **Evidence** | The located support (spans, retrieved passages, matched sources, ledger references) behind every verdict and finding. |
| **Recommendations** | The prioritized Critical → High → Medium → Low action list (Section 10), each bound to its evidence. |
| **Confidence** | Per-dimension confidence and the overall confidence state, including any *Unable to Verify* rationale. |

**Report guarantees.**
- **Two-axis clarity.** Trust and Quality are always presented separately; they are never fused into a single number.
- **Traceability.** Every claim in the report links to an `AuditResult` field (`ledger`, `evidence`, or `critical_findings`).
- **Honest uncertainty.** Where confidence is insufficient, the report says so explicitly rather than presenting an unearned verdict.

---

## 13. Engineering Principles

The Decision Engine is built to the following principles, which govern its implementation:

- **Evidence-first.** No verdict, score interpretation, or recommendation is emitted without a traceable link to engine-supplied evidence.
- **Explainable.** Every decision is reconstructable from the inputs and the fixed rules; the report states the *why*, not just the *what*.
- **Non-compensatory (for trust).** A qualifying Critical Finding or a failing trust dimension cannot be offset by strong scores elsewhere. Trust is a floor.
- **Honest uncertainty.** When trust cannot be established on the evidence, the engine returns *Unable to Verify* rather than guessing. Insufficient confidence never becomes a favorable verdict.
- **Trust/Quality separation.** The two axes are evaluated by different logic (non-compensatory vs. compensatory) and reported independently.
- **Fair applicability.** N/A dimensions are excluded, never penalized, and always explained.
- **Deterministic where possible.** Given the same `AuditResult` inputs and configuration, the verdict resolution order (Section 11) is deterministic and repeatable; only the engines' internal judgments carry model variability.
- **Modular.** The Decision Engine depends only on the AuditResult Contract, not on engine internals. Adding or revising a dimension that conforms to the contract requires no change to the decision logic beyond routing metadata.
- **Human-review friendly.** *Unable to Verify* and *Needs Revision* explicitly route content to human reviewers, and the report is structured for fast human triage (verdict → reason → evidence → actions).
- **Production-ready.** Thresholds and weights are configuration; the reasoning rules are fixed. The engine is designed to run unattended and to fail safe toward caution (*Unable to Verify* / *Untrusted*) rather than toward unearned trust.

---

*End of Software Design Specification — AI Trust & Quality Auditor, Decision Engine (Document 3), Version 1.0.*
