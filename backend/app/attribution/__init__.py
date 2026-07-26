"""Attribution substrate (AI Output Auditor, MB2).

The retrieve-then-entail engine that maps every output claim to its supporting
source location — or an explicit "Not Found." It is the single fan-in every
Layer-1 metric is derived from (Evaluation Framework §5.1; Software Architecture
D2), isolated from the legacy evaluation pipeline.
"""

from app.attribution.attribution import (
    AttributionResult,
    AttributionService,
    ClaimAttribution,
)

__all__ = ["AttributionService", "AttributionResult", "ClaimAttribution"]
