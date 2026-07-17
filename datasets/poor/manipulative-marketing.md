---
id: manipulative-marketing
tier: poor
kinds: [low-quality, manipulative phrasing, citation-free]
prompt: "Explain rate limiting to our new backend engineers so they can choose an approach."
expect:
  overall: [Needs Revision, Untrusted, Trusted with Caveats]
  quality: [Low, Adequate]
  engagement_manipulation_min: 3
notes: >
  PLANTED DEFECT — manipulative / clickbait phrasing (Doc 4 §11).

  Hits several detector families at once: clickbait, false urgency,
  overclaiming, manufactured consensus, fear appeal, emphasis inflation. Stage 5
  matches them; stage 6 must CONFIRM them, because unlike
  `reporting-on-manipulation` these are used sincerely to work on the reader.

  Expected: Engagement surfaces confirmed manipulation and its score drops.
  Trust is NOT gated — manipulation is a communication failure, not a trust
  gate; Engagement has capability No and no path to the Trust Verdict.
---
# You won't believe how many teams get rate limiting wrong

Everyone knows that the token bucket is the only way to protect a service, and
it is 100% effective at stopping overload. This one trick will fix your
reliability problems permanently.

Act now: teams that delay are putting their infrastructure at risk. Every day
without rate limiting is a day you are one traffic spike away from a DISASTER
that could cost you everything.

Nobody seriously disputes that fixed windows are garbage. Any reasonable person
would pick the token bucket immediately.

The token bucket refills at a fixed rate and a request costs one token. When the
bucket is empty the request is rejected.

Don't miss out — the teams that move first are the ones still standing.
