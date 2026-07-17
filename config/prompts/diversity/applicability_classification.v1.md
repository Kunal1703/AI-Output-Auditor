You are deciding whether "perspective balance" is a meaningful thing to ask of the content below.

This is a gate, not a score. If the answer is no, the auditor stops and reports that this dimension does not apply — the content is neither rewarded nor penalised for it.

## Answer **Not applicable** when

- The content addresses a **settled factual or technical question**. How TCP works, what a token bucket is, what the boiling point of water is. There are no "sides" here, and there is nothing to balance.
- The content is a **summary, a translation, or a transformation** of a source. Its job is to reflect the source, not to survey opinion.
- The content is **procedural or instructional** — how to configure a service, how to file a form.
- The content is **creative writing**, or a personal account that makes no claim to survey a debate.
- The content addresses a question where **the evidence is one-sided** even though people disagree loudly. That vaccines do not cause autism is not a question with two legitimate perspectives; it is a settled question with a persistent false claim attached.

## Answer **Applicable** when

- The content addresses a question on which **informed, reasonable, well-intentioned people genuinely differ**: policy trade-offs, contested interpretations, ethical questions, matters of ongoing scientific dispute, editorial judgments about value.
- The content **surveys, compares, or adjudicates** competing positions.
- The content makes **recommendations that reasonable people would contest**.

## The error to avoid

Answering *Applicable* on settled content is worse than the alternative. It demands the output manufacture a controversy that does not exist, and then marks it down for refusing. That is **false balance**, and avoiding it is the entire reason this gate exists.

An explanation of rate limiting that does not present "the opposing view on rate limiting" is not unbalanced. There is no opposing view. It is Not applicable.

When you are genuinely torn, ask: *would a knowledgeable reader be misled by this content presenting only one perspective?* If they would not — because there is only one — answer Not applicable.

## Rules

1. **Judge the question, not the treatment.** A one-sided article about a genuinely contested question is Applicable *and* will be marked down by the next stage. Do not answer Not applicable because the output happens to be one-sided; that is the finding, not the gate.
2. **A reason is required either way.** It is shown verbatim in the audit report, so a reader can see exactly why the dimension was or was not assessed. "N/A" with no reason is indistinguishable from an auditor who gave up.
3. **Name the question** the content addresses, in `topic`. Later stages need it.

## Output

Return JSON only:

```json
{
  "applicable": false,
  "reason": "The content explains how rate limiting algorithms work. This is a settled technical question with no legitimate opposing perspectives; requiring balance would mean inventing a controversy that does not exist.",
  "topic": "How rate limiting works and which algorithm to choose"
}
```

## The user's prompt

${prompt}

## Output under audit

${ai_output}
