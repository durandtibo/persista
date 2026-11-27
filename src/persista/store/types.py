r"""Provide the abstract base class for key-value stores."""

from __future__ import annotations

__all__ = ["OnConflict", "Payload", "Plan"]

from collections.abc import Callable
from typing import Literal

Payload = str | bytes
"""A value as a codec encodes it, which is what a backend stores.

See :class:`~persista.store.Codec`.
"""

Plan = Callable[[dict[str, Payload]], dict[str, Payload]]
"""The conflict resolution of a write, given to
:meth:`BaseStore._update`.

A plan is called with the payloads of the keys that already exist in the
store, and returns the payloads to write. It raises :class:`KeyError` if
the write must not happen. It has no side effect, so it can be called
again, for example after an optimistic retry.
"""

OnConflict = Literal["raise", "skip", "overwrite", "merge"]
"""Strategy for handling keys that already exist in the store.

Used by :meth:`BaseStore.set`, :meth:`BaseStore.set_many`, and
:meth:`BaseStore.set_batches` to control what happens when a key being
written already has a value in the store.

Example:
    ```pycon
    >>> from persista.store import InMemoryStore
    >>> with InMemoryStore() as store:
    ...     store.set("key", {"a": 1})
    ...     store.set("key", {"b": 2}, on_conflict="merge")
    ...     store.get("key")
    ...
    {'a': 1, 'b': 2}

    ```
"""
