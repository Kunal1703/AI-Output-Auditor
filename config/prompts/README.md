# Prompt Templates

Versioned prompt templates loaded and rendered by the **Prompt Manager**
(`backend/app/shared/prompt_manager.py`, Document 4 §4).

Engines never inline prompt text. They ask the Prompt Manager for a template by
name and version, and the Prompt Manager renders it with the supplied
variables. This keeps prompts configuration rather than code (Document 1 §11,
Document 4 §15).

## Layout

```
config/prompts/
  <engine>/
    <stage>.<version>.md
```

For example, the Accuracy engine's claim-extraction stage (Document 2 §7.2,
pipeline stage 2) would live at:

```
config/prompts/accuracy/claim_extraction.v1.md
```

## Template format

A template is a Markdown file. Variables use `${name}` placeholders, rendered
via `string.Template`. Metadata is carried by the filename
(`<stage>.<version>.md`) rather than by frontmatter.

## Status

No templates ship in Milestone 1 — the engine pipelines that consume them are
not yet implemented. The Prompt Manager interface, discovery, and rendering
contract are in place so that Milestone 2 only adds files to this directory.
