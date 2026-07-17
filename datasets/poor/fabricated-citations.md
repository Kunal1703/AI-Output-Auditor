---
id: fabricated-citations
tier: poor
kinds: [citation-heavy, planted fabricated citation, AI-generated text]
prompt: "Summarise the evidence on structured discharge protocols, with sources."
expect:
  overall: [Untrusted]
  trust: [Untrusted]
  critical_findings_min: 1
  finding_dimension: Credibility
notes: >
  PLANTED DEFECT — fabricated citations (Doc 4 §11).

  The URLs and DOIs here point at hosts and identifiers that cannot resolve
  (.invalid is reserved by RFC 2606 and can never exist). Credibility's stage-4
  URL/DOI verification is deterministic, so this must produce a "Fabricated
  citation" critical finding and gate the verdict to Untrusted.

  The prose is deliberately competent: this is the polished-but-untrustworthy
  case. Quality should stay respectable while Trust fails, demonstrating the
  two-axis separation on real content.
---
# Evidence on structured discharge protocols

Structured discharge protocols have been studied extensively over the past
decade, and the evidence base is now reasonably mature.

A large multi-centre trial found a 30% reduction in readmissions across 500
patients (Halvorsen et al., 2021, https://journal-of-care-science.invalid/halvorsen-2021).
The effect was consistent across age groups and persisted at eighteen months.

A subsequent meta-analysis pooled fourteen trials and reported a comparable
effect size (Okonjo & Bertram, 2022, doi:10.9999/jcs.2022.44817), concluding
that the mechanism is robust across health systems.

The Nordic Registry Study confirmed the finding at population scale, tracking
outcomes across 40,000 discharges (see https://nordic-health-registry.invalid/2023-report).

Taken together, the literature supports structured discharge as a cost-effective
intervention with a consistent effect on early readmission.
