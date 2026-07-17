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

**§6.3 fixes one further vocabulary.** :class:`RedundancyVerdict` — the Novelty
row of the §6.3 ledger table names its verdict set as *Redundant candidate /
Functional repetition*. It is frozen by that table even though §6.4 does not
repeat it.

**Five vocabularies are this implementation's choice and are marked as such.**
Document 2 §6.3 names each engine's ledger and unit but fixes no verdict set for
Relevance, Readability, Engagement, or Diversity, and §2 puts prompt text and
metric detail out of scope. :class:`RequirementVerdict`,
:class:`ReadabilityVerdict`, :class:`TaskFitnessVerdict`,
:class:`ManipulationVerdict`, and :class:`BalanceVerdict` are therefore documented
as assumptions rather than smuggled in as frozen. Each docstring says why its
middle value exists — in every case, to stop a shortfall being reported as a
breach.

:class:`StanceContract` is likewise ours: §7.8 stage 4 names "Stance Contract
Detection" and §3 defines the term, but fixes no label set.
"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "BalanceVerdict",
    "ClaimType",
    "ClaimVerdict",
    "CoverageVerdict",
    "GroundingVerdict",
    "ManipulationVerdict",
    "ReadabilityVerdict",
    "RedundancyVerdict",
    "RequirementType",
    "RequirementVerdict",
    "SourceClass",
    "StanceContract",
    "TaskFitnessVerdict",
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


class RedundancyVerdict(str, Enum):
    """Redundancy vocabulary (Document 2, §6.3).

    Novelty's stage 6 outcome — the "Functional Repetition Review". The §6.3
    ledger table fixes these two values for the Redundancy Ledger; §6.4 does not
    repeat them, but §6.3 is no less binding for that.

    **The distinction is the whole engine.** Stage 4 finds text that *looks*
    duplicated — that is a similarity measurement, not a fault. A recap that
    restates the source's headline finding is repetition doing a job for the
    reader, and Novelty's purpose is efficiency *"while preserving important
    content"* (§7.5). Only a candidate this review confirms as unnecessary costs
    the score; functional repetition costs nothing.
    """

    REDUNDANT = "Redundant candidate"
    FUNCTIONAL = "Functional repetition"


class ReadabilityVerdict(str, Enum):
    """Per-aspect outcome for Readability's stage 3 review.

    **Not frozen.** Document 2 §7.6 names the stage "LLM Readability Review
    (Clarity, Coherence, Structure)" and §6.3 names the ledger unit as an Issue,
    but no verdict set is fixed. These three values are chosen here.

    Why three rather than a boolean: prose is rarely either lucid or
    incomprehensible. *Acceptable* is the honest verdict for writing a reader can
    follow with effort, and collapsing it into either neighbour would make
    Readability report ordinary competent prose as a defect, or genuinely
    confusing prose as fine.
    """

    CLEAR = "Clear"
    ACCEPTABLE = "Acceptable"
    UNCLEAR = "Unclear"


class TaskFitnessVerdict(str, Enum):
    """Per-criterion outcome for Engagement's stage 4 Task Fitness Evaluation.

    **Not frozen.** Document 2 §7.7 names the stage; §6.3 names the ledger unit
    as a "Task-fitness / manipulation item" and fixes no verdict set. Chosen
    here.

    *Partially Met* exists for the same reason as Relevance's *Partially
    Satisfied*: content that serves the user's goal incompletely has not failed
    to serve it, and a two-value vocabulary would have to call it one or the
    other.
    """

    MET = "Met"
    PARTIALLY_MET = "Partially Met"
    UNMET = "Unmet"


class ManipulationVerdict(str, Enum):
    """Per-pattern outcome for Engagement's stage 6 Manipulation Verification.

    **Not frozen.** Document 2 §7.7 names stage 5 "Manipulation Pattern
    Detection" and stage 6 "LLM Manipulation Verification"; no verdict set is
    fixed. Chosen here.

    **The two stages exist because a pattern is not a verdict.** A rhetorical
    question, a strong headline, or the word "guaranteed" inside a quoted
    warranty are all *patterns* the regex will match and none of them is
    manipulation. Stage 5 finds candidates; this vocabulary is how stage 6 says
    which ones were real. *Legitimate* is the verdict that clears a false
    positive, and without it the engine would cry wolf on ordinary emphatic
    prose.
    """

    MANIPULATIVE = "Manipulative"
    BORDERLINE = "Borderline"
    LEGITIMATE = "Legitimate"


class BalanceVerdict(str, Enum):
    """Per-viewpoint outcome for Diversity's stage 7 Balance Evaluation.

    **Not frozen.** Document 2 §7.8 names the stage; §6.3 names the ledger unit
    as a "Viewpoint / bias item" and fixes no verdict set. Chosen here.

    *Misrepresented* is deliberately distinct from *Omitted*. A viewpoint stated
    only as a strawman is present in the text and absent from the argument, and
    reporting it as covered would let the most common form of unbalanced writing
    pass as balanced.
    """

    FAIRLY_REPRESENTED = "Fairly Represented"
    UNDERREPRESENTED = "Underrepresented"
    MISREPRESENTED = "Misrepresented"
    OMITTED = "Omitted"


class StanceContract(str, Enum):
    """Whether the output presents itself as neutral or as declared advocacy.

    **Not frozen.** Document 2 §3 defines the Stance Contract as "whether the AI
    Output presents itself as neutral/objective or as declared advocacy" and
    §7.8 stage 4 names the detection stage. The labels are ours.

    **It sets the standard the rest of the engine judges against.** An essay that
    announces itself as arguing a position is not required to give equal room to
    the other side — that is what an argument is, and demanding balance of it
    would be demanding it stop being one. What it *is* required to do is not
    misrepresent the opposition and not pass itself off as neutral. A piece that
    claims neutrality and then argues one way is the failure Diversity exists to
    catch, and the two cases are indistinguishable without this label.
    """

    NEUTRAL = "Neutral"
    DECLARED_ADVOCACY = "Declared Advocacy"


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
