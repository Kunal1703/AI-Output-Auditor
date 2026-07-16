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
    "RetrievalSettings",
    "PromptSettings",
    "OrchestratorSettings",
    "DecisionSettings",
    "AccuracyEngineSettings",
    "CredibilityEngineSettings",
    "RelevanceEngineSettings",
    "CoverageEngineSettings",
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
        default="qwen/qwen3-32b",
        description="Provider-qualified model id. Set via LLM_MODEL.",
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
    reasoning_format: str | None = Field(
        default=None,
        description="Groq-only. 'hidden' suppresses a reasoning model's "
        "<think> block, which would otherwise corrupt the structured JSON the "
        "engine pipelines parse. Valid only on reasoning models (the default "
        "qwen/qwen3-32b is one) — leave null for any other provider or model, "
        "since they reject the parameter.",
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


class EngineSettings(BaseModel):
    """Per-engine tunables, grouped."""

    accuracy: AccuracyEngineSettings = Field(default_factory=AccuracyEngineSettings)
    credibility: CredibilityEngineSettings = Field(
        default_factory=CredibilityEngineSettings
    )
    relevance: RelevanceEngineSettings = Field(default_factory=RelevanceEngineSettings)
    coverage: CoverageEngineSettings = Field(default_factory=CoverageEngineSettings)


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
