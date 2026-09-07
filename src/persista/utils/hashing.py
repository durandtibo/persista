r"""Provide UUID hashing utilities for Python dictionaries."""

from __future__ import annotations

__all__ = ["canonicalize_dict", "hash_dict_uuid"]

import json
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

# Project-specific namespace for deterministic dict UUIDs.
# Generated once with uuid.uuid4() and fixed here so hashes are
# stable across runs and reproducible across environments.
_NAMESPACE = uuid.UUID("21e6c43e-bc36-4f09-8e20-98201adab5df")


def canonicalize_dict(data: dict[str, Any], *, default: Callable[[Any], Any] | None = None) -> str:
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

    Args:
        data: The dictionary to canonicalize.
        default: Optional :func:`json.dumps`-style ``default``
            callback for values that are not natively JSON-serialisable.
            Left as ``None`` (the ``json.dumps`` default), a
            non-serialisable value raises ``TypeError``.

    Returns:
        The canonical JSON string for ``data``.

    Raises:
        TypeError: If any value in ``data`` is not JSON-serialisable
            and no ``default`` is given (or ``default`` itself raises).
    """
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=default)


def hash_dict_uuid(data: dict[str, Any]) -> str:
    """Compute a stable, reproducible UUID for a Python dictionary.

    Canonicalizes ``data`` via :func:`canonicalize_dict` to guarantee a
    consistent representation regardless of dict insertion order, then
    derives a deterministic UUID using :func:`uuid.uuid5` with a fixed
    project-specific namespace.

    Args:
        data: The dictionary to hash.  All values must be
            JSON-serialisable.

    Returns:
        A lowercase UUID string of the form
        ``'xxxxxxxx-xxxx-5xxx-xxxx-xxxxxxxxxxxx'``.

    Raises:
        TypeError: If any value in ``data`` is not JSON-serialisable.

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
    return str(uuid.uuid5(_NAMESPACE, canonicalize_dict(data)))
