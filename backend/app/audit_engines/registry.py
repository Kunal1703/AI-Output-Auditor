"""Engine Registry — maps each dimension to its engine class.

The orchestrator needs to construct eight engines without importing eight
modules and hardcoding eight names. This registry is that indirection: engines
register themselves at import, and the orchestrator asks for a dimension.

Registration is validated on the spot. An engine whose ``dimension`` is not one
of the frozen eight, or a second engine claiming a dimension already taken, is
rejected at import rather than at audit time — the dimension set is closed
(Document 4, §14), and a silent overwrite would make the active engine depend on
import order.

:func:`validate_registry` gives the container a startup check that all eight
dimensions are actually covered, so a missing engine surfaces as a failed boot
rather than as a report with seven dimensions in it.
"""

from __future__ import annotations

from typing import Callable, Iterable, Mapping, Type, TypeVar

from app.audit_engines.base import AuditEngine, EngineServices
from app.core.constants import ALL_DIMENSIONS, DIMENSION_SPECS
from app.core.errors import ConfigurationError

__all__ = [
    "register_engine",
    "get_engine_class",
    "registered_dimensions",
    "build_engines",
    "validate_registry",
]

_REGISTRY: dict[str, Type[AuditEngine]] = {}

E = TypeVar("E", bound=AuditEngine)


def register_engine(cls: Type[E]) -> Type[E]:
    """Class decorator registering an engine for its declared dimension.

    Usage::

        @register_engine
        class AccuracyAuditEngine(AuditEngine):
            dimension = "Accuracy"

    Args:
        cls: The engine class. Its ``dimension`` must be one of the frozen
            eight.

    Returns:
        ``cls`` unchanged, so the decorator is transparent.

    Raises:
        ConfigurationError: If the dimension is unknown or already registered.
    """
    dimension = getattr(cls, "dimension", "")
    if not dimension:
        raise ConfigurationError(
            f"{cls.__name__} must declare a 'dimension' class attribute to be "
            "registered."
        )
    if dimension not in DIMENSION_SPECS:
        raise ConfigurationError(
            f"{cls.__name__} declares dimension {dimension!r}, which is not one "
            f"of the eight frozen dimensions: {', '.join(ALL_DIMENSIONS)}."
        )
    existing = _REGISTRY.get(dimension)
    if existing is not None and existing is not cls:
        raise ConfigurationError(
            f"Dimension {dimension!r} is already served by {existing.__name__}; "
            f"{cls.__name__} cannot also claim it."
        )
    _REGISTRY[dimension] = cls
    return cls


def get_engine_class(dimension: str) -> Type[AuditEngine]:
    """Return the engine class serving ``dimension``.

    Args:
        dimension: A dimension name.

    Returns:
        The registered engine class.

    Raises:
        ConfigurationError: If no engine is registered for the dimension.
    """
    try:
        return _REGISTRY[dimension]
    except KeyError as exc:
        raise ConfigurationError(
            f"No engine registered for dimension {dimension!r}. Registered: "
            f"{', '.join(registered_dimensions()) or 'none'}."
        ) from exc


def registered_dimensions() -> tuple[str, ...]:
    """Return the dimensions that currently have an engine, in frozen order."""
    return tuple(d for d in ALL_DIMENSIONS if d in _REGISTRY)


def validate_registry() -> None:
    """Assert that all eight frozen dimensions have an engine.

    Called at startup by the service container. A report is defined over all
    eight dimensions; discovering a missing one mid-audit would produce a
    verdict built on an incomplete measurement set.

    Raises:
        ConfigurationError: If any dimension lacks an engine.
    """
    missing = [d for d in ALL_DIMENSIONS if d not in _REGISTRY]
    if missing:
        raise ConfigurationError(
            f"No engine registered for: {', '.join(missing)}. All eight "
            "dimensions must be served."
        )


def build_engines(
    services: EngineServices, dimensions: Iterable[str] | None = None
) -> Mapping[str, AuditEngine]:
    """Instantiate engines for ``dimensions`` with shared services.

    Args:
        services: The injected Shared Services handed to each engine.
        dimensions: Which dimensions to build. Defaults to all registered ones.

    Returns:
        Engine instances keyed by dimension.

    Raises:
        ConfigurationError: If a requested dimension has no registered engine.
    """
    wanted = tuple(dimensions) if dimensions is not None else registered_dimensions()
    return {d: get_engine_class(d)(services) for d in wanted}
