You are classifying readability issues that a review has already found. Assign each one a category.

## Rules

1. **Classify what the issue is, not how bad it is.** Severity is assigned by a separate stage and is not your question here.
2. **Name the category in two or three words**, lowercase. Common ones: `ambiguous wording`, `undefined jargon`, `sentence complexity`, `missing transition`, `disordered structure`, `inconsistent terminology`, `unexplained reference`, `dense paragraph`, `missing overview`.
3. **The list above is not exhaustive.** If none of them fits, name the category that does. Do not force an issue into a category it does not belong in.
4. **The aspect is a hint, not the answer.** An issue raised under `clarity` may be a structure problem in truth. Classify what the issue text and quote actually describe.
5. **Do not re-litigate the issue.** It has been found. You are labelling it, not deciding whether it is real.

## Output

Return JSON only:

```json
{
  "classifications": [
    {
      "id": "iss_1",
      "category": "undefined jargon",
      "rationale": "A domain term is used before any definition is given."
    }
  ]
}
```

Return one entry per issue, using the exact `id` given. Do not add, drop, merge, or reorder issues.

## Issues

${issues}
