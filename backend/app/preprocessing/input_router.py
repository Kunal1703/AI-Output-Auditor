"""Input Router — normalizes text / URL / file into a ``SharedContext``.

Document 4 §5 states the module's one job and its one prohibition:

    **Responsibility.** Normalize text/url/file input into the engines' expected
    input (and extract clean content from URLs/files).
    **Must NOT do.** Evaluate anything.

That boundary is worth guarding. It is tempting to let preprocessing "help" —
strip a suspicious-looking passage, normalize away odd formatting. Don't. Every
such edit silently changes what the engines measure, and the audit would then
describe a text the user never submitted. Normalize the container; leave the
content alone.

**Output.** A :class:`SharedContext` wrapping the ``PreprocessedContent``. The
content is the Engine Input Contract (Document 2, §6.1); the context adds the
run id and the shared derivation store that lets engines reuse expensive work
instead of each recomputing it.

All three paths are complete: text needs no extraction, URL and file delegate
to the content extractor. **Routing never evaluates** (Document 4, §5) — it
decides which extractor runs and hands the result on.
"""

from __future__ import annotations

import abc
import uuid
from dataclasses import dataclass
from typing import Any, Sequence

from app.core.errors import ValidationError
from app.preprocessing.content_extractor import ContentExtractor
from app.shared.context import SharedContext
from app.shared.output_context import OutputContext
from app.shared.schemas import InputType, OutputInput, PreprocessedContent, SourceInput
from app.shared.source_context import SourceContext

__all__ = ["InputRouter", "DefaultInputRouter", "AuditContexts"]


