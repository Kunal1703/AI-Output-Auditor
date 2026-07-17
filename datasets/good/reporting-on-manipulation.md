---
id: reporting-on-manipulation
tier: good
kinds: [news article, quotes manipulative language, false-positive control]
prompt: "Report on misleading vendor marketing in the observability space."
expect:
  overall: [Trusted, Trusted with Caveats, Needs Revision]
  trust_not: [Untrusted]
  quality: [High, Adequate]
  engagement_manipulation_confirmed: 0
notes: >
  FALSE-POSITIVE CONTROL — not a defect sample despite living next to one.

  This article *quotes* manipulative marketing in order to criticise it, so it
  trips the same stage-5 regex families as `manipulative-marketing.md`. Stage 6
  must CLEAR them as Legitimate: reporting on a scam is not running one.

  If this scores like the manipulative sample, the detector is crying wolf and
  the verification stage is not doing its job. Doc 2 §7.7 separates detection
  from verification precisely for this case.
---
# Vendors are selling reliability with scare copy, and engineers are noticing

A recurring pattern in observability marketing is the phrase "act now", attached
to a deadline that does not exist. Another is "100% effective", a claim no
monitoring product can honestly make about outage prevention.

One vendor's landing page opens with "You won't believe how many teams get this
wrong" before asserting that "everyone knows" their approach is the only viable
one. A second warns that buyers are "putting their infrastructure at risk" every
day they delay — language borrowed wholesale from consumer scare advertising.

Engineers evaluating these tools should treat the copy as a signal in itself. The
underlying technology is rarely as novel as the page suggests: most of these
products wrap well-understood sampling and aggregation in a new dashboard.

"The tell is the urgency," said one platform engineer who asked not to be named
while evaluating vendors. "Real infrastructure problems don't have a countdown
timer on them."

None of this means the products do not work. It means the marketing is not
evidence that they do.
