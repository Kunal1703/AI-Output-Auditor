"""Structured units produced by the extraction services.

These are the "atomic units of evaluation" of Document 2 §5.1 — what LLM
Extraction turns an input *into*, before any engine judges them.

**Every classification field here is deliberately optional and unset.**
Document 2 keeps extraction (§5.1) and Classification & Weighting (§5.2) as two
separate shared components, and the frozen pipelines run them as separate
stages: Relevance extracts requirements at stage 2 and classifies them Hard/Soft
at stage 3; Accuracy extracts claims at stage 2, classifies them
Factual/Opinion/Non-verifiable at stage 3, and assigns centrality at stage 4.

So the extraction services fill ``text`` and leave ``requirement_type``,
``claim_type``, and ``centrality`` as ``None``. A Milestone 3 engine fills them
at its own frozen stage. The fields exist here — with the frozen vocabularies
attached — so the shape is settled and the engines have somewhere to put their
answer, not so that extraction can answer early.

If you find yourself wanting to set one of them inside an extraction service,
that is the signal you have crossed from §5.1 into §5.2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, Sequence, TypeVar

from app.shared.schemas import Severity
from app.shared.text_segmentation import TextSpan
from app.shared.vocabularies import ClaimType, RequirementType, SourceClass

__all__ = [
    "RequirementType",
    "ClaimType",
    "SourceClass",
    "Requirement",
    "Claim",
    "KeyPoint",
    "Citation",
    "Viewpoint",
    "ExtractionResult",
]


@dataclass(frozen=True)
class Requirement:
    """One atomic instruction or expectation extracted from the Prompt.

    The unit of Relevance's Requirement Checklist ledger (Document 2, §6.3).

    Attributes:
        requirement_id: Run-unique id, e.g. ``"req_1"``.
        text: The requirement, stated as an atomic instruction.
        source_span: Where it came from in the prompt, when locatable. Enables
            the Evidence Viewer to show *which words* imposed the requirement.
            ``None`` when the model restated it rather than quoting.
        requirement_type: Hard or Soft. **Always ``None`` from extraction** —
            filled by Relevance's stage 3 (Document 2, §7.1).
        attributes: Extra labels an engine attaches later. Extraction leaves it
            empty.
    """

    requirement_id: str
    text: str
    source_span: TextSpan | None = None
    requirement_type: RequirementType | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def is_classified(self) -> bool:
        """Whether stage 3 has assigned a type yet."""
        return self.requirement_type is not None


@dataclass(frozen=True)
class Claim:
    """One atomic, independently checkable statement from the AI Output.

    The unit of Accuracy's Claim Verification Ledger (Document 2, §6.3).

    Attributes:
        claim_id: Run-unique id, e.g. ``"clm_1"``.
        text: The claim, stated so it can be checked on its own. A claim that
            needs surrounding context to interpret cannot be verified in
            isolation, which is what makes atomicity an extraction concern
            rather than a stylistic one.
        source_span: Where it sits in the AI Output, when locatable. Backs the
            evidence pointer on any finding about this claim. ``None`` when the
            model paraphrased beyond recovery.
        claim_type: Factual / Opinion / Non-verifiable. **Always ``None`` from
            extraction** — filled by Accuracy's stage 3 (Document 2, §7.2).
        centrality: How load-bearing the claim is, in [0, 1]. **Always ``None``
            from extraction** — filled by Accuracy's stage 4. Used later as a
            tiebreaker when ordering Critical Findings (Document 3, §5).
        attributes: Extra labels an engine attaches later. Extraction leaves it
            empty.
    """

    claim_id: str
    text: str
    source_span: TextSpan | None = None
    claim_type: ClaimType | None = None
    centrality: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def is_classified(self) -> bool:
        """Whether stage 3 has assigned a type yet."""
        return self.claim_type is not None

    @property
    def is_located(self) -> bool:
        """Whether the claim was traced back to a span of the source.

        An unlocated claim can still be verified, but any finding about it will
        have a weaker evidence pointer — worth knowing before Accuracy reports
        confidence on it.
        """
        return self.source_span is not None


@dataclass(frozen=True)
class KeyPoint:
    """One atomic unit of important information from the Reference Source.

    The unit of Coverage's Coverage Ledger (Document 2, §6.3).

    Attributes:
        key_point_id: Run-unique id, e.g. ``"kpt_1"``.
        text: The key point, stated so its presence in the output can be checked.
        source_span: Where it sits in the reference source, when locatable.
        salience: Assessed importance, in [0, 1]. **Always ``None`` from
            extraction** — filled by Coverage's stage 3 (Document 2, §7.3).
            Load-bearing: it is what separates a legitimate summarization from a
            Critical Omission, and therefore what keeps Coverage from punishing
            a summary for being a summary.
        category: What kind of information this is, e.g. ``"finding"``,
            ``"caveat"``, ``"method"``. **Always ``None`` from extraction** —
            filled by Coverage's stage 4.
        severity: Impact of omitting it. **Always ``None`` from extraction** —
            filled by Coverage's stage 4.
        attributes: Extra labels an engine attaches later.
    """

    key_point_id: str
    text: str
    source_span: TextSpan | None = None
    salience: float | None = None
    category: str | None = None
    severity: Severity | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def is_classified(self) -> bool:
        """Whether stages 3–4 have assigned salience and severity yet."""
        return self.salience is not None and self.severity is not None


@dataclass(frozen=True)
class Citation:
    """One reference, URL, DOI, or attribution present in the AI Output.

    The unit of Credibility's Citation Ledger (Document 2, §6.3).

    Attributes:
        citation_id: Run-unique id, e.g. ``"cit_1"``.
        text: The citation as it appears, e.g. ``"Smith et al. (2023)"``.
        url: Extracted URL, when the citation carries one.
        doi: Extracted DOI, when the citation carries one.
        source_span: Where it sits in the AI Output, when locatable.
        source_class: Primary / Secondary / Government / Academic. **Always
            ``None`` from extraction** — filled by Credibility's stage 7.
        attributes: Extra labels an engine attaches later — the verification
            outcome, the mapped claim ids, the grounding verdict.
    """

    citation_id: str
    text: str
    url: str | None = None
    doi: str | None = None
    source_span: TextSpan | None = None
    source_class: SourceClass | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def is_locatable_source(self) -> bool:
        """Whether this citation points at something machine-checkable.

        A citation with a URL or DOI can be *verified* — fetched, resolved,
        grounded. A bare "Smith et al. (2023)" cannot: it may be perfectly real
        and simply unlinked. That difference must not become a fabrication
        finding, so the engine has to be able to tell the two apart before it
        judges (Document 2, §7.4).
        """
        return bool(self.url or self.doi)


@dataclass(frozen=True)
class Viewpoint:
    """One legitimate perspective on the question the content addresses.

    Half of Diversity's Diversity Ledger unit (Document 2, §6.3: "Viewpoint /
    bias item"), produced by §7.8 stage 6, "Viewpoint Extraction".

    **A viewpoint is not a side.** It is a position a reasonable, informed person
    holds on the question, together with the reasoning behind it. That framing is
    what keeps Diversity from manufacturing false balance: on a settled factual
    question there is one legitimate viewpoint, and an engine that assumed there
    were two would reward inventing a controversy — the exact failure §7.8 names.

    Attributes:
        viewpoint_id: Run-unique id, e.g. ``"vwp_1"``.
        text: The position, stated as someone holding it would state it. Not as
            an opponent would characterize it — a viewpoint written by its
            critics is a strawman, and the engine would then measure the output
            against one.
        source_span: Where the output states this viewpoint, when it does and
            when it can be located. ``None`` when the output omits it entirely,
            which is itself the answer to stage 7's question.
        legitimacy: How well-founded the viewpoint is, in [0, 1]. **Always
            ``None`` from extraction** — the balance evaluation weighs it.
            Load-bearing: it is what separates "the output ignored a serious
            objection" from "the output declined to platform a fringe claim",
            and only the first is a failure.
        in_output: Whether extraction saw this viewpoint in the AI Output at all,
            as opposed to finding it in the retrieved perspectives.
        attributes: Extra labels a later stage attaches.
    """

    viewpoint_id: str
    text: str
    source_span: TextSpan | None = None
    legitimacy: float | None = None
    in_output: bool = False
    attributes: dict[str, Any] = field(default_factory=dict)


UnitT = TypeVar("UnitT")


@dataclass(frozen=True)
class ExtractionResult(Generic[UnitT]):
    """What an extraction service returns: the units plus how it went.

    The diagnostics are not decoration. Document 2 §5.10 has every engine report
    confidence *separately from its score*, and an engine's confidence in its own
    judgment depends on how cleanly its inputs were extracted — twelve claims of
    which two could not be located is a different footing from twelve cleanly
    located ones. Extraction reports the facts; the engine decides what they mean
    for its confidence (that decision is Milestone 3's).

    Attributes:
        units: The extracted units, in source order where locatable.
        source_characters: Size of the text extraction ran over.
        located_count: How many units were traced back to a source span.
        duplicate_count: How many near-duplicates were merged away.
        truncated: Whether the source was truncated to fit the model's window.
            A truthful signal that extraction did not see everything.
        raw_unit_count: Units the model returned, before validation and
            deduplication.
    """

    units: tuple[UnitT, ...]
    source_characters: int = 0
    located_count: int = 0
    duplicate_count: int = 0
    truncated: bool = False
    raw_unit_count: int = 0

    def __len__(self) -> int:
        return len(self.units)

    def __iter__(self):
        return iter(self.units)

    @property
    def is_empty(self) -> bool:
        """Whether nothing was extracted.

        Ambiguous on its own, and deliberately left that way: an empty result
        may mean the text genuinely contains no claims, or that extraction
        failed to find them. Only the engine has the context to tell those apart
        and to set its confidence accordingly.
        """
        return not self.units

    @property
    def location_rate(self) -> float:
        """Fraction of units traced to a source span, in [0, 1]."""
        return self.located_count / len(self.units) if self.units else 0.0

    @staticmethod
    def empty() -> "ExtractionResult[UnitT]":
        """An empty result, for inputs with nothing to extract from."""
        return ExtractionResult(units=())


def as_texts(units: Sequence[Requirement | Claim]) -> tuple[str, ...]:
    """Project units to their texts, for callers that need no structure."""
    return tuple(unit.text for unit in units)
