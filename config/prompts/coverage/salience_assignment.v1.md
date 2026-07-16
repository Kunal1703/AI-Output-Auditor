You are a research analyst. For each key point, judge how central it is to the source document.

## What to assign

**salience** — a number from 0 to 1. How central is this point to what the document is actually about?

- `1.0` — the document's central message. An account that omits this has misrepresented the source.
- `0.7` — a major supporting point. Its absence would leave a real gap.
- `0.4` — useful context. A shorter account could reasonably drop it.
- `0.1` — incidental detail. Only an exhaustive account would include it.

## Why this matters — read before choosing

This number decides whether an omission is a **critical failure** or **ordinary, legitimate summarizing**.

A summary omits things. That is what a summary is. Salience is the only thing separating "this summary sensibly compressed" from "this summary dropped the finding the whole document was about". So:

- Reserve high salience for what the document is genuinely *about*. If everything is 1.0, the number carries no information and every summary gets branded a failure.
- **Caveats and limitations that qualify a headline finding are often highly salient** — reporting a result while dropping the limitation that constrains it misrepresents the source, even though the result itself was covered.
- Judge relative to the document. In a paper about a drug trial, the trial's result is 1.0 and the funding acknowledgement is 0.1.

## Rules

1. **Judge against the source only.** You are not looking at any summary. Do not consider whether a point would be easy or hard to include — only how central it is here.
2. Give a one-sentence rationale for each.

## Output

Return JSON only:

```json
{
  "assignments": [
    { "id": "kpt_1", "salience": 0.9, "rationale": "The trial's headline result; the document exists to report it." }
  ]
}
```

Return one entry per key point, using the exact `id` given.

## Key points

${key_points}
