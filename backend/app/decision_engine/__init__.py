"""Decision Engine — the reasoning layer (Document 3).

Consumes the eight ``AuditResult`` objects and produces one explainable,
evidence-backed decision. One module per stage of the Document 3 §4 workflow, in
execution order:

* ``workflow`` — the ordered pipeline and the deterministic verdict resolution.
* ``applicability`` — Stage 3, N/A exclusion (§9).
* ``critical_findings`` — Stage 4, non-compensatory gating (§5).
* ``trust_eval`` — Stage 5, worst-case trust reasoning (§6).
* ``quality_eval`` — Stage 6, compensatory quality reasoning (§7).
* ``confidence_integration`` — Stage 7, assertability (§8).
* ``recommendations`` — Stage 8, prioritization (§10).
* ``report_builder`` — Stage 10, the Final Audit Report (§12).

The boundary that keeps this layer honest: **engines measure, this decides**. It
never re-measures a dimension, overrides a score, or generates evidence — it
interprets what the engines produced, and depends only on the ``AuditResult``
contract (Document 3, §1 and §13).
"""

from app.decision_engine.report_builder import build_placeholder_report, build_report
from app.decision_engine.workflow import DecisionEngine, validate_results

__all__ = [
    "DecisionEngine",
    "build_placeholder_report",
    "build_report",
    "validate_results",
]
