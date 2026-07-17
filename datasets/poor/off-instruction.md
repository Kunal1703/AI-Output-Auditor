---
id: off-instruction
tier: poor
kinds: [low-quality, ignored hard requirement, scope drift]
prompt: "Explain rate limiting in under 60 words. Do not discuss databases."
expect:
  overall: [Needs Revision, Untrusted]
  critical_findings_min: 1
  finding_dimension: Relevance
notes: >
  PLANTED DEFECT — off-instruction / ignored hard requirement (Doc 4 §11).

  Two hard requirements are violated and both are machine-checkable:
  the 60-word cap (this runs ~200) and the explicit "do not discuss databases"
  exclusion (it discusses them at length).

  This is the case where Relevance's DETERMINISTIC stage 7 must override the
  LLM judge — a word count is a fact, not an impression. Expected: a
  "Violated hard requirement" critical finding, and scope drift on the database
  paragraphs, which are off-topic against the prompt.
---
Rate limiting caps how many requests a client may make in a window of time, and
it is worth understanding in depth before you choose an approach for a new
service.

Now, let's talk about databases, because the storage layer is where rate
limiting actually gets interesting. Postgres has a connection limit governed by
`max_connections`, and once you exhaust it, new connections are refused
outright. This is itself a form of rate limiting, though a crude one.

PgBouncer sits in front of Postgres and pools connections, which changes the
failure mode entirely. In transaction pooling mode it multiplexes many client
connections onto a few server connections. You lose session-level features —
prepared statements, advisory locks, `SET` state — but you gain the ability to
absorb a connection spike.

MySQL handles this differently. Its thread pool plugin queues rather than
refuses, which trades latency for availability. Whether that is the right trade
depends entirely on whether your callers have timeouts.

Redis is often used as the counter store for a token bucket, since `INCR` with
`EXPIRE` is atomic and cheap. The tradeoff is that Redis becomes a hard
dependency of your ingress path, and its failure mode is now your failure mode.

Anyway, the token bucket refills at a fixed rate and each request costs one
token.
