"""Scoring helpers — the arithmetic shared by the engines' scoring stages.

Document 2 §5.9 names Scoring as a shared component: *"Production of the
dimension Score from the per-unit results and findings."*

**What is shared and what is not.** The specification names the stage but
prescribes no formula — §2 puts thresholds and metric details out of scope. So
each engine defines *its own* scoring rule, and only the arithmetic those rules
have in common lives here: weighted means, importance weighting, banding. An
engine's formula is part of that engine.

**Every helper here is pure and deterministic.** Document 4 §11 wants results
stable across re-runs, and Document 3 §13 wants decisions reconstructable from
their inputs. A score computed by these functions can be re-derived by hand from
the ledger — which is what makes a disputed verdict arguable rather than
mysterious.

**Scores never encode confidence.** Document 2 §5.10 reports confidence
separately, and Document 3 §8 makes it a first-class gate on assertability. A
score of 0.9 means "the measurements say this is good"; whether the auditor can
*assert* that is the confidence's business. Nothing here mixes them.
"""

from __future__ import annotations

from typing import Mapping, Sequence

__all__ = [
    "weighted_mean",
    "importance_weighted_rate",
    "clamp",
    "apply_penalty",
]


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Constrain ``value`` to ``[low, high]``."""
    return min(high, max(low, value))


def weighted_mean(pairs: Sequence[tuple[float, float]], default: float = 0.0) -> float:
    """Return the weighted mean of ``(value, weight)`` pairs.

    Args:
        pairs: The values and their weights. Non-positive weights are ignored.
        default: Returned when no pair carries positive weight.

    Returns:
        The weighted mean, or ``default``.

    Note:
        The ``default`` is the caller's decision and matters. For a trust-relevant
        dimension with nothing to average, ``0.0`` is usually wrong as a *score* —
        "we measured nothing" is not "we measured badly". The honest encoding is
        a neutral score with **zero confidence**, which is what routes the run to
        *Unable to Verify* (Document 3, §8) rather than to a false failure.
    """
    total_weight = sum(weight for _, weight in pairs if weight > 0)
    if total_weight <= 0:
        return default
    total = sum(value * weight for value, weight in pairs if weight > 0)
    return clamp(total / total_weight)


def importance_weighted_rate(
    outcomes: Sequence[tuple[float, float]], default: float = 0.0
) -> float:
    """Return the importance-weighted success rate of ``(credit, importance)`` pairs.

    The shape every engine's score takes here: each unit earns partial credit in
    [0, 1] and carries an importance in [0, 1], and the score is the credit rate
    weighted by importance.

    Why importance-weighted rather than a plain rate: a failure on a load-bearing
    claim and a failure on an incidental aside are not the same failure, and a
    plain rate would say they were. This is the mechanism that lets Accuracy
    report a low score for one central hallucination among twenty true asides —
    which is the correct answer, and the one a plain rate cannot give.

    Args:
        outcomes: ``(credit, importance)`` per unit.
        default: Returned when nothing carries importance.

    Returns:
        The weighted rate in [0, 1].
    """
    return weighted_mean(outcomes, default=default)


def apply_penalty(score: float, penalties: Mapping[str, float]) -> float:
    """Subtract named penalties from a score, clamped at zero.

    Args:
        score: The base score in [0, 1].
        penalties: Named penalty magnitudes.

    Returns:
        The penalized score in [0, 1].

    Note:
        Penalties adjust a *score*; they never gate trust. A qualifying Critical
        Finding gates trust non-compensatorily in the Decision Engine
        (Document 3, §5), and an engine must not try to express that by driving
        its score to zero. Doing so would be both redundant and misleading —
        the report would show a dimension that "scored 0" rather than one that
        raised a finding, and the two mean different things.
    """
    return clamp(score - sum(penalties.values()))
