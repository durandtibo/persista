r"""Provide a resolution utility for creating persista ``Cache``
instances."""

from __future__ import annotations

__all__ = ["resolve_cache"]

from typing import Any

from coola.factory import resolve_object

from persista.cache.cache import Cache


def resolve_cache(cache: Cache | dict[str, Any]) -> Cache:
    """Resolve a :class:`~persista.cache.Cache` instance from an
    existing object or a configuration dictionary.

    If ``cache`` is already a :class:`~persista.cache.Cache`
    instance it is returned as-is. If it is a :class:`dict`, it is
    treated as an ``objectory`` factory configuration and instantiated
    via :func:`objectory.factory`. See
    :func:`~coola.factory.resolve_object` for details.

    Args:
        cache: Either a fully configured
            :class:`~persista.cache.Cache` instance, or a
            :class:`dict` containing an ``objectory`` factory
            specification (must include a ``"_target_"`` key
            pointing to the fully-qualified class name).

    Returns:
        A configured :class:`~persista.cache.Cache` instance.

    Raises:
        TypeError: If the resolved object is not a
            :class:`~persista.cache.Cache` instance.

    Example:
        ```pycon
        >>> from persista.cache import Cache, resolve_cache
        >>> # From an existing instance:
        >>> cache = resolve_cache(Cache())
        >>> # From a configuration dictionary:
        >>> cache = resolve_cache({"_target_": "persista.cache.Cache"})

        ```
    """
    return resolve_object(cache, cls=Cache)
