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

**Extraction never evaluates** (Document 4, §5). It decides where the article
ends and the navigation begins; it forms no opinion about what the article says.
"""

from __future__ import annotations

import abc
import asyncio
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import ExtractionError, UnsupportedInputError
from app.core.logging import bind, get_logger

__all__ = ["ExtractedContent", "ContentExtractor", "DefaultContentExtractor"]

logger = get_logger(__name__)

#: Below this many characters, an "extraction" is almost certainly a cookie
#: banner, a paywall stub, or a JS shell rather than an article. Auditing it
#: would produce a confident report about the wrong text, so it is an error.
MIN_EXTRACTED_CHARS = 120

#: Upload ceiling. A 200MB PDF would be extracted into memory and then handed to
#: eight engines; the bound belongs here rather than at the point of collapse.
MAX_FILE_BYTES = 10 * 1024 * 1024

#: Extensions we can turn into clean text, mapped to their handler kind.
_TEXT_SUFFIXES = frozenset({".txt", ".md", ".markdown", ".rst", ".text"})
_PDF_SUFFIXES = frozenset({".pdf"})
_HTML_SUFFIXES = frozenset({".html", ".htm"})

_WHITESPACE_RUNS = re.compile(r"\n{3,}")

#: YAML front matter: a ``---`` fence on the first line, its content, and a
#: closing ``---`` fence, all before the document body. Anchored to the start so
#: a ``---`` horizontal rule mid-document is never mistaken for it.
_FRONT_MATTER = re.compile(r"^﻿?---[ \t]*\n.*?\n---[ \t]*(?:\n|$)", re.DOTALL)


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
    """Trafilatura-primary extractor with a BeautifulSoup fallback.

    Args:
        settings: Supplies fetch timeouts and the user agent.
        client: Inject an HTTP client to test without network access.

    Note:
        The heavy libraries are imported lazily inside the methods that use
        them, so importing this module — which ``app.app`` does at startup —
        never pulls in lxml or pypdf. The backend boots without them installed
        and fails only if a URL or file is actually submitted.
    """

    def __init__(
        self, settings: Settings, client: httpx.AsyncClient | None = None
    ) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.retrieval.fetch_timeout_seconds),
            follow_redirects=True,
            headers={"User-Agent": settings.retrieval.user_agent},
        )
        self._owns_client = client is None

    # -- URL ---------------------------------------------------------------- #

    async def from_url(self, url: str) -> ExtractedContent:
        """Fetch and extract a URL. See :meth:`ContentExtractor.from_url`.

        Raises rather than degrading, and the distinction from Credibility's
        ``RetrievalService.fetch`` is deliberate. There, an unreachable URL *is*
        the finding. Here, the URL **is the content under audit** — if it cannot
        be read there is nothing to audit, and returning an empty string would
        produce eight confident measurements of nothing.
        """
        if not re.match(r"^https?://", url.strip(), re.IGNORECASE):
            raise UnsupportedInputError(
                f"{url!r} is not an http(s) URL. Submit a full URL including "
                "the scheme, e.g. https://example.org/article."
            )

        try:
            response = await self._client.get(url)
        except httpx.TimeoutException as exc:
            raise ExtractionError(
                f"{url} did not respond within "
                f"{self._settings.retrieval.fetch_timeout_seconds}s."
            ) from exc
        except httpx.HTTPError as exc:
            raise ExtractionError(
                f"{url} could not be fetched: {type(exc).__name__}."
            ) from exc

        if response.status_code >= 400:
            raise ExtractionError(f"{url} returned HTTP {response.status_code}.")

        title, text, extractor = await asyncio.to_thread(
            _extract_html, response.text, url
        )
        text = _tidy(text)

        if len(text) < MIN_EXTRACTED_CHARS:
            # A paywall, a consent wall, or a JS-only shell. All three return
            # 200 with no article, and auditing the leftovers would be worse
            # than refusing.
            raise ExtractionError(
                f"{url} yielded only {len(text)} characters of text. The page "
                "may be paywalled, consent-gated, or rendered client-side. "
                "Paste the text directly instead."
            )

        logger.info(
            "url extracted",
            extra=bind(
                url=url,
                extractor=extractor,
                characters=len(text),
                status_code=response.status_code,
            ),
        )
        return ExtractedContent(
            text=text,
            title=title,
            source_uri=url,
            extractor=extractor,
            metadata={
                "characters": len(text),
                "status_code": response.status_code,
                "content_type": response.headers.get("content-type"),
            },
        )

    # -- File --------------------------------------------------------------- #

    async def from_file(
        self, filename: str, data: bytes, content_type: str | None = None
    ) -> ExtractedContent:
        """Extract text from an uploaded file. See :meth:`ContentExtractor.from_file`.

        The **filename suffix decides**, not the declared MIME type. Browsers
        send ``application/octet-stream`` for anything they do not recognize and
        will happily label a ``.md`` file ``text/markdown`` or nothing at all;
        the suffix is what the user actually chose.
        """
        if not data:
            raise ExtractionError(f"{filename} is empty.")
        if len(data) > MAX_FILE_BYTES:
            raise UnsupportedInputError(
                f"{filename} is {len(data) / 1_048_576:.1f}MB; the limit is "
                f"{MAX_FILE_BYTES // 1_048_576}MB."
            )

        suffix = PurePosixPath(filename).suffix.lower()
        front_matter_stripped = False

        if suffix in _PDF_SUFFIXES:
            text, extractor = await asyncio.to_thread(_extract_pdf, data, filename)
            title = None
        elif suffix in _HTML_SUFFIXES:
            title, text, extractor = await asyncio.to_thread(
                _extract_html, data.decode("utf-8", errors="replace"), filename
            )
        elif suffix in _TEXT_SUFFIXES or (
            not suffix and (content_type or "").startswith("text/")
        ):
            text, extractor = _decode_text(data), "plain"
            text, front_matter_stripped = _strip_front_matter(text)
            title = _first_markdown_heading(text)
        else:
            raise UnsupportedInputError(
                f"{filename} has an unsupported format ({suffix or 'no suffix'}). "
                f"Supported: {', '.join(sorted(_TEXT_SUFFIXES | _PDF_SUFFIXES | _HTML_SUFFIXES))}."
            )

        text = _tidy(text)
        if len(text) < MIN_EXTRACTED_CHARS:
            raise ExtractionError(
                f"{filename} yielded only {len(text)} characters of text. A "
                "scanned PDF needs OCR before it can be audited."
            )

        logger.info(
            "file extracted",
            extra=bind(
                file=filename,
                extractor=extractor,
                characters=len(text),
                byte_count=len(data),
            ),
        )
        return ExtractedContent(
            text=text,
            title=title,
            source_uri=filename,
            extractor=extractor,
            metadata={
                "characters": len(text),
                "bytes": len(data),
                "content_type": content_type,
                "front_matter_stripped": front_matter_stripped,
            },
        )

    async def aclose(self) -> None:
        """Close the HTTP client, if this extractor created it."""
        if self._owns_client:
            await self._client.aclose()


# --------------------------------------------------------------------------- #
# Extractors. Blocking and CPU-bound — always called through asyncio.to_thread.
# --------------------------------------------------------------------------- #


def _tidy(text: str) -> str:
    """Normalize an extraction's whitespace without altering its content.

    Collapses runs of three-plus newlines to a paragraph break and strips the
    ends. Deliberately conservative: paragraph structure is what
    ``TextSegmenter`` reads and what Readability judges, so flattening it would
    change a measurement rather than clean an artifact.
    """
    return _WHITESPACE_RUNS.sub("\n\n", text.replace("\r\n", "\n")).strip()


def _decode_text(data: bytes) -> str:
    """Decode uploaded bytes as text, tolerating a BOM and stray bytes."""
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _strip_front_matter(text: str) -> tuple[str, bool]:
    """Remove a leading YAML front-matter block from a text/markdown document.

    Markdown from static-site generators (and this project's own corpus) opens
    with a ``---`` … ``---`` metadata block. It is *metadata about* the document,
    not the document — auditing it means Readability judging ``tier: good`` and
    Relevance measuring against ``id:`` lines, a confident report about the wrong
    text. Stripping it is container normalization, not content editing (the
    body is untouched); the router's rule is "normalize the container, leave the
    content alone", and front matter is container.

    Only a block that opens the document is removed, so a ``---`` horizontal rule
    between paragraphs is never touched.

    Returns:
        ``(body, stripped)`` — the document without its front matter, and whether
        any was present.
    """
    match = _FRONT_MATTER.match(text)
    if not match:
        return text, False
    return text[match.end() :].lstrip("\n"), True


def _first_markdown_heading(text: str) -> str | None:
    """Return the first ATX heading, when the document opens with one."""
    match = re.search(r"^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def _extract_html(html: str, source: str) -> tuple[str | None, str, str]:
    """Extract title and main content from HTML.

    Trafilatura primary, BeautifulSoup fallback — Document 4 §2's stack. This
    mirrors ``retrieval_service._extract_html`` in shape but not in purpose:
    that one recovers a *cited source* for grounding, this one recovers the
    *content under audit*. They are allowed to diverge, and the audited path
    tightens the screws that matter here — tables kept, comments dropped.

    Returns:
        ``(title, text, extractor_name)``. Text may be empty; the caller decides
        whether that is fatal.
    """
    try:
        import trafilatura  # noqa: PLC0415

        extracted = trafilatura.extract(
            html,
            include_comments=False,   # reader comments are not the article
            include_tables=True,      # tables often carry the actual findings
            favor_precision=True,     # a nav menu in the text is worse than a lost aside
            url=source if source.startswith("http") else None,
        )
        if extracted and extracted.strip():
            title = None
            try:
                meta = trafilatura.extract_metadata(html)
                title = getattr(meta, "title", None) if meta else None
            except Exception:  # metadata is a nicety; never fail extraction for it
                pass
            return title, extracted.strip(), "trafilatura"
        logger.debug("trafilatura found no content; falling back", extra=bind(source=source))
    except ImportError:
        logger.warning("trafilatura not installed; falling back to BeautifulSoup")
    except Exception as exc:
        logger.warning(
            "trafilatura failed; falling back",
            extra=bind(source=source, error=type(exc).__name__),
        )

    try:
        from bs4 import BeautifulSoup  # noqa: PLC0415

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(
            ["script", "style", "nav", "header", "footer", "aside", "form", "noscript"]
        ):
            tag.decompose()
        title = soup.title.string.strip() if soup.title and soup.title.string else None
        # Paragraph-aware rather than one flat blob: TextSegmenter reads
        # paragraph breaks, and a wall of text is a different document.
        blocks = [
            block.get_text(separator=" ", strip=True)
            for block in soup.find_all(["p", "h1", "h2", "h3", "h4", "li", "blockquote"])
        ]
        text = "\n\n".join(b for b in blocks if b)
        if not text.strip():
            text = soup.get_text(separator="\n", strip=True)
        return title, text, "beautifulsoup"
    except ImportError as exc:
        raise ExtractionError(
            "No HTML extractor is installed. Install trafilatura and "
            "beautifulsoup4 (see backend/requirements-m2.txt)."
        ) from exc
    except Exception as exc:
        raise ExtractionError(
            f"HTML from {source} could not be parsed: {type(exc).__name__}."
        ) from exc


def _extract_pdf(data: bytes, filename: str) -> tuple[str, str]:
    """Extract text from a PDF with pypdf.

    Page text is joined with paragraph breaks rather than newlines: a page
    boundary is not a sentence boundary, and running the pages together would
    have the segmenter merge the last sentence of one page with the first of the
    next.

    Returns:
        ``(text, extractor_name)``.
    """
    try:
        from pypdf import PdfReader  # noqa: PLC0415
    except ImportError as exc:
        raise ExtractionError(
            "pypdf is not installed, so PDF upload is unavailable. Install it "
            "with `pip install -r requirements-m2.txt`."
        ) from exc

    import io  # noqa: PLC0415

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")  # many PDFs are "encrypted" with an empty password
            except Exception as exc:
                raise ExtractionError(
                    f"{filename} is password-protected and cannot be read."
                ) from exc
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(
            f"{filename} could not be read as a PDF: {type(exc).__name__}."
        ) from exc

    return "\n\n".join(p for p in pages if p), "pypdf"
