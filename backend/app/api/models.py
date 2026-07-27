"""API request and response models (transport shapes).

Kept separate from ``shared.schemas`` (the domain contracts): this module holds
only the HTTP surface for the AI Output Auditor — the ``{source, outputs[]}``
request, the health response, and the frozen error contract.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.shared.schemas import (
    AuditOptions as DomainAuditOptions,
    OutputInput,
    SourceInput,
)

__all__ = [
    "AuditOutputsRequest",
    "HealthResponse",
    "ErrorBody",
    "ErrorResponse",
]


class AuditOutputsRequest(BaseModel):
    """``POST /audit/outputs`` — the AI Output Auditor entry point.

    Audits one or more outputs against a mandatory source article and returns a
    ``ComparativeReport``. Reuses the domain input contracts
    (``SourceInput``/``OutputInput``) rather than redefining them.
    """

    model_config = ConfigDict(extra="forbid")

    source: SourceInput = Field(description="The mandatory ground-truth source article.")
    outputs: list[OutputInput] = Field(
        min_length=1, description="One or more outputs to audit against the source."
    )
    options: DomainAuditOptions = Field(default_factory=DomainAuditOptions)


class HealthResponse(BaseModel):
    """``GET /health``."""

    status: str = Field(description="'ok' when the service is live.")
    llm_provider: str
    version: str
    llm_model: str | None = None
    llm_configured: bool | None = Field(
        default=None, description="Whether the provider has credentials."
    )
    llm_reachable: bool | None = Field(
        default=None, description="Whether the provider answered a probe."
    )
    llm_model_available: bool | None = Field(
        default=None,
        description="Whether the configured model is one the key is currently "
        "served. None means it could not be checked (offline).",
    )
    embedding_model: str | None = None
    embedding_cache_enabled: bool | None = None
    embedding_cache_hit_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    prompt_templates: int | None = Field(
        default=None,
        description="Prompt templates discovered under config/prompts/.",
    )
    nli_model: str | None = Field(
        default=None,
        description="The configured local NLI model id — the backbone of Layer 1 "
        "and Attribution.",
    )
    nli_ready: bool | None = Field(
        default=None,
        description="Whether the local NLI model is loaded and ready to score.",
    )


class ErrorBody(BaseModel):
    """The inner object of the frozen error contract."""

    code: str
    message: str


class ErrorResponse(BaseModel):
    """``{ "error": { "code": "...", "message": "..." } }``."""

    error: ErrorBody
