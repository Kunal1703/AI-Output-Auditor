"""Configuration Manager — the single source of every tunable.

Document 4 §4 lists the Configuration Manager as a Shared Service and §15 makes
"thresholds, weights, models, and prompts are configuration, not code" an
engineering principle. Document 3 reinforces it: the *reasoning rules* are
fixed, but every threshold and weight they compare against is deployment
configuration.

**Two sources, layered. The environment always wins over YAML.**

* ``config/settings.yaml`` — thresholds, weights, model and provider selection.
  Checked into the repo; safe to read.
* ``.env`` / environment — secrets and per-deployment overrides. Never checked
  in.

**Two environment spellings, both supported.**

* **Flat, documented names** — ``GROQ_API_KEY``, ``LLM_PROVIDER``, ``LLM_MODEL``.
  These are the ones in ``.env.example`` and are what most deployments set.
* **Prefixed names** — ``AUDITOR_*`` with ``__`` for nesting, e.g.
  ``AUDITOR_DECISION__MIN_TRUST_CONFIDENCE``. These reach every field, including
  ones with no flat alias.

The API key is resolved *per provider* (``GROQ_API_KEY`` for Groq,
``OPENROUTER_API_KEY`` for OpenRouter), so adding the paid provider later means
adding its key to ``.env`` — not renaming the one you already have.

Configuration is loaded once at startup and injected (Document 4, §4). Modules
receive a :class:`Settings` instance rather than importing a global, which is
what makes them testable with alternative thresholds.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any, Mapping

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.errors import ConfigurationError
from app.shared.schemas import Severity

__all__ = [
    "LLMSettings",
    "EmbeddingSettings",
    "NLISettings",
    "InputSettings",
    "RetrievalSettings",
    "PromptSettings",
    "OrchestratorSettings",
    "DecisionSettings",
    "AccuracyEngineSettings",
    "CredibilityEngineSettings",
    "RelevanceEngineSettings",
    "CoverageEngineSettings",
    "ReadabilityEngineSettings",
    "NoveltyEngineSettings",
    "EngagementEngineSettings",
    "DiversityEngineSettings",
    "EngineSettings",
    "JobSettings",
    "Settings",
    "get_settings",
    "load_settings",
    "BACKEND_ROOT",
    "PROJECT_ROOT",
]

#: ``backend/`` — the directory ``uvicorn app.main:app`` is launched from.
BACKEND_ROOT: Path = Path(__file__).resolve().parents[2]

#: The repository root, which owns ``config/`` and ``datasets/``.
PROJECT_ROOT: Path = BACKEND_ROOT.parent

#: Which environment variable holds the API key, per provider. Keeping these
#: distinct means enabling the paid provider is additive — you add its key
#: alongside the Groq one rather than repurposing a generic name and losing
#: track of which backend a key belongs to.
_PROVIDER_API_KEY_ENV: Mapping[str, str] = {
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


class LLMSettings(BaseModel):
    """Settings for the Shared LLM Service (Document 4, §4).

    ``provider`` selects an implementation from the provider registry. The
    engines never see this value: they call the LLM Service, which resolves the
    provider. Switching providers is therefore a config change with no engine
    edits (Document 4, §2).
    """

    provider: str = Field(
        default="groq",
        description="Provider key registered in shared.llm_providers.registry. "
        "Set via LLM_PROVIDER.",
    )
    model: str = Field(
        default="llama-3.3-70b-versatile",
        description="Provider-qualified model id. Set via LLM_MODEL. Must be a "
        "model the key is currently served (Groq retires models — "
        "ServiceContainer.verify_model checks this at startup).",
    )
    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="Defaults to 0.0. The auditor's verdicts should be as "
        "reproducible as the provider allows (Document 4, §11 stability "
        "criterion).",
    )
    max_tokens: int = Field(default=4096, gt=0)
    tokens_per_minute: int = Field(
        default=0,
        ge=0,
        description="Client-side token-per-minute pacing cap for the LLM "
        "Service. Hosted providers admit a request against prompt_tokens + "
        "max_tokens and rate-limit on a rolling per-minute window, so a wave of "
        "six concurrent engines bursts past a free-tier TPM the instant it "
        "starts — the provider then 429s most of the wave and those dimensions "
        "degrade (Document 4, §12), a rate limit misread as a verification gap. "
        "Set this at or below the provider's TPM to pace requests and keep the "
        "wave under the limit. 0 disables pacing (the default, for offline "
        "tests and providers without a TPM ceiling).",
    )
    timeout_seconds: float = Field(
        default=60.0,
        gt=0,
        description="Per-call budget. On expiry the service raises, the engine "
        "degrades, and the run continues (Document 4, §12).",
    )
    max_retries: int = Field(
        default=3, ge=0, description="Bounded retries for transient errors. Never infinite."
    )
    retry_backoff_seconds: float = Field(default=1.5, gt=0)
    retry_after_cap_seconds: float = Field(
        default=0.0,
        ge=0.0,
        description="Upper bound, in seconds, on how long a provider-supplied "
        "Retry-After is honored. A per-minute token limit resets within ~60s, "
        "but a provider under a concurrent burst can return a Retry-After far "
        "longer than an engine's whole budget — honoring it verbatim then "
        "guarantees a timeout and a degraded dimension for a limit that has "
        "already cleared. Capping the wait at roughly one reset window lets the "
        "retry land. 0 disables the cap (honor Retry-After verbatim).",
    )
    reasoning_format: str | None = Field(
        default=None,
        description="Groq-only. 'hidden' suppresses a reasoning model's "
        "<think> block, which would otherwise corrupt the structured JSON the "
        "engine pipelines parse. Valid only on reasoning models (the default "
        "qwen/qwen3-32b is one) — leave null for any other provider or model, "
        "since they reject the parameter.",
    )
    reasoning_effort: str | None = Field(
        default=None,
        description="Groq-only, reasoning models only. 'none' disables the "
        "model's chain-of-thought entirely. For qwen/qwen3-32b that thinking is "
        "generated, counted against the tokens-per-minute budget, then — with "
        "reasoning_format 'hidden' — discarded, so on the free tier it was "
        "~5x the token cost of the structured answer for no surfaced benefit "
        "and pushed calls past max_tokens into truncation. 'none' makes the "
        "engine stages' short JSON tasks small and fast. Leave null for any "
        "non-reasoning model or other provider, which reject the parameter.",
    )

    # Populated from the environment, never from YAML.
    api_key: SecretStr | None = Field(default=None, exclude=True)
    base_url: str | None = Field(default=None)


class EmbeddingSettings(BaseModel):
    """Settings for the Shared Embedding Service.

    Consumed by Relevance (scope drift) and Novelty (semantic duplicate
    detection) — Document 2 §5.5.
    """

    provider: str = Field(default="local")
    model: str = Field(default="all-MiniLM-L6-v2")
    batch_size: int = Field(default=32, gt=0)
    cache_enabled: bool = Field(
        default=True,
        description="Share embeddings across engines and runs (Document 4, §12 "
        "names caching embeddings as a reliability measure).",
    )
    cache_max_entries: int = Field(
        default=20_000,
        gt=0,
        description="Cache capacity in vectors. At 384 dimensions this is on "
        "the order of tens of MB — bounded so a long-lived process cannot grow "
        "without limit.",
    )
    api_key: SecretStr | None = Field(default=None, exclude=True)


class NLISettings(BaseModel):
    """Settings for the Shared NLI Service (AI Output Auditor, MB1).

    The local NLI cross-encoder is the backbone of Layer 1 and Attribution in
    the new evaluation pipeline: it produces an entailment label —
    ``entailed / neutral / contradicted`` — for a (premise, hypothesis) pair on
    CPU, at zero token cost. It is the same class of dependency as the embedding
    model (``sentence-transformers`` / ``torch``, already shipped), so no new
    package is required.

    Consumed in MB2+ by Attribution and the Layer-1 metrics. In MB1 the service
    exists, loads, and is reported on ``/health``; no metric runs against it yet.
    """

    provider: str = Field(default="local")
    model: str = Field(
        default="cross-encoder/nli-deberta-v3-base",
        description="A SentenceTransformers ``CrossEncoder`` NLI model with a "
        "3-class (entailment / neutral / contradiction) head. Loaded lazily; the "
        "first load downloads ~180MB into the local HF cache.",
    )
    entail_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Softmax-probability floor the entailment class must clear "
        "for the service to return SUPPORTED. Below it, a top-entailment pair is "
        "reported NEUTRAL. This is the precision/recall dial for 'supported' the "
        "research calls out — a printed number, not a guess (calibrated in a "
        "later milestone).",
    )
    batch_size: int = Field(
        default=32,
        gt=0,
        description="Pairs scored per model call. Batching matters because "
        "Attribution scores a claim against several candidate source spans at "
        "once (MB2).",
    )
    warm_on_startup: bool = Field(
        default=True,
        description="Load the model during startup so ``/health`` reports "
        "``nli_ready: true`` immediately. Non-fatal: if the load fails (e.g. "
        "offline with no cached model) the app still boots and ``nli_ready`` is "
        "False, mirroring the graceful-degradation policy used elsewhere.",
    )
    api_key: SecretStr | None = Field(default=None, exclude=True)


class InputSettings(BaseModel):
    """Bounds for the new ``{source, outputs[]}`` audit input contract (MB1).

    The AI Output Auditor audits one mandatory source article against one or
    more outputs. This caps how many outputs a single request may carry so a
    pathological request cannot fan out without limit.
    """

    max_outputs: int = Field(
        default=10,
        gt=0,
        description="Maximum number of outputs audited against the source in a "
        "single request.",
    )


class RetrievalSettings(BaseModel):
    """Settings for the Shared Retrieval Service.

    Consumed by Accuracy (reference-first evidence retrieval), Credibility
    (source fetching), and Diversity (credible-perspective retrieval).
    """

    fetch_timeout_seconds: float = Field(default=20.0, gt=0)
    max_retries: int = Field(default=2, ge=0)
    chunk_size: int = Field(default=800, gt=0)
    chunk_overlap: int = Field(default=120, ge=0)
    top_k: int = Field(default=5, gt=0)
    external_retrieval_enabled: bool = Field(
        default=False,
        description="Default for the request-level ``external_retrieval`` "
        "option. Accuracy is reference-first; external retrieval is optional "
        "(Document 2, §7.2).",
    )
    user_agent: str = Field(default="AI-Trust-Auditor/1.0")

    @model_validator(mode="after")
    def _overlap_below_chunk(self) -> "RetrievalSettings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


class PromptSettings(BaseModel):
    """Settings for the Prompt Manager."""

    directory: Path = Field(default=Path("config/prompts"))
    strict_rendering: bool = Field(
        default=True,
        description="When True, a template variable with no supplied value is "
        "an error rather than an empty string. A silently blank prompt "
        "variable produces a confidently wrong audit.",
    )


class OrchestratorSettings(BaseModel):
    """Settings for the Engine Orchestrator."""

    engine_timeout_seconds: float = Field(default=120.0, gt=0)
    max_parallel_engines: int = Field(default=8, gt=0)


class DecisionSettings(BaseModel):
    """Thresholds and weights for the Decision Engine.

    Document 3 is explicit that these are deployment configuration while the
    rules that consume them are fixed. Retuning a threshold changes *where* the
    line sits; it can never change the fact that a qualifying Critical Finding
    gates trust, or that insufficient confidence blocks a Trusted verdict.
    """

    trust_blocking_severity: Severity = Field(
        default=Severity.HIGH,
        description="A Critical Finding at or above this severity forces "
        "Untrusted (Document 3, §5).",
    )
    min_trust_confidence: float = Field(
        default=0.60,
        ge=0.0,
        le=1.0,
        description="Below this on a trust-relevant dimension, no favorable "
        "trust verdict may be asserted; the run routes to Unable to Verify.",
    )
    trust_dimension_pass_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    trust_caveat_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    quality_bands: dict[str, float] = Field(
        default_factory=lambda: {"high": 0.80, "adequate": 0.60}
    )
    quality_weights: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _bands_ordered(self) -> "DecisionSettings":
        high = self.quality_bands.get("high")
        adequate = self.quality_bands.get("adequate")
        if high is None or adequate is None:
            raise ValueError("quality_bands must define both 'high' and 'adequate'")
        if not 0.0 <= adequate < high <= 1.0:
            raise ValueError(
                "quality_bands must satisfy 0 <= adequate < high <= 1; "
                f"got adequate={adequate}, high={high}"
            )
        if self.trust_caveat_threshold < self.trust_dimension_pass_threshold:
            raise ValueError(
                "trust_caveat_threshold must be >= trust_dimension_pass_threshold"
            )
        return self


class AccuracyEngineSettings(BaseModel):
    """Tunables for the Accuracy engine (Document 2, §7.2).

    Document 2 §2 puts thresholds out of its own scope, and Document 1 §11 makes
    them configuration rather than code. Retuning these moves where a line sits;
    none of them can change the frozen pipeline or the rule that a qualifying
    Critical Finding gates trust.
    """

    evidence_similarity_threshold: float = Field(
        default=0.45,
        ge=0.0,
        le=1.0,
        description="Minimum similarity for a retrieved passage to be offered "
        "to the verification judge. Below it, the passage is noise — and a "
        "judge shown noise is more likely to hallucinate support than to say "
        "'unverifiable'.",
    )
    evidence_top_k: int = Field(
        default=4, gt=0, description="Passages retrieved per claim."
    )
    contradiction_blocking_severity: Severity = Field(
        default=Severity.HIGH,
        description="Severity floor at which a contradicted claim becomes a "
        "Critical Finding. Stage 4 assigns each claim its own severity; this is "
        "the bar it must clear.",
    )
    min_centrality_for_finding: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Centrality floor for raising a Critical Finding on a "
        "contradicted claim. Defaults to 0 — a contradicted claim is a "
        "contradicted claim, and suppressing peripheral ones by default would "
        "hide real hallucinations.",
    )


class CredibilityEngineSettings(BaseModel):
    """Tunables for the Credibility engine (Document 2, §7.4)."""

    fabrication_severity: Severity = Field(
        default=Severity.HIGH,
        description="Severity for a citation that does not resolve.",
    )
    misattribution_severity: Severity = Field(
        default=Severity.HIGH,
        description="Severity for a citation whose source is unrelated to, or "
        "contradicts, the claim it was offered for.",
    )
    max_sources_fetched: int = Field(
        default=12,
        gt=0,
        description="Ceiling on source fetches per audit, so a document with "
        "200 links cannot stall the run past its budget.",
    )
    source_excerpt_chars: int = Field(
        default=4000,
        gt=0,
        description="Characters of fetched source text shown to the grounding "
        "judge per citation.",
    )


class RelevanceEngineSettings(BaseModel):
    """Tunables for the Relevance engine (Document 2, §7.1)."""

    scope_drift_threshold: float = Field(
        default=0.30,
        ge=0.0,
        le=1.0,
        description="Similarity floor, against the prompt, below which a "
        "sentence counts as scope drift (§7.1, stage 6).",
    )
    scope_drift_tolerance: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Fraction of drifting sentences tolerated before scope "
        "drift affects the score. Some drift is normal — transitions, framing, "
        "caveats — and penalizing the first off-topic sentence would punish "
        "ordinary prose.",
    )
    hard_requirement_blocking_severity: Severity = Field(
        default=Severity.HIGH,
        description="Severity assigned to a violated Hard requirement.",
    )


class CoverageEngineSettings(BaseModel):
    """Tunables for the Coverage engine (Document 2, §7.3)."""

    critical_omission_salience: float = Field(
        default=0.70,
        ge=0.0,
        le=1.0,
        description="Salience floor at which an absent key point becomes a "
        "Critical Omission. This is the threshold that keeps Coverage from "
        "over-penalizing summarization (§7.3): below it, an omission is a "
        "score effect, not a trust gate.",
    )
    critical_omission_severity: Severity = Field(
        default=Severity.HIGH,
        description="Severity floor an absent key point's own severity must "
        "clear to become a Critical Omission.",
    )
    partial_credit: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Credit a 'Partial' key point earns toward the score. The "
        "middle value exists because a briefly-mentioned point is neither fully "
        "covered nor omitted.",
    )


class ReadabilityEngineSettings(BaseModel):
    """Tunables for the Readability engine (Document 2, §7.6).

    The heuristic bounds are the ones the Deterministic Analysis stage measures
    against. They are *bounds a measurement is compared to*, never verdicts: the
    engine's stage 3 review decides what exceeding one means, and the score
    weights that review three times as heavily as these.
    """

    max_mean_sentence_words: float = Field(
        default=25.0,
        gt=0,
        description="Mean sentence length above which the check flags. Ordinary "
        "professional prose runs 15–25 words.",
    )
    max_sentence_words: float = Field(
        default=45.0,
        gt=0,
        description="Length of a single sentence above which the check flags.",
    )
    min_reading_ease: float = Field(
        default=30.0,
        description="Flesch reading-ease floor. Below ~30 is dense academic "
        "register. Set low deliberately: technical content is legitimately "
        "dense, and a stricter floor would flag every engineering document.",
    )
    max_grade_level: float = Field(
        default=14.0,
        gt=0,
        description="Flesch-Kincaid grade-level bound.",
    )
    max_paragraph_words: float = Field(
        default=150.0,
        gt=0,
        description="Paragraph length above which the check flags.",
    )
    structure_required_above_words: float = Field(
        default=400.0,
        gt=0,
        description="Word count above which the absence of headings, lists, or "
        "tables is worth reporting. Below it, a short answer needs no "
        "navigation and faulting it for having none would fault it for being "
        "short.",
    )
    min_words_for_review: int = Field(
        default=25,
        gt=0,
        description="Below this the output is too short to assess for coherence "
        "or structure, and the engine reports a neutral score with low "
        "confidence rather than a verdict it could not reach.",
    )
    words_for_full_confidence: int = Field(
        default=150,
        gt=0,
        description="Word count at which the content-sufficiency confidence "
        "signal saturates.",
    )
    expected_check_count: int = Field(
        default=8,
        gt=0,
        description="Deterministic checks a healthy run produces, used to scale "
        "the checks-ran confidence signal. Fewer means a library was "
        "unavailable and the analysis is thinner than designed.",
    )

    def thresholds(self) -> dict[str, float]:
        """Project the heuristic bounds for ``validators.analyze_readability``.

        Only the bounds — the confidence and gating knobs above are the engine's
        own business, and the validator has no use for them.
        """
        return {
            "max_mean_sentence_words": self.max_mean_sentence_words,
            "max_sentence_words": self.max_sentence_words,
            "min_reading_ease": self.min_reading_ease,
            "max_grade_level": self.max_grade_level,
            "max_paragraph_words": self.max_paragraph_words,
            "structure_required_above_words": self.structure_required_above_words,
        }


class NoveltyEngineSettings(BaseModel):
    """Tunables for the Novelty engine (Document 2, §7.5)."""

    semantic_threshold: float = Field(
        default=0.60,
        ge=0.0,
        le=1.0,
        description="Relatedness above which two segments become a redundancy "
        "*candidate* — never a finding; stage 6 decides. **Raw cosine** (see "
        "embedding_service.relatedness), not rescaled from [-1,1]. Measured on "
        "this model: genuine padding scores 0.66–0.94, a genuine recap 0.72, "
        "and merely same-topic sentences 0.56 and below — so the separation "
        "sits at ~0.60. A higher bar misses real restatement; the review is "
        "what clears the false positives a lower bar admits.",
    )
    literal_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Token-overlap (Jaccard) floor at which two segments count "
        "as literal duplicates, catching a near-verbatim repeat that differs by "
        "an article. A literal duplicate becomes a candidate regardless of its "
        "embedding similarity.",
    )
    min_segment_words: int = Field(
        default=5,
        gt=0,
        description="Segments shorter than this are not compared. 'Yes.' is "
        "similar to everything and redundant with nothing.",
    )
    max_candidates: int = Field(
        default=25,
        gt=0,
        description="Ceiling on candidate pairs sent to the review, worst first. "
        "A pathologically repetitive text could otherwise blow the engine "
        "timeout and degrade the dimension to nothing at all.",
    )
    coverage_match_threshold: float = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        description="Relatedness at which a redundant segment counts as "
        "restating a Coverage key point and is rescued as functional "
        "repetition. Raw cosine, same scale as semantic_threshold. Set below it "
        "on purpose: a recap paraphrases a key point rather than echoing it, so "
        "requiring near-identity here would defeat the rescue.",
    )
    coverage_salience_floor: float = Field(
        default=0.60,
        ge=0.0,
        le=1.0,
        description="Salience a Coverage key point must carry before repetition "
        "of it counts as functional. Repeating a peripheral detail is padding "
        "however faithfully it tracks the source.",
    )
    words_for_full_confidence: int = Field(
        default=120,
        gt=0,
        description="Word count at which the content-sufficiency confidence "
        "signal saturates.",
    )


class EngagementEngineSettings(BaseModel):
    """Tunables for the Engagement engine (Document 2, §7.7)."""

    manipulation_penalty: dict[str, float] = Field(
        default_factory=lambda: {
            "critical": 0.35,
            "high": 0.25,
            "medium": 0.12,
            "low": 0.05,
            "info": 0.0,
        },
        description="Score penalty per confirmed manipulation item, by the "
        "pattern's severity. Subtracted rather than averaged: content that "
        "manipulates its reader has done something wrong that being useful does "
        "not excuse, and averaging would let a high fitness score dilute it.",
    )
    borderline_penalty_factor: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description="Fraction of the penalty a *Borderline* item carries. Pushy "
        "phrasing is a real cost and a smaller one than deception; a factor of "
        "0 would make the middle verdict meaningless and 1 would make it a "
        "synonym for Manipulative.",
    )

    @model_validator(mode="after")
    def _penalties_cover_severities(self) -> "EngagementEngineSettings":
        missing = {s.value for s in Severity} - set(self.manipulation_penalty)
        if missing:
            raise ValueError(
                "engagement.manipulation_penalty must define a penalty for every "
                f"severity; missing: {sorted(missing)}"
            )
        return self


class DiversityEngineSettings(BaseModel):
    """Tunables for the Diversity engine (Document 2, §7.8).

    Note:
        There is no threshold here for *applicability*. Whether the dimension
        applies is a judgment made by stage 2 against the criteria in its prompt,
        not a number to tune — and a configurable applicability gate would let a
        deployment quietly switch the only N/A in the system on or off.
    """

    perspective_similarity_threshold: float = Field(
        default=0.35,
        ge=0.0,
        le=1.0,
        description="Relatedness floor for a reference passage to count as a "
        "retrieved perspective. **Raw cosine** (see relatedness), not rescaled. "
        "Set lower than Accuracy's evidence floor on purpose: a passage arguing "
        "a position the output never took is topically distant from the topic "
        "sentence by construction, and a strict floor would retrieve only the "
        "perspectives the output already holds.",
    )
    perspective_top_k: int = Field(
        default=6, gt=0, description="Reference passages retrieved per audit."
    )
    max_sources_fetched: int = Field(
        default=6,
        gt=0,
        description="Ceiling on external fetches, and only when the request "
        "opted into external retrieval.",
    )
    source_excerpt_chars: int = Field(
        default=3000,
        gt=0,
        description="Characters of a fetched source shown to viewpoint "
        "extraction.",
    )
    bias_penalty: dict[str, float] = Field(
        default_factory=lambda: {
            "critical": 0.30,
            "high": 0.20,
            "medium": 0.10,
            "low": 0.04,
            "info": 0.0,
        },
        description="Score penalty per detected bias item, by severity. "
        "Subtracted rather than averaged: loaded framing is a fault that naming "
        "every viewpoint does not offset.",
    )

    @model_validator(mode="after")
    def _penalties_cover_severities(self) -> "DiversityEngineSettings":
        missing = {s.value for s in Severity} - set(self.bias_penalty)
        if missing:
            raise ValueError(
                "diversity.bias_penalty must define a penalty for every "
                f"severity; missing: {sorted(missing)}"
            )
        return self


class EngineSettings(BaseModel):
    """Per-engine tunables, grouped."""

    accuracy: AccuracyEngineSettings = Field(default_factory=AccuracyEngineSettings)
    credibility: CredibilityEngineSettings = Field(
        default_factory=CredibilityEngineSettings
    )
    relevance: RelevanceEngineSettings = Field(default_factory=RelevanceEngineSettings)
    coverage: CoverageEngineSettings = Field(default_factory=CoverageEngineSettings)
    readability: ReadabilityEngineSettings = Field(
        default_factory=ReadabilityEngineSettings
    )
    novelty: NoveltyEngineSettings = Field(default_factory=NoveltyEngineSettings)
    engagement: EngagementEngineSettings = Field(
        default_factory=EngagementEngineSettings
    )
    diversity: DiversityEngineSettings = Field(default_factory=DiversityEngineSettings)


class JobSettings(BaseModel):
    """Settings for the async audit job store (Document 4, §7)."""

    retention_seconds: float = Field(default=3600.0, gt=0)
    max_concurrent_audits: int = Field(default=4, gt=0)


class Settings(BaseSettings):
    """The complete, validated backend configuration.

    Built by :func:`load_settings`, which layers ``config/settings.yaml`` under
    the environment. Constructed once at startup and injected via the service
    container (``app.app``), never imported as a mutable global.
    """

    model_config = SettingsConfigDict(
        env_prefix="AUDITOR_",
        env_nested_delimiter="__",
        env_file=(BACKEND_ROOT / ".env", PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI Trust & Quality Auditor"
    version: str = "1.0"
    environment: str = Field(
        default="development", description="development | staging | production."
    )
    debug: bool = False
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="text", description="text | json.")
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"],
        description="Vite's dev server origins. Tighten for production.",
    )
    settings_file: Path = Field(default=PROJECT_ROOT / "config" / "settings.yaml")

    llm: LLMSettings = Field(default_factory=LLMSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    nli: NLISettings = Field(default_factory=NLISettings)
    input: InputSettings = Field(default_factory=InputSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    prompts: PromptSettings = Field(default_factory=PromptSettings)
    orchestrator: OrchestratorSettings = Field(default_factory=OrchestratorSettings)
    decision: DecisionSettings = Field(default_factory=DecisionSettings)
    engines: EngineSettings = Field(default_factory=EngineSettings)
    jobs: JobSettings = Field(default_factory=JobSettings)

    @property
    def prompts_directory(self) -> Path:
        """Absolute path to the prompt template root."""
        directory = self.prompts.directory
        return directory if directory.is_absolute() else PROJECT_ROOT / directory

    @property
    def llm_configured(self) -> bool:
        """Whether the LLM provider has the credentials it needs.

        Reported by ``/health`` so a deployment missing its key is visible
        immediately rather than at the first audit.
        """
        return self.llm.api_key is not None

    @property
    def llm_api_key_env_var(self) -> str:
        """The environment variable that supplies this provider's key.

        Surfaced in error messages so a missing key names the variable to set
        rather than making the reader guess.
        """
        return _PROVIDER_API_KEY_ENV.get(self.llm.provider, "LLM_API_KEY")


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML mapping, tolerating absence but not corruption.

    A missing settings file is fine — the field defaults are the documented
    values. A malformed one is not: silently falling back to defaults would run
    the auditor on thresholds nobody chose.
    """
    if not path.is_file():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Could not parse {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ConfigurationError(
            f"{path} must contain a YAML mapping at the top level, got "
            f"{type(loaded).__name__}."
        )
    return loaded


def _environment() -> dict[str, str]:
    """Merge the ``.env`` files under the real environment.

    Read here rather than left to pydantic-settings because the flat names
    (``GROQ_API_KEY``, ``LLM_PROVIDER``, ``LLM_MODEL``) carry no ``AUDITOR_``
    prefix and map onto *nested* fields, which the prefixed env source cannot
    express. The real environment wins over ``.env``, so an exported variable or
    a container secret overrides a checked-out file.
    """
    merged: dict[str, str] = {}
    for env_file in (PROJECT_ROOT / ".env", BACKEND_ROOT / ".env"):
        if env_file.is_file():
            merged.update(
                {k: v for k, v in dotenv_values(env_file).items() if v is not None}
            )
    merged.update(os.environ)
    return merged


def _apply_flat_env(overrides: dict[str, Any], env: Mapping[str, str]) -> None:
    """Overlay the flat, documented env names onto the YAML-derived overrides.

    Applied *after* the YAML so the environment wins, which is what
    ``.env.example`` and the README promise.

    Args:
        overrides: The YAML-derived override dict, mutated in place.
        env: The merged environment.
    """
    llm: dict[str, Any] = dict(overrides.get("llm") or {})

    if provider := env.get("LLM_PROVIDER"):
        llm["provider"] = provider.strip()
    if model := env.get("LLM_MODEL"):
        llm["model"] = model.strip()
    if base_url := env.get("LLM_BASE_URL"):
        llm["base_url"] = base_url.strip()

    # Resolve the key from the variable that belongs to the *selected* provider,
    # so a stale key for a different backend cannot be picked up by accident.
    provider_name = str(llm.get("provider", LLMSettings.model_fields["provider"].default))
    key_var = _PROVIDER_API_KEY_ENV.get(provider_name, "LLM_API_KEY")
    api_key = env.get(key_var) or env.get("LLM_API_KEY")
    if api_key and api_key.strip():
        llm["api_key"] = api_key.strip()

    if llm:
        overrides["llm"] = llm


def load_settings(settings_file: Path | None = None) -> Settings:
    """Build a :class:`Settings` from YAML plus the environment.

    Args:
        settings_file: Override for ``config/settings.yaml``. Tests use this to
            supply alternative thresholds without touching the repo file.

    Returns:
        A validated :class:`Settings`.

    Raises:
        ConfigurationError: If the YAML is unreadable, the resulting
            configuration is invalid, or a production deployment has no API key.
            Startup fails loudly rather than serving audits under thresholds that
            did not validate.
    """
    path = settings_file or Path(
        Settings.model_fields["settings_file"].default  # type: ignore[arg-type]
    )
    raw = _read_yaml(path)

    overrides: dict[str, Any] = {}
    for section in (
        "llm",
        "embedding",
        "nli",
        "input",
        "retrieval",
        "prompts",
        "orchestrator",
        "decision",
        "engines",
        "jobs",
    ):
        if isinstance(raw.get(section), dict):
            overrides[section] = raw[section]

    _apply_flat_env(overrides, _environment())

    try:
        settings = Settings(settings_file=path, **overrides)
    except Exception as exc:  # pydantic ValidationError and friends
        raise ConfigurationError(f"Invalid configuration in {path}: {exc}") from exc

    if settings.llm.api_key is None and settings.environment == "production":
        raise ConfigurationError(
            f"{settings.llm_api_key_env_var} is required in production: the "
            f"auditor cannot reach the {settings.llm.provider!r} provider "
            "without it."
        )
    return settings


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, loaded once.

    The cache exists so FastAPI dependencies and the service container observe
    the same instance. Prefer receiving a :class:`Settings` by injection over
    calling this — a module that reaches for the global is a module that cannot
    be tested under different thresholds.
    """
    return load_settings()
