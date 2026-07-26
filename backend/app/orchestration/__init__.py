"""Audit orchestration (AI Output Auditor, MB4).

Assembles the completed MB2/MB3 evaluators into the finalized ``OutputAudit`` and
``ComparativeReport``. The :class:`~app.orchestration.audit_orchestrator.AuditOrchestrator`
is the **only** component responsible for execution order; the evaluators remain
pure computation units. Isolated from the legacy ``audit_engines`` /
``decision_engine`` pipeline.
"""

from app.orchestration.audit_orchestrator import AuditOrchestrator
from app.orchestration.decision import DecisionOutcome, GroundingDecisionEngine

__all__ = ["AuditOrchestrator", "GroundingDecisionEngine", "DecisionOutcome"]
