r"""Provide UUID hashing utilities for Python dictionaries."""

from __future__ import annotations

__all__ = ["Key", "canonicalize_dict", "hash_dict_uuid"]

import json
import uuid
from typing import TYPE_CHECKING, Any, overload

if TYPE_CHECKING:
    from collections.abc import Callable

# Project-specific namespace for deterministic dict UUIDs.
# Generated once with uuid.uuid4() and fixed here so hashes are
# stable across runs and reproducible across environments.
_NAMESPACE = uuid.UUID("21e6c43e-bc36-4f09-8e20-98201adab5df")

# The mapping key types this module accepts - the same ones ``json.dumps``
# accepts and coerces to strings. Public so callers can annotate dicts
# with non-``str`` or mixed-type keys destined for :func:`canonicalize_dict`
# or :func:`hash_dict_uuid`.
Key = str | int | float | bool | None


def _stringify_key(key: Any) -> str:
    """Render a mapping key the way :func:`json.dumps` would.

    ``json.dumps`` happily coerces non-string keys (``None``, ``bool``,
    ``int``, ``float``) to their JSON string form, but ``sort_keys=True``
    sorts the *original* keys before that coercion happens - so a dict
    mixing key types (e.g. ``{"a": 1, 2: "b"}``) raises a raw
    ``TypeError: '<' not supported between instances of ...`` instead of
    producing a canonical form. Normalising keys to strings ourselves
    first, before sorting, avoids that crash for any dict whose keys
    ``json.dumps`` would otherwise accept.

    Args:
        key: The mapping key to render.

    Returns:
        The JSON string form of ``key``.

    Raises:
        TypeError: If ``key`` is of a type ``json.dumps`` would also
            reject as a mapping key.
    """
    if isinstance(key, str):
        return key
    if key is None or isinstance(key, (bool, int, float)):
        # ``bool`` is an ``int`` subclass, so this also covers True/False,
        # matching how ``json.dumps`` stringifies them ("true"/"false").
        return json.dumps(key)
    msg = f"keys must be str, int, float, bool or None, not {type(key).__name__}"
    raise TypeError(msg)


def _normalize(obj: Any) -> Any:
    """Recursively coerce mapping keys to strings ahead of
    serialisation.

    Walks ``dict`` and ``list``/``tuple`` containers so every nested
    mapping - not just the top-level one - has string keys before
    ``json.dumps(..., sort_keys=True)`` runs, avoiding the mixed-key-type
    crash described in :func:`_stringify_key`. Leaf values are passed
    through unchanged; unserialisable leaves are still reported by
    ``json.dumps`` itself (optionally via its ``default`` callback).

    Args:
        obj: The value to normalize.

    Returns:
        An equivalent structure with all mapping keys as strings.
    """
    if isinstance(obj, dict):
        return {_stringify_key(k): _normalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalize(v) for v in obj]
    return obj


@overload
def canonicalize_dict(
    data: dict[str, Any], *, default: Callable[[Any], Any] | None = None
) -> str: ...
@overload
def canonicalize_dict(
    data: dict[Key, Any], *, default: Callable[[Any], Any] | None = None
) -> str: ...
def canonicalize_dict(data: dict[Any, Any], *, default: Callable[[Any], Any] | None = None) -> str:
    """Serialise a dictionary into a single canonical JSON string.

    This is the one place that defines what "the same dict" means
    across the project: keys are sorted (so insertion order does not
    affect the result) and separators are fixed to the compact
    ``(",", ":")`` form (so whitespace differences between
    ``json.dumps`` call sites cannot affect the result either). Any
    code that needs a stable, reproducible representation of a dict -
    to hash it, derive a UUID from it, or compare two dicts for
    content equality - should go through this function rather than
    calling :func:`json.dumps` directly, so all such derivations stay
    consistent with each other for the same input.

    Keys are normalised to their JSON string form (recursively, for
    nested dicts) before sorting, so dicts whose keys are ``None``,
    ``bool``, ``int`` or ``float`` - or a mix of those with ``str`` -
    canonicalize the same way :func:`json.dumps` would render them,
    instead of raising a ``TypeError`` from comparing mixed key types.

    Args:
        data: The dictionary to canonicalize. Keys may be ``str`` or any
            mix of :data:`Key` types (``str``, ``int``, ``float``,
            ``bool``, ``None``).
        default: Optional :func:`json.dumps`-style ``default``
            callback for values that are not natively JSON-serialisable.
            Left as ``None`` (the ``json.dumps`` default), a
            non-serialisable value raises ``TypeError``.

    Returns:
        The canonical JSON string for ``data``.

    Raises:
        TypeError: If any value in ``data`` is not JSON-serialisable
            and no ``default`` is given (or ``default`` itself raises),
            or if a mapping key is of a type ``json.dumps`` would also
            reject.
    """
    return json.dumps(_normalize(data), sort_keys=True, separators=(",", ":"), default=default)


@overload
def hash_dict_uuid(data: dict[str, Any], *, default: Callable[[Any], Any] | None = None) -> str: ...
@overload
def hash_dict_uuid(data: dict[Key, Any], *, default: Callable[[Any], Any] | None = None) -> str: ...
def hash_dict_uuid(data: dict[Any, Any], *, default: Callable[[Any], Any] | None = None) -> str:
    """Compute a stable, reproducible UUID for a Python dictionary.

    Canonicalizes ``data`` via :func:`canonicalize_dict` to guarantee a
    consistent representation regardless of dict insertion order, then
    derives a deterministic UUID using :func:`uuid.uuid5` with a fixed
    project-specific namespace.

    Args:
        data: The dictionary to hash. Keys may be ``str`` or any mix of
            :data:`Key` types (``str``, ``int``, ``float``, ``bool``,
            ``None``); values must be JSON-serialisable, unless
            ``default`` is given.
        default: Optional :func:`json.dumps`-style ``default`` callback
            for values that are not natively JSON-serialisable, forwarded
            to :func:`canonicalize_dict`. Left as ``None``, such a value
            raises ``TypeError``.

    Returns:
        A lowercase UUID string of the form
        ``'xxxxxxxx-xxxx-5xxx-xxxx-xxxxxxxxxxxx'``.

    Raises:
        TypeError: If any value in ``data`` is not JSON-serialisable and
            no ``default`` is given (or ``default`` itself raises), or
            if a mapping key is of an unsupported type.

    Example:
        ```pycon
        >>> from persista.utils.hashing import hash_dict_uuid
        >>> hash_dict_uuid({"source": "cats.txt", "page": 1})  # doctest: +ELLIPSIS
        '...'
        >>> hash_dict_uuid({"page": 1, "source": "cats.txt"}) == hash_dict_uuid(
        ...     {"source": "cats.txt", "page": 1}
        ... )
        True

        ```
    """
    return str(uuid.uuid5(_NAMESPACE, canonicalize_dict(data, default=default)))
