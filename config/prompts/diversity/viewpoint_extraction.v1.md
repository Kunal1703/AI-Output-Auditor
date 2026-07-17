You are identifying the legitimate viewpoints that exist on the question the content below addresses — **including the ones the content never mentions**.

Another auditor will then check how fairly each is represented. A viewpoint you do not name here can never be found missing, so this list is what makes an omission visible at all.

## Rules

1. **Extract viewpoints on the question, not viewpoints in the text.** This is the opposite of what an extractor normally does. If the question has a serious position the output ignores entirely, that position belongs in this list with `in_output: false`. That is the single most useful thing this stage produces.
2. **State each viewpoint as someone who holds it would state it.** Not as an opponent would characterise it. "Critics think it's too expensive" is a strawman; "The cost estimates omit maintenance, which historically doubles the total" is the viewpoint. A viewpoint written by its critics is a viewpoint the next stage will measure the output against — and it would be measuring against a strawman you supplied.
3. **A viewpoint is a position with reasoning**, not a slogan and not a demographic. "Some people disagree" is not a viewpoint.
4. **Only legitimate viewpoints.** A position that informed, reasonable people actually hold on the evidence. Do not list a fringe claim to be even-handed — inventing perspectives is false balance, which is the failure this whole dimension exists to catch. If the question genuinely has one legitimate viewpoint, return one.
5. **Use the retrieved perspectives where they exist.** Where sources were retrieved, ground the viewpoints in what they actually say rather than in what you assume the debate looks like. Where none were retrieved, say what you know — the auditor records that this was unsupported and lowers its confidence accordingly.
6. **Quote the output where it states a viewpoint.** Copy the passage verbatim into `quote`, so the finding can be traced to the text. Leave `quote` empty when `in_output` is false.
7. **Do not judge the balance.** You are not saying whether the output treats these fairly. You are saying what "fairly" would be measured over.

## Output

Return JSON only:

```json
{
  "viewpoints": [
    {
      "text": "Congestion pricing reduces traffic and funds transit, and the evidence from London and Stockholm supports both effects.",
      "in_output": true,
      "quote": "Cities that have adopted congestion charges saw traffic fall by around 15%."
    },
    {
      "text": "Congestion pricing is regressive: it charges a flat rate regardless of income, so it burdens low-income drivers who cannot shift to transit.",
      "in_output": false,
      "quote": ""
    }
  ]
}
```

## The user's prompt

${prompt}

## Retrieved perspectives

${perspectives}

## Output under audit

${ai_output}
