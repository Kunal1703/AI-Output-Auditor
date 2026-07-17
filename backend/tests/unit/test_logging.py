"""Structured logging (Document 4, §12).

One rule under test above all: **a logging call must never be able to fail the
operation it describes.** An audit lost to its own telemetry is the worst kind
of bug — the system was working, and the record of it killed it.
"""

from __future__ import annotations

import logging

import pytest

from app.core.logging import _RESERVED_LOG_FIELDS, bind, get_logger

pytestmark = pytest.mark.unit


def test_bind_passes_ordinary_fields_through():
    assert bind(audit_id="aud_1", dimension="Accuracy") == {
        "audit_id": "aud_1",
        "dimension": "Accuracy",
    }


@pytest.mark.parametrize("reserved", sorted(_RESERVED_LOG_FIELDS))
def test_reserved_field_never_raises(reserved, caplog):
    """`LogRecord` owns these names and refuses to have them overwritten.

    Several are exactly the words a caller reaches for — `filename`, `module`,
    `name`, `process`, `args`. Uploading a file crashed a whole audit on
    `bind(filename=…)` before this guard existed.
    """
    logger = get_logger("test.reserved")
    with caplog.at_level(logging.INFO):
        logger.info("event", extra=bind(**{reserved: "value"}))
    assert caplog.records, f"logging with extra={reserved!r} produced no record"


def test_reserved_field_is_renamed_not_dropped():
    """The value survives; only the key moves out of the way."""
    bound = bind(filename="notes.md", module="x", audit_id="aud_1")
    assert bound["filename_"] == "notes.md"
    assert bound["module_"] == "x"
    assert bound["audit_id"] == "aud_1"
    assert "filename" not in bound


def test_real_call_site_shape_is_safe(caplog):
    """The exact shape the content extractor logs on a file upload."""
    logger = get_logger("test.extractor")
    with caplog.at_level(logging.INFO):
        logger.info(
            "file extracted",
            extra=bind(
                file="notes.md", extractor="plain", characters=412, byte_count=980
            ),
        )
    assert caplog.records[0].message == "file extracted"
