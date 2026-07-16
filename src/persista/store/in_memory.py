r"""Provide an in-memory implementation of ``BaseStore``."""

from __future__ import annotations

__all__ = ["InMemoryStore"]

import copy
import logging
from typing import TYPE_CHECKING, Any

from coola.display import InlineDisplayMixin
from coola.utils.batching import batchify

from persista.store.base import BaseStore
from persista.store.validation import normalize_on_conflict, validate_batch_size

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator, Mapping

    from persista.store.types import OnConflict


logger: logging.Logger = logging.getLogger(__name__)


class InMemoryStore(BaseStore, InlineDisplayMixin):
    """A :class:`~persista.store.BaseStore` implementation backed
    by a plain ``dict``.

    Values are held entirely in process memory -- nothing is
    persisted to disk. This is primarily useful for testing,
    small-scale exploration, or pipelines that don't need durability.

    Values are deep-copied on both write and read so that mutating a
    value returned by this store (or a value passed into :meth:`set`
    / :meth:`set_many`) never affects the store's internal state.
    This trades some performance for isolation; for very large values
    or hot loops, consider a store that doesn't copy on every access.

    Example:
        ```pycon
        >>> from persista.store import InMemoryStore
        >>> store = InMemoryStore()
        >>> store.set("1", {"text": "hello"})
        >>> store.count()
        1
        >>> store.get("1")
        {'text': 'hello'}

        ```
    """

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    @property
    def data(self) -> dict[str, dict[str, Any]]:
        return self._data

    def close(self) -> None:
        # Discard all values: an in-memory store has nothing to
        # persist, so closing (and later reopening via the context
        # manager) it is equivalent to starting over with a fresh,
        # empty store.
        self._data.clear()

    def get(self, key: str) -> dict[str, Any] | None:
        value = self._data.get(key)
        return copy.deepcopy(value) if value is not None else None

    def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        return [self.get(key) for key in keys]

    def set(self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite") -> None:
        self.set_many({key: value}, on_conflict=on_conflict)

    def set_many(
        self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
    ) -> None:
        on_conflict = normalize_on_conflict(on_conflict)

        conflicts = [key for key in items if key in self._data]
        if conflicts and on_conflict == "raise":
            msg = f"Key(s) already exist in the store: {conflicts}"
            raise KeyError(msg)

        for key, value in items.items():
            if key in self._data:
                if on_conflict == "skip":
                    continue
                if on_conflict == "merge":
                    self._data[key] = {**self._data[key], **copy.deepcopy(value)}
                    continue
            self._data[key] = copy.deepcopy(value)

        logger.debug("Added/replaced %d key-value pair(s)", len(items))

    def filter(self, **field_filters: Any) -> list[dict[str, Any]]:
        if not field_filters:
            return [copy.deepcopy(value) for value in self._data.values()]

        matches = [
            value
            for value in self._data.values()
            if all(value.get(key) == val for key, val in field_filters.items())
        ]
        return [copy.deepcopy(value) for value in matches]

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def delete_many(self, keys: list[str]) -> None:
        for key in keys:
            self.delete(key)

    def contains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        found = [key for key in keys if key in self._data]
        missing = [key for key in keys if key not in self._data]
        return found, missing

    def keys(self) -> Iterator[str]:
        yield from list(self._data.keys())

    def iter_batches(
        self, batch_size: int = 32
    ) -> Generator[dict[str, dict[str, Any]], None, None]:
        validate_batch_size(batch_size)
        for batch in batchify(self._data.items(), size=batch_size):
            yield dict(batch)

    def count(self) -> int:
        return len(self._data)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"count": self.count()}
