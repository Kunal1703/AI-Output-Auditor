"""Shared Embedding Service — sentence embeddings, similarity, and a shared cache.

Document 2 §5.5 ("Embedding Analysis") names exactly two consumers:

* **Relevance** — Sentence Embedding-based Scope Drift Detection (§7.1, stage 6).
* **Novelty** — Sentence Embedding Generation and Semantic & Literal Duplicate
  Detection (§7.5, stages 3–4).

No other engine may embed text, and neither of those engines may import a model
directly (Document 4, §4).

**The cache is the reason those two engines can coexist cheaply.** Document 4
§12 lists caching embeddings as a reliability measure, and the overlap here is
real: Relevance and Novelty both embed sentences of the same AI Output, and they
run in different waves, so without a cache the same text is encoded twice per
audit. The cache is **application-scoped** (built once in ``app.app``), so it
also spans runs — re-auditing the same content, or auditing two texts that share
boilerplate, costs one encode.

The cache sits *inside* this service rather than in the engines. An engine asks
for embeddings and gets them; whether they were computed or recalled is not its
concern, and pushing that decision outward would mean two engines each
implementing it slightly differently.

Milestone 1 ships the interface, the cache, and the pure-math helpers.
:meth:`LocalEmbeddingService._embed_uncached` — the single model call — lands in
Milestone 2 with the two engines that consume it.
"""

from __future__ import annotations

import abc
import asyncio
import hashlib
import math
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Sequence

from app.core.config import Settings
from app.core.errors import ProviderError
from app.core.logging import bind, get_logger

__all__ = [
    "EmbeddingService",
    "LocalEmbeddingService",
    "EmbeddingCache",
    "InMemoryEmbeddingCache",
    "NullEmbeddingCache",
    "CacheStats",
    "cosine_similarity",
    "relatedness",
]

logger = get_logger(__name__)

#: A single embedding vector.
Vector = Sequence[float]


def relatedness(left: Vector, right: Vector) -> float:
    """Return the semantic relatedness of two vectors, in [0, 1].

    Raw cosine with negatives clamped to zero — **not** rescaled from [-1, 1].
    The distinction is not cosmetic; it decides whether a threshold works at
    all.

    Rescaling with ``(cos + 1) / 2`` looks like the obvious way to reach [0, 1],
    but sentence-transformer embeddings of natural-language text essentially
    never produce negative cosines. Their useful range is about [0, 0.8], which
    rescaling squashes into [0.5, 0.9]. Measured on this model: two sentences
    about entirely different subjects score **0.59** rescaled and **0.18** raw.
    Any threshold set on the intuitive scale — "below 0.3 is unrelated" — then
    silently never fires, and scope-drift detection reports nothing while
    appearing to work.

    Clamping instead preserves the scale practitioners actually calibrate
    against: ~0.3 is loosely related, ~0.7 is strongly related. A negative
    cosine means "no relationship", which is what 0.0 already means.

    Args:
        left: First vector.
        right: Second vector.

    Returns:
        Relatedness in [0, 1].

    Raises:
        ValueError: If the vectors have different lengths, which always means a
            caller mixed embeddings from two different models.
    """
    return max(0.0, cosine_similarity(left, right))


def cosine_similarity(left: Vector, right: Vector) -> float:
    """Return the cosine similarity of two vectors, in [-1, 1].

    The raw mathematical quantity. Prefer :func:`relatedness` for any threshold
    comparison — see its docstring for why rescaling this into [0, 1] breaks
    thresholds.

    Pure and dependency-free, so duplicate-detection and scope-drift thresholds
    can be unit-tested without loading a model (Document 4, §10).

    Args:
        left: First vector.
        right: Second vector.

    Returns:
        Cosine similarity, or ``0.0`` if either vector has zero magnitude —
        an undefined angle is treated as "unrelated" rather than raising, since
        an empty segment is a legitimate input to duplicate detection.

    Raises:
        ValueError: If the vectors have different lengths, which always means a
            caller mixed embeddings from two different models.
    """
    if len(left) != len(right):
        raise ValueError(
            f"cannot compare vectors of length {len(left)} and {len(right)}; "
            "they likely came from different embedding models"
        )
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


