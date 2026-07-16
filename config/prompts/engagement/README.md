# Engagement prompts (`ENG-ENGAGEMENT`)

Prompt templates for the Engagement Audit Engine's LLM-backed stages
(Document 2, §7.7).

| Template | Frozen pipeline stage | Status |
|---|---|---|
| `task_fitness.v1.md` | Stage 4 — LLM-based Task Fitness Evaluation | Milestone 3 |
| `manipulation_verification.v1.md` | Stage 6 — LLM Manipulation Verification | Milestone 3 |

## Conventions

- **Filename:** `<stage>.<version>.md`. The version is pinned at the call site,
  so revising a prompt means adding `.v2.md` and changing one line — never
  editing `.v1.md` in place. An engine's verdicts change when its prompt
  changes, and that must not happen silently (Document 4, §11).
- **Variables:** `${name}` placeholders, rendered by the Prompt Manager. Under
  strict rendering a placeholder with no supplied value raises *before* the
  model is called.
- **Literal `$`:** escape as `$$`.
- **Output:** every template asks for JSON only. Engine stages parse structured
  results, not prose.

## Rule

Prompts are configuration, not code (Document 4, §15). No engine may inline
prompt text; it asks the Prompt Manager for a template by name and version.
