"""Frozen system constants for the AI Trust & Quality Auditor.

This module is the single in-code transcription of the classification data that
Documents 2 and 3 declare frozen:

* the eight dimensions and their engine ids (Document 2, §1 and §7);
* the Dimension Classification & Capability Matrix (Document 2, §4.1);
* the ledger name each engine populates (Document 2, §6.3);
* the cross-engine execution ordering (Document 2, §8; Document 4, §6).

Nothing here is a tunable. Thresholds and weights are configuration and live in
``config/settings.yaml``; this module holds only the facts the specification
freezes. The Decision Engine consumes ``dimension_type`` as fixed input rather
than computing it (Document 3, §3), so this table is the authority for routing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from app.shared.schemas import CriticalFindingCapability, DimensionType

__all__ = [
    "DimensionSpec",
    "DIMENSION_SPECS",
    "ALL_DIMENSIONS",
    "TRUST_RELEVANT_DIMENSIONS",
    "QUALITY_CONTRIBUTING_DIMENSIONS",
    "CRITICAL_FINDING_CAPABLE_DIMENSIONS",
    "EXECUTION_WAVES",
    "CROSS_ENGINE_INPUTS",
    "spec_for",
]


@dataclass(frozen=True)
class DimensionSpec:
    """The frozen descriptor for one audit dimension.

    Attributes:
        dimension: Human-readable dimension name, e.g. ``"Accuracy"``.
        engine_id: Stable engine identifier from Document 2 §7, e.g.
            ``"ENG-ACCURACY"``.
        dimension_type: Trust / Quality / Hybrid routing class consumed by the
            Decision Engine (Document 3, §3).
        critical_finding_capability: Whether the engine may emit Critical
            Findings. Engines with ``NO`` always return an empty
            ``critical_findings`` array, and an empty array is therefore
            expected rather than anomalous (Document 3, §3).
        supports_na: Whether the engine may legitimately return ``"N/A"``
            instead of a score. Only Diversity does today (Document 2, §7.8).
        ledger_name: The engine's named ledger (Document 2, §6.3).
        governing_question: The question the engine answers (Document 2, §1).
    """

    dimension: str
    engine_id: str
    dimension_type: DimensionType
    critical_finding_capability: CriticalFindingCapability
    supports_na: bool
    ledger_name: str
    governing_question: str


#: The frozen Dimension Classification & Capability Matrix (Document 2, §4.1),
#: enriched with ledger names (§6.3) and governing questions (§1).
DIMENSION_SPECS: Mapping[str, DimensionSpec] = {
    spec.dimension: spec
    for spec in (
        DimensionSpec(
            dimension="Relevance",
            engine_id="ENG-RELEVANCE",
            dimension_type=DimensionType.HYBRID,
            critical_finding_capability=CriticalFindingCapability.YES,
            supports_na=False,
            ledger_name="Requirement Checklist",
            governing_question=(
                "Does the output satisfy the user's instruction and intent "
                "without off-topic content?"
            ),
        ),
        DimensionSpec(
            dimension="Accuracy",
            engine_id="ENG-ACCURACY",
            dimension_type=DimensionType.TRUST,
            critical_finding_capability=CriticalFindingCapability.YES,
            supports_na=False,
            ledger_name="Claim Verification Ledger",
            governing_question=(
                "Is every factual claim supported, contradicted, or "
                "unverifiable against available evidence?"
            ),
        ),
        DimensionSpec(
            dimension="Coverage",
            engine_id="ENG-COVERAGE",
            dimension_type=DimensionType.HYBRID,
            critical_finding_capability=CriticalFindingCapability.YES,
            supports_na=False,
            ledger_name="Coverage Ledger",
            governing_question=(
                "Does the output include all important information from the "
                "reference source without over-penalizing summarization?"
            ),
        ),
        DimensionSpec(
            dimension="Credibility",
            engine_id="ENG-CREDIBILITY",
            dimension_type=DimensionType.TRUST,
            critical_finding_capability=CriticalFindingCapability.YES,
            supports_na=False,
            ledger_name="Citation Ledger",
            governing_question=(
                "Are factual claims supported by trustworthy, correctly cited, "
                "verifiable sources?"
            ),
        ),
        DimensionSpec(
            dimension="Novelty",
            engine_id="ENG-NOVELTY",
            dimension_type=DimensionType.QUALITY,
            critical_finding_capability=CriticalFindingCapability.NO,
            supports_na=False,
            ledger_name="Redundancy Ledger",
            governing_question=(
                "Does the output communicate efficiently, minimizing "
                "unnecessary repetition while preserving important content?"
            ),
        ),
        DimensionSpec(
            dimension="Readability",
            engine_id="ENG-READABILITY",
            dimension_type=DimensionType.QUALITY,
            critical_finding_capability=CriticalFindingCapability.NO,
            supports_na=False,
            ledger_name="Readability Ledger",
            governing_question=(
                "Is the content easy for its intended audience to understand "
                "(clarity, coherence, structure)?"
            ),
        ),
        DimensionSpec(
            dimension="Engagement",
            engine_id="ENG-ENGAGEMENT",
            dimension_type=DimensionType.QUALITY,
            critical_finding_capability=CriticalFindingCapability.NO,
            supports_na=False,
            ledger_name="Engagement Ledger",
            governing_question=(
                "Does the content help the user achieve their goal without "
                "manipulative or misleading communication?"
            ),
        ),
        DimensionSpec(
            dimension="Diversity",
            engine_id="ENG-DIVERSITY",
            dimension_type=DimensionType.QUALITY,
            critical_finding_capability=CriticalFindingCapability.NO,
            supports_na=True,
            ledger_name="Diversity Ledger",
            governing_question=(
                "Where appropriate, does the content fairly represent "
                "legitimate perspectives while avoiding false balance?"
            ),
        ),
    )
}

#: All eight dimension names, in specification order (Document 2, §1).
ALL_DIMENSIONS: tuple[str, ...] = tuple(DIMENSION_SPECS)

#: Dimensions that participate in Trust Evaluation: the Trust dimensions plus
#: the trust-gating contribution of the Hybrid dimensions (Document 3, §6).
TRUST_RELEVANT_DIMENSIONS: tuple[str, ...] = tuple(
    spec.dimension
    for spec in DIMENSION_SPECS.values()
    if spec.dimension_type in (DimensionType.TRUST, DimensionType.HYBRID)
)

#: Dimensions that participate in Quality Evaluation: the Quality dimensions
#: plus the quality contribution of the Hybrid dimensions (Document 3, §7).
#: Trust dimensions do not contribute to the Quality Verdict.
QUALITY_CONTRIBUTING_DIMENSIONS: tuple[str, ...] = tuple(
    spec.dimension
    for spec in DIMENSION_SPECS.values()
    if spec.dimension_type in (DimensionType.QUALITY, DimensionType.HYBRID)
)

#: The four engines that may emit Critical Findings and can therefore gate
#: trust (Document 3, §5). Quality dimensions never appear here.
CRITICAL_FINDING_CAPABLE_DIMENSIONS: tuple[str, ...] = tuple(
    spec.dimension
    for spec in DIMENSION_SPECS.values()
    if spec.critical_finding_capability is CriticalFindingCapability.YES
)

#: The frozen orchestration schedule (Document 2, §8; Document 4, §6 and §12).
#:
#: Engines run in parallel except where cross-engine inputs force ordering.
#: Wave 1 runs the six engines with no cross-engine inputs; Novelty follows
#: because it performs a Coverage Cross-check; Engagement runs last because it
#: reuses Relevance, Coverage, Readability, and Novelty results.
EXECUTION_WAVES: tuple[tuple[str, ...], ...] = (
    ("Relevance", "Accuracy", "Coverage", "Credibility", "Readability", "Diversity"),
    ("Novelty",),
    ("Engagement",),
)

#: Which prior engine results each engine receives as ``prior_audit_results``
#: (Document 2, §8). Engines absent from this mapping have no cross-engine
#: inputs and must never read another engine's output.
CROSS_ENGINE_INPUTS: Mapping[str, tuple[str, ...]] = {
    "Novelty": ("Coverage",),
    "Engagement": ("Relevance", "Coverage", "Readability", "Novelty"),
}


def spec_for(dimension: str) -> DimensionSpec:
    """Return the frozen descriptor for ``dimension``.

    Args:
        dimension: A dimension name, e.g. ``"Credibility"``.

    Returns:
        The matching :class:`DimensionSpec`.

    Raises:
        KeyError: If ``dimension`` is not one of the frozen eight. The
            dimension set is closed; new dimensions are explicitly out of
            scope (Document 4, §14).
    """
    try:
        return DIMENSION_SPECS[dimension]
    except KeyError as exc:
        raise KeyError(
            f"{dimension!r} is not one of the eight frozen dimensions: "
            f"{', '.join(ALL_DIMENSIONS)}"
        ) from exc
