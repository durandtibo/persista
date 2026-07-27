r"""Provide the abstract base class for key-value stores."""

from __future__ import annotations

__all__ = ["OnConflict"]

from typing import Literal

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
