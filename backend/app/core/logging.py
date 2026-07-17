"""Structured logging utilities.

Document 4 §12 requires structured logs per stage — engine start/finish,
durations, provider errors, degradations — for debugging and demo transparency,
and adds one privacy rule that this module enforces by construction:

    *Log evidence/finding ids, not full content, where sensitive.*

That rule is why :func:`bind` takes ids and durations rather than text. The
content under audit is the user's; it belongs in the report, not in a log file
or an aggregator. When you need to correlate a log line to a span, log the
``evidence_id`` and let the reader resolve it through the report.

Two formatters are available, selected by ``AUDITOR_LOG_FORMAT``: ``text`` for
readable local development, ``json`` for machine ingestion in deployment.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from contextlib import contextmanager
from typing import Any, Iterator

__all__ = [
    "configure_logging",
    "get_logger",
    "bind",
    "log_duration",
    "JsonFormatter",
]

#: Keys the LogRecord always carries; anything else in ``__dict__`` is context
#: added via ``extra=`` and is emitted as structured fields.
_RESERVED = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """Render records as one JSON object per line.

    Any keyword passed through ``extra=`` becomes a top-level field, so
    ``logger.info("engine finished", extra=bind(dimension="Accuracy"))`` emits a
    queryable ``dimension`` field rather than an unparseable message string.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _TextFormatter(logging.Formatter):
    """Human-readable format with context appended as ``key=value`` pairs."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-7s %(name)-38s %(message)s",
            datefmt="%H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        context = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED and not key.startswith("_")
        }
        if context:
            rendered = " ".join(f"{k}={v}" for k, v in sorted(context.items()))
            base = f"{base}  [{rendered}]"
        return base


def configure_logging(level: str = "INFO", fmt: str = "text") -> None:
    """Install the root logging configuration.

    Idempotent: existing handlers on the root logger are replaced, so calling
    this from both application startup and a test fixture will not duplicate
    output.

    Args:
        level: A standard level name, e.g. ``"INFO"`` or ``"DEBUG"``.
        fmt: ``"text"`` or ``"json"``. Unknown values fall back to ``"text"``.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt.lower() == "json" else _TextFormatter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())

    # These are chatty at INFO and drown out the stage logs that matter.
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return the module logger for ``name``.

    Call as ``get_logger(__name__)`` so the emitted logger name reflects the
    module path and log lines are attributable to a stage.
    """
    return logging.getLogger(name)


#: Attribute names ``logging.LogRecord`` owns. Passing any of them through
#: ``extra=`` raises ``KeyError: Attempt to overwrite ... in LogRecord``.
#:
#: This list is a trap, not a curiosity. Several entries — ``filename``,
#: ``module``, ``name``, ``process``, ``args``, ``msg`` — are exactly the words
#: a caller reaches for when describing what they are logging, and the failure
#: is a hard exception at the call site rather than a dropped field. Uploading a
#: file crashed an entire audit on ``bind(filename=…)`` before this guard
#: existed.
_RESERVED_LOG_FIELDS: frozenset[str] = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message", "module",
        "msecs", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "taskName", "thread", "threadName",
    }
)


def bind(**context: Any) -> dict[str, Any]:
    """Build an ``extra=`` mapping of structured fields.

    Pass ids and measurements, not content::

        logger.info(
            "critical finding recorded",
            extra=bind(audit_id=audit_id, dimension="Credibility",
                       finding_id="cf_3", severity="high"),
        )

    Do not pass the claim text, the output under audit, or a retrieved passage.
    Document 4 §12 restricts logs to ids for exactly this reason.

    **Reserved names are renamed rather than rejected.** A field colliding with a
    ``LogRecord`` attribute (``filename``, ``module``, ``name``, …) is suffixed
    with an underscore instead of raising. A logging call must never be able to
    fail the operation it is describing — an audit that crashes because of the
    word chosen for a log field is an audit lost to its own telemetry.

    Args:
        **context: Structured fields to attach to the record.

    Returns:
        A mapping safe to pass as the ``extra`` argument of a logging call.
    """
    return {
        (f"{key}_" if key in _RESERVED_LOG_FIELDS else key): value
        for key, value in context.items()
    }


@contextmanager
def log_duration(
    logger: logging.Logger, event: str, **context: Any
) -> Iterator[dict[str, Any]]:
    """Log the start and end of a stage, with its duration.

    On success emits ``<event> finished`` at INFO with ``duration_ms``. On
    failure emits ``<event> failed`` at ERROR with the duration and exception,
    then re-raises — this observes, it does not swallow. Deciding whether a
    failure degrades a dimension or fails the run belongs to the caller.

    Args:
        logger: The stage's logger.
        event: A stage name, e.g. ``"engine.accuracy"``.
        **context: Structured fields, subject to the ids-not-content rule.

    Yields:
        A mutable dict merged into the completion record, letting the body add
        outcome fields such as ``{"engines_completed": 6}``.
    """
    extra: dict[str, Any] = dict(context)
    started = time.perf_counter()
    logger.info(f"{event} started", extra=bind(**extra))
    try:
        yield extra
    except Exception as exc:
        elapsed = (time.perf_counter() - started) * 1000
        logger.error(
            f"{event} failed",
            extra=bind(**extra, duration_ms=round(elapsed, 2), error=type(exc).__name__),
            exc_info=True,
        )
        raise
    else:
        elapsed = (time.perf_counter() - started) * 1000
        logger.info(f"{event} finished", extra=bind(**extra, duration_ms=round(elapsed, 2)))
