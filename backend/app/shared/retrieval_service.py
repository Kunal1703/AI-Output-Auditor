"""Shared Retrieval Service — evidence acquisition.

Document 2 §5.3 defines three instantiations, one per consuming engine:

* **Accuracy** — Evidence Retrieval: *reference document first*, external
  retrieval optional (§7.2, stage 5).
* **Credibility** — Source Retrieval: fetching cited sources (§7.4, stage 5).
* **Diversity** — Retrieval of Credible Perspectives, on the Applicable=Yes
  branch only (§7.8, stage 5).

**Reference-first is frozen behavior, not an optimization.** Accuracy verifies
against the supplied ground truth before it considers anything external, and
external retrieval stays opt-in per request (``options.external_retrieval``).
A claim marked *Unverifiable* because the reference did not cover it is a
different, honest outcome from one silently "verified" against a search result
the user never sanctioned.

**In-process by design.** Document 4 §2 rules out an external vector store at
demo scale: chunk, embed, cosine, done. The embeddings come from the Shared
Embedding Service, so chunk vectors land in the same application-scoped cache
every other consumer uses — re-auditing against the same reference document
costs one encode, not two.
"""

from __future__ import annotations

import abc
import asyncio
from dataclasses import dataclass, field
from typing import Any, Sequence

import httpx

from app.core.config import Settings
from app.core.logging import bind, get_logger
from app.shared.embedding_service import EmbeddingService, relatedness

__all__ = [
    "Chunk",
    "RetrievedPassage",
    "FetchedDocument",
    "RetrievalService",
    "DefaultRetrievalService",
]

logger = get_logger(__name__)


@dataclass(frozen=True)
class Chunk:
    """One indexed span of a reference document.

    Attributes:
        chunk_id: Run-unique id.
        text: The chunk's text.
        start: Character offset of the chunk's start in the source document.
            Retained so evidence can point at a real location in the original
            rather than at a detached snippet — the Evidence Viewer needs to
            highlight the span in context (Document 4, §8).
        end: Character offset of the chunk's end.
        source_ref: Origin identifier — a URL, DOI, or reference-document id.
    """

    chunk_id: str
    text: str
    start: int
    end: int
    source_ref: str | None = None


@dataclass(frozen=True)
class RetrievedPassage:
    """A chunk returned by a similarity search, with its score.

    Attributes:
        chunk: The matched chunk.
        score: Similarity to the query, in [0, 1].
    """

    chunk: Chunk
    score: float


@dataclass(frozen=True)
class FetchedDocument:
    """Clean text extracted from a fetched URL or source.

    Attributes:
        url: The URL fetched.
        title: Extracted document title, when available.
        text: Extracted main content, cleaned of navigation and boilerplate.
        status_code: HTTP status observed.
        reachable: Whether the fetch succeeded. Credibility depends on this
            distinction: a citation pointing at an unreachable URL is a
            different finding from one pointing at a page that fails to support
            the claim (Document 2, §7.4).
        error: Why the fetch failed, when it did.
        metadata: Extractor provenance — which extractor ran, content length.
    """

    url: str
    title: str | None
    text: str
    status_code: int | None = None
    reachable: bool = True
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_content(self) -> bool:
        """Whether usable text was recovered.

        Distinct from :attr:`reachable`: a paywall or a JS-only page returns 200
        with nothing to read. Credibility must not treat "fetched but empty" as
        "source supports the claim".
        """
        return bool(self.text and self.text.strip())


class RetrievalService(abc.ABC):
    """The interface Accuracy, Credibility, and Diversity depend on for evidence."""

    @abc.abstractmethod
    def chunk(self, text: str, source_ref: str | None = None) -> list[Chunk]:
        """Split a document into overlapping chunks.

        Overlap matters: a claim's support often straddles a naive boundary, and
        a missed passage becomes a false *Unverifiable* verdict. Size and
        overlap come from ``retrieval.chunk_size`` / ``retrieval.chunk_overlap``.

        Args:
            text: The document to chunk.
            source_ref: Origin identifier propagated onto every chunk.

        Returns:
            Chunks in document order.
        """

    @abc.abstractmethod
    async def search(
        self, query: str, chunks: Sequence[Chunk], top_k: int | None = None
    ) -> list[RetrievedPassage]:
        """Return the chunks most similar to ``query``.

        Args:
            query: The claim or key point to find support for.
            chunks: The corpus to search.
            top_k: Result ceiling; defaults to ``retrieval.top_k``.

        Returns:
            Passages ordered by descending score.
        """

    @abc.abstractmethod
    async def fetch(self, url: str) -> FetchedDocument:
        """Fetch a URL and extract its main content.

        Must not raise on an unreachable URL. It returns a
        :class:`FetchedDocument` with ``reachable=False``, because "this
        citation points nowhere" is itself an audit finding that Credibility
        needs to record, not an error that should abort the run.

        Args:
            url: The URL to fetch.

        Returns:
            The fetched document, reachable or not.
        """

    async def aclose(self) -> None:
        """Release HTTP resources on shutdown."""
        return None


