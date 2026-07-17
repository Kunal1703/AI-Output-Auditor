"""Error taxonomy for the auditor backend.

Document 4 §7 fixes the wire error contract::

    { "error": { "code": "...", "message": "..." } }

Every exception raised deliberately by backend code derives from
:class:`AuditorError` so the API layer can translate it into that shape without
inspecting exception types from third-party libraries. Anything that escapes as
a bare ``Exception`` is a bug and is reported as ``internal_error``.

Note the deliberate omission: there is no exception for "an engine failed".
Engine and provider failures must not crash a run. They degrade into a
low-confidence ``AuditResult`` that the Decision Engine reads as a verification
gap, biasing the verdict toward *Unable to Verify* rather than a silent pass
(Document 3, §8; Document 4, §12).
"""

from __future__ import annotations

__all__ = [
    "AuditorError",
    "ConfigurationError",
    "ValidationError",
    "NotFoundError",
    "UnsupportedInputError",
    "ExtractionError",
    "ProviderError",
    "ProviderTimeoutError",
    "PromptNotFoundError",
]


class AuditorError(Exception):
    """Base class for every error the auditor raises on purpose.

    Attributes:
        code: Stable, machine-readable identifier placed in ``error.code`` on
            the wire. Clients may branch on this; the message is for humans and
            may change.
        message: Human-readable explanation placed in ``error.message``.
        http_status: The HTTP status the API layer should use.
    """

    code: str = "internal_error"
    http_status: int = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def to_payload(self) -> dict[str, dict[str, str]]:
        """Render this error in the frozen wire contract (Document 4, §7)."""
        return {"error": {"code": self.code, "message": self.message}}


class ConfigurationError(AuditorError):
    """Configuration is missing, malformed, or internally inconsistent.

    Raised at startup rather than per-request: a misconfigured auditor should
    fail loudly on boot instead of degrading silently into wrong verdicts.
    """

    code = "configuration_error"
    http_status = 500


class ValidationError(AuditorError):
    """A request or internal object violates its contract."""

    code = "validation_error"
    http_status = 422


class NotFoundError(AuditorError):
    """A referenced resource — typically an ``audit_id`` — does not exist."""

    code = "not_found"
    http_status = 404


class UnsupportedInputError(AuditorError):
    """The submitted input type or media type cannot be audited."""

    code = "unsupported_input"
    http_status = 415


class ExtractionError(AuditorError):
    """Content could not be extracted from a URL or file into clean text."""

    code = "extraction_error"
    http_status = 422


class ProviderError(AuditorError):
    """An upstream provider (LLM, embedding, retrieval target) failed.

    Shared Services raise this after their bounded retries are exhausted
    (Document 4, §12). Callers inside an engine are expected to catch it and
    degrade, not to propagate it to the API.

    **Not every provider failure is worth retrying, and retrying the ones that
    are not is how a misconfiguration becomes a timeout.** A missing key, a
    rejected key, and a malformed request will fail identically on the fourth
    attempt as on the first; the only thing the retries buy is backoff. With
    eight engines each making several calls, that turns a clear configuration
    error into minutes of silence — the failure mode most likely to greet a
    first-time user, who has by definition not set up their key yet.

    So the classification travels with the error. The provider knows why it
    failed; the LLM Service knows what to do about it. Neither has to guess.

    Args:
        message: Human-readable explanation.
        retryable: Whether another identical attempt could plausibly succeed.
            Defaults to ``True``, which preserves the behavior of every raise
            site that does not care — transient failure is the common case, and
            a provider that has not been taught the distinction should keep
            retrying rather than silently stop.
        retry_after: Seconds the provider asked the caller to wait, from a
            ``Retry-After`` header. Honored as a floor on the backoff — a
            rate limiter that names its own interval knows better than our
            exponential curve does.
        status_code: The upstream HTTP status, when there was one. Recorded for
            logs and for the classification itself.

    Attributes:
        retryable: See above.
        retry_after: See above.
        status_code: See above.
    """

    code = "provider_error"
    http_status = 502

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = True,
        retry_after: float | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after
        self.status_code = status_code


class ProviderTimeoutError(ProviderError):
    """An upstream provider exceeded its configured timeout.

    Retryable by default: a timeout is the canonical transient failure, and the
    next attempt may well land.
    """

    code = "provider_timeout"
    http_status = 504


class PromptNotFoundError(ConfigurationError):
    """A requested prompt template does not exist in ``config/prompts/``."""

    code = "prompt_not_found"
    http_status = 500
