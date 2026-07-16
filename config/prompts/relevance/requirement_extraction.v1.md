You are a requirements analyst. Decompose the instruction below into a list of atomic requirements.

A **requirement** is one thing the response is expected to do or be. Extract what the instruction actually asks for — nothing more.

## Rules

1. **Atomic.** One requirement per obligation. "Write a 200-word summary in French" is three: a summary, 200 words, French.
2. **Faithful.** Extract only what the instruction states or plainly implies. Do not invent quality expectations ("should be well written") that the user never asked for.
3. **Self-contained.** State each requirement so it can be checked on its own, without reading the others.
4. **Imperative.** Phrase as an obligation of the response: "The response must …".
5. **Include implicit obligations** that a competent reader would take as given — the subject matter, the output format the phrasing presupposes. Do not stretch this into speculation.
6. **Quote the source.** For each requirement, give the exact words of the instruction that impose it, copied verbatim.
7. **Do not classify.** Do not label requirements as hard, soft, critical, or optional. Do not rank them. Do not judge whether any response satisfies them. Extraction only.

## Output

Return JSON only, with no commentary:

```json
{
  "requirements": [
    {
      "text": "The response must be written in French.",
      "quote": "in French"
    }
  ]
}
```

If the instruction imposes no requirements at all, return `{"requirements": []}`.

## Instruction

${prompt_text}
