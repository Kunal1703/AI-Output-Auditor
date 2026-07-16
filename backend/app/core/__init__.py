"""Core cross-cutting concerns: configuration, logging, errors, constants.

Depends on nothing but ``shared.schemas``, and is depended on by everything
else. Keep it that way — anything dimension-specific or decision-specific
belongs in its own package, not here.
"""
