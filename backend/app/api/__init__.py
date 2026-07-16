"""API layer — the HTTP surface (Document 4, §7).

Accepts requests, creates and tracks async audit jobs, returns the report, and
exposes ``/health``.

Deliberately thin. Document 4 §5: the API layer "must NOT contain audit or
decision logic" — it delegates to Preprocessing, the orchestrator, and the
Decision Engine, and depends only on the ``AuditReport`` contract.
"""
