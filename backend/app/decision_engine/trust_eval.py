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
"""

from __future__ import annotations

from typing import Mapping

from app.core.config import DecisionSettings
from app.decision_engine.critical_findings import CriticalFindingOutcome
from app.shared.schemas import AuditResult, TrustVerdict

__all__ = ["evaluate"]


def evaluate(
    scored: Mapping[str, AuditResult],
    findings: CriticalFindingOutcome,
    settings: DecisionSettings,
) -> TrustVerdict:
    """Produce the Trust Verdict.

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

    Raises:
        NotImplementedError: Until Milestone 2.
    """
    raise NotImplementedError(
        "Trust Evaluation is implemented in Milestone 2 (Document 3, §6)."
    )
