from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

import pytest

from persista.store import BaseStore, normalize_on_conflict, validate_batch_size

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator, Mapping

    from persista.store import OnConflict


class InMemoryTestStore(BaseStore):
    r"""Minimal concrete implementation of ``BaseStore`` used to
    exercise the concrete methods it provides (``values``,
    ``set_batches``, ``__enter__``/``__exit__``)."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}
        self._closed = False

    def close(self) -> None:
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

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
            if key in self._data and on_conflict == "skip":
                continue
            if key in self._data and on_conflict == "merge":
                self._data[key] = {**self._data[key], **copy.deepcopy(value)}
                continue
            self._data[key] = copy.deepcopy(value)

    def filter(self, **field_filters: Any) -> list[dict[str, Any]]:
        if not field_filters:
            return [copy.deepcopy(value) for value in self._data.values()]
        return [
            copy.deepcopy(value)
            for value in self._data.values()
            if all(value.get(key) == val for key, val in field_filters.items())
        ]

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def delete_many(self, keys: list[str]) -> None:
        for key in keys:
            self.delete(key)

    def clear(self) -> None:
        self._data.clear()

    def contains(self, key: str) -> bool:
        return key in self._data

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
        items = list(self._data.items())
        for i in range(0, len(items), batch_size):
            yield dict(items[i : i + batch_size])

    def count(self) -> int:
        return len(self._data)

    def to_uri(self) -> str:
        return "test-memory://"

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> InMemoryTestStore:  # noqa: ARG003
        return cls()


@pytest.fixture
def store() -> InMemoryTestStore:
    return InMemoryTestStore()


def test_base_store_is_abstract() -> None:
    with pytest.raises(TypeError, match="abstract"):
        BaseStore()


def test_base_store_is_abstract_missing_to_uri_from_uri() -> None:
    class IncompleteStore(BaseStore):
        def get(self, key) -> None:
            return None

        def get_many(self, keys):
            return []

        def set(self, key, value, on_conflict="overwrite") -> None:
            pass

        def set_many(self, items, on_conflict="overwrite") -> None:
            pass

        def filter(self, **field_filters):
            return []

        def delete(self, key) -> None:
            pass

        def delete_many(self, keys) -> None:
            pass

        def clear(self) -> None:
            pass

        def contains(self, key) -> bool:
            return False

        def contains_many(self, keys):
            return [], []

        def keys(self):
            return iter(())

        def iter_batches(self, batch_size=32):
            yield from ()

        def count(self) -> int:
            return 0

        def close(self) -> None:
            pass

        @property
        def closed(self) -> bool:
            return False

    with pytest.raises(TypeError, match="abstract"):
        IncompleteStore()


def test_base_store_values(store: InMemoryTestStore) -> None:
    store.set_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
    values = list(store.values(batch_size=2))
    assert sorted(values, key=lambda v: v["a"]) == [{"a": 1}, {"a": 2}, {"a": 3}]


def test_base_store_set_batches(store: InMemoryTestStore) -> None:
    store.set_batches([("1", {"a": 1}), ("2", {"a": 2}), ("3", {"a": 3})], batch_size=2)
    assert store.count() == 3


def test_base_store_set_batches_default_batch_size(store: InMemoryTestStore) -> None:
    store.set_batches([(str(i), {"a": i}) for i in range(5)])
    assert store.count() == 5


def test_base_store_context_manager() -> None:
    with InMemoryTestStore() as store:
        assert not store.closed
    assert store.closed


# --- clear ---


def test_base_store_clear_removes_all_values(store: InMemoryTestStore) -> None:
    store.set_many({"1": {"a": 1}, "2": {"a": 2}})
    store.clear()
    assert store.count() == 0
    assert list(store.keys()) == []


def test_base_store_clear_empty_store_is_no_op(store: InMemoryTestStore) -> None:
    store.clear()
    assert store.count() == 0


def test_base_store_clear_returns_none(store: InMemoryTestStore) -> None:
    assert store.clear() is None
