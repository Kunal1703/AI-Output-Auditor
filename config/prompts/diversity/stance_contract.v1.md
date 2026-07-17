You are detecting what the content below **promises its reader** about its own stance.

## Stances

- **Neutral** — the content presents itself as an objective survey, explanation, or overview. It does not announce a position it is arguing for.
- **Declared Advocacy** — the content openly argues a position. It tells the reader, or makes unmistakably plain, that it is making a case rather than surveying one.

## The distinction that matters

**"Declared" means declared.** Advocacy counts as declared only if the content *tells the reader* it is making a case — in its framing, its thesis, its first person, or a statement of position. A reader must be able to know what they are holding without having to infer it.

- An essay that opens "I want to argue that remote work has been oversold" is **Declared Advocacy**. It is honest, and the next auditor will judge it gently for not giving the other side equal room — that is what an argument is.
- A piece titled "The truth about remote work" that reads as a one-sided case while never admitting it is arguing is **Neutral**. That is what it presents itself as, and it will be held to the standard it implied. If it turns out to be one-sided, the next auditor will find that — and the gap between the pose and the substance is exactly what makes it a failure rather than an argument.

So: judge what the content **presents itself as**, not what it turns out to be. Undeclared advocacy is `Neutral`.

## Rules

1. **Do not judge whether the content is balanced.** That is the next stage's question. You are establishing the standard it will be judged against, and a one-sided piece that poses as neutral must be answered `Neutral` here so that the standard bites.
2. **Look for the signals a reader would use**: first-person argument, a thesis stated up front, "should" and "must" framing, a framing section that names the position, a conclusion that urges. Compare against the signals of a survey: attribution to multiple parties, hedged summary, "some argue / others hold".
3. **A neutral survey does not have to announce its neutrality.** Almost none do. The absence of "this is an objective account" is not a mark against anything — the default reading of unannounced content is Neutral.
4. **Do not treat confidence as advocacy.** An explanation can be firm about a settled matter and still be a neutral explanation.
5. **When it is genuinely ambiguous, answer Neutral.** That is the stricter standard. Content that wanted the latitude of an argument should have said so, and this is the answer that declines to grant it for free.
6. Give a reason, quoting what establishes the stance.

## Output

Return JSON only:

```json
{
  "stance": "Declared Advocacy",
  "reason": "The second paragraph states 'this article argues that the trade-off is not worth it', so the reader is told plainly that a case is being made."
}
```

## The user's prompt

${prompt}

## Output under audit

${ai_output}
