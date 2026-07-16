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

Milestone 1 ships the interface and a complete text path. URL and file routing
land in Milestone 2 with the extractors they depend on.
"""

from __future__ import annotations

import abc
import uuid
from typing import Any

from app.preprocessing.content_extractor import ContentExtractor
from app.shared.context import SharedContext
from app.shared.schemas import InputType, PreprocessedContent

__all__ = ["InputRouter", "DefaultInputRouter"]


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
        """Fetch, extract, and normalize a URL.

        Raises:
            NotImplementedError: Until Milestone 2, with the content extractor.
        """
        raise NotImplementedError(
            "URL routing is implemented in Milestone 2, with the content "
            "extractor it depends on."
        )

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
        """Extract and normalize an uploaded file.

        Raises:
            NotImplementedError: Until Milestone 2, with the content extractor.
        """
        raise NotImplementedError(
            "File routing is implemented in Milestone 2, with the content "
            "extractor it depends on."
        )
