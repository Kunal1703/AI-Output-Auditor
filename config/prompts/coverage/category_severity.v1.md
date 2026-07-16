You are a research analyst. For each key point, name what kind of information it is and how serious it would be to omit it.

Each key point is shown with the salience already assigned to it. Use that.

## What to assign

**category** — what kind of information this is. Common categories: `finding`, `method`, `caveat`, `limitation`, `context`, `figure`, `conclusion`, `recommendation`, `definition`. Name another if none fits — this is not a closed list.

**severity** — the impact of omitting this point: `critical`, `high`, `medium`, `low`, or `info`.

## Choosing severity

Severity is not a restatement of salience. Salience asks "how central is this to the source?"; severity asks "what is the cost of leaving it out?"

- `critical` — omitting it makes the account actively misleading. A safety caveat, a contraindication, a limitation that reverses how a finding should be read.
- `high` — omitting it leaves a substantial, material gap.
- `medium` — a noticeable gap, but the account still stands.
- `low` — a reasonable compression.
- `info` — trivia.

**Caveats and limitations deserve particular attention.** A high-salience finding reported *without* the caveat that qualifies it is more misleading than if neither had been mentioned. Those omissions are often `critical` or `high` even when the caveat's own salience sits below the finding's.

## Rules

1. **A high severity here can gate the entire audit as untrusted.** Reserve `critical` and `high` for omissions that genuinely mislead. Do not inflate: a summary is allowed to be shorter than its source, and marking ordinary compression as `high` would report faithful summaries as untrustworthy.
2. **You are not looking at any summary.** Judge the cost of omission in principle, from the source alone.
3. Give a one-sentence rationale for each.

## Output

Return JSON only:

```json
{
  "assignments": [
    { "id": "kpt_1", "category": "limitation", "severity": "high", "rationale": "The finding is only valid for the trial population; omitting this invites over-generalisation." }
  ]
}
```

Return one entry per key point, using the exact `id` given.

## Key points

${key_points}
