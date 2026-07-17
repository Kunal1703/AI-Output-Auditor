"""Stage 5 — Trust Evaluation (Document 3, §6).

Consumes the Trust dimensions (Accuracy, Credibility), the trust-gating
contribution of the Hybrid dimensions (Relevance, Coverage), and the aggregated
Critical Findings from Stage 4. Quality dimensions do not participate.

**Trust is a floor, not an average.** The question is not "how good is this on
balance?" but "is there anything here that makes it unsafe to rely on?" So the
evaluation is pessimistic and worst-case driven:

* Any qualifying Critical Finding → **Untrusted**.
* Otherwise trust is bounded by the **weakest** trust-relevant dimension, not
  the mean. A strong Accuracy score does not offset a failing Credibility score;
  the lower governs.
* A trust-relevant dimension that cannot be evaluated with sufficient confidence
  **does not pass by default**. It routes to *Unable to Verify* — never to
  *Trusted*.

That last rule is the one that must never be softened. Every path out of this
stage that is not a confident pass leads somewhere other than *Trusted*.

**Resolution table (Document 3, §6).**

| Condition | Trust outcome |
|---|---|
| A qualifying Critical Finding is present | **Untrusted** |
| No qualifying finding; all trust-relevant dimensions clear their thresholds with sufficient confidence | **Trust-Pass** |
| No qualifying finding; dimensions acceptable but carrying minor, non-blocking issues | **Trust-Pass with caveats** |
| No qualifying finding, but one or more trust-relevant dimensions lack sufficient confidence/evidence | **Unable to Verify** |

**The table has no row for "confident, but scores badly", and that is not an
omission.** *Untrusted* is reserved for a **disqualifying** failure — a
qualifying Critical Finding. A trust dimension that scores 0.4 with high
confidence and raises no finding has not disqualified the content; it has
reported a weakness. Document 3 §8 routes exactly that case — *"low score + high
confidence"* on a trust-relevant dimension that is **not gating** — to *"Needs
Revision"*, and §11 step 3 confirms it: *"trust passes but quality or non-gating
trust issues require correction → Needs Revision"*.

So a weak-but-confident trust dimension yields **Trust-Pass with caveats** on
this axis, and the *overall* verdict becomes *Needs Revision* via
:func:`requires_revision`. Reporting *Untrusted* instead would make the
critical-finding gate meaningless — every low score would trip it, and the
distinction between "this is wrong" and "this is weak" would be gone.
"""

from __future__ import annotations

from typing import Mapping

from app.core.config import DecisionSettings
from app.core.constants import TRUST_RELEVANT_DIMENSIONS
from app.core.logging import bind, get_logger
from app.decision_engine.critical_findings import CriticalFindingOutcome
from app.shared.schemas import AuditResult, TrustOutcome, TrustVerdict

__all__ = ["evaluate", "trust_dimensions", "weakest", "requires_revision"]

logger = get_logger(__name__)


def trust_dimensions(
    scored: Mapping[str, AuditResult],
) -> dict[str, AuditResult]:
    """Return the trust-relevant results — the Trust and Hybrid dimensions.

    Reads the frozen routing set from ``core.constants`` rather than each
    result's own metadata, so the set of dimensions that can gate trust is fixed
    by Document 2 §4.1 and cannot be widened by an engine describing itself
    differently.

    Only results carrying a numeric score are returned. An ``"N/A"`` score
    cannot participate in a floor comparison, and no trust-relevant dimension is
    permitted to return one anyway (``supports_na`` is False for all four).
    """
    return {
        dimension: result
        for dimension, result in scored.items()
        if dimension in TRUST_RELEVANT_DIMENSIONS and isinstance(result.score, float)
    }


def weakest(scored: Mapping[str, AuditResult]) -> tuple[str, float] | None:
    """Return the weakest trust-relevant dimension and its score.

    **This is the whole of Document 3 §6's non-compensatory rule in one
    function.** Trust is bounded by the weakest trust-relevant dimension, not
    the mean: a strong Accuracy score does not offset a failing Credibility
    score, so the minimum governs and nothing averages.

    Returns:
        ``(dimension, score)`` for the lowest-scoring trust-relevant dimension,
        or ``None`` when none could be read — which is itself a verification gap
        and never a pass.
    """
    candidates = trust_dimensions(scored)
    if not candidates:
        return None
    dimension = min(candidates, key=lambda d: float(candidates[d].score))
    return dimension, float(candidates[dimension].score)


def requires_revision(
    scored: Mapping[str, AuditResult], settings: DecisionSettings
) -> tuple[bool, list[str]]:
    """Whether a trust-relevant dimension is too weak to rely on as-is.

    The *non-gating* trust half of Document 3 §11 step 3. A dimension scoring
    below ``trust_dimension_pass_threshold`` with no qualifying finding has not
    disqualified the content — it has reported a weakness that needs correcting
    before reliance. See the module docstring.

    Deliberately threshold-driven rather than counted from recommendations: the
    score already reflects the issue, and letting a single High-tier
    recommendation force *Needs Revision* would make the verdict a function of
    how chatty an engine is rather than of what it measured.

    Args:
        scored: The applicable results from Stage 3.
        settings: Supplies ``trust_dimension_pass_threshold``.

    Returns:
        ``(requires_revision, reasons)``.
    """
    reasons: list[str] = []
    for dimension, result in sorted(trust_dimensions(scored).items()):
        score = float(result.score)
        if score < settings.trust_dimension_pass_threshold:
            reasons.append(
                f"{dimension} scored {score:.2f}, below the "
                f"{settings.trust_dimension_pass_threshold:.2f} threshold a "
                "trust-relevant dimension must clear"
            )
    return bool(reasons), reasons


