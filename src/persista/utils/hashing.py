r"""Provide UUID hashing utilities for Python dictionaries."""

from __future__ import annotations

__all__ = ["hash_dict_uuid"]

import json
import uuid
from typing import Any

# Project-specific namespace for deterministic dict UUIDs.
# Generated once with uuid.uuid4() and fixed here so hashes are
# stable across runs and reproducible across environments.
_NAMESPACE = uuid.UUID("21e6c43e-bc36-4f09-8e20-98201adab5df")


def hash_dict_uuid(data: dict[str, Any]) -> str:
    """Compute a stable, reproducible UUID for a Python dictionary.

    Serialises ``data`` via :func:`json.dumps` with ``sort_keys=True``
    to guarantee a consistent ordering regardless of dict insertion
    order, then derives a deterministic UUID using :func:`uuid.uuid5`
    with a fixed project-specific namespace.

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
    return str(uuid.uuid5(_NAMESPACE, json.dumps(data, sort_keys=True, separators=(",", ":"))))
