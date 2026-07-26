"""Shared NLI Service — local natural-language-inference entailment.

The AI Output Auditor's Metric Implementation Research names one decision that
shapes six of the eighteen metrics: **add a local NLI cross-encoder**. It labels
a ``(premise, hypothesis)`` pair as ``entailed / neutral / contradicted`` on CPU,
in milliseconds, at **zero token cost** — which is exactly what Faithfulness,
Hallucinations, Unsupported Claims, Contradictions, the Coverage presence-check,
and Attribution reduce to (run NLI over claim↔source sentence pairs).

**Same dependency class as embeddings.** This uses the ``sentence-transformers``
``CrossEncoder`` API on the ``torch`` stack the project already ships for the
embedding model, so it adds no new package. Like the embedding service, the model
is loaded lazily off the event loop and every failure surfaces as a
:class:`ProviderError`, so importing this module never pulls in ``torch``.

**MB1 scope.** This ships the service, the lazy load, batched scoring, the
3-class → label mapping, and the ``/health`` readiness signal. No metric consumes
it yet — Attribution and the Layer-1 metrics wire it in MB2.

**Label mapping.** The model emits three logits. We softmax them to
probabilities, read the class names from the model's own ``id2label`` config
(their order varies by checkpoint, so we never hard-code it), and map:

* ``entailment``    → :attr:`NLILabel.SUPPORTED`
* ``neutral``       → :attr:`NLILabel.NEUTRAL`
* ``contradiction`` → :attr:`NLILabel.CONTRADICTED`

with one guard: the ``entail_threshold`` dial. If the top class is entailment but
its probability is below the threshold, the pair is reported ``NEUTRAL`` rather
than ``SUPPORTED`` — the precision/recall knob for "supported" the research asks
to be a printed number rather than an implicit 0.5.
"""

from __future__ import annotations

import abc
import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Any, Sequence

from app.core.config import Settings
from app.core.errors import ProviderError
from app.core.logging import bind, get_logger

__all__ = [
    "NLILabel",
    "NLIResult",
    "NLIService",
    "LocalNLIService",
]

logger = get_logger(__name__)


class NLILabel(str, Enum):
    """The entailment verdict for a ``(premise, hypothesis)`` pair.

    Named for the grounding states the auditor cares about rather than the raw
    NLI class names: entailment means the hypothesis is **supported** by the
    premise, contradiction means it is **contradicted**, and neutral means the
    premise neither supports nor contradicts it.
    """

    SUPPORTED = "supported"
    NEUTRAL = "neutral"
    CONTRADICTED = "contradicted"


@dataclass(frozen=True)
class NLIResult:
    """One entailment decision.

    Attributes:
        label: The mapped verdict — supported / neutral / contradicted.
        score: Confidence in ``label``: the softmax probability of the winning
            class, in [0, 1].
        probabilities: The full distribution, keyed by :class:`NLILabel`, so a
            caller (e.g. the confidence estimator, MB2) can read the margin
            between the top two classes.
    """

    label: NLILabel
    score: float
    probabilities: dict[NLILabel, float]

    @property
    def entailment(self) -> float:
        """Probability mass on the entailment (supported) class."""
        return self.probabilities.get(NLILabel.SUPPORTED, 0.0)

    @property
    def contradiction(self) -> float:
        """Probability mass on the contradiction class."""
        return self.probabilities.get(NLILabel.CONTRADICTED, 0.0)


class NLIService(abc.ABC):
    """The interface Attribution and the Layer-1 metrics depend on (MB2+)."""

    @abc.abstractmethod
    async def label(self, premise: str, hypothesis: str) -> NLIResult:
        """Label a single ``(premise, hypothesis)`` pair.

        Args:
            premise: The grounding text (a source span).
            hypothesis: The text whose support is in question (an output claim).

        Returns:
            The entailment verdict with a confidence score.

        Raises:
            ProviderError: If the model could not be loaded or scoring failed.
        """

    @abc.abstractmethod
    async def label_batch(
        self, pairs: Sequence[tuple[str, str]]
    ) -> list[NLIResult]:
        """Label a batch of pairs in one model call.

        Batch rather than single by design: Attribution scores one claim against
        several candidate source spans at once (SummaC-style), and a per-pair
        round trip would dominate the audit's latency budget.

        Args:
            pairs: ``(premise, hypothesis)`` pairs, in order.

        Returns:
            One :class:`NLIResult` per input pair, in the same order.

        Raises:
            ProviderError: If the model could not be loaded or scoring failed.
        """

    @property
    @abc.abstractmethod
    def model_name(self) -> str:
        """The configured NLI model id, surfaced on ``/health``."""

    @property
    @abc.abstractmethod
    def is_ready(self) -> bool:
        """Whether the model is loaded and ready to score, for ``/health``."""

    async def warm(self) -> bool:
        """Load the model ahead of first use.

        Returns:
            True if the model is ready after the call, False if the load failed
            (offline with no cached model). Callers treat a False as non-fatal.
        """
        return self.is_ready

    async def aclose(self) -> None:
        """Release model resources on shutdown."""
        return None


