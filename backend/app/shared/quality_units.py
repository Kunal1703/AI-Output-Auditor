"""The units of evaluation the four Quality engines work over.

The counterpart to :mod:`app.shared.extraction.models`, which holds the units
Document 2 §5.1 produces — Requirement, Claim, Key Point, Citation. The Quality
engines evaluate units of their own, named by the §6.3 ledger table:

===============  ==============================  =============================
Engine           §6.3 unit                       Class here
===============  ==============================  =============================
Novelty          Text segment                    :class:`RedundancyCandidate`
Readability      Issue                           :class:`ReadabilityIssue`
Engagement       Task-fitness / manipulation      :class:`TaskCriterion`,
                 item                            :class:`ManipulationCandidate`
Diversity        Viewpoint / bias item           :class:`BiasItem` (viewpoints
                                                 live with the other extraction
                                                 units, being an §5.1-shaped
                                                 product)
===============  ==============================  =============================

:class:`ReadabilityAspect` is the one unit here with no ledger row of its own
reason to exist: Document 2 §7.6 stage 3 reviews *Clarity, Coherence, and
Structure*, and those three are what the review renders a verdict on. They are
units of evaluation in every sense the judge cares about, so they are modelled as
such rather than smuggled in as prompt text.

**The same rule as extraction applies: classification fields default to
``None``.** Document 2 keeps labelling (§5.2) separate from the stage that
produces a unit, and the frozen Readability pipeline runs Issue Classification at
stage 4 and Severity Assignment at stage 5 — two stages, after the stage 3 review
that surfaces the issues. So a freshly reviewed issue carries no ``category`` and
no ``severity``, and there is nowhere to put one early.

Every unit is a frozen dataclass. A stage returns a new instance rather than
mutating its input, which is what keeps the pipeline's stage boundaries
verifiable after the fact — you can hold the pre- and post-classification unit
side by side and see exactly what a stage decided.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.shared.schemas import Severity
from app.shared.text_segmentation import TextSpan

__all__ = [
    "ReadabilityAspect",
    "ReadabilityIssue",
    "RedundancyCandidate",
    "TaskContext",
    "TaskCriterion",
    "ManipulationCandidate",
    "BiasItem",
    "READABILITY_ASPECTS",
]


# --------------------------------------------------------------------------- #
# Readability (Document 2, §7.6)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ReadabilityAspect:
    """One of the three aspects the stage 3 review renders a verdict on.

    Attributes:
        aspect_id: Stable id — ``"clarity"``, ``"coherence"``, ``"structure"``.
            Stable rather than minted per run because the judge matches verdicts
            to units by id, and these three units are the same on every audit.
        name: Display name, e.g. ``"Clarity"``.
        question: What the reviewer is being asked about this aspect. Carried on
            the unit rather than baked into the prompt so the prompt stays a
            template and the three questions stay legible next to each other.
    """

    aspect_id: str
    name: str
    question: str


#: The three aspects Document 2 §7.6 stage 3 names, in the order it names them.
#:
#: Fixed, not configuration. The stage is frozen as "LLM Readability Review
#: (Clarity, Coherence, Structure)" — adding a fourth aspect would be redesigning
#: the stage, and dropping one would be skipping part of it.
READABILITY_ASPECTS: tuple[ReadabilityAspect, ...] = (
    ReadabilityAspect(
        aspect_id="clarity",
        name="Clarity",
        question=(
            "Can a reader understand each sentence on first reading? Consider "
            "ambiguous wording, undefined jargon, and sentences that have to be "
            "re-read to be parsed."
        ),
    ),
    ReadabilityAspect(
        aspect_id="coherence",
        name="Coherence",
        question=(
            "Do the ideas follow from one another? Consider abrupt topic shifts, "
            "missing connective reasoning, and claims that arrive without the "
            "setup they need."
        ),
    ),
    ReadabilityAspect(
        aspect_id="structure",
        name="Structure",
        question=(
            "Is the content organized so a reader can navigate it? Consider "
            "ordering, grouping of related material, and whether the shape of "
            "the document fits its length and purpose."
        ),
    ),
)


@dataclass(frozen=True)
class ReadabilityIssue:
    """One readability problem, from either the deterministic stage or the review.

    The unit of the Readability Ledger (Document 2, §6.3).

    Attributes:
        issue_id: Run-unique id, e.g. ``"iss_1"``.
        text: The problem, stated so a reader can act on it.
        aspect: Which aspect it belongs to — ``"clarity"``, ``"coherence"``,
            ``"structure"``, or a deterministic check's family.
        quote: The span of the output the issue is about, verbatim. ``None`` for
            a document-level issue that no single span carries.
        source_span: Where the quote sits in the output, when it could be
            located. Backs the evidence pointer.
        origin: ``"deterministic"`` or ``"review"``. Load-bearing: it is why an
            issue does or does not pass through the stage 4–5 LLM classifiers.
            A deterministic issue arrives already classified — the check that
            produced it *is* its category, and its severity came from a rule, not
            a guess — and re-asking a model to label it would be asking what a
            regex already knows (Document 4, §11).
        category: Issue class from stage 4. ``None`` from a review issue until
            that stage runs; pre-filled for a deterministic one.
        severity: Impact from stage 5. Same rule as ``category``.
        attributes: Extra labels a stage attaches — the classifier's rationale,
            the validator's observed measurements.
    """

    issue_id: str
    text: str
    aspect: str
    quote: str | None = None
    source_span: TextSpan | None = None
    origin: str = "review"
    category: str | None = None
    severity: Severity | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def is_deterministic(self) -> bool:
        """Whether a rule produced this issue rather than a model.

        A deterministic issue is worth more than a reviewed one in exactly one
        respect: it reads identically on every re-run (Document 4, §11).
        """
        return self.origin == "deterministic"

    @property
    def is_classified(self) -> bool:
        """Whether stages 4 and 5 have both labelled this issue."""
        return self.category is not None and self.severity is not None


# --------------------------------------------------------------------------- #
# Novelty (Document 2, §7.5)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RedundancyCandidate:
    """A pair of segments that stage 4 found similar enough to question.

    The unit of the Redundancy Ledger (Document 2, §6.3), whose unit the table
    names as a *text segment*. The candidate carries both segments because the
    stage 6 review cannot judge repetition from one of them — the question is
    whether *this* segment adds anything over *that* one, and that needs both.

    Attributes:
        candidate_id: Run-unique id, e.g. ``"red_1"``.
        segment: The later segment — the one whose presence is in question.
            Ordering matters: the first statement of an idea is not the
            redundant one, so it is always the later segment that pays.
        earlier: The earlier segment it echoes.
        similarity: Relatedness of the two, in [0, 1]. Raw cosine via
            :func:`~app.shared.embedding_service.relatedness`, on the scale the
            configured threshold is calibrated against — never rescaled.
        is_literal: Whether the two are literal duplicates rather than merely
            semantic ones. A verbatim repeat is much harder to defend as
            functional than a restatement, and the review is told which it is.
        covers_key_point: Text of the high-salience Coverage key point this
            segment restates, when the stage 7 cross-check found one. ``None``
            when it restates nothing Coverage considered important.
        key_point_salience: That key point's salience, in [0, 1].
        attributes: Extra labels later stages attach.
    """

    candidate_id: str
    segment: TextSpan
    earlier: TextSpan
    similarity: float
    is_literal: bool = False
    covers_key_point: str | None = None
    key_point_salience: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        """The segment under question — what the judge is asked about."""
        return self.segment.text

    @property
    def serves_coverage(self) -> bool:
        """Whether the stage 7 cross-check tied this to a salient key point.

        The signal that keeps Novelty from contradicting Coverage. A recap that
        restates the source's headline finding is repetition Coverage wants
        present, and penalizing it here would have the two engines issue
        opposite instructions about the same sentence.
        """
        return self.covers_key_point is not None


# --------------------------------------------------------------------------- #
# Engagement (Document 2, §7.7)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TaskContext:
    """What stage 2 identified about the user's task.

    Attributes:
        task_type: The kind of request, e.g. ``"summarization"``,
            ``"explanation"``, ``"comparison"``.
        goal: What the user is trying to accomplish, in one sentence.
        audience: Who the output is for, as far as the prompt reveals.
        criteria: The success criteria stage 4 evaluates fitness against.
        identified: Whether the stage could identify a task at all. ``False``
            when no prompt was supplied — the honest answer, and the one that
            makes Engagement report low confidence rather than invent a goal to
            measure against.
    """

    task_type: str
    goal: str
    audience: str = ""
    criteria: tuple["TaskCriterion", ...] = ()
    identified: bool = True


@dataclass(frozen=True)
class TaskCriterion:
    """One success criterion for the identified task.

    Half of the Engagement Ledger's unit (Document 2, §6.3: "Task-fitness /
    manipulation item").

    Attributes:
        criterion_id: Run-unique id, e.g. ``"crt_1"``.
        text: What the output must do to serve the user's goal.
        importance: How much this criterion matters to the goal, in [0, 1].
            Weights the score, so that failing the central criterion moves it
            further than failing an incidental one.
        attributes: Extra labels later stages attach.
    """

    criterion_id: str
    text: str
    importance: float = 0.5
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ManipulationCandidate:
    """A phrase stage 5 matched, awaiting the stage 6 verdict.

    The other half of the Engagement Ledger's unit.

    **A candidate is not a finding**, and the name is doing real work. Stage 5
    matches a regex; only stage 6 decides whether the phrase manipulates anyone.
    An article reporting on a scam quotes the scam's language and matches every
    pattern in the list.

    Attributes:
        candidate_id: Run-unique id, e.g. ``"man_1"``.
        family: The pattern family matched, e.g. ``"clickbait"``.
        text: The matched phrase, verbatim.
        source_span: Where it sits in the output, when locatable.
        pattern_severity: The impact *if* stage 6 confirms it, from the
            validator. Not a claim that it will.
        attributes: Extra labels later stages attach.
    """

    candidate_id: str
    family: str
    text: str
    source_span: TextSpan | None = None
    pattern_severity: Severity = Severity.LOW
    attributes: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Diversity (Document 2, §7.8)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BiasItem:
    """One instance of biased framing or loaded language, from stage 8.

    Half of the Diversity Ledger's unit (Document 2, §6.3: "Viewpoint / bias
    item").

    Attributes:
        bias_id: Run-unique id, e.g. ``"bia_1"``.
        text: The loaded phrasing, verbatim from the output.
        bias_type: What kind — ``"loaded language"``, ``"strawman"``,
            ``"false balance"``, ``"unattributed assertion"``.
        explanation: Why this framing is loaded, and what neutral phrasing would
            look like. Without it the item is an accusation with no argument.
        severity: Impact, assigned by the detection stage.
        source_span: Where it sits in the output, when locatable.
        attributes: Extra labels later stages attach.
    """

    bias_id: str
    text: str
    bias_type: str
    explanation: str
    severity: Severity = Severity.LOW
    source_span: TextSpan | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