class DefaultRetrievalService(RetrievalService):
    """In-process retrieval over chunk embeddings, plus web fetching.

    Args:
        settings: Supplies chunk size, overlap, top_k, and fetch timeouts.
        embedding_service: Used to embed chunks and queries for similarity
            search. Injected rather than constructed so retrieval and the
            engines share one model instance and one cache.
        client: Inject an HTTP client to test without network access.
    """

    def __init__(
        self,
        settings: Settings,
        embedding_service: EmbeddingService,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._embeddings = embedding_service
        self._counter = 0
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.retrieval.fetch_timeout_seconds),
            follow_redirects=True,
            headers={"User-Agent": settings.retrieval.user_agent},
        )
        self._owns_client = client is None

    def chunk(self, text: str, source_ref: str | None = None) -> list[Chunk]:
        """Split a document into overlapping chunks. See :meth:`RetrievalService.chunk`.

        Chunks are cut on whitespace rather than mid-word. A boundary that
        splits "1889" into "18" and "89" would make the passage unreadable to
        the judge that has to verify a claim against it.
        """
        if not text or not text.strip():
            return []

        size = self._settings.retrieval.chunk_size
        overlap = self._settings.retrieval.chunk_overlap
        stride = max(1, size - overlap)

        chunks: list[Chunk] = []
        start = 0
        length = len(text)

        while start < length:
            end = min(start + size, length)

            # Prefer a whitespace boundary, but only if one exists reasonably
            # near the target — otherwise a long unbroken token would drag the
            # boundary back to the chunk start and stall the loop.
            if end < length:
                window = text.rfind(" ", start + stride // 2, end)
                if window > start:
                    end = window

            body = text[start:end]
            if body.strip():
                self._counter += 1
                leading = len(body) - len(body.lstrip())
                trailing = len(body) - len(body.rstrip())
                chunks.append(
                    Chunk(
                        chunk_id=f"chk_{self._counter}",
                        text=body.strip(),
                        start=start + leading,
                        end=end - trailing,
                        source_ref=source_ref,
                    )
                )

            if end >= length:
                break
            start = max(start + stride, end - overlap)

        return chunks

    async def search(
        self, query: str, chunks: Sequence[Chunk], top_k: int | None = None
    ) -> list[RetrievedPassage]:
        """Return the chunks most similar to ``query``.

        One batched embed call for the query and every chunk, so a corpus is
        encoded once and served from the shared cache on every later query
        against it — which is what makes verifying twenty claims against one
        reference document affordable.

        Scores come from :func:`~app.shared.embedding_service.relatedness` —
        raw cosine clamped at zero, **not** rescaled from [-1, 1]. Rescaling
        would compress every score into [0.5, 0.9] and quietly disable the
        configured similarity threshold; see that function's docstring.
        """
        if not chunks or not query.strip():
            return []

        limit = top_k or self._settings.retrieval.top_k
        vectors = await self._embeddings.embed([query, *(c.text for c in chunks)])
        query_vector, chunk_vectors = vectors[0], vectors[1:]

        scored = [
            RetrievedPassage(chunk=chunk, score=relatedness(query_vector, vector))
            for chunk, vector in zip(chunks, chunk_vectors)
        ]
        scored.sort(key=lambda passage: passage.score, reverse=True)
        return scored[:limit]

    async def fetch(self, url: str) -> FetchedDocument:
        """Fetch a URL and extract its main content.

        Never raises. Every failure mode — DNS, timeout, 404, unparseable body —
        comes back as ``reachable=False`` with a reason, because for Credibility
        an unreachable citation is *the finding*, not an error. Raising here
        would turn "this source does not exist" into "the audit crashed", which
        loses the single most important thing the engine learned.

        Bounded retries with backoff for transient errors only (Document 4,
        §12). A 404 is not retried: it is an answer.
        """
        attempts = self._settings.retrieval.max_retries + 1
        last_error = "unknown error"

        for attempt in range(attempts):
            try:
                response = await self._client.get(url)
            except httpx.TimeoutException:
                last_error = "request timed out"
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code >= 400:
                    # A definite answer from the server. Retrying a 404 would
                    # only delay recording the finding.
                    return FetchedDocument(
                        url=url,
                        title=None,
                        text="",
                        status_code=response.status_code,
                        reachable=False,
                        error=f"HTTP {response.status_code}",
                    )
                title, body, extractor = await asyncio.to_thread(
                    _extract_html, response.text, url
                )
                return FetchedDocument(
                    url=url,
                    title=title,
                    text=body,
                    status_code=response.status_code,
                    reachable=True,
                    metadata={"extractor": extractor, "characters": len(body)},
                )

            if attempt < attempts - 1:
                await asyncio.sleep(1.5 * (2**attempt))

        logger.info("source unreachable", extra=bind(url=url, error=last_error))
        return FetchedDocument(
            url=url, title=None, text="", reachable=False, error=last_error
        )

    async def aclose(self) -> None:
        """Close the HTTP client, if this service created it."""
        if self._owns_client:
            await self._client.aclose()


def _extract_html(html: str, url: str) -> tuple[str | None, str, str]:
    """Extract title and main content from HTML.

    Trafilatura primary, BeautifulSoup fallback (Document 4, §2). Runs in a
    worker thread — parsing a large page is blocking CPU work.

    Returns:
        ``(title, text, extractor_name)``. An empty text is a legitimate result
        for a paywall or a JS-only page; the caller distinguishes "fetched but
        empty" from "unreachable".
    """
    try:
        import trafilatura  # noqa: PLC0415

        extracted = trafilatura.extract(
            html, include_comments=False, include_tables=True, url=url
        )
        if extracted and extracted.strip():
            title = None
            try:
                meta = trafilatura.extract_metadata(html)
                title = getattr(meta, "title", None) if meta else None
            except Exception:
                pass
            return title, extracted.strip(), "trafilatura"
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("trafilatura failed; falling back", extra=bind(error=str(exc)))

    try:
        from bs4 import BeautifulSoup  # noqa: PLC0415

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        title = soup.title.string.strip() if soup.title and soup.title.string else None
        text = " ".join(soup.get_text(separator=" ").split())
        return title, text, "beautifulsoup"
    except ImportError:
        return None, "", "none"
    except Exception as exc:
        logger.debug("html extraction failed", extra=bind(error=str(exc)))
        return None, "", "none"