def evaluate(
    scored: Mapping[str, AuditResult],
    findings: CriticalFindingOutcome,
    settings: DecisionSettings,
) -> TrustVerdict:
    """Produce the Trust Verdict.

    The order of the checks below *is* the non-compensatory guarantee. The gate
    is tested first and returns immediately, so no score — however strong — is
    ever consulted on content that carries a qualifying Critical Finding.

    Args:
        scored: The applicable results from Stage 3, keyed by dimension. Only
            the Trust and Hybrid entries are read here.
        findings: Stage 4's outcome. When ``findings.trust_is_gated`` is set,
            the verdict is *Untrusted* and no score may override it.
        settings: Supplies ``trust_dimension_pass_threshold``,
            ``trust_caveat_threshold``, and ``min_trust_confidence``.

    Returns:
        The Trust Verdict, always carrying its specific reason — the gating
        finding, or the confidence gap.
    """
    # -- 1. The non-compensatory gate. Nothing below this is consulted. ---- #
    if findings.trust_is_gated:
        gating = findings.gating
        refs = list(
            dict.fromkeys(ref for f in gating for ref in f.evidence_refs)
        )
        headline = gating[0]
        detail = (
            f"{headline.dimension} raised a {headline.severity.value}-severity "
            f"finding: {headline.type} — {headline.description}"
        )
        if len(gating) > 1:
            detail += f" ({len(gating) - 1} further qualifying finding(s) follow.)"

        logger.info(
            "trust gated by critical finding",
            extra=bind(
                gating=len(gating),
                dimension=headline.dimension,
                severity=headline.severity.value,
            ),
        )
        return TrustVerdict(
            verdict=TrustOutcome.UNTRUSTED,
            reason=(
                "A qualifying Critical Finding is present, so the content must "
                f"not be relied upon regardless of how it scores elsewhere. {detail}"
            ),
            evidence_refs=refs,
            gating_finding_ids=[f.finding_id for f in gating],
        )

    # -- 2. Every trust-relevant dimension must be present. ---------------- #
    candidates = trust_dimensions(scored)
    missing = [d for d in TRUST_RELEVANT_DIMENSIONS if d not in candidates]
    if missing:
        return TrustVerdict(
            verdict=TrustOutcome.UNABLE_TO_VERIFY,
            reason=(
                "Trust cannot be asserted on an incomplete measurement set: "
                f"{', '.join(sorted(missing))} produced no readable result. "
                "This is undetermined trust, not failed trust."
            ),
            evidence_refs=[],
            gating_finding_ids=[],
        )

    # -- 3. Confidence gates assertability, before any score is read. ------ #
    #
    # A trust-relevant dimension that could not be evaluated with sufficient
    # confidence does NOT pass by default. This check precedes the score checks
    # deliberately: a high score reached without evidence is exactly the
    # "high score + low confidence" case Document 3 §8 forbids asserting, and
    # testing the score first would let it through.
    unconfident = sorted(
        (d for d, r in candidates.items() if r.confidence < settings.min_trust_confidence),
        key=lambda d: candidates[d].confidence,
    )
    if unconfident:
        detail = "; ".join(
            f"{d} at {candidates[d].confidence:.2f}" for d in unconfident
        )
        logger.info(
            "trust not assertable: confidence below minimum",
            extra=bind(dimensions=unconfident, minimum=settings.min_trust_confidence),
        )
        return TrustVerdict(
            verdict=TrustOutcome.UNABLE_TO_VERIFY,
            reason=(
                f"{len(unconfident)} trust-relevant dimension(s) could not be "
                f"measured with the confidence required to assert a verdict "
                f"(minimum {settings.min_trust_confidence:.2f}): {detail}. "
                "The auditor can neither confirm nor deny trustworthiness on the "
                "available evidence."
            ),
            evidence_refs=[],
            gating_finding_ids=[],
        )

    # -- 4. The weakest dimension governs. Never the mean. ----------------- #
    floor = weakest(scored)
    assert floor is not None  # candidates is non-empty and complete by step 2
    weakest_dimension, weakest_score = floor

    if weakest_score >= settings.trust_caveat_threshold:
        return TrustVerdict(
            verdict=TrustOutcome.TRUST_PASS,
            reason=(
                "No qualifying Critical Finding, and every trust-relevant "
                f"dimension cleared its threshold with sufficient confidence. "
                f"The weakest was {weakest_dimension} at {weakest_score:.2f}."
            ),
            evidence_refs=[],
            gating_finding_ids=[],
        )

    return TrustVerdict(
        verdict=TrustOutcome.TRUST_PASS_WITH_CAVEATS,
        reason=(
            "No qualifying Critical Finding, and the trust-relevant dimensions "
            "carry no disqualifying failure — but they are not uniformly strong. "
            f"Trust is bounded by the weakest, {weakest_dimension} at "
            f"{weakest_score:.2f} (below the {settings.trust_caveat_threshold:.2f} "
            "clean-pass threshold)."
        ),
        evidence_refs=[],
        gating_finding_ids=[],
    )