class LocalNLIService(NLIService):
    """Local ``sentence-transformers`` ``CrossEncoder`` NLI backend.

    Args:
        settings: Supplies ``nli.model``, ``nli.entail_threshold``, and
            ``nli.batch_size``.

    Note:
        The model is loaded lazily inside :meth:`_ensure_model`, off the event
        loop via ``asyncio.to_thread`` — its ``predict`` is synchronous,
        CPU-bound work that would otherwise block the loop the orchestrator runs
        engines on. The import lives inside the loader so importing this module
        never pulls in ``torch``.
    """

    #: The canonical NLI class names we map from, lower-cased. Different
    #: checkpoints order their logits differently, so we resolve names from the
    #: model's own ``id2label`` and match against these rather than assuming an
    #: index. Some checkpoints spell them ``entail`` / ``contradict``.
    _ENTAIL_NAMES = frozenset({"entailment", "entail"})
    _CONTRADICT_NAMES = frozenset({"contradiction", "contradict"})
    _NEUTRAL_NAMES = frozenset({"neutral"})

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model_name = settings.nli.model
        self._entail_threshold = settings.nli.entail_threshold
        self._batch_size = settings.nli.batch_size
        self._model: Any = None
        #: Maps a logit index to an :class:`NLILabel`, resolved at load time.
        self._index_to_label: dict[int, NLILabel] = {}
        self._model_lock = asyncio.Lock()

    @property
    def model_name(self) -> str:
        """The configured NLI model id — reported on ``/health``."""
        return self._model_name

    @property
    def is_ready(self) -> bool:
        """Whether the model has been loaded and is ready to score."""
        return self._model is not None

    async def label(self, premise: str, hypothesis: str) -> NLIResult:
        """Label one pair. See :meth:`NLIService.label`."""
        results = await self.label_batch([(premise, hypothesis)])
        return results[0]

    async def label_batch(
        self, pairs: Sequence[tuple[str, str]]
    ) -> list[NLIResult]:
        """Label a batch of pairs. See :meth:`NLIService.label_batch`."""
        if not pairs:
            return []

        model = await self._ensure_model()

        def score() -> list[list[float]]:
            # ``CrossEncoder.predict`` on an NLI model returns one row of 3
            # logits per pair. ``apply_softmax=False`` keeps raw logits so we
            # softmax ourselves and can also expose the full distribution.
            raw = model.predict(
                [list(pair) for pair in pairs],
                batch_size=self._batch_size,
                apply_softmax=False,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            return [list(map(float, row)) for row in raw]

        try:
            logit_rows = await asyncio.to_thread(score)
        except Exception as exc:  # pragma: no cover - backend failure path
            raise ProviderError(
                f"NLI scoring failed for {len(pairs)} pair(s) with model "
                f"{self._model_name!r}: {exc}"
            ) from exc

        return [self._to_result(row) for row in logit_rows]

    def _to_result(self, logits: Sequence[float]) -> NLIResult:
        """Softmax a logit row and map it to an :class:`NLIResult`."""
        probs = _softmax(logits)
        distribution: dict[NLILabel, float] = {}
        for index, prob in enumerate(probs):
            label = self._index_to_label.get(index)
            if label is not None:
                # Fold any duplicate mapping defensively (should not happen).
                distribution[label] = distribution.get(label, 0.0) + prob

        # Guarantee all three keys are present so callers can read margins.
        for label in NLILabel:
            distribution.setdefault(label, 0.0)

        winner = max(distribution, key=lambda label: distribution[label])
        # The entail_threshold dial: a low-confidence "supported" is reported
        # neutral instead. This is the precision/recall knob for grounding.
        if (
            winner is NLILabel.SUPPORTED
            and distribution[NLILabel.SUPPORTED] < self._entail_threshold
        ):
            winner = NLILabel.NEUTRAL

        return NLIResult(
            label=winner,
            score=distribution[winner],
            probabilities=distribution,
        )

    def _load_model_sync(self) -> Any:
        """Import and construct the CrossEncoder, then resolve its label order.

        Blocking: the first call downloads (or reads from the HF cache) and
        loads the model. Always call through :meth:`_ensure_model`.
        """
        from sentence_transformers import CrossEncoder  # noqa: PLC0415

        model = CrossEncoder(self._model_name)
        self._index_to_label = self._resolve_label_order(model)
        return model

    def _resolve_label_order(self, model: Any) -> dict[int, NLILabel]:
        """Map each logit index to an :class:`NLILabel` from ``id2label``.

        NLI checkpoints do not agree on logit order (some are
        contradiction/entailment/neutral, others neutral/entailment/…), so we
        read the model's own ``config.id2label`` rather than assume one. Falls
        back to the common DeBERTa-MNLI order (0=contradiction, 1=entailment,
        2=neutral) only if the config is unreadable.
        """
        id2label = getattr(getattr(model, "config", None), "id2label", None)
        mapping: dict[int, NLILabel] = {}
        if isinstance(id2label, dict) and id2label:
            for raw_index, raw_name in id2label.items():
                try:
                    index = int(raw_index)
                except (TypeError, ValueError):
                    continue
                name = str(raw_name).strip().lower()
                if name in self._ENTAIL_NAMES:
                    mapping[index] = NLILabel.SUPPORTED
                elif name in self._CONTRADICT_NAMES:
                    mapping[index] = NLILabel.CONTRADICTED
                elif name in self._NEUTRAL_NAMES:
                    mapping[index] = NLILabel.NEUTRAL

        if len(mapping) == 3:
            return mapping

        logger.warning(
            "NLI model id2label was unusable; falling back to DeBERTa-MNLI order",
            extra=bind(model=self._model_name, id2label=str(id2label)),
        )
        return {
            0: NLILabel.CONTRADICTED,
            1: NLILabel.SUPPORTED,
            2: NLILabel.NEUTRAL,
        }

    async def _ensure_model(self) -> Any:
        """Load the model once, off the event loop.

        The lock prevents two concurrent callers from both triggering a
        multi-second load of the same model. Double-checked so the hot path
        takes no lock.
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
                    "sentence-transformers is not installed, so the NLI service "
                    "is unavailable. Install it with "
                    "`pip install -r requirements.txt`."
                ) from exc
            except Exception as exc:
                raise ProviderError(
                    f"Could not load NLI model {self._model_name!r}: {exc}"
                ) from exc
            logger.info(
                "NLI model loaded",
                extra=bind(
                    model=self._model_name,
                    labels={i: l.value for i, l in sorted(self._index_to_label.items())},
                ),
            )
            return self._model

    async def warm(self) -> bool:
        """Load the model ahead of first use, non-fatally.

        Called at startup so ``/health`` reports ``nli_ready: true`` before the
        first audit. A failed load (offline, no cached model) is logged and
        swallowed: the app still boots and ``is_ready`` stays False, matching the
        graceful-degradation policy the rest of the system uses.
        """
        try:
            await self._ensure_model()
        except ProviderError as exc:
            logger.warning(
                "NLI model warm-up failed; proceeding without it",
                extra=bind(model=self._model_name, error=str(exc)),
            )
            return False
        return True

    async def aclose(self) -> None:
        """Release the model on shutdown."""
        self._model = None


def _softmax(logits: Sequence[float]) -> list[float]:
    """Numerically stable softmax over a logit row.

    Pure and dependency-free (no numpy) so the label mapping can be unit-tested
    without loading a model.
    """
    if not logits:
        return []
    import math  # noqa: PLC0415 - local, keeps module import torch-free & light

    largest = max(logits)
    exps = [math.exp(value - largest) for value in logits]
    total = sum(exps)
    if total == 0.0:
        # Degenerate row; distribute uniformly rather than divide by zero.
        return [1.0 / len(logits)] * len(logits)
    return [value / total for value in exps]
