"""API layer — the HTTP surface.

Exposes ``POST /audit/outputs`` (source + outputs → ``ComparativeReport``) and
``GET /health``.

Deliberately thin: it accepts requests and returns the report, delegating all
audit and decision logic to Preprocessing, the Audit Orchestrator, and the
Decision Engine.
"""