@dataclass
class CacheStats:
    """Hit/miss counters for the embedding cache.

    Surfaced on ``/health`` so cache effectiveness is observable rather than
    assumed — a hit rate near zero usually means the model id is changing
    between calls, which silently doubles embedding cost.
    """

    hits: int = 0
    misses: int = 0
    evictions: int = 0

    @property
    def lookups(self) -> int:
        """Total lookups served."""
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        """Fraction of lookups served from cache, in [0, 1]."""
        return self.hits / self.lookups if self.lookups else 0.0


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #


class EmbeddingCache(abc.ABC):
    """Stores embedding vectors keyed by model and text.

    Keyed by **model and text together**, never text alone. Vectors from
    different models are not comparable, and returning an ``all-MiniLM-L6-v2``
    vector to a caller expecting a different model's would not error — it would
    silently produce wrong similarity scores, and therefore wrong Novelty and
    Relevance results.
    """

    @abc.abstractmethod
    def get(self, model: str, text: str) -> list[float] | None:
        """Return the cached vector for ``text`` under ``model``, or None."""

    @abc.abstractmethod
    def set(self, model: str, text: str, vector: Sequence[float]) -> None:
        """Store a vector for ``text`` under ``model``."""

    @abc.abstractmethod
    def clear(self) -> None:
        """Drop every entry."""

    @property
    @abc.abstractmethod
    def stats(self) -> CacheStats:
        """Hit/miss counters."""

    @staticmethod
    def make_key(model: str, text: str) -> str:
        """Build the cache key for ``(model, text)``.

        Hashes rather than storing the text as the key: the AI Output's
        sentences can be long, and the cache should not hold a second copy of
        the content under audit.
        """
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"{model}\x00{digest}"


class InMemoryEmbeddingCache(EmbeddingCache):
    """Bounded LRU cache of embedding vectors.

    Args:
        max_entries: Capacity in vectors. Bounded so a long-lived process
            cannot grow without limit; the least-recently-used entry is evicted
            on overflow.

    Note:
        Not thread-safe, and does not need to be. The orchestrator runs engines
        as asyncio tasks on one event loop, and every method here completes
        without awaiting, so no two callers can interleave mid-update. Moving
        engines to threads would require a lock.
    """

    def __init__(self, max_entries: int = 20_000) -> None:
        self._entries: OrderedDict[str, list[float]] = OrderedDict()
        self._max_entries = max_entries
        self._stats = CacheStats()

    def get(self, model: str, text: str) -> list[float] | None:
        """Return the cached vector, or None. Marks the entry recently used."""
        key = self.make_key(model, text)
        vector = self._entries.get(key)
        if vector is None:
            self._stats.misses += 1
            return None
        self._entries.move_to_end(key)
        self._stats.hits += 1
        return vector

    def set(self, model: str, text: str, vector: Sequence[float]) -> None:
        """Store a vector, evicting the least-recently-used entry on overflow."""
        key = self.make_key(model, text)
        self._entries[key] = list(vector)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
            self._stats.evictions += 1

    def clear(self) -> None:
        """Drop every entry. Counters are preserved."""
        self._entries.clear()

    @property
    def stats(self) -> CacheStats:
        """Hit/miss counters."""
        return self._stats

    def __len__(self) -> int:
        return len(self._entries)


class NullEmbeddingCache(EmbeddingCache):
    """A cache that stores nothing.

    Selected when ``embedding.cache_enabled`` is false. Exists so the service
    has no ``if self._cache is not None`` branch — the caching path is the only
    path, and disabling it swaps the implementation rather than adding a
    condition to every call site.
    """

    def __init__(self) -> None:
        self._stats = CacheStats()

    def get(self, model: str, text: str) -> list[float] | None:
        """Always a miss."""
        self._stats.misses += 1
        return None

    def set(self, model: str, text: str, vector: Sequence[float]) -> None:
        """Discard the vector."""

    def clear(self) -> None:
        """No-op."""

    @property
    def stats(self) -> CacheStats:
        """Hit/miss counters — hits are always zero."""
        return self._stats


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #


