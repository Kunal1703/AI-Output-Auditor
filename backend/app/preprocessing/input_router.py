"""Input Router — normalizes the ``{source, outputs[]}`` request into contexts.

Its one job is to turn an audit request into one shared
:class:`~app.shared.source_context.SourceContext` and one
:class:`~app.shared.output_context.OutputContext` per output. Text is used as-is;
URLs are extracted via the shared content extractor.

**Routing never evaluates.** It decides which extractor runs and hands the
result on — normalize the container, leave the content alone.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any, Sequence

from app.core.errors import ValidationError
from app.preprocessing.content_extractor import ContentExtractor
from app.shared.output_context import OutputContext
from app.shared.schemas import OutputInput, SourceInput
from app.shared.source_context import SourceContext

__all__ = ["InputRouter", "DefaultInputRouter", "AuditContexts"]


@dataclass(frozen=True)
class AuditContexts:
    """The normalized inputs of one audit: one source, N outputs.

    The single :class:`SourceContext` is shared (read-only) by every
    :class:`OutputContext`, so all source-side derivations are computed once per
    audit and reused across outputs.

    Attributes:
        audit_id: The run these contexts belong to.
        source: The shared per-audit source context.
        outputs: One context per supplied output, in request order.
    """

    audit_id: str
    source: SourceContext
    outputs: tuple[OutputContext, ...]


class InputRouter(abc.ABC):
    """The interface the API uses to normalize an incoming audit request."""

    @abc.abstractmethod
    async def from_audit_request(
        self,
        audit_id: str,
        source: SourceInput,
        outputs: Sequence[OutputInput],
        max_outputs: int | None = None,
    ) -> AuditContexts:
        """Normalize the ``{source, outputs[]}`` audit contract.

        Args:
            audit_id: The run's id, carried on every context.
            source: The mandatory ground-truth source article.
            outputs: One or more outputs to audit against the source.
            max_outputs: Optional cap on the number of outputs
                (``input.max_outputs``). ``None`` disables the check.

        Returns:
            The normalized source and output contexts for the audit.

        Raises:
            ValidationError: No outputs, or the count exceeds ``max_outputs``.
            ExtractionError: A URL source or output could not be extracted.
            UnsupportedInputError: A URL was not an http(s) URL.
        """


class DefaultInputRouter(InputRouter):
    """Routes text/URL inputs and delegates extraction to the content extractor.

    Args:
        extractor: Used for the URL path. The text path needs no extraction —
            the content arrived as content.
    """

    def __init__(self, extractor: ContentExtractor) -> None:
        self._extractor = extractor

    async def from_audit_request(
        self,
        audit_id: str,
        source: SourceInput,
        outputs: Sequence[OutputInput],
        max_outputs: int | None = None,
    ) -> AuditContexts:
        """Normalize ``{source, outputs[]}``. See :meth:`InputRouter.from_audit_request`.

        The source is resolved once (text as-is, URL extracted) into the shared
        :class:`SourceContext`; each output is then resolved and wrapped into an
        :class:`OutputContext` bound to that source.
        """
        if not outputs:
            raise ValidationError("At least one output is required to run an audit.")
        if max_outputs is not None and len(outputs) > max_outputs:
            raise ValidationError(
                f"Too many outputs: {len(outputs)} supplied, at most {max_outputs} "
                "allowed per audit."
            )

        source_text, source_uri, source_meta = await self._resolve(
            source.text, source.url
        )
        source_context = SourceContext.build(
            audit_id=audit_id,
            text=source_text,
            source_uri=source_uri,
            extraction_metadata=source_meta,
        )

        output_contexts: list[OutputContext] = []
        for index, spec in enumerate(outputs):
            output_text, output_uri, output_meta = await self._resolve(
                spec.text, spec.url
            )
            output_contexts.append(
                OutputContext.build(
                    audit_id=audit_id,
                    output_id=spec.output_id or f"out_{index + 1}",
                    text=output_text,
                    source=source_context,
                    producer=spec.producer,
                    output_type=spec.output_type,
                    task_prompt=(spec.task_prompt.strip() if spec.task_prompt else None),
                    source_uri=output_uri,
                    extraction_metadata=output_meta,
                )
            )

        return AuditContexts(
            audit_id=audit_id,
            source=source_context,
            outputs=tuple(output_contexts),
        )

    async def _resolve(
        self, text: str | None, url: str | None
    ) -> tuple[str, str | None, dict[str, Any]]:
        """Resolve a text-or-URL input to ``(text, source_uri, metadata)``.

        The text path needs no extraction; the URL path delegates to the shared
        content extractor. Exactly one of ``text``/``url`` is expected — the
        :class:`SourceInput`/:class:`OutputInput` validators guarantee it, and
        this restates it defensively.
        """
        if text and text.strip():
            stripped = text.strip()
            return (
                stripped,
                None,
                {"extractor": "none", "character_count": len(stripped)},
            )
        if url and url.strip():
            extracted = await self._extractor.from_url(url.strip())
            return (
                extracted.text,
                extracted.source_uri,
                {
                    "extractor": extracted.extractor,
                    "character_count": len(extracted.text),
                    "title": extracted.title,
                    **extracted.metadata,
                },
            )
        raise ValidationError("Each input requires exactly one of 'text' or 'url'.")
