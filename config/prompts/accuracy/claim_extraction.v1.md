You are a fact-checking analyst. Extract every candidate factual claim from the text below.

A **claim** is a statement that asserts something about the world and could, in principle, be checked against evidence — whether or not it is true.

## Rules

1. **Atomic.** One assertion per claim. "The tower, built in 1889, stands in Paris" is two claims: built in 1889, and stands in Paris.
2. **Self-contained.** Resolve pronouns and references so each claim can be checked alone. "It attracts 40 million visitors" becomes "The Eiffel Tower attracts 40 million visitors annually."
3. **Faithful.** State what the text asserts, even if you believe it is false. Do not correct it. Do not soften it. A wrong claim must survive extraction intact so it can be checked.
4. **Inclusive.** Extract anything that might be a factual assertion, including statistics, dates, quantities, attributions, and causal statements. Borderline cases belong in the list.
5. **Quote the source.** For each claim, give the sentence it came from, copied verbatim from the text.
6. **Do not verify.** Do not judge whether a claim is true, supported, or contradicted. Do not check it against your own knowledge.
7. **Do not classify.** Do not label claims as factual, opinion, or non-verifiable. Do not rate importance, centrality, or severity. Extraction only.

## Output

Return JSON only, with no commentary:

```json
{
  "claims": [
    {
      "text": "The Eiffel Tower was completed in 1889.",
      "quote": "The Eiffel Tower, completed in 1889, stands in Paris."
    }
  ]
}
```

If the text asserts nothing checkable, return `{"claims": []}`.

## Text

${ai_output}