class EmbeddingService(abc.ABC):
    """The interface Relevance and Novelty depend on for vector analysis."""

    @abc.abstractmethod
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts, serving what it can from the shared cache.

        Batch rather than single-text by design: Novelty embeds every segment of
        the output, and a per-sentence round trip would dominate the audit's
        latency budget (Document 4, §12).

        Args:
            texts: The texts to embed, in order.

        Returns:
            One vector per input, in the same order.

        Raises:
            ProviderError: If the embedding backend fails.
        """

    @abc.abstractmethod
    async def similarity_matrix(self, texts: Sequence[str]) -> list[list[float]]:
        """Return the pairwise cosine similarity matrix for ``texts``.

        Backs Novelty's semantic duplicate detection, which needs every pair
        rather than a single comparison.

        Args:
            texts: The texts to compare.

        Returns:
            A symmetric matrix where ``m[i][j]`` is the similarity of
            ``texts[i]`` and ``texts[j]``.
        """

    @property
    @abc.abstractmethod
    def cache_stats(self) -> CacheStats:
        """Hit/miss counters for the shared embedding cache."""

    async def aclose(self) -> None:
        """Release model resources on shutdown."""
        return None


class LocalEmbeddingService(EmbeddingService):
    """Local ``sentence-transformers`` backend with a shared cache.

    Local by default (Document 4, §2) so embedding costs nothing per call and
    adds no network latency to a run that already makes many LLM calls.

    Args:
        settings: Supplies ``embedding.model`` and ``embedding.batch_size``.
        cache: The shared embedding cache. Injected rather than constructed so
            that one cache is shared across every engine and every run — which
            is the entire point of caching here. Omit to build an unshared cache
            from settings, which is appropriate only in tests.

    Note:
        Milestone 1 implements the cache, the batching, and the ordering.
        :meth:`_embed_uncached` — the model call itself — lands in Milestone 2
        with Relevance and Novelty, its only consumers. The model is loaded
        lazily inside it, so importing this module never pulls in torch.
    """

    def __init__(self, settings: Settings, cache: EmbeddingCache | None = None) -> None:
        self._settings = settings
        self._model_name = settings.embedding.model
        self._batch_size = settings.embedding.batch_size
        self._cache = cache or build_embedding_cache(settings)
        self._model: Any = None
        self._model_lock = asyncio.Lock()

    @property
    def model_name(self) -> str:
        """The configured embedding model id — half of every cache key."""
        return self._model_name

    @property
    def cache_stats(self) -> CacheStats:
        """Hit/miss counters for the shared cache."""
        return self._cache.stats

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch, computing only what the cache does not already hold.

        Complete as written. It resolves hits, computes the misses in one call,
        writes them back, and restores the caller's ordering — so Milestone 2
        only has to implement :meth:`_embed_uncached`.

        See :meth:`EmbeddingService.embed`.
        """
        if not texts:
            return []

        vectors: list[list[float] | None] = [None] * len(texts)
        missing_indices: list[int] = []

        for index, text in enumerate(texts):
            cached = self._cache.get(self._model_name, text)
            if cached is None:
                missing_indices.append(index)
            else:
                vectors[index] = cached

        if missing_indices:
            # Deduplicate before encoding: a repeated sentence is exactly what
            # Novelty is looking for, so the same text arriving twice in one
            # batch is the common case, not the edge case.
            unique_texts: list[str] = []
            seen: dict[str, int] = {}
            for index in missing_indices:
                text = texts[index]
                if text not in seen:
                    seen[text] = len(unique_texts)
                    unique_texts.append(text)

            computed = await self._embed_uncached(unique_texts)
            if len(computed) != len(unique_texts):
                raise ValueError(
                    f"embedding backend returned {len(computed)} vectors for "
                    f"{len(unique_texts)} texts"
                )

            for text, vector in zip(unique_texts, computed):
                self._cache.set(self._model_name, text, vector)
            for index in missing_indices:
                vectors[index] = computed[seen[texts[index]]]

            logger.debug(
                "embedded batch",
                extra=bind(
                    model=self._model_name,
                    requested=len(texts),
                    cache_hits=len(texts) - len(missing_indices),
                    encoded=len(unique_texts),
                ),
            )

        return [v for v in vectors if v is not None]

    def _load_model_sync(self) -> Any:
        """Import and construct the sentence-transformers model.

        Blocking: the first call downloads (or reads from the HF cache) and
        loads the model, which takes seconds. Always call it through
        :meth:`_ensure_model`, never directly from the event loop.

        The import is inside the function so that importing this module — which
        ``app.app`` does at startup — never pulls in torch. The backend boots in
        a second and boots even with sentence-transformers uninstalled.
        """
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415

        return SentenceTransformer(self._model_name)

    async def _ensure_model(self) -> Any:
        """Load the model once, off the event loop.

        The lock matters: Relevance and Novelty can request embeddings
        concurrently, and without it both would trigger a multi-second load of
        the same model. Double-checked so the common path takes no lock.
        """
        if self._model is not None:
            return self._model

        async with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                self._model = await asyncio.to_thread(self._load_model_sync)
            except ImportError as exc:
                raise ProviderError(
                    "sentence-transformers is not installed, so embeddings are "
                    "unavailable. Install it with "
                    "`pip install -r requirements.txt`."
                ) from exc
            except Exception as exc:
                raise ProviderError(
                    f"Could not load embedding model {self._model_name!r}: {exc}"
                ) from exc
            logger.info("embedding model loaded", extra=bind(model=self._model_name))
            return self._model

    async def _embed_uncached(self, texts: Sequence[str]) -> list[list[float]]:
        """Encode texts with the model, bypassing the cache.

        Both the load and the encode go through ``asyncio.to_thread``.
        ``SentenceTransformer.encode`` is synchronous, CPU-bound work: called
        directly it would block the event loop that five other engines are
        running on, silently converting the orchestrator's parallel wave into a
        serial one. That would not fail — it would just quietly cost the system
        the single biggest latency win it has (Document 4, §12).

        Vectors are L2-normalized at encode time, which makes the cosine
        similarity in :func:`cosine_similarity` a plain dot product and keeps
        every consumer on the same scale.

        Args:
            texts: Deduplicated texts with no cache entry.

        Returns:
            One vector per input, in the same order.

        Raises:
            ProviderError: The model could not be loaded or encoding failed.
        """
        model = await self._ensure_model()

        def encode() -> list[list[float]]:
            vectors = model.encode(
                list(texts),
                batch_size=self._batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            return [vector.tolist() for vector in vectors]

        try:
            return await asyncio.to_thread(encode)
        except Exception as exc:
            raise ProviderError(
                f"Embedding failed for {len(texts)} text(s) with model "
                f"{self._model_name!r}: {exc}"
            ) from exc

    async def aclose(self) -> None:
        """Release the model on shutdown."""
        self._model = None

    async def similarity_matrix(self, texts: Sequence[str]) -> list[list[float]]:
        """Return pairwise cosine similarities.

        Already complete: it composes :meth:`embed` with the pure
        :func:`cosine_similarity`, so it needs no further work once the backend
        lands.
        """
        vectors = await self.embed(texts)
        return [[cosine_similarity(a, b) for b in vectors] for a in vectors]


def build_embedding_cache(settings: Settings) -> EmbeddingCache:
    """Construct the embedding cache named by configuration.

    Called once in ``app.app`` so a single cache instance is shared by every
    engine and every run.

    Args:
        settings: Supplies ``embedding.cache_enabled`` and
            ``embedding.cache_max_entries``.

    Returns:
        An :class:`InMemoryEmbeddingCache`, or a :class:`NullEmbeddingCache`
        when caching is disabled.
    """
    if not settings.embedding.cache_enabled:
        return NullEmbeddingCache()
    return InMemoryEmbeddingCache(max_entries=settings.embedding.cache_max_entries)
