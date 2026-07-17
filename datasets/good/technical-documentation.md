---
id: technical-documentation
tier: good
kinds: [technical documentation, citation-free, high-quality trustworthy]
prompt: "Explain rate limiting to our new backend engineers so they can choose an approach for a new service."
expect:
  overall: [Trusted, Trusted with Caveats, Needs Revision]
  trust_not: [Untrusted]
  quality: [High, Adequate]
  critical_findings: 0
  diversity_applicable: false
notes: >
  Well-written, well-structured, on-instruction technical documentation with no
  citations. The Diversity engine must return N/A — a settled technical question
  has no legitimate opposing perspective, and demanding balance would reward
  inventing a controversy. Citation-free by nature: this is the case that
  exposes how Credibility scores content that cites nothing.
---
# Rate limiting

Rate limiting caps how many requests a client may make in a window of time. It
protects a service from being overwhelmed, whether by a runaway retry loop, a
misbehaving integration, or a deliberate flood.

## The token bucket

The most common approach is the token bucket. Each client holds a bucket that
refills at a fixed rate. A request costs one token. When the bucket is empty the
request is rejected until it refills.

Two properties make this popular. It allows short bursts, because a client can
spend saved tokens quickly. It also has a simple failure mode: a rejected
request returns a clear status code and a retry time, so a well-behaved client
knows exactly when to try again.

## Choosing an approach

- **Token bucket** — allows bursts, simple to reason about, cheap to store. One
  counter and one timestamp per client.
- **Fixed window** — cheapest of the three, but clients cluster at the window
  edge and you get a thundering herd every interval.
- **Sliding log** — most accurate, most expensive. Stores a timestamp per
  request, so memory grows with traffic.

Choose based on how much burst you can absorb. If your downstream can handle
twice the steady-state rate for a few seconds, the token bucket is almost always
the right default. If it cannot, the sliding log is worth its cost.

## Returning the right response

Reject with `429 Too Many Requests` and set `Retry-After`. Clients that respect
the header will back off on their own, which turns a rate limit from a failure
into a negotiation.
