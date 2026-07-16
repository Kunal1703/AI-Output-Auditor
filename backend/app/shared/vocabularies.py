"""The frozen verdict vocabularies (Document 2, §6.4).

Every per-unit verdict an engine can render, in one module. Document 2 §6.4
tabulates these as *Common Verdict Vocabularies* — they are contracts, not
implementation choices, and an engine that invented a ninth value for a
four-value vocabulary would produce a ledger the report cannot render and the
Decision Engine cannot interpret.

| Vocabulary | Values | Engine |
|---|---|---|
| Claim verification | Supported / Contradicted / Unverifiable | Accuracy |
| Coverage presence | Present / Partial / Absent | Coverage |
| Grounding | Supports / Partial / Contradicts / Unrelated | Credibility |
| Claim type | Factual / Opinion / Non-verifiable | Accuracy |
| Source class | Primary / Secondary / Government / Academic | Credibility |
| Requirement type | Hard / Soft | Relevance |
| Applicability | Applicable / Not Applicable | Diversity |

**One vocabulary is not in §6.4 and is marked as such.**
:class:`RequirementVerdict` — Document 2 §6.3 specifies Relevance's ledger as
"Per-requirement evaluation (Hard / Soft classified)" without fixing a verdict
set. The three values below are this implementation's choice, documented as an
assumption rather than smuggled in as frozen. See its docstring.
"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "ClaimType",
    "ClaimVerdict",
    "CoverageVerdict",
    "GroundingVerdict",
    "RequirementType",
    "RequirementVerdict",
    "SourceClass",
]


class RequirementType(str, Enum):
    """Requirement vocabulary (Document 2, §6.4).

    Assigned by Relevance's stage 3, "Hard / Soft Requirement Classification" —
    never by extraction.

    The distinction has teeth: a violated **hard** requirement is a Critical
    Finding that gates trust (Document 2, §3), while a missed **soft** one is a
    quality signal. Guessing it during extraction would put a trust gate behind
    a stage that was never meant to carry one.
    """

    HARD = "Hard"
    SOFT = "Soft"


class RequirementVerdict(str, Enum):
    """Per-requirement outcome for Relevance's stage 4.

    **Not frozen.** Document 2 §6.3 names the stage "Per-Requirement Evaluation"
    and the ledger "Requirement Checklist" but fixes no verdict set, and §2 puts
    thresholds and prompt text out of scope. These three values are chosen here.

    Why three rather than a boolean: a requirement can be *addressed but
    incompletely* — asked for five examples, given three. Collapsing that into
    "violated" would make Relevance report a hard-requirement breach where none
    occurred and, through the critical-finding gate, drive an *Untrusted*
    verdict on content that merely under-delivered. The middle value exists to
    keep that from happening.
    """

    SATISFIED = "Satisfied"
    PARTIALLY_SATISFIED = "Partially Satisfied"
    VIOLATED = "Violated"


class ClaimType(str, Enum):
    """Claim vocabulary (Document 2, §6.4).

    Assigned by Accuracy's stage 3, "Claim Classification" — never by
    extraction.

    Load-bearing for scoring: only **Factual** claims are verifiable, so only
    they reach stages 5–7 and only they contribute to the Accuracy score. An
    opinion marked Factual would be sent for verification, come back
    *Unverifiable*, and depress a score it has no business touching.
    """

    FACTUAL = "Factual"
    OPINION = "Opinion"
    NON_VERIFIABLE = "Non-verifiable"


class ClaimVerdict(str, Enum):
    """Claim verification vocabulary (Document 2, §6.4).

    Accuracy's stage 7 outcome.

    **Contradicted and Unverifiable are not the same and must never be merged.**
    A Contradicted claim is a confident negative — the evidence says otherwise —
    and drives a Critical Finding toward *Untrusted*. An Unverifiable claim is a
    gap: the evidence could not settle it, which lowers confidence and heads for
    *Unable to Verify* (Document 3, §8). Collapsing them would convert honest
    uncertainty into a false accusation, which is the exact failure mode this
    system exists to prevent.
    """

    SUPPORTED = "Supported"
    CONTRADICTED = "Contradicted"
    UNVERIFIABLE = "Unverifiable"


class CoverageVerdict(str, Enum):
    """Coverage presence vocabulary (Document 2, §6.4).

    Coverage's stage 5 outcome. **Partial** is what keeps Coverage from
    over-penalizing summarization (§7.3): a key point mentioned briefly is not
    the same as one omitted, and a two-value vocabulary would force the engine
    to call it one or the other.
    """

    PRESENT = "Present"
    PARTIAL = "Partial"
    ABSENT = "Absent"


class GroundingVerdict(str, Enum):
    """Grounding vocabulary (Document 2, §6.4).

    Credibility's stage 6 outcome — whether a cited source actually supports the
    claim attached to it.

    **Unrelated is the misattribution signal.** A real, reachable URL attached
    to a paper that says nothing about the claim is not a broken link; it is a
    citation that was invented to look authoritative. That is a different
    finding from a fabricated URL, and the vocabulary keeps them distinguishable.
    """

    SUPPORTS = "Supports"
    PARTIAL = "Partial"
    CONTRADICTS = "Contradicts"
    UNRELATED = "Unrelated"


class SourceClass(str, Enum):
    """Source class vocabulary (Document 2, §6.4).

    Credibility's stage 7 outcome. Describes *what kind* of source a citation
    points at. It is descriptive: this implementation does not treat one class
    as automatically more trustworthy than another, because a primary source can
    be junk and a secondary one authoritative. Class informs the score; it does
    not determine it.
    """

    PRIMARY = "Primary"
    SECONDARY = "Secondary"
    GOVERNMENT = "Government"
    ACADEMIC = "Academic"
