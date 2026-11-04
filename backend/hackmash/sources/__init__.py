"""Source adapter registry.

Every module in this package (except ``base`` and names starting with ``_``)
is imported and scanned for ``Source`` subclasses with a ``key``. Adding a
platform means adding one module; nothing else needs editing.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil

from .base import Source

log = logging.getLogger("hackmash.sources")

_registry: dict[str, type[Source]] | None = None
import_errors: dict[str, str] = {}


def discover(refresh: bool = False) -> dict[str, type[Source]]:
    global _registry
    if _registry is not None and not refresh:
        return _registry
    found: dict[str, type[Source]] = {}
    import_errors.clear()
    for mod in pkgutil.iter_modules(__path__):
        if mod.name == "base" or mod.name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"{__name__}.{mod.name}")
        except Exception as exc:  # one broken adapter must not take down the rest
            log.exception("failed to import source module %s", mod.name)
            import_errors[mod.name] = repr(exc)
            continue
        for obj in vars(module).values():
            if (
                isinstance(obj, type)
                and issubclass(obj, Source)
                and obj is not Source
                and getattr(obj, "key", None)
                and obj.__module__ == module.__name__
            ):
                found[obj.key] = obj
    _registry = dict(sorted(found.items()))
    return _registry


def enabled_sources() -> dict[str, type[Source]]:
    return {k: v for k, v in discover().items() if v.enabled}
