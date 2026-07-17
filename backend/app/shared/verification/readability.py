"""Readability Review — Readability's stage 3.

Document 2 §5.4 catalogues this as an LLM Verification / Judge instantiation:
*"Readability Review — Clarity, Coherence, Structure (Readability)"*. §7.6 places
it at stage 3, immediately after the deterministic analysis.

**The stage produces two things, and both are frozen.** It renders a verdict on
each of the three named aspects, and it surfaces the issues that stages 4 and 5
then classify and assign severity to — Document 2 §6.3 makes an *Issue* the unit
of the Readability Ledger, and stage 3 is the only stage that can produce one.
So :meth:`ReadabilityReviewJudge.review` returns both, from one call.

One call rather than two is not an optimization. Splitting "what is wrong with
the clarity here" from "rate the clarity" would let the model rate an aspect
*Clear* and then list three clarity issues under it, with nothing to reconcile
them. Asking once keeps the verdict and its reasons answerable to each other.

**The deterministic analysis is shown to the reviewer.** Stage 2 runs first for
this reason (§7.6): "the longest sentence runs 68 words" is a fact the model
cannot miscount, and a reviewer holding it writes a better clarity verdict than
one estimating sentence length by eye. It is context, not instruction — the model
is told plainly that a long sentence is not automatically an unclear one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Sequence

from app.core.logging import bind, get_logger
from app.shared.quality_units import ReadabilityAspect
from app.shared.verification.base import Judgment, LLMJudge
from app.shared.vocabularies import ReadabilityVerdict

__all__ = ["ReadabilityReviewJudge", "ReadabilityReview", "ReviewedIssue"]

logger = get_logger(__name__)


@dataclass(frozen=True)
class ReviewedIssue:
    """One issue the reviewer surfaced, before stages 4–5 label it.

    Attributes:
        aspect: Which aspect it belongs to, e.g. ``"clarity"``.
        text: The problem, stated so a reader can act on it.
        quote: The span of the output it is about, verbatim. Empty when the
            issue is document-level and no single span carries it.
    """

    aspect: str
    text: str
    quote: str = ""


@dataclass(frozen=True)
class ReadabilityReview:
    """What stage 3 returns: the aspect verdicts and the issues behind them.

    Attributes:
        aspects: One :class:`~app.shared.verification.base.Judgment` per aspect,
            in the order the aspects were supplied. An aspect the model skipped
            comes back unjudged — never defaulted.
        issues: The issues the reviewer surfaced, in the order it gave them.
    """

    aspects: tuple[Judgment[ReadabilityAspect, ReadabilityVerdict], ...]
    issues: tuple[ReviewedIssue, ...]

    @property
    def judged_count(self) -> int:
        """How many aspects came back with a verdict."""
        return sum(1 for judgment in self.aspects if judgment.is_judged)


class ReadabilityReviewJudge(LLMJudge[ReadabilityAspect, ReadabilityVerdict]):
    """Stage 3 — reviews Clarity, Coherence, and Structure, and names the issues.

    Note:
        The AI Output is passed as the ``ai_output`` prompt variable rather than
        as evidence items. It is the thing being reviewed, not support for a
        conclusion, and coherence cannot be judged from retrieved fragments of
        it — the reviewer needs the document whole.
    """

    engine = "readability"
    stage = "readability_review"
    version = "v1"
    verdict_enum = ReadabilityVerdict
    id_attr = "aspect_id"
    unit_name = "aspect"
    collection_key = "assessments"

    def _render_unit(self, unit: ReadabilityAspect) -> dict[str, Any]:
        """Render one aspect for the prompt."""
        return {"id": unit.aspect_id, "aspect": unit.name, "assess": unit.question}

    def _prompt_variables(
        self, units_json: str, evidence_block: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Supply the prompt template's variables.

        Args:
            units_json: The rendered aspects.
            evidence_block: Unused — see the class note.
            **kwargs: Must carry ``ai_output`` and ``deterministic_analysis``.
        """
        return {
            "aspects": units_json,
            "ai_output": kwargs["ai_output"],
            "deterministic_analysis": kwargs["deterministic_analysis"],
        }

    def _response_schema(self) -> dict[str, Any]:
        """Extend the shared judge schema with the issues each verdict rests on.

        The base schema's ``id`` / ``verdict`` / ``rationale`` / ``confidence``
        are unchanged, so :meth:`~app.shared.verification.base.LLMJudge.build_judgments`
        reads this response exactly as it reads any other judge's. The ``issues``
        array is additive.
        """
        schema = super()._response_schema()
        item = schema["properties"][self.collection_key]["items"]
        item["properties"]["issues"] = {
            "type": "array",
            "description": (
                "The specific problems behind this verdict. Empty when the "
                "aspect is Clear."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "issue": {
                        "type": "string",
                        "description": "What is wrong, stated so a writer can "
                        "act on it.",
                    },
                    "quote": {
                        "type": "string",
                        "description": "The passage from the output this is "
                        "about, copied verbatim. Empty for a document-level "
                        "issue.",
                    },
                },
                "required": ["issue"],
                "additionalProperties": False,
            },
        }
        return schema

    async def review(
        self,
        aspects: Sequence[ReadabilityAspect],
        ai_output: str,
        deterministic_analysis: str,
    ) -> ReadabilityReview:
        """Review every aspect and surface its issues, in one call.

        Args:
            aspects: The aspects to review — normally
                :data:`~app.shared.quality_units.READABILITY_ASPECTS`.
            ai_output: The content under audit, whole.
            deterministic_analysis: The rendered stage 2 measurements.

        Returns:
            The aspect judgments and the issues behind them.

        Raises:
            VerificationError: The prompt could not be rendered, the provider
                failed, or the response could not be parsed. Readability catches
                this and decides what it means for the dimension.
        """
        if not aspects:
            return ReadabilityReview(aspects=(), issues=())

        units_json = json.dumps(
            [self._render_unit(aspect) for aspect in aspects],
            ensure_ascii=False,
            indent=2,
        )
        records = await self._run_records(
            self._prompt_variables(
                units_json,
                evidence_block="",
                ai_output=ai_output,
                deterministic_analysis=deterministic_analysis,
            ),
            self._response_schema(),
        )

        judgments = self.build_judgments(aspects, records)
        issues = self._issues_from(records)

        logger.info(
            "readability review complete",
            extra=bind(
                stage=self.identifier,
                aspects_judged=sum(1 for j in judgments if j.is_judged),
                issues=len(issues),
            ),
        )
        return ReadabilityReview(aspects=judgments, issues=issues)

    @staticmethod
    def _issues_from(records: Sequence[dict[str, Any]]) -> tuple[ReviewedIssue, ...]:
        """Collect the issues from every aspect's record.

        A malformed issue is dropped rather than defaulted. An issue with no text
        says nothing a writer could act on, and inventing text for it would put
        an assertion in the ledger that the model never made.
        """
        issues: list[ReviewedIssue] = []
        for record in records:
            aspect_id = record.get("id")
            if not isinstance(aspect_id, str) or not aspect_id.strip():
                continue
            for raw in record.get("issues") or []:
                if not isinstance(raw, dict):
                    continue
                text = raw.get("issue")
                if not isinstance(text, str) or not text.strip():
                    continue
                quote = raw.get("quote")
                issues.append(
                    ReviewedIssue(
                        aspect=aspect_id.strip(),
                        text=text.strip(),
                        quote=quote.strip() if isinstance(quote, str) else "",
                    )
                )
        return tuple(issues)
