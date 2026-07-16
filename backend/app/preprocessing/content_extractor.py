"""Content Extraction — clean text out of URLs and files.

Document 4 §3: turns raw URL/file input into clean article text. Document 4 §2
names ``trafilatura`` as the primary extractor with ``readability-lxml`` /
``BeautifulSoup`` as fallbacks, and supports txt/md/pdf uploads.

**Why extraction quality is an audit-correctness concern, not a convenience.**
Every engine measures the text this module produces. Leave a navigation menu or
a cookie banner in it and Readability reports poor structure that the author
never wrote; drop the final section and Coverage reports a critical omission that
does not exist. A bad extraction does not produce a bad-looking report — it
produces a *confident* report about the wrong text. That is why extraction
failure raises rather than returning whatever it managed to scrape.

Milestone 1 ships the interface. The extractors land in Milestone 2 with the
``/audit/url`` and ``/audit/file`` paths that need them.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings

__all__ = ["ExtractedContent", "ContentExtractor", "DefaultContentExtractor"]


@dataclass(frozen=True)
class ExtractedContent:
    """Clean text plus the provenance of how it was obtained.

    Attributes:
        text: The extracted main content.
        title: Document title, when available.
        source_uri: The URL or filename it came from.
        extractor: Which extractor produced it, e.g. ``"trafilatura"``. Recorded
            because extraction quality varies by extractor, and a surprising
            report is much easier to diagnose when you know which one ran.
        metadata: Detected language, character counts, and other provenance.
    """

    text: str
    title: str | None
    source_uri: str
    extractor: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ContentExtractor(abc.ABC):
    """The interface Preprocessing uses to obtain clean text."""

    @abc.abstractmethod
    async def from_url(self, url: str) -> ExtractedContent:
        """Fetch a URL and extract its main content.

        Args:
            url: The URL to fetch.

        Returns:
            The extracted content.

        Raises:
            ExtractionError: The page could not be fetched, or no meaningful
                content could be recovered. Raising is correct here — unlike
                Credibility's source fetching, where an unreachable URL is a
                *finding*, a failure to extract the content under audit means
                there is nothing to audit at all.
        """

    @abc.abstractmethod
    async def from_file(
        self, filename: str, data: bytes, content_type: str | None = None
    ) -> ExtractedContent:
        """Extract text from an uploaded file (txt/md/pdf).

        Args:
            filename: Original filename, used to infer the format.
            data: Raw file bytes.
            content_type: Declared MIME type, when the client sent one.

        Returns:
            The extracted content.

        Raises:
            UnsupportedInputError: The file format is not supported.
            ExtractionError: The file was corrupt or yielded no text.
        """

    async def aclose(self) -> None:
        """Release HTTP resources on shutdown."""
        return None


class DefaultContentExtractor(ContentExtractor):
    """Trafilatura-primary extractor with readability/BeautifulSoup fallback.

    Args:
        settings: Supplies fetch timeouts and the user agent.

    Note:
        Milestone 1 provides the wiring. The extractors land in Milestone 2 with
        the ``/audit/url`` and ``/audit/file`` paths.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def from_url(self, url: str) -> ExtractedContent:
        """Fetch and extract a URL.

        Raises:
            NotImplementedError: Until Milestone 2.
        """
        raise NotImplementedError(
            "URL extraction is implemented in Milestone 2, with the "
            "POST /audit/url endpoint (Document 4, §2 and §7)."
        )

    async def from_file(
        self, filename: str, data: bytes, content_type: str | None = None
    ) -> ExtractedContent:
        """Extract text from an uploaded file.

        Raises:
            NotImplementedError: Until Milestone 2.
        """
        raise NotImplementedError(
            "File extraction is implemented in Milestone 2, with the "
            "POST /audit/file endpoint (Document 4, §7)."
        )
