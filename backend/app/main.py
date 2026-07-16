"""ASGI entry point.

Run from ``backend/``::

    uvicorn app.main:app --reload

The module exists only to expose the ASGI callable that uvicorn's
``module:attribute`` target needs. All construction lives in
:func:`app.api.main.create_app`, so tests build their own app with their own
settings rather than importing this module's instance.
"""

from __future__ import annotations

from app.api.main import create_app

__all__ = ["app"]

#: The ASGI application served by ``uvicorn app.main:app``.
app = create_app()
