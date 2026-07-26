"""Loaded-language lexicon — subjective / editorializing terms (MB3).

The Bias / Objectivity evaluator (Evaluation Framework §4.4) checks whether the
output introduces slant, framing, or emphasis **not present in the source**. This
lexicon is the cheap deterministic half of that check (Metric Research §14):
words that carry an evaluative charge — praise, condemnation, alarm, hype — which
an objective restatement of a source would not add on its own.

A match is only *evidence of introduced bias when the term is absent from the
source*; the evaluator makes that comparison. The lexicon here just names the
charged vocabulary. It is intentionally conservative — common, unambiguous
editorializing words — because a false accusation of bias is worse than a missed
one, and the terms are grouped by the framing they carry.
"""

from __future__ import annotations

from typing import Iterator

__all__ = ["LOADED_TERMS", "iter_loaded_terms"]

#: Charged terms grouped by the kind of framing they introduce. Values are
#: lower-cased single words matched on word boundaries by the evaluator.
LOADED_TERMS: dict[str, tuple[str, ...]] = {
    # Condemnation / alarm.
    "alarm": (
        "disastrous", "catastrophic", "devastating", "alarming", "shocking",
        "outrageous", "appalling", "horrific", "dangerous", "reckless",
        "scandalous", "disgraceful", "damning", "grim", "dire", "chaotic",
        "crippling", "ruinous", "toxic", "sinister",
    ),
    # Praise / hype.
    "praise": (
        "brilliant", "stunning", "remarkable", "extraordinary", "spectacular",
        "phenomenal", "flawless", "groundbreaking", "revolutionary", "stellar",
        "magnificent", "unprecedented", "incredible", "amazing", "superb",
        "masterful", "triumphant", "visionary",
    ),
    # Editorial certainty / dismissal.
    "certainty": (
        "obviously", "clearly", "undeniably", "undoubtedly", "certainly",
        "plainly", "surely", "indisputably", "unquestionably",
    ),
    # Contempt / derision.
    "derision": (
        "absurd", "ridiculous", "laughable", "pathetic", "foolish", "nonsense",
        "clueless", "incompetent", "botched", "shameful", "hypocritical",
    ),
    # Intensifiers that inflate emphasis.
    "intensifier": (
        "extremely", "wildly", "massively", "utterly", "hugely", "vastly",
        "staggeringly", "immensely",
    ),
}


def iter_loaded_terms() -> Iterator[tuple[str, str]]:
    """Yield ``(term, category)`` for every loaded term in the lexicon."""
    for category, terms in LOADED_TERMS.items():
        for term in terms:
            yield term, category
