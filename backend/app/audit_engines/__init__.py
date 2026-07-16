"""Audit Engine Framework — the eight engines and their orchestration.

Document 2 §7 and Document 4 §3. Each engine measures exactly one dimension and
returns an ``AuditResult``; the orchestrator runs them in the frozen order
(Document 2, §8).

Importing this package registers all eight engines. That is the point: the
registry is populated as a side effect of import, so the service container can
call ``validate_registry()`` at startup and fail the boot if a dimension is
missing, rather than discovering it mid-audit.

The division of labor to keep in mind: **engines measure; the Decision Engine
decides; the frontend presents** (Document 1, §3). An engine never renders a
verdict, and never reads another engine's results except through the two frozen
cross-engine inputs the orchestrator passes in.
"""

from app.audit_engines.base import AuditEngine, EngineServices
from app.audit_engines.orchestrator import EngineOrchestrator, ProgressCallback
from app.audit_engines.registry import (
    build_engines,
    get_engine_class,
    register_engine,
    registered_dimensions,
    validate_registry,
)

# Imported for their registration side effect. The registry is keyed by
# dimension, so import order does not matter and a duplicate claim raises.
from app.audit_engines import (  # noqa: F401  (registration side effects)
    accuracy,
    coverage,
    credibility,
    diversity,
    engagement,
    novelty,
    readability,
    relevance,
)

__all__ = [
    "AuditEngine",
    "EngineServices",
    "EngineOrchestrator",
    "ProgressCallback",
    "build_engines",
    "get_engine_class",
    "register_engine",
    "registered_dimensions",
    "validate_registry",
]