@dataclass(frozen=True)
class AuditContexts:
    """The normalized inputs of one audit: one source, N outputs.

    Produced by :meth:`InputRouter.from_audit_request`. The single
    :class:`~app.shared.source_context.SourceContext` is shared (read-only) by
    every :class:`~app.shared.output_context.OutputContext`, so all source-side
    derivations are computed once per audit and reused across outputs
    (Software Architecture D3).

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
    async def from_text(
        self,
        audit_id: str,
        text: str,
        prompt: str | None = None,
        reference_source: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> SharedContext:
        """Normalize raw text.

        Args:
            audit_id: The run's id, carried on the context for log correlation.
            text: The AI-generated output under audit.
            prompt: The original instruction. Used by Relevance, Engagement,
                and Diversity.
            reference_source: Ground truth. Optional for Accuracy; Coverage
                requires it in order to score.
            options: Request flags, e.g. ``external_retrieval``.

        Returns:
            The context handed to the orchestrator.
        """

    @abc.abstractmethod
    async def from_url(
        self,
        audit_id: str,
        url: str,
        prompt: str | None = None,
        reference_source: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> SharedContext:
        """Fetch a URL, extract it, and normalize the result.

        Raises:
            ExtractionError: The page could not be fetched or extracted.
        """

    @abc.abstractmethod
    async def from_file(
        self,
        audit_id: str,
        filename: str,
        data: bytes,
        content_type: str | None = None,
        prompt: str | None = None,
        reference_source: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> SharedContext:
        """Extract an uploaded file and normalize the result.

        Raises:
            UnsupportedInputError: The format is not supported.
            ExtractionError: The file yielded no usable text.
        """

    @abc.abstractmethod
    async def from_audit_request(
        self,
        audit_id: str,
        source: SourceInput,
        outputs: Sequence[OutputInput],
        max_outputs: int | None = None,
    ) -> AuditContexts:
        """Normalize the new ``{source, outputs[]}`` audit contract.

        Builds one shared :class:`~app.shared.source_context.SourceContext` from
        the mandatory source article and one
        :class:`~app.shared.output_context.OutputContext` per output, each
        audited independently against the same source
        (AI Output Auditor, Software Architecture §6).

        Args:
            audit_id: The run's id, carried on every context.
            source: The mandatory ground-truth source article.
            outputs: One or more outputs to audit against the source.
            max_outputs: Optional cap on the number of outputs
                (``input.max_outputs``). ``None`` disables the check.

        Returns:
            The normalized source and output contexts for the audit.

        Raises:
            ValidationError: No outputs were supplied, or the count exceeds
                ``max_outputs``.
            ExtractionError: A URL source or output could not be extracted.
            UnsupportedInputError: A URL was not an http(s) URL.
        """


class DefaultInputRouter(InputRouter):
    """Routes by input type and delegates extraction to the content extractor.

    Args:
        extractor: Used for the URL and file paths. The text path needs no
            extraction — the content arrived as content.
    """

    def __init__(self, extractor: ContentExtractor) -> None:
        self._extractor = extractor

    @staticmethod
    def _content_id() -> str:
        return f"con_{uuid.uuid4().hex[:16]}"

    async def from_text(
        self,
        audit_id: str,
        text: str,
        prompt: str | None = None,
        reference_source: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> SharedContext:
        """Normalize raw text. See :meth:`InputRouter.from_text`.

        Complete as-is. The text path needs no extraction, and normalization is
        limited to trimming surrounding whitespace — the content reaches the
        engines exactly as the user submitted it.
        """
        content = PreprocessedContent(
            content_id=self._content_id(),
            ai_output=text.strip(),
            prompt=prompt.strip() if prompt else None,
            reference_source=reference_source.strip() if reference_source else None,
            input_type=InputType.TEXT,
            source_uri=None,
            options=dict(options or {}),
            extraction_metadata={
                "extractor": "none",
                "character_count": len(text.strip()),
            },
        )
        return SharedContext.build(audit_id, content)

    async def from_url(
        self,
        audit_id: str,
        url: str,
        prompt: str | None = None,
        reference_source: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> SharedContext:
        """Fetch, extract, and normalize a URL. See :meth:`InputRouter.from_url`.

        The extractor's provenance is carried into ``extraction_metadata`` and
        surfaces through ``context.metadata.extra``. That matters when a report
        is surprising: "Readability found no headings" reads very differently
        once you know BeautifulSoup produced the text after trafilatura
        declined, and the only way to know is to record it here.

        Raises:
            ExtractionError: The page could not be fetched or yielded no usable
                text.
            UnsupportedInputError: The string is not an http(s) URL.
        """
        extracted = await self._extractor.from_url(url)
        content = PreprocessedContent(
            content_id=self._content_id(),
            ai_output=extracted.text,
            prompt=prompt.strip() if prompt else None,
            reference_source=reference_source.strip() if reference_source else None,
            input_type=InputType.URL,
            source_uri=extracted.source_uri,
            options=dict(options or {}),
            extraction_metadata={
                "extractor": extracted.extractor,
                "character_count": len(extracted.text),
                "title": extracted.title,
                **extracted.metadata,
            },
        )
        return SharedContext.build(audit_id, content)

    async def from_file(
        self,
        audit_id: str,
        filename: str,
        data: bytes,
        content_type: str | None = None,
        prompt: str | None = None,
        reference_source: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> SharedContext:
        """Extract and normalize an uploaded file. See :meth:`InputRouter.from_file`.

        Raises:
            UnsupportedInputError: The format is not supported, or the upload
                exceeds the size limit.
            ExtractionError: The file was corrupt, empty, or yielded no text —
                a scanned PDF with no text layer being the common case.
        """
        extracted = await self._extractor.from_file(filename, data, content_type)
        content = PreprocessedContent(
            content_id=self._content_id(),
            ai_output=extracted.text,
            prompt=prompt.strip() if prompt else None,
            reference_source=reference_source.strip() if reference_source else None,
            input_type=InputType.FILE,
            source_uri=extracted.source_uri,
            options=dict(options or {}),
            extraction_metadata={
                "extractor": extracted.extractor,
                "character_count": len(extracted.text),
                "title": extracted.title,
                **extracted.metadata,
            },
        )
        return SharedContext.build(audit_id, content)

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
        :class:`OutputContext` bound to that source. Text and URL inputs are
        supported here; multipart file uploads arrive via the MB4 route.
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
                    task_prompt=(
                        spec.task_prompt.strip() if spec.task_prompt else None
                    ),
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

        The text path needs no extraction (content arrived as content); the URL
        path delegates to the shared content extractor. Exactly one of ``text``
        or ``url`` is expected — the :class:`SourceInput`/:class:`OutputInput`
        validators guarantee it, and this restates it defensively.
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
