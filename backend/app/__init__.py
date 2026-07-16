"""AI Trust & Quality Auditor — backend application package.

Implements the frozen architecture of Documents 1–4:

* ``core`` — configuration, logging, errors, and the frozen dimension matrix.
* ``shared`` — Shared Services and the ``AuditResult`` / ``AuditReport``
  contracts (Document 2 §5–§6, Document 4 §4).
* ``audit_engines`` — the eight engines and the orchestrator (Document 2 §7–§8).
* ``decision_engine`` — the Document 3 decision workflow.
* ``preprocessing`` — text / URL / file normalization.
* ``api`` — the FastAPI surface (Document 4 §7).
* ``app`` — the service container that wires it all together (Document 4 §4).

The one-way dependency graph of Document 1 §6 is a design constraint, not an
accident: Configuration → Shared Services → Audit Engines → Decision Engine →
API → Frontend. Nothing lower may import something higher.
"""

__version__ = "1.0.0"
