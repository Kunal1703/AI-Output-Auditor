"""Shared Services — the reusable capabilities every engine consumes.

Document 2 §5 and Document 4 §4. This package is the single place each
cross-cutting concern is implemented, and it enforces the rule that keeps the
engines thin and the providers swappable:

    An engine never calls a provider SDK, an HTTP client, or a model directly.
    It calls a Shared Service. (Document 4, §4)

``schemas`` is the contract boundary of the whole system and is imported by
everything; the services are injected into engines by the container in
``app.app`` (Document 4, §4) rather than imported as globals.

``context`` holds the ``SharedContext`` — produced by Preprocessing, passed to
every engine. It lives here rather than in ``preprocessing`` so the dependency
arrow keeps pointing one way: engines depend on ``shared``, never on the layer
that happens to construct their input (Document 1, §6).

This module stays import-free on purpose. ``core.config`` imports
``shared.schemas``, so re-exporting submodules here would put ``core`` and
``shared`` into an import cycle that only shows up as an error at startup.
Import from the submodule directly: ``from app.shared.context import SharedContext``.
"""
