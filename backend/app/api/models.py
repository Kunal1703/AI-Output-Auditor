"""API request and response models (Document 4, §7).

Pydantic models for the HTTP surface, kept separate from ``shared.schemas``.
The distinction matters: ``shared.schemas`` holds the *domain* contracts
(``AuditResult``, ``AuditReport``) that Documents 2 and 3 freeze; this module
holds the *transport* shapes that Document 4 §7 specifies. Coupling them would
let an HTTP convenience leak into a frozen contract.

The request contracts are verbatim from Document 4 §7.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.shared.schemas import JobStatus

__all__ = [
    "AuditOptions",
    "AuditTextRequest",
    "AuditUrlRequest",
    "AuditRequest",
    "AuditCreatedResponse",
    "AuditStatusResponse",
    "HealthResponse",
    "ErrorBody",
    "ErrorResponse",
]


class AuditOptions(BaseModel):
    """Optional request flags (Document 4, §7)."""

    model_config = ConfigDict(extra="allow")

    external_retrieval: bool = Field(
        default=False,
        description="Allow Accuracy to retrieve evidence beyond the supplied "
        "reference source. Accuracy is reference-first regardless; this only "
        "controls whether the optional external step runs at all (Document 2, "
        "§7.2, stage 5).",
    )


class AuditTextRequest(BaseModel):
    """``POST /audit/text`` — audit raw AI-generated text (Document 4, §7)."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, description="The AI-generated output under audit.")
    prompt: str | None = Field(
        default=None,
        description="The original instruction. Used by Relevance, Engagement, "
        "and Diversity. Without it those engines have no stated intent to "
        "measure against.",
    )
    reference_source: str | None = Field(
        default=None,
        description="Ground-truth text. Optional for Accuracy; **Coverage "
        "requires it in order to score** — completeness is meaningless without "
        "something to be complete with respect to.",
    )
    options: AuditOptions = Field(default_factory=AuditOptions)


class AuditUrlRequest(BaseModel):
    """``POST /audit/url`` — fetch, extract, and audit a URL (Document 4, §7)."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, description="The URL to fetch and audit.")
    prompt: str | None = None
    reference_source: str | None = None
    options: AuditOptions = Field(default_factory=AuditOptions)


class AuditRequest(BaseModel):
    """``POST /audit`` — the unified entry point.

    Accepts either ``text`` or ``url`` and dispatches to the matching path.
    Convenience over the type-specific endpoints, which remain available.
    """

    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(
        default=None, description="The output under audit. Mutually exclusive with url."
    )
    url: str | None = Field(
        default=None, description="A URL to fetch and audit. Mutually exclusive with text."
    )
    prompt: str | None = None
    reference_source: str | None = None
    options: AuditOptions = Field(default_factory=AuditOptions)

    @model_validator(mode="after")
    def _exactly_one_source(self) -> "AuditRequest":
        """Require exactly one of ``text`` or ``url``.

        Rejecting both rather than silently preferring one keeps it impossible
        to audit a different text than the caller believed they submitted.
        """
        has_text = bool(self.text and self.text.strip())
        has_url = bool(self.url and self.url.strip())
        if has_text == has_url:
            raise ValueError(
                "Provide exactly one of 'text' or 'url'."
                if not has_text
                else "Provide 'text' or 'url', not both."
            )
        return self


class AuditCreatedResponse(BaseModel):
    """Async creation response for every ``POST /audit*`` (Document 4, §7)."""

    audit_id: str = Field(description="Retrieve the report with this id.")
    status: JobStatus = Field(default=JobStatus.PROCESSING)


class AuditStatusResponse(BaseModel):
    """``GET /audit/{id}/status`` (Document 4, §7).

    ``engines_completed`` reflects **actual** engine completion, not elapsed
    time. Document 4 §8: "Progress is real." A system whose premise is not
    overstating what it knows should not begin by faking a progress bar.
    """

    audit_id: str
    status: JobStatus
    engines_completed: int = Field(ge=0)
    engines_total: int = Field(ge=0)
    error: str | None = Field(
        default=None, description="Failure reason. Present only when status is failed."
    )


class HealthResponse(BaseModel):
    """``GET /health`` (Document 4, §7)."""

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
    engines_registered: int | None = Field(
        default=None, description="Registered engines. Should be 8."
    )
    embedding_model: str | None = None
    embedding_cache_enabled: bool | None = None
    embedding_cache_hit_rate: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Fraction of embedding lookups served from the shared "
        "cache. A rate near zero with caching enabled usually means the model "
        "id is changing between calls, which silently doubles embedding cost.",
    )
    prompt_templates: int | None = Field(
        default=None,
        description="Prompt templates discovered under config/prompts/. Zero "
        "means every LLM-backed stage will degrade.",
    )


class ErrorBody(BaseModel):
    """The inner object of the frozen error contract."""

    code: str
    message: str


class ErrorResponse(BaseModel):
    """``{ "error": { "code": "...", "message": "..." } }`` (Document 4, §7)."""

    error: ErrorBody
