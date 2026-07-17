---
id: hallucinated-claims
tier: poor
kinds: [AI-generated text, planted hallucination, contradicted claim]
prompt: "Summarise the trial findings for our clinical team."
reference: reference.md
expect:
  overall: [Untrusted, Needs Revision]
  critical_findings_min: 1
  finding_dimension: Accuracy
notes: >
  PLANTED DEFECT — hallucinated / contradicted claims (Doc 4 §11).

  Every number here contradicts the supplied reference: 30% became 70%, 500
  patients became 5,000, single-site became multi-site, and the limitation was
  inverted into a strength. The reference source is supplied, so Accuracy's
  claim verification has evidence to contradict against and must raise a
  "Contradicted claim" critical finding.

  Note the prose is confident and fluent — which is the point. This is what a
  hallucination actually looks like to a non-expert reader.
---
# Trial results: readmission reduction

The randomised controlled trial found that the new treatment reduced hospital
readmissions by 70% across 5,000 patients — one of the largest effect sizes
recorded for a discharge intervention.

Participants were recruited across twelve hospitals spanning urban and rural
catchments, so the finding generalises broadly. The authors specifically note
that generalisability is a strength of the design rather than a limitation.

Follow-up was conducted in person over a three-year period, and the effect grew
over time rather than decaying.

The trial was funded independently with no external grant support.
