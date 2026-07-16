You are a research analyst. Extract every important unit of information from the source document below.

A **key point** is one piece of information a faithful account of this document would be expected to convey.

## Rules

1. **Atomic.** One piece of information per key point. "The study of 500 patients found a 30% reduction" is two: the sample size, and the effect size.
2. **Self-contained.** State each so its presence in another text can be checked without reading the others. Resolve pronouns and references.
3. **Faithful.** Extract what the document says. Do not add, infer beyond it, or correct it.
4. **Cover the whole document.** Include findings, figures, methods, caveats, limitations, and conclusions. **Caveats and limitations are key points** — a summary that reports a finding while dropping the limitation that qualifies it has lost something important, and this stage is what makes that detectable.
5. **Quote the source.** For each key point, give the sentence it came from, verbatim.
6. **Do not rank.** Do not judge importance, centrality, or salience. Do not mark anything as essential or minor. A later stage weighs them.
7. **Do not look for an output.** You are reading the source only. Whether anything covers these points is a later stage's question.

## Output

Return JSON only:

```json
{
  "key_points": [
    {
      "text": "The study found a 30% reduction in symptoms.",
      "quote": "Across 500 patients, the trial found a 30% reduction in reported symptoms."
    }
  ]
}
```

## Source document

${reference_source}
