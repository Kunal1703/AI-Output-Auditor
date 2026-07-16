# Validation Corpus

Labeled samples proving the auditor's central claim: **it reliably distinguishes
good AI-generated content from bad** (Document 4, §11).

## Layout

| Folder | Contents |
|---|---|
| `good/` | Accurate, well-sourced, on-instruction, complete, clear. |
| `medium/` | Acceptable but with noticeable issues — minor omissions, some redundancy, uneven clarity. |
| `poor/` | Planted defects: hallucinations, fabricated citations, off-instruction content, critical omissions, heavy redundancy, poor readability, manipulative phrasing. |

Cover both input types: raw text via `/audit/text` and real URLs via `/audit/url`.

## Expected behavior per planted defect

| Planted defect | Expected auditor behavior |
|---|---|
| Hallucinated / contradicted claim | Accuracy critical finding → **Untrusted** |
| Fabricated / misattributed citation | Credibility critical finding → **Untrusted** |
| Off-instruction / ignored hard requirement | Relevance critical finding → at least **Needs Revision** |
| Material omission | Coverage critical omission → at least **Needs Revision** |
| Heavy redundancy / low density | Novelty lowers Quality band; **trust unaffected** |
| Poor structure / clarity | Readability lowers Quality band; **trust unaffected** |
| Manipulative / clickbait phrasing | Engagement manipulation flag surfaced |
| Unverifiable content, no retrievable evidence | Trust dimensions low-confidence → **Unable to Verify** |

## Success criteria

- Good samples trend to **Trusted** / **Trusted with Caveats**; poor samples to
  **Needs Revision** / **Untrusted**; genuinely unverifiable samples land on
  **Unable to Verify** rather than a false pass or a false fail.
- Every detected defect traces to the correct dimension and to concrete evidence.
- Results are stable across re-runs, allowing for bounded model variability —
  the Decision Engine's rules are deterministic given fixed engine outputs.

Record outcomes as *sample → expected class → observed verdict → pass/fail*.

## Status

Empty in Milestone 1 — there are no engines to validate yet. The corpus is
assembled in Milestone 2 once the system runs end to end.
