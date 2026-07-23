# Unified Sync+Async Stores Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge `BaseStore`/`AsyncBaseStore` into a single `BaseStore` ABC so each backend is one class (e.g. `SQLiteStore`) with both sync methods (`get`, `set`, ...) and async twins (`aget`, `aset`, ...).

**Architecture:** `BaseStore` declares paired abstract methods for every operation. Category-A backends (SQLite, Postgres, Redis) hold two connections — sync eager, async lazy — and implement both sides natively (SQLite falls back to `asyncio.to_thread` if `aiosqlite` isn't installed). Category-B backends (in-memory, null, file, lmdb, duckdb) have one connection and get their async side for free via a `ThreadedAsyncStoreMixin` that wraps every sync method in `asyncio.to_thread`.

**Tech Stack:** Python 3.13, sqlite3/aiosqlite, psycopg (sync+async), redis-py (sync+async), duckdb, lmdb, pytest.

## Global Constraints

- No change to on-disk formats, table schemas, or URI encoding (verbatim port of existing SQL/encoding logic).
- No change to `OnConflict` semantics — `aset`/`aset_many` apply the same `raise`/`skip`/`overwrite`/`merge` rules as `set`/`set_many`.
- `AsyncBaseStore` and every `Async*Store` class are removed with no deprecation aliases (pre-1.0 package).
- `iter_batches`/`aiter_batches` abstract signatures use `Iterator`/`AsyncIterator`; implementations stay plain generator functions.
- Every commit must leave `pytest tests/unit -q` green (integration tests may skip without live services).

---

### Task 1: Rewrite `BaseStore` ABC, remove `AsyncBaseStore`

**Files:**
- Modify: `src/persista/store/base.py` (full rewrite)
- Test: `tests/unit/store/test_base.py` (merge `tests/unit/store/test_base_async.py` into it, then delete that file)

**Interfaces:**
- Produces: `BaseStore` with abstract `get`/`aget`, `get_many`/`aget_many`, `set`/`aset`, `set_many`/`aset_many`, `filter`/`afilter`, `delete`/`adelete`, `delete_many`/`adelete_many`, `clear`/`aclear`, `contains`/`acontains`, `contains_many`/`acontains_many`, `keys() -> Iterator[str]`/`akeys() -> AsyncIterator[str]`, `iter_batches(batch_size=32) -> Iterator[dict[str, dict[str, Any]]]`/`aiter_batches(batch_size=32) -> AsyncIterator[dict[str, dict[str, Any]]]`, `count`/`acount`, `close`/`aclose`, `closed` property, `to_uri`, `from_uri`. Concrete: `set_batches`/`aset_batches`, `values`/`avalues`, `__enter__`/`__exit__`/`__aenter__`/`__aexit__`.

- [ ] **Step 1: Write the failing test for the merged base class**

Replace the top of `tests/unit/store/test_base.py` — keep the existing `InMemoryTestStore` fixture class but add async methods so the same class can be tested both ways, and merge in the async assertions from `test_base_async.py`:

```python
from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

import pytest

from persista.store import BaseStore, normalize_on_conflict, validate_batch_size

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator, Mapping

    from persista.store import OnConflict


class InMemoryTestStore(BaseStore):
    r"""Minimal concrete implementation of ``BaseStore`` used to
    exercise the concrete methods it provides (``values``/``avalues``,
    ``set_batches``/``aset_batches``, the sync and async context
    manager protocols)."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}
        self._closed = False

    def close(self) -> None:
        self._closed = True

    async def aclose(self) -> None:
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    def get(self, key: str) -> dict[str, Any] | None:
        value = self._data.get(key)
        return copy.deepcopy(value) if value is not None else None

    async def aget(self, key: str) -> dict[str, Any] | None:
        return self.get(key)

    def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        return [self.get(key) for key in keys]

    async def aget_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        return [await self.aget(key) for key in keys]

    def set(self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite") -> None:
        self.set_many({key: value}, on_conflict=on_conflict)

    async def aset(
        self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite"
    ) -> None:
        self.set(key, value, on_conflict=on_conflict)

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

    async def aset_many(
        self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
    ) -> None:
        self.set_many(items, on_conflict=on_conflict)

    def filter(self, **field_filters: Any) -> list[dict[str, Any]]:
        if not field_filters:
            return [copy.deepcopy(value) for value in self._data.values()]
        return [
            copy.deepcopy(value)
            for value in self._data.values()
            if all(value.get(k) == v for k, v in field_filters.items())
        ]

    async def afilter(self, **field_filters: Any) -> list[dict[str, Any]]:
        return self.filter(**field_filters)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def adelete(self, key: str) -> None:
        self.delete(key)

    def delete_many(self, keys: list[str]) -> None:
        for key in keys:
            self.delete(key)

    async def adelete_many(self, keys: list[str]) -> None:
        self.delete_many(keys)

    def clear(self) -> None:
        self._data.clear()

    async def aclear(self) -> None:
        self.clear()

    def contains(self, key: str) -> bool:
        return key in self._data

    async def acontains(self, key: str) -> bool:
        return self.contains(key)

    def contains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        found = [key for key in keys if key in self._data]
        missing = [key for key in keys if key not in self._data]
        return found, missing

    async def acontains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        return self.contains_many(keys)

    def keys(self) -> Iterator[str]:
        yield from list(self._data.keys())

    async def akeys(self) -> AsyncIterator[str]:
        for key in list(self._data.keys()):
            yield key

    def iter_batches(self, batch_size: int = 32) -> Iterator[dict[str, dict[str, Any]]]:
        validate_batch_size(batch_size)
        items = list(self._data.items())
        for i in range(0, len(items), batch_size):
            yield dict(items[i : i + batch_size])

    async def aiter_batches(
        self, batch_size: int = 32
    ) -> AsyncIterator[dict[str, dict[str, Any]]]:
        for batch in self.iter_batches(batch_size=batch_size):
            yield batch

    def count(self) -> int:
        return len(self._data)

    async def acount(self) -> int:
        return self.count()

    def to_uri(self) -> str:
        return "test://"

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> InMemoryTestStore:  # noqa: ARG003
        return cls()


def test_base_store_values_iterates_all() -> None:
    store = InMemoryTestStore()
    store.set_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
    assert sorted(v["a"] for v in store.values(batch_size=2)) == [1, 2, 3]


@pytest.mark.asyncio
async def test_base_store_avalues_iterates_all() -> None:
    store = InMemoryTestStore()
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
    values = [v async for v in store.avalues(batch_size=2)]
    assert sorted(v["a"] for v in values) == [1, 2, 3]


def test_base_store_set_batches() -> None:
    store = InMemoryTestStore()
    store.set_batches([("1", {"a": 1}), ("2", {"a": 2})], batch_size=1)
    assert store.count() == 2


@pytest.mark.asyncio
async def test_base_store_aset_batches() -> None:
    store = InMemoryTestStore()
    await store.aset_batches([("1", {"a": 1}), ("2", {"a": 2})], batch_size=1)
    assert await store.acount() == 2


def test_base_store_sync_context_manager_calls_close() -> None:
    with InMemoryTestStore() as store:
        assert not store.closed
    assert store.closed


@pytest.mark.asyncio
async def test_base_store_async_context_manager_calls_aclose() -> None:
    async with InMemoryTestStore() as store:
        assert not store.closed
    assert store.closed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/store/test_base.py -v`
Expected: FAIL — `BaseStore` doesn't yet declare `aget`/`aset_many`/`aclose`/etc., so `InMemoryTestStore` either can't be instantiated (missing abstract methods) or `avalues`/`aset_batches` don't exist on `BaseStore`.

- [ ] **Step 3: Rewrite `base.py`**

```python
r"""Provide the abstract base class for key-value stores, supporting
both sync and async access from the same instance."""

from __future__ import annotations

__all__ = ["BaseStore"]

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from coola.utils.batching import batchify

from persista.store.validation import validate_batch_size

if TYPE_CHECKING:
    from collections.abc import (
        AsyncIterator,
        Iterable,
        Iterator,
        Mapping,
    )
    from typing import Self

    from persista.store.types import OnConflict


class BaseStore(ABC):
    """Abstract base class for key-value stores.

    Defines the common interface that all key-value store
    implementations must provide. Values are stored as dicts, which
    allows :meth:`filter` to match on the content of a value.

    Every operation that touches the underlying store has a sync
    method (e.g. :meth:`get`) and an async twin prefixed with ``a``
    (e.g. :meth:`aget`), both callable on the same instance -- there
    is no separate async class. Implementations back these with
    whatever mix of blocking and native-async drivers suits the
    backend (see subclasses for details); callers only need to pick
    which method to call based on whether they're in sync or async
    code.

    To implement a custom store, subclass :class:`BaseStore` and
    implement all abstract methods.

    Implementations are expected to support use as a sync context
    manager (``with SomeStore(...) as store: ...``, calling
    :meth:`close` on exit) and as an async context manager
    (``async with SomeStore(...) as store: ...``, calling
    :meth:`aclose` on exit).
    """

    @abstractmethod
    def get(self, key: str) -> dict[str, Any] | None:
        """Retrieve a single value by its key.

        Args:
            key: The key to look up.

        Returns:
            The value associated with ``key``, or ``None`` if the
            key is not found.
        """

    @abstractmethod
    async def aget(self, key: str) -> dict[str, Any] | None:
        """Async equivalent of :meth:`get`."""

    @abstractmethod
    def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        """Retrieve multiple values by their keys.

        Args:
            keys: The keys to look up.

        Returns:
            A list the same length as ``keys``, with the
            corresponding value for each key that exists, or
            ``None`` for keys that are not found.
        """

    @abstractmethod
    async def aget_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        """Async equivalent of :meth:`get_many`."""

    @abstractmethod
    def set(self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite") -> None:
        """Add a single key-value pair to the store.

        Args:
            key: The key to set.
            value: The value to associate with ``key``.
            on_conflict: The strategy to use if ``key`` already
                exists in the store:

                - ``"raise"``: raise a :class:`KeyError` and leave
                  the existing value unchanged.
                - ``"skip"``: leave the existing value unchanged.
                - ``"overwrite"``: replace the existing value with
                  ``value``.
                - ``"merge"``: shallow-merge ``value`` into the
                  existing value, with fields from ``value`` taking
                  precedence on overlapping keys.

        Raises:
            KeyError: If ``on_conflict`` is ``"raise"`` and ``key``
                already exists.
        """

    @abstractmethod
    async def aset(
        self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite"
    ) -> None:
        """Async equivalent of :meth:`set`."""

    @abstractmethod
    def set_many(
        self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
    ) -> None:
        """Add multiple key-value pairs to the store.

        Args:
            items: The values to add, keyed by their unique key.
            on_conflict: The strategy to use for keys in ``items``
                that already exist in the store. See :meth:`set` for
                the meaning of each option.

        Raises:
            KeyError: If ``on_conflict`` is ``"raise"`` and any key
                in ``items`` already exists.
        """

    @abstractmethod
    async def aset_many(
        self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
    ) -> None:
        """Async equivalent of :meth:`set_many`."""

    def set_batches(
        self,
        items: Iterable[tuple[str, dict[str, Any]]],
        batch_size: int = 32,
        on_conflict: OnConflict = "overwrite",
    ) -> None:
        """Add key-value pairs from an iterable, writing them to the
        store in mini-batches.

        This is the streaming equivalent of :meth:`set_many`: instead
        of requiring every key-value pair to be materialized into a
        single mapping upfront, it consumes ``items`` lazily and
        writes at most ``batch_size`` pairs at a time. This keeps
        memory usage bounded when ``items`` comes from a generator
        over a large or unbounded source.

        Args:
            items: An iterable of ``(key, value)`` pairs to add.
            batch_size: The maximum number of pairs to write to the
                store per underlying :meth:`set_many` call. Must be a
                positive integer.
            on_conflict: The strategy to use for keys that already
                exist in the store. See :meth:`set` for the meaning
                of each option. Applied independently per batch, so
                with ``"raise"`` a conflict is only detected once the
                offending batch is written, not upfront.

        Raises:
            KeyError: If ``on_conflict`` is ``"raise"`` and any key
                already exists.
        """
        validate_batch_size(batch_size)
        for batch in batchify(items, size=batch_size):
            self.set_many(dict(batch), on_conflict=on_conflict)

    async def aset_batches(
        self,
        items: Iterable[tuple[str, dict[str, Any]]],
        batch_size: int = 32,
        on_conflict: OnConflict = "overwrite",
    ) -> None:
        """Async equivalent of :meth:`set_batches`."""
        validate_batch_size(batch_size)
        for batch in batchify(items, size=batch_size):
            await self.aset_many(dict(batch), on_conflict=on_conflict)

    @abstractmethod
    def filter(self, **field_filters: Any) -> list[dict[str, Any]]:
        """Retrieve values whose content matches all provided field
        filters.

        All filters should be combined with ``AND``. Each keyword
        argument matches the corresponding key in the stored value
        exactly.

        Args:
            **field_filters: Key-value pairs where each key is a
                field name within a stored value and the value is
                the exact value to match. Calling with no arguments
                should return every value in the store.

        Returns:
            A list of matching values.
        """

    @abstractmethod
    async def afilter(self, **field_filters: Any) -> list[dict[str, Any]]:
        """Async equivalent of :meth:`filter`."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete a value by its key.

        Keys that do not exist should be silently ignored.

        Args:
            key: The key of the value to delete.
        """

    @abstractmethod
    async def adelete(self, key: str) -> None:
        """Async equivalent of :meth:`delete`."""

    @abstractmethod
    def delete_many(self, keys: list[str]) -> None:
        """Delete multiple values by their keys.

        Keys that do not exist should be silently ignored.

        Args:
            keys: The keys of the values to delete.
        """

    @abstractmethod
    async def adelete_many(self, keys: list[str]) -> None:
        """Async equivalent of :meth:`delete_many`."""

    @abstractmethod
    def clear(self) -> None:
        """Remove every key-value pair from the store.

        This is equivalent to resetting the store to empty, without
        closing it.
        """

    @abstractmethod
    async def aclear(self) -> None:
        """Async equivalent of :meth:`clear`."""

    @abstractmethod
    def contains(self, key: str) -> bool:
        """Check if the key exists in the store.

        Args:
            key: The key to check.

        Returns:
            True if the key exists in the store, False otherwise.
        """

    @abstractmethod
    async def acontains(self, key: str) -> bool:
        """Async equivalent of :meth:`contains`."""

    @abstractmethod
    def contains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        """Check which keys exist in the store.

        Args:
            keys: The keys to check.

        Returns:
            A tuple of two lists: ``(found, missing)`` where ``found``
            contains the keys that exist in the store and ``missing``
            contains the keys that do not.
        """

    @abstractmethod
    async def acontains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        """Async equivalent of :meth:`contains_many`."""

    @abstractmethod
    def keys(self) -> Iterator[str]:
        """Iterate over all keys in the store.

        Yields:
            Every key currently in the store.
        """

    @abstractmethod
    def akeys(self) -> AsyncIterator[str]:
        """Async equivalent of :meth:`keys`."""

    def values(self, batch_size: int = 32) -> Iterator[dict[str, Any]]:
        """Iterate over all values without loading them all into memory
        at once.

        Args:
            batch_size: The batch size used internally when pulling
                values from the underlying store. Does not affect
                the granularity of what is yielded -- values are
                always yielded one at a time.

        Yields:
            One value at a time, in the same order as
            :meth:`iter_batches`.
        """
        for batch in self.iter_batches(batch_size=batch_size):
            yield from batch.values()

    async def avalues(self, batch_size: int = 32) -> AsyncIterator[dict[str, Any]]:
        """Async equivalent of :meth:`values`."""
        async for batch in self.aiter_batches(batch_size=batch_size):
            for value in batch.values():
                yield value

    @abstractmethod
    def iter_batches(self, batch_size: int = 32) -> Iterator[dict[str, dict[str, Any]]]:
        """Yield key-value pairs in batches, avoiding loading the whole
        store into memory at once.

        This is the scalable equivalent of :meth:`values`: instead of
        materializing every value as a single mapping, it streams
        them from the underlying store in chunks of ``batch_size``.

        Args:
            batch_size: The maximum number of pairs to yield per
                batch. Must be a positive integer.

        Yields:
            Dicts mapping key to value, each with at most
            ``batch_size`` entries, in the same order as
            :meth:`values`. The last batch may contain fewer than
            ``batch_size`` entries.
        """

    @abstractmethod
    def aiter_batches(self, batch_size: int = 32) -> AsyncIterator[dict[str, dict[str, Any]]]:
        """Async equivalent of :meth:`iter_batches`."""

    @abstractmethod
    def count(self) -> int:
        """Return the total number of key-value pairs in the store.

        Returns:
            The number of key-value pairs currently stored.
        """

    @abstractmethod
    async def acount(self) -> int:
        """Async equivalent of :meth:`count`."""

    @abstractmethod
    def close(self) -> None:
        r"""Close the store and release any underlying resources (e.g.
        database connections, file handles).

        Implementations should make repeated calls to ``close()`` safe
        (i.e. idempotent), since :meth:`__exit__` calls it
        unconditionally and callers may also close a store manually
        before using it as a context manager.
        """

    @abstractmethod
    async def aclose(self) -> None:
        """Async equivalent of :meth:`close`."""

    @property
    @abstractmethod
    def closed(self) -> bool:
        r"""Indicate whether the store is closed.

        Returns:
            ``True`` if the store has been closed, ``False`` if it is
            open and ready to use.
        """

    @abstractmethod
    def to_uri(self) -> str:
        """Return a URI that identifies where this store's data lives.

        Returns:
            A URI. For a store backed by a file/database, passing
            this URI to :meth:`from_uri` reconnects to the same
            data. For a process-local store, the URI carries no
            reconnection information and :meth:`from_uri` returns a
            fresh, empty store.
        """

    @classmethod
    @abstractmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> Self:
        """Reconstruct a store from a URI produced by :meth:`to_uri`.

        Args:
            uri: A URI produced by :meth:`to_uri` (of a store of this
                same class).
            read_only: If ``True`` and this store type supports a
                read-only connection mode, open it read-only.
                Ignored by store types with no such mode.

        Returns:
            A new store instance.
        """

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
```

- [ ] **Step 4: Delete the now-redundant async base test file**

```bash
git rm tests/unit/store/test_base_async.py
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/store/test_base.py -v`
Expected: PASS. (Other files under `tests/unit/store/` will still fail to import at this point since every backend module still subclasses the old `BaseStore`/`AsyncBaseStore` split with mismatched abstract methods — that's expected until Tasks 2-12 land; don't run the full suite yet.)

- [ ] **Step 6: Commit**

```bash
git add src/persista/store/base.py tests/unit/store/test_base.py
git commit -m "feat(store): merge BaseStore/AsyncBaseStore into a single dual-mode ABC"
```

---

### Task 2: `ThreadedAsyncStoreMixin` helper

**Files:**
- Create: `src/persista/store/_threaded.py`
- Test: `tests/unit/store/test_threaded.py`

**Interfaces:**
- Consumes: `BaseStore` (Task 1) sync abstract methods (`get`, `get_many`, `set`, `set_many`, `filter`, `delete`, `delete_many`, `clear`, `contains`, `contains_many`, `keys`, `iter_batches`, `count`, `close`).
- Produces: `ThreadedAsyncStoreMixin` providing concrete `aget`, `aget_many`, `aset`, `aset_many`, `afilter`, `adelete`, `adelete_many`, `aclear`, `acontains`, `acontains_many`, `akeys`, `aiter_batches`, `acount`, `aclose` — all via `asyncio.to_thread`. A category-B backend does `class Foo(ThreadedAsyncStoreMixin, BaseStore)` and only implements the sync side.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import copy
from typing import Any

import pytest

from persista.store._threaded import ThreadedAsyncStoreMixin
from persista.store.base import BaseStore
from persista.store.validation import normalize_on_conflict, validate_batch_size


class _ThreadedTestStore(ThreadedAsyncStoreMixin, BaseStore):
    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}
        self._closed = False

    def close(self) -> None:
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    def get(self, key):
        value = self._data.get(key)
        return copy.deepcopy(value) if value is not None else None

    def get_many(self, keys):
        return [self.get(key) for key in keys]

    def set(self, key, value, on_conflict="overwrite"):
        self.set_many({key: value}, on_conflict=on_conflict)

    def set_many(self, items, on_conflict="overwrite"):
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

    def filter(self, **field_filters):
        if not field_filters:
            return [copy.deepcopy(v) for v in self._data.values()]
        return [
            copy.deepcopy(v)
            for v in self._data.values()
            if all(v.get(k) == val for k, val in field_filters.items())
        ]

    def delete(self, key):
        self._data.pop(key, None)

    def delete_many(self, keys):
        for key in keys:
            self.delete(key)

    def clear(self):
        self._data.clear()

    def contains(self, key):
        return key in self._data

    def contains_many(self, keys):
        found = [key for key in keys if key in self._data]
        missing = [key for key in keys if key not in self._data]
        return found, missing

    def keys(self):
        yield from list(self._data.keys())

    def iter_batches(self, batch_size: int = 32):
        validate_batch_size(batch_size)
        items = list(self._data.items())
        for i in range(0, len(items), batch_size):
            yield dict(items[i : i + batch_size])

    def count(self):
        return len(self._data)

    def to_uri(self):
        return "threaded-test://"

    @classmethod
    def from_uri(cls, uri, *, read_only=False):
        return cls()


@pytest.mark.asyncio
async def test_threaded_mixin_aget_aset_round_trip() -> None:
    store = _ThreadedTestStore()
    await store.aset("1", {"a": 1})
    assert await store.aget("1") == {"a": 1}
    assert await store.aget("missing") is None


@pytest.mark.asyncio
async def test_threaded_mixin_aset_many_and_acontains_many() -> None:
    store = _ThreadedTestStore()
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    found, missing = await store.acontains_many(["1", "3"])
    assert found == ["1"]
    assert missing == ["3"]


@pytest.mark.asyncio
async def test_threaded_mixin_akeys_yields_all_keys() -> None:
    store = _ThreadedTestStore()
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    keys = sorted([key async for key in store.akeys()])
    assert keys == ["1", "2"]


@pytest.mark.asyncio
async def test_threaded_mixin_aiter_batches_respects_batch_size() -> None:
    store = _ThreadedTestStore()
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
    batches = [batch async for batch in store.aiter_batches(batch_size=2)]
    assert sum(len(b) for b in batches) == 3
    assert all(len(b) <= 2 for b in batches)


@pytest.mark.asyncio
async def test_threaded_mixin_adelete_and_aclear() -> None:
    store = _ThreadedTestStore()
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    await store.adelete("1")
    assert await store.acontains("1") is False
    await store.aclear()
    assert await store.acount() == 0


@pytest.mark.asyncio
async def test_threaded_mixin_aclose_sets_closed() -> None:
    store = _ThreadedTestStore()
    await store.aclose()
    assert store.closed


@pytest.mark.asyncio
async def test_threaded_mixin_afilter_matches_field() -> None:
    store = _ThreadedTestStore()
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    result = await store.afilter(a=2)
    assert result == [{"a": 2}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/store/test_threaded.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'persista.store._threaded'`

- [ ] **Step 3: Write the implementation**

```python
r"""Provide a mixin that derives async methods from a store's sync
methods via a background thread, for backends with no native async
driver."""

from __future__ import annotations

__all__ = ["ThreadedAsyncStoreMixin"]

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from persista.store.types import OnConflict


class ThreadedAsyncStoreMixin:
    r"""Provide every ``a``-prefixed async method as an
    ``asyncio.to_thread`` wrapper around the corresponding sync
    method.

    Mix this into a :class:`~persista.store.base.BaseStore` subclass
    whose backend has no native async driver (in-memory, file, LMDB,
    DuckDB): the subclass only needs to implement the sync side, and
    this mixin supplies a fully-conformant async side for free by
    running each sync call in a worker thread. ``akeys``/
    ``aiter_batches`` additionally bridge the sync generators returned
    by ``keys``/``iter_batches`` across the thread boundary, pulling
    one key/batch at a time via ``asyncio.to_thread`` rather than
    materializing the whole store in memory.

    Must be listed before ``BaseStore`` in the MRO (e.g.
    ``class Foo(ThreadedAsyncStoreMixin, BaseStore)``) so its concrete
    methods satisfy ``BaseStore``'s abstract async methods.
    """

    async def aget(self, key: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.get, key)

    async def aget_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        return await asyncio.to_thread(self.get_many, keys)

    async def aset(
        self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite"
    ) -> None:
        await asyncio.to_thread(self.set, key, value, on_conflict)

    async def aset_many(
        self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
    ) -> None:
        await asyncio.to_thread(self.set_many, items, on_conflict)

    async def afilter(self, **field_filters: Any) -> list[dict[str, Any]]:
        return await asyncio.to_thread(lambda: self.filter(**field_filters))

    async def adelete(self, key: str) -> None:
        await asyncio.to_thread(self.delete, key)

    async def adelete_many(self, keys: list[str]) -> None:
        await asyncio.to_thread(self.delete_many, keys)

    async def aclear(self) -> None:
        await asyncio.to_thread(self.clear)

    async def acontains(self, key: str) -> bool:
        return await asyncio.to_thread(self.contains, key)

    async def acontains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        return await asyncio.to_thread(self.contains_many, keys)

    async def akeys(self) -> AsyncIterator[str]:
        iterator = await asyncio.to_thread(lambda: iter(self.keys()))
        while True:
            try:
                key = await asyncio.to_thread(next, iterator)
            except StopIteration:
                return
            yield key

    async def aiter_batches(
        self, batch_size: int = 32
    ) -> AsyncIterator[dict[str, dict[str, Any]]]:
        iterator = await asyncio.to_thread(lambda: iter(self.iter_batches(batch_size=batch_size)))
        while True:
            try:
                batch = await asyncio.to_thread(next, iterator)
            except StopIteration:
                return
            yield batch

    async def acount(self) -> int:
        return await asyncio.to_thread(self.count)

    async def aclose(self) -> None:
        await asyncio.to_thread(self.close)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/store/test_threaded.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/persista/store/_threaded.py tests/unit/store/test_threaded.py
git commit -m "feat(store): add ThreadedAsyncStoreMixin for no-native-async backends"
```

---

### Task 3: Merge `NullStore`

**Files:**
- Modify: `src/persista/store/null.py` (full rewrite)
- Delete: `src/persista/store/async_null.py`
- Modify: `tests/unit/store/test_null.py` (merge in assertions from `tests/unit/store/test_async_null.py`, then delete that file)

**Interfaces:**
- Consumes: `BaseStore` (Task 1).
- Produces: `NullStore(BaseStore)` with both sync and async methods (async methods are direct no-ops, not thread-wrapped, since there is no I/O to offload).

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/store/test_null.py` (keep existing sync tests, add async ones):

```python
import pytest


@pytest.mark.asyncio
async def test_null_store_aget_always_none() -> None:
    store = NullStore()
    await store.aset("1", {"a": 1})
    assert await store.aget("1") is None


@pytest.mark.asyncio
async def test_null_store_acontains_always_false() -> None:
    store = NullStore()
    await store.aset("1", {"a": 1})
    assert await store.acontains("1") is False


@pytest.mark.asyncio
async def test_null_store_acount_always_zero() -> None:
    store = NullStore()
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    assert await store.acount() == 0


@pytest.mark.asyncio
async def test_null_store_akeys_empty() -> None:
    store = NullStore()
    keys = [key async for key in store.akeys()]
    assert keys == []


@pytest.mark.asyncio
async def test_null_store_aiter_batches_empty() -> None:
    store = NullStore()
    batches = [batch async for batch in store.aiter_batches()]
    assert batches == []


@pytest.mark.asyncio
async def test_null_store_afilter_always_empty() -> None:
    store = NullStore()
    await store.aset("1", {"a": 1})
    assert await store.afilter(a=1) == []


@pytest.mark.asyncio
async def test_null_store_async_context_manager() -> None:
    async with NullStore() as store:
        assert not store.closed
    assert store.closed
```

(Add `from persista.store import NullStore` at the top if not already imported, matching the existing file's import style.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/store/test_null.py -v`
Expected: FAIL — `NullStore` has no `aget`/`aset`/etc.

- [ ] **Step 3: Rewrite `null.py`**

```python
r"""Provide a no-op implementation of ``BaseStore``."""

from __future__ import annotations

__all__ = ["NullStore"]

import logging
from typing import TYPE_CHECKING, Any

from coola.display import InlineDisplayMixin

from persista.store.base import BaseStore
from persista.utils.asyncio import EmptyAsyncIterator

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator, Mapping

    from typing_extensions import Self

    from persista.store.types import OnConflict


logger: logging.Logger = logging.getLogger(__name__)


class NullStore(BaseStore, InlineDisplayMixin):
    """A :class:`~persista.store.base.BaseStore` implementation that
    forgets everything written to it.

    Every :meth:`set`/:meth:`aset`/:meth:`set_many`/:meth:`aset_many`
    call is silently discarded, so :meth:`get`/:meth:`aget` always
    report a miss and the store always reports as empty. This is
    primarily useful for plugging into
    :class:`~persista.cache.cache.Cache` to disable caching without
    changing any calling code: every lookup misses, so
    ``get_or_compute``/``memoize`` always recompute the value.

    There is no I/O to offload here, so the async methods run inline
    rather than through a thread pool.

    Example:
        ```pycon
        >>> from persista.store import NullStore
        >>> from persista.cache import Cache
        >>> cache = Cache(store=NullStore())
        >>> cache.set("greeting", "hello")
        >>> cache.get("greeting") is None
        True

        ```
    """

    def __init__(self) -> None:
        self._closed = False

    def close(self) -> None:
        self._closed = True

    async def aclose(self) -> None:
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    def get(self, key: str) -> dict[str, Any] | None:  # noqa: ARG002
        return None

    async def aget(self, key: str) -> dict[str, Any] | None:  # noqa: ARG002
        return None

    def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        return [None] * len(keys)

    async def aget_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        return [None] * len(keys)

    def set(
        self,
        key: str,
        value: dict[str, Any],  # noqa: ARG002
        on_conflict: OnConflict = "overwrite",  # noqa: ARG002
    ) -> None:
        logger.debug("Discarding key-value pair: %s", key)

    async def aset(
        self,
        key: str,
        value: dict[str, Any],  # noqa: ARG002
        on_conflict: OnConflict = "overwrite",  # noqa: ARG002
    ) -> None:
        logger.debug("Discarding key-value pair: %s", key)

    def set_many(
        self,
        items: Mapping[str, dict[str, Any]],
        on_conflict: OnConflict = "overwrite",  # noqa: ARG002
    ) -> None:
        logger.debug("Discarding %d key-value pair(s)", len(items))

    async def aset_many(
        self,
        items: Mapping[str, dict[str, Any]],
        on_conflict: OnConflict = "overwrite",  # noqa: ARG002
    ) -> None:
        logger.debug("Discarding %d key-value pair(s)", len(items))

    def filter(self, **field_filters: Any) -> list[dict[str, Any]]:  # noqa: ARG002
        return []

    async def afilter(self, **field_filters: Any) -> list[dict[str, Any]]:  # noqa: ARG002
        return []

    def delete(self, key: str) -> None:  # noqa: ARG002
        return

    async def adelete(self, key: str) -> None:  # noqa: ARG002
        return

    def delete_many(self, keys: list[str]) -> None:  # noqa: ARG002
        return

    async def adelete_many(self, keys: list[str]) -> None:  # noqa: ARG002
        return

    def clear(self) -> None:
        return

    async def aclear(self) -> None:
        return

    def contains(self, key: str) -> bool:  # noqa: ARG002
        return False

    async def acontains(self, key: str) -> bool:  # noqa: ARG002
        return False

    def contains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        return [], list(keys)

    async def acontains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        return [], list(keys)

    def keys(self) -> Iterator[str]:
        return iter(())

    def akeys(self) -> AsyncIterator[str]:
        return EmptyAsyncIterator()

    def iter_batches(
        self,
        batch_size: int = 32,  # noqa: ARG002
    ) -> Iterator[dict[str, dict[str, Any]]]:
        yield from ()

    def aiter_batches(
        self,
        batch_size: int = 32,  # noqa: ARG002
    ) -> AsyncIterator[dict[str, dict[str, Any]]]:
        return EmptyAsyncIterator()

    def count(self) -> int:
        return 0

    async def acount(self) -> int:
        return 0

    def to_uri(self) -> str:
        return "null://"

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> Self:  # noqa: ARG003
        return cls()

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"count": 0}
```

- [ ] **Step 4: Delete the redundant async module and test file**

```bash
git rm src/persista/store/async_null.py tests/unit/store/test_async_null.py
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/store/test_null.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/persista/store/null.py tests/unit/store/test_null.py
git commit -m "feat(store): merge NullStore/AsyncNullStore into one dual-mode class"
```

---

### Task 4: Merge `InMemoryStore`

**Files:**
- Modify: `src/persista/store/in_memory.py` (full rewrite, mixing in `ThreadedAsyncStoreMixin`)
- Delete: `src/persista/store/async_in_memory.py`
- Modify: `tests/unit/store/test_in_memory.py` (merge in `tests/unit/store/test_async_in_memory.py`, then delete that file)

**Interfaces:**
- Consumes: `BaseStore` (Task 1), `ThreadedAsyncStoreMixin` (Task 2).
- Produces: `InMemoryStore(ThreadedAsyncStoreMixin, BaseStore)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/store/test_in_memory.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_in_memory_store_aget_aset_round_trip() -> None:
    store = InMemoryStore()
    await store.aset("1", {"text": "hello"})
    assert await store.aget("1") == {"text": "hello"}


@pytest.mark.asyncio
async def test_in_memory_store_aset_many_on_conflict_merge() -> None:
    store = InMemoryStore()
    await store.aset("1", {"a": 1})
    await store.aset_many({"1": {"b": 2}}, on_conflict="merge")
    assert await store.aget("1") == {"a": 1, "b": 2}


@pytest.mark.asyncio
async def test_in_memory_store_afilter() -> None:
    store = InMemoryStore()
    await store.aset_many({"1": {"author": "Alice"}, "2": {"author": "Bob"}})
    assert await store.afilter(author="Alice") == [{"author": "Alice"}]


@pytest.mark.asyncio
async def test_in_memory_store_acount_and_aclear() -> None:
    store = InMemoryStore()
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    assert await store.acount() == 2
    await store.aclear()
    assert await store.acount() == 0


@pytest.mark.asyncio
async def test_in_memory_store_akeys() -> None:
    store = InMemoryStore()
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    assert sorted([key async for key in store.akeys()]) == ["1", "2"]


@pytest.mark.asyncio
async def test_in_memory_store_aclose_clears_data() -> None:
    store = InMemoryStore()
    await store.aset("1", {"a": 1})
    await store.aclose()
    assert store.closed
    assert store.data == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/store/test_in_memory.py -v`
Expected: FAIL — `InMemoryStore` has no `aget`/`aset`/etc.

- [ ] **Step 3: Rewrite `in_memory.py`**

```python
r"""Provide an in-memory implementation of ``BaseStore``."""

from __future__ import annotations

__all__ = ["InMemoryStore"]

import copy
import logging
from typing import TYPE_CHECKING, Any

from coola.display import InlineDisplayMixin
from coola.utils.batching import batchify

from persista.store._threaded import ThreadedAsyncStoreMixin
from persista.store.base import BaseStore
from persista.store.validation import normalize_on_conflict, validate_batch_size

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from typing_extensions import Self

    from persista.store.types import OnConflict


logger: logging.Logger = logging.getLogger(__name__)


class InMemoryStore(ThreadedAsyncStoreMixin, BaseStore, InlineDisplayMixin):
    """A :class:`~persista.store.BaseStore` implementation backed
    by a plain ``dict``.

    Values are held entirely in process memory -- nothing is
    persisted to disk. This is primarily useful for testing,
    small-scale exploration, or pipelines that don't need durability.
    Async methods (``aget``, ``aset``, ...) are provided by
    :class:`~persista.store._threaded.ThreadedAsyncStoreMixin`, which
    runs each sync call in a worker thread.

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
        self._closed = False

    @property
    def data(self) -> dict[str, dict[str, Any]]:
        return self._data

    def close(self) -> None:
        # Discard all values: an in-memory store has nothing to
        # persist, so closing (and later reopening via the context
        # manager) it is equivalent to starting over with a fresh,
        # empty store.
        self._data.clear()
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

        if on_conflict == "overwrite":
            for key, value in items.items():
                self._data[key] = copy.deepcopy(value)
            logger.debug("Added/replaced %d key-value pair(s)", len(items))
            return

        conflicts = [key for key in items if key in self._data]
        if conflicts and on_conflict == "raise":
            msg = f"Key(s) already exist in the store: {conflicts}"
            raise KeyError(msg)

        for key, value in items.items():
            if key in self._data:
                if on_conflict == "skip":
                    continue
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

    def iter_batches(self, batch_size: int = 32) -> Iterator[dict[str, dict[str, Any]]]:
        validate_batch_size(batch_size)
        for batch in batchify(self._data.items(), size=batch_size):
            yield dict(batch)

    def count(self) -> int:
        return len(self._data)

    def to_uri(self) -> str:
        return "memory://"

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> Self:  # noqa: ARG003
        return cls()

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"count": self.count()}
```

- [ ] **Step 4: Delete the redundant async module and test file**

```bash
git rm src/persista/store/async_in_memory.py tests/unit/store/test_async_in_memory.py
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/store/test_in_memory.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/persista/store/in_memory.py tests/unit/store/test_in_memory.py
git commit -m "feat(store): merge InMemoryStore/AsyncInMemoryStore via ThreadedAsyncStoreMixin"
```

---

### Task 5: Merge `file.py` (`JsonFileStore`/`PickleFileStore`)

**Files:**
- Modify: `src/persista/store/file.py` (mix in `ThreadedAsyncStoreMixin` on `BaseFileStore`)
- Modify: `tests/unit/store/test_file.py` (add async assertions; there is no pre-existing async file store, so this is additive only)

**Interfaces:**
- Consumes: `BaseStore` (Task 1), `ThreadedAsyncStoreMixin` (Task 2).
- Produces: `BaseFileStore(ThreadedAsyncStoreMixin, BaseStore, MultilineDisplayMixin)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/store/test_file.py` (adjust `store_cls`/fixture names to match the file's existing parametrization over `JsonFileStore`/`PickleFileStore`):

```python
import pytest


@pytest.mark.asyncio
async def test_file_store_aget_aset_round_trip(store) -> None:
    await store.aset("1", {"a": 1})
    assert await store.aget("1") == {"a": 1}


@pytest.mark.asyncio
async def test_file_store_afilter(store) -> None:
    await store.aset_many({"1": {"author": "Alice"}, "2": {"author": "Bob"}})
    assert await store.afilter(author="Alice") == [{"author": "Alice"}]


@pytest.mark.asyncio
async def test_file_store_acount_adelete(store) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    assert await store.acount() == 2
    await store.adelete("1")
    assert await store.acount() == 1


@pytest.mark.asyncio
async def test_file_store_akeys(store) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    assert sorted([key async for key in store.akeys()]) == ["1", "2"]
```

(Use whatever fixture name the existing file already defines for a fresh store per test — read the file first to match it exactly; if the existing fixture is function-scoped and named `store`, these slot in directly.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/store/test_file.py -v`
Expected: FAIL — `BaseFileStore` has no `aget`/`aset`/etc.

- [ ] **Step 3: Modify `file.py`**

Change only the class declaration and imports; leave every sync method and the `JsonFileStore`/`PickleFileStore` subclasses untouched:

```python
from persista.store._threaded import ThreadedAsyncStoreMixin
from persista.store.base import BaseStore
```

```python
class BaseFileStore(ThreadedAsyncStoreMixin, BaseStore, MultilineDisplayMixin):
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/store/test_file.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/persista/store/file.py tests/unit/store/test_file.py
git commit -m "feat(store): add async methods to file stores via ThreadedAsyncStoreMixin"
```

---

### Task 6: Merge `lmdb.py` (`LmdbStore`/`PickleLmdbStore`)

**Files:**
- Modify: `src/persista/store/lmdb.py` (mix in `ThreadedAsyncStoreMixin` on `BaseLmdbStore`)
- Modify: `tests/unit/store/test_lmdb.py` (additive async assertions, same shape as Task 5)

**Interfaces:**
- Consumes: `BaseStore` (Task 1), `ThreadedAsyncStoreMixin` (Task 2).
- Produces: `BaseLmdbStore(ThreadedAsyncStoreMixin, BaseStore, MultilineDisplayMixin)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/store/test_lmdb.py`, matching whatever fixture the file already provides for a fresh store (an LMDB path fixture, per the existing sync tests):

```python
import pytest


@pytest.mark.asyncio
async def test_lmdb_store_aget_aset_round_trip(store) -> None:
    await store.aset("1", {"a": 1})
    assert await store.aget("1") == {"a": 1}


@pytest.mark.asyncio
async def test_lmdb_store_acontains_many(store) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    found, missing = await store.acontains_many(["1", "3"])
    assert found == ["1"]
    assert missing == ["3"]


@pytest.mark.asyncio
async def test_lmdb_store_akeys(store) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    assert sorted([key async for key in store.akeys()]) == ["1", "2"]


@pytest.mark.asyncio
async def test_lmdb_store_aiter_batches(store) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
    batches = [batch async for batch in store.aiter_batches(batch_size=2)]
    assert sum(len(b) for b in batches) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/store/test_lmdb.py -v`
Expected: FAIL — `BaseLmdbStore` has no `aget`/`aset`/etc.

- [ ] **Step 3: Modify `lmdb.py`**

```python
from persista.store._threaded import ThreadedAsyncStoreMixin
from persista.store.base import BaseStore
```

```python
class BaseLmdbStore(ThreadedAsyncStoreMixin, BaseStore, MultilineDisplayMixin):
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/store/test_lmdb.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/persista/store/lmdb.py tests/unit/store/test_lmdb.py
git commit -m "feat(store): add async methods to LMDB stores via ThreadedAsyncStoreMixin"
```

---

### Task 7: Merge `duckdb.py` (`DuckDBStore`/`TypedDuckDBStore`)

**Files:**
- Modify: `src/persista/store/duckdb.py` (mix in `ThreadedAsyncStoreMixin` on `BaseDuckDBStore`)
- Modify: `tests/unit/store/test_duckdb.py` (additive async assertions, same shape as Task 5/6)

**Interfaces:**
- Consumes: `BaseStore` (Task 1), `ThreadedAsyncStoreMixin` (Task 2).
- Produces: `BaseDuckDBStore(ThreadedAsyncStoreMixin, BaseStore, MultilineDisplayMixin)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/store/test_duckdb.py`, matching the existing fixture for a fresh `":memory:"` store:

```python
import pytest


@pytest.mark.asyncio
async def test_duckdb_store_aget_aset_round_trip(store) -> None:
    await store.aset("1", {"a": 1})
    assert await store.aget("1") == {"a": 1}


@pytest.mark.asyncio
async def test_duckdb_store_afilter(store) -> None:
    await store.aset_many({"1": {"author": "Alice"}, "2": {"author": "Bob"}})
    assert await store.afilter(author="Alice") == [{"author": "Alice"}]


@pytest.mark.asyncio
async def test_duckdb_store_acount(store) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    assert await store.acount() == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/store/test_duckdb.py -v`
Expected: FAIL — `BaseDuckDBStore` has no `aget`/`aset`/etc.

- [ ] **Step 3: Modify `duckdb.py`**

```python
from persista.store._threaded import ThreadedAsyncStoreMixin
from persista.store.base import BaseStore
```

```python
class BaseDuckDBStore(ThreadedAsyncStoreMixin, BaseStore, MultilineDisplayMixin):
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/store/test_duckdb.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/persista/store/duckdb.py tests/unit/store/test_duckdb.py
git commit -m "feat(store): add async methods to DuckDB stores via ThreadedAsyncStoreMixin"
```

---

### Task 8: Merge SQLite stores (the big one — dual connection + aiosqlite-optional fallback)

**Files:**
- Modify: `src/persista/store/sqlite.py` (full rewrite of `BaseSQLiteStore`; `SQLiteStore`/`TypedSQLiteStore`/`PickleSQLiteStore` gain `_aset_many`/`_arow_to_value` hooks alongside their existing sync ones)
- Delete: `src/persista/store/async_sqlite.py`
- Modify: `tests/unit/store/test_sqlite.py` (merge in `tests/unit/store/test_async_sqlite.py`; add a new test for the aiosqlite-missing fallback)
- Delete: `tests/unit/store/test_async_sqlite.py`

**Interfaces:**
- Consumes: `BaseStore` (Task 1), `is_aiosqlite_available` (`persista.utils.imports.is_aiosqlite_available`).
- Produces: `BaseSQLiteStore(BaseStore, MultilineDisplayMixin)` with abstract sync hooks (`_create_table_sql`, `_row_to_value`, `_build_filter_condition`, `_set_many`) unchanged, plus a new abstract `_aset_many` hook mirroring `_set_many` for the native-async path. `SQLiteStore`, `TypedSQLiteStore`, `PickleSQLiteStore` implement both.

- [ ] **Step 1: Write the failing test**

Merge these into `tests/unit/store/test_sqlite.py` (the file already parametrizes `store_cls` over `[SQLiteStore, TypedSQLiteStore]` per the existing fixture read earlier — reuse that fixture):

```python
import pytest


@pytest.mark.asyncio
async def test_sqlite_store_aget_aset_round_trip(store) -> None:
    await store.aset("1", {"title": "Intro to Python"})
    assert await store.aget("1") == {"title": "Intro to Python"}
    assert await store.aget("missing") is None


@pytest.mark.asyncio
async def test_sqlite_store_aset_many_and_afilter(store) -> None:
    await store.aset_many(
        {
            "1": {"author": "Alice", "category": "Programming"},
            "2": {"author": "Bob", "category": "History"},
        }
    )
    assert len(await store.afilter(author="Alice")) == 1
    assert len(await store.afilter(category="History")) == 1


@pytest.mark.asyncio
async def test_sqlite_store_acontains_many(store) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    found, missing = await store.acontains_many(["1", "3"])
    assert found == ["1"]
    assert missing == ["3"]


@pytest.mark.asyncio
async def test_sqlite_store_adelete_acount(store) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    await store.adelete("1")
    assert await store.acount() == 1


@pytest.mark.asyncio
async def test_sqlite_store_akeys_and_aiter_batches(store) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
    assert sorted([key async for key in store.akeys()]) == ["1", "2", "3"]
    batches = [batch async for batch in store.aiter_batches(batch_size=2)]
    assert sum(len(b) for b in batches) == 3


@pytest.mark.asyncio
async def test_sqlite_store_aclose_is_idempotent(store_cls) -> None:
    store = store_cls(":memory:")
    await store.aget("1")  # forces the lazy async connection open
    await store.aclose()
    await store.aclose()
    assert store.closed


def test_sqlite_store_async_methods_work_without_aiosqlite(
    store_cls, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from persista.store import sqlite as sqlite_module

    monkeypatch.setattr(sqlite_module, "is_aiosqlite_available", lambda: False)
    store = store_cls(":memory:")

    async def _run() -> dict[str, object] | None:
        await store.aset("1", {"a": 1})
        return await store.aget("1")

    assert asyncio.run(_run()) == {"a": 1}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/store/test_sqlite.py -v`
Expected: FAIL — `BaseSQLiteStore` has no `aget`/`aset`/etc.

- [ ] **Step 3: Rewrite `sqlite.py`'s `BaseSQLiteStore`**

Keep every existing sync method in `BaseSQLiteStore`, `SQLiteStore`, `TypedSQLiteStore`, and `PickleSQLiteStore` byte-for-byte (they already work), and add the pieces below. First, extend the imports and class body:

```python
r"""Provide a SQLite-backed implementation of ``BaseStore``, storing
values as JSON."""

from __future__ import annotations

__all__ = ["BaseSQLiteStore", "PickleSQLiteStore", "SQLiteStore", "TypedSQLiteStore"]

import asyncio
import json
import logging
import pickle
import sqlite3
from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin
from coola.utils.batching import batchify

from persista.store.base import BaseStore
from persista.store.uri import decode_path_uri, encode_path_uri
from persista.store.validation import (
    normalize_on_conflict,
    validate_batch_size,
    validate_field_name,
)
from persista.utils.imports import is_aiosqlite_available
from persista.utils.path import prepare_store_path

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator, Mapping
    from pathlib import Path

    from typing_extensions import Self

    from persista.store.types import OnConflict

if is_aiosqlite_available():  # pragma: no cover
    import aiosqlite

logger: logging.Logger = logging.getLogger(__name__)
```

Add the dual-connection state to `__init__` and the lazy-async-connection helper, right after the existing `_ensure_schema` method:

```python
    def __init__(self, database: Path | str, **kwargs: Any) -> None:
        self._database = database
        self._path_for_uri: Path | str = database
        self._kwargs = kwargs
        self._closed = False
        self._conn = sqlite3.connect(database, **kwargs)
        self._ensure_schema()
        self._aconn: aiosqlite.Connection | None = None
        self._aconn_lock = asyncio.Lock()
        self._aschema_ready = False

    async def _ensure_aconn(self) -> aiosqlite.Connection:
        """Lazily open (and schema-initialize) the aiosqlite connection.

        Only called when :func:`is_aiosqlite_available` is ``True``;
        callers must check that first and fall back to
        ``asyncio.to_thread`` otherwise (see e.g. :meth:`aget`).
        """
        async with self._aconn_lock:
            if self._aconn is None:
                self._aconn = await aiosqlite.connect(self._database, **self._kwargs)
            if not self._aschema_ready:
                try:
                    await self._aconn.execute(self._create_table_sql())
                    await self._aconn.commit()
                except sqlite3.OperationalError:
                    pass
                self._aschema_ready = True
        return self._aconn
```

Add the new abstract async write hook next to `_set_many`:

```python
    @abstractmethod
    async def _aset_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        """Async equivalent of :meth:`_set_many`, using the lazily
        opened ``aiosqlite`` connection."""
```

Add every `a`-prefixed method after its sync counterpart:

```python
    async def aget(self, key: str) -> dict[str, Any] | None:
        if not is_aiosqlite_available():
            return await asyncio.to_thread(self.get, key)
        conn = await self._ensure_aconn()
        cursor = await conn.execute(
            f"SELECT * FROM store WHERE {self._key_column} = ?",  # noqa: S608
            (key,),
        )
        row = await cursor.fetchone()
        return self._row_to_value(row) if row else None

    async def aget_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        if not keys:
            return []
        if not is_aiosqlite_available():
            return await asyncio.to_thread(self.get_many, keys)
        conn = await self._ensure_aconn()
        placeholders = ", ".join("?" * len(keys))
        cursor = await conn.execute(
            f"SELECT * FROM store WHERE {self._key_column} IN ({placeholders})",  # noqa: S608
            keys,
        )
        rows = await cursor.fetchall()
        by_key = {row[0]: self._row_to_value(row) for row in rows}
        return [by_key.get(key) for key in keys]

    async def aset(
        self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite"
    ) -> None:
        await self.aset_many({key: value}, on_conflict=on_conflict)

    async def aset_many(
        self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
    ) -> None:
        if not items:
            return
        if not is_aiosqlite_available():
            await asyncio.to_thread(self.set_many, items, on_conflict)
            return
        on_conflict = normalize_on_conflict(on_conflict)
        if on_conflict == "overwrite":
            await self._aset_many(items)
            return

        conflicts = set((await self.acontains_many(list(items)))[0])
        if conflicts and on_conflict == "raise":
            msg = f"Key(s) already exist in the store: {sorted(conflicts)}"
            raise KeyError(msg)

        to_write: dict[str, dict[str, Any]] = {}
        for key, value in items.items():
            if key in conflicts:
                if on_conflict == "skip":
                    continue
                to_write[key] = {**(await self.aget(key) or {}), **value}
                continue
            to_write[key] = value

        await self._aset_many(to_write)

    async def afilter(self, **field_filters: Any) -> list[dict[str, Any]]:
        if not is_aiosqlite_available():
            return await asyncio.to_thread(lambda: self.filter(**field_filters))
        conn = await self._ensure_aconn()
        if not field_filters:
            cursor = await conn.execute("SELECT * FROM store")
            rows = await cursor.fetchall()
            return [self._row_to_value(row) for row in rows]

        conditions = [self._build_filter_condition(key) for key in field_filters]
        where = " AND ".join(conditions)
        cursor = await conn.execute(
            f"SELECT * FROM store WHERE {where}",  # noqa: S608
            list(field_filters.values()),
        )
        rows = await cursor.fetchall()
        return [self._row_to_value(row) for row in rows]

    async def adelete(self, key: str) -> None:
        if not is_aiosqlite_available():
            await asyncio.to_thread(self.delete, key)
            return
        conn = await self._ensure_aconn()
        await conn.execute(f"DELETE FROM store WHERE {self._key_column} = ?", (key,))  # noqa: S608
        await conn.commit()

    async def adelete_many(self, keys: list[str]) -> None:
        if not keys:
            return
        if not is_aiosqlite_available():
            await asyncio.to_thread(self.delete_many, keys)
            return
        conn = await self._ensure_aconn()
        placeholders = ", ".join("?" * len(keys))
        await conn.execute(
            f"DELETE FROM store WHERE {self._key_column} IN ({placeholders})",  # noqa: S608
            keys,
        )
        await conn.commit()

    async def aclear(self) -> None:
        if not is_aiosqlite_available():
            await asyncio.to_thread(self.clear)
            return
        conn = await self._ensure_aconn()
        await conn.execute("DELETE FROM store")
        await conn.commit()

    async def acontains(self, key: str) -> bool:
        if not is_aiosqlite_available():
            return await asyncio.to_thread(self.contains, key)
        conn = await self._ensure_aconn()
        cursor = await conn.execute(
            f"SELECT 1 FROM store WHERE {self._key_column} = ? LIMIT 1",  # noqa: S608
            [key],
        )
        return await cursor.fetchone() is not None

    async def acontains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        if not keys:
            return [], []
        if not is_aiosqlite_available():
            return await asyncio.to_thread(self.contains_many, keys)
        conn = await self._ensure_aconn()
        placeholders = ", ".join("?" * len(keys))
        cursor = await conn.execute(
            f"SELECT {self._key_column} FROM store "  # noqa: S608
            f"WHERE {self._key_column} IN ({placeholders})",
            keys,
        )
        existing = {row[0] for row in await cursor.fetchall()}
        found = [key for key in keys if key in existing]
        missing = [key for key in keys if key not in existing]
        return found, missing

    async def akeys(self) -> AsyncIterator[str]:
        if not is_aiosqlite_available():
            iterator = await asyncio.to_thread(lambda: iter(self.keys()))
            while True:
                try:
                    key = await asyncio.to_thread(next, iterator)
                except StopIteration:
                    return
                yield key
            return
        conn = await self._ensure_aconn()
        cursor = await conn.execute(f"SELECT {self._key_column} FROM store")  # noqa: S608
        async for (key,) in cursor:
            yield key

    async def aiter_batches(
        self, batch_size: int = 32
    ) -> AsyncIterator[dict[str, dict[str, Any]]]:
        validate_batch_size(batch_size)
        if not is_aiosqlite_available():
            iterator = await asyncio.to_thread(
                lambda: iter(self.iter_batches(batch_size=batch_size))
            )
            while True:
                try:
                    batch = await asyncio.to_thread(next, iterator)
                except StopIteration:
                    return
                yield batch
            return
        conn = await self._ensure_aconn()
        cursor = await conn.execute("SELECT * FROM store")
        batch: dict[str, dict[str, Any]] = {}
        async for row in cursor:
            batch[row[0]] = self._row_to_value(row)
            if len(batch) >= batch_size:
                yield batch
                batch = {}
        if batch:
            yield batch

    async def acount(self) -> int:
        if not is_aiosqlite_available():
            return await asyncio.to_thread(self.count)
        conn = await self._ensure_aconn()
        cursor = await conn.execute("SELECT COUNT(*) FROM store")
        row = await cursor.fetchone()
        return row[0]

    async def aclose(self) -> None:
        if self._aconn is not None:
            await self._aconn.close()
            self._aconn = None
        if not self._closed:
            logger.info("Closing SQLite at %s", self._database)
            self._conn.close()
            self._closed = True
```

Modify the existing sync `close()` to also reap an already-opened async connection when it's safe to do so:

```python
    def close(self) -> None:
        if self._aconn is not None:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(self._aconn.close())
                self._aconn = None
            else:
                msg = (
                    "An async SQLite connection is open and close() was called from "
                    "inside a running event loop; use `await store.aclose()` instead."
                )
                raise RuntimeError(msg)
        if self._closed:
            return
        logger.info("Closing SQLite at %s", self._database)
        self._conn.close()
        self._closed = True
```

Add `_aset_many` to each concrete subclass, right after its existing `_set_many`:

```python
    # SQLiteStore
    async def _aset_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            conn = await self._ensure_aconn()
            await conn.executemany(
                "INSERT OR REPLACE INTO store VALUES (?, ?)",
                [(key, json.dumps(value)) for key, value in items.items()],
            )
            await conn.commit()
        logger.debug("Added/replaced %d key-value pair(s)", len(items))
```

```python
    # TypedSQLiteStore
    async def _aset_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            conn = await self._ensure_aconn()
            await conn.executemany(
                self._build_insert(),
                [self._value_to_row(key, value) for key, value in items.items()],
            )
            await conn.commit()
        logger.debug("Added/replaced %d key-value pair(s)", len(items))
```

```python
    # PickleSQLiteStore
    async def _aset_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            conn = await self._ensure_aconn()
            await conn.executemany(
                "INSERT OR REPLACE INTO store VALUES (?, ?)",
                [(key, pickle.dumps(value)) for key, value in items.items()],
            )
            await conn.commit()
        logger.debug("Added/replaced %d key-value pair(s)", len(items))
```

`PickleSQLiteStore` also needs an async `afilter` override mirroring its sync `filter` override (since its base `_build_filter_condition` raises `NotImplementedError`, the base class's `afilter` would too):

```python
    async def afilter(self, **field_filters: Any) -> list[dict[str, Any]]:
        if not is_aiosqlite_available():
            return await asyncio.to_thread(lambda: self.filter(**field_filters))
        conn = await self._ensure_aconn()
        cursor = await conn.execute("SELECT * FROM store")
        rows = await cursor.fetchall()
        values = (self._row_to_value(row) for row in rows)
        if not field_filters:
            return list(values)
        return [
            value
            for value in values
            if all(value.get(name) == expected for name, expected in field_filters.items())
        ]
```

Finally, update `__enter__`/add `__aenter__`/`__aexit__` at the bottom of `BaseSQLiteStore` (the sync `__enter__` is unchanged; add the async pair after it):

```python
    async def __aenter__(self) -> Self:
        if self._closed:
            self._conn = sqlite3.connect(self._database, **self._kwargs)
            self._closed = False
            self._ensure_schema()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
```

- [ ] **Step 4: Delete the redundant async module and test file**

```bash
git rm src/persista/store/async_sqlite.py tests/unit/store/test_async_sqlite.py
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/store/test_sqlite.py tests/unit/store/test_sqlite_pickle.py -v`
Expected: PASS. Also run with aiosqlite uninstalled to confirm the fallback path is exercised in CI too: `pip uninstall -y aiosqlite && pytest tests/unit/store/test_sqlite.py -k aiosqlite -v` (then `pip install aiosqlite` to restore your environment).

- [ ] **Step 6: Commit**

```bash
git add src/persista/store/sqlite.py tests/unit/store/test_sqlite.py tests/unit/store/test_sqlite_pickle.py
git commit -m "feat(store): merge SQLite stores with dual connections and aiosqlite-optional async fallback"
```

---

### Task 9: Merge Postgres stores

**Files:**
- Modify: `src/persista/store/postgres.py` (full rewrite of `BasePostgresStore`; `PostgresStore`/`TypedPostgresStore` gain `_aset_many`)
- Delete: `src/persista/store/async_postgres.py`
- Modify: `tests/integration/store/test_postgres.py` (merge in `tests/integration/store/test_async_postgres.py`)
- Delete: `tests/integration/store/test_async_postgres.py`

**Interfaces:**
- Consumes: `BaseStore` (Task 1).
- Produces: `BasePostgresStore(BaseStore, MultilineDisplayMixin)` holding both `psycopg.Connection` (eager) and `psycopg.AsyncConnection` (lazy, `asyncio.Lock`-guarded). No aiosqlite-style fallback here — `psycopg` (already a hard requirement for the sync side) ships `AsyncConnection` in the same package.

- [ ] **Step 1: Write the failing test**

Read `tests/integration/store/postgres_helpers.py` and `tests/integration/store/test_async_postgres.py` first to reuse the existing `testcontainers`-based fixture exactly (container URL, table setup). Then merge their test bodies into `tests/integration/store/test_postgres.py` as `async def test_*` functions marked `@pytest.mark.asyncio`, using the same `store_cls`/connection-string fixtures already defined there, e.g.:

```python
import pytest


@pytest.mark.asyncio
async def test_postgres_store_aget_aset_round_trip(store) -> None:
    await store.aset("1", {"title": "Intro to Python"})
    assert await store.aget("1") == {"title": "Intro to Python"}


@pytest.mark.asyncio
async def test_postgres_store_afilter(store) -> None:
    await store.aset_many({"1": {"author": "Alice"}, "2": {"author": "Bob"}})
    assert len(await store.afilter(author="Alice")) == 1


@pytest.mark.asyncio
async def test_postgres_store_acontains_many(store) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    found, missing = await store.acontains_many(["1", "3"])
    assert found == ["1"]
    assert missing == ["3"]


@pytest.mark.asyncio
async def test_postgres_store_akeys_aiter_batches(store) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
    assert sorted([key async for key in store.akeys()]) == ["1", "2", "3"]
    batches = [batch async for batch in store.aiter_batches(batch_size=2)]
    assert sum(len(b) for b in batches) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/store/test_postgres.py -v` (requires Docker; skip locally if unavailable and rely on CI)
Expected: FAIL — `BasePostgresStore` has no `aget`/`aset`/etc.

- [ ] **Step 3: Rewrite `postgres.py`'s `BasePostgresStore`**

Extend imports:

```python
import asyncio
import logging
from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin
from coola.utils.batching import batchify

from persista.store.base import BaseStore
from persista.store.validation import (
    normalize_on_conflict,
    validate_batch_size,
    validate_field_name,
    validate_table_name,
)
from persista.utils.imports import check_psycopg, is_psycopg_available

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator, Mapping
    from typing import Self

    from persista.store.types import OnConflict

if is_psycopg_available():  # pragma: no cover
    import psycopg
    from psycopg import sql
    from psycopg.types.json import Jsonb
```

Add dual-connection state to `__init__`:

```python
    def __init__(self, conninfo: str, *, table: str = "store", **kwargs: Any) -> None:
        check_psycopg()
        validate_table_name(table)
        self._conninfo = conninfo
        self._table = table
        self._kwargs = kwargs
        self._closed = False
        self._conn = psycopg.connect(conninfo, autocommit=True, **kwargs)
        self._conn.execute(self._create_table_sql())
        self._aconn: psycopg.AsyncConnection | None = None
        self._aconn_lock = asyncio.Lock()

    async def _ensure_aconn(self) -> psycopg.AsyncConnection:
        async with self._aconn_lock:
            if self._aconn is None:
                self._aconn = await psycopg.AsyncConnection.connect(
                    self._conninfo, autocommit=True, **self._kwargs
                )
                await self._aconn.execute(self._create_table_sql())
        return self._aconn
```

Add the abstract async write hook next to `_set_many`:

```python
    @abstractmethod
    async def _aset_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        """Async equivalent of :meth:`_set_many`."""
```

Add every `a`-prefixed method after its sync counterpart:

```python
    async def aget(self, key: str) -> dict[str, Any] | None:
        conn = await self._ensure_aconn()
        query = sql.SQL("SELECT * FROM {table} WHERE {key_col} = %s").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        async with conn.cursor() as cur:
            await cur.execute(query, (key,))
            row = await cur.fetchone()
        return self._row_to_value(row) if row else None

    async def aget_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        if not keys:
            return []
        conn = await self._ensure_aconn()
        query = sql.SQL("SELECT * FROM {table} WHERE {key_col} = ANY(%s)").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        async with conn.cursor() as cur:
            await cur.execute(query, (keys,))
            rows = await cur.fetchall()
        by_key = {row[0]: self._row_to_value(row) for row in rows}
        return [by_key.get(key) for key in keys]

    async def aset(
        self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite"
    ) -> None:
        await self.aset_many({key: value}, on_conflict=on_conflict)

    async def aset_many(
        self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
    ) -> None:
        if not items:
            return
        on_conflict = normalize_on_conflict(on_conflict)
        if on_conflict == "overwrite":
            await self._aset_many(items)
            return

        conflicts = set((await self.acontains_many(list(items)))[0])
        if conflicts and on_conflict == "raise":
            msg = f"Key(s) already exist in the store: {sorted(conflicts)}"
            raise KeyError(msg)

        to_write: dict[str, dict[str, Any]] = {}
        for key, value in items.items():
            if key in conflicts:
                if on_conflict == "skip":
                    continue
                to_write[key] = {**(await self.aget(key) or {}), **value}
                continue
            to_write[key] = value

        await self._aset_many(to_write)

    async def afilter(self, **field_filters: Any) -> list[dict[str, Any]]:
        conn = await self._ensure_aconn()
        if not field_filters:
            query = sql.SQL("SELECT * FROM {table}").format(table=self._table_ident)
            async with conn.cursor() as cur:
                await cur.execute(query)
                rows = await cur.fetchall()
            return [self._row_to_value(row) for row in rows]

        conditions = [self._build_filter_condition(key) for key in field_filters]
        where = sql.SQL(" AND ").join(conditions)
        query = sql.SQL("SELECT * FROM {table} WHERE {where}").format(
            table=self._table_ident, where=where
        )
        async with conn.cursor() as cur:
            await cur.execute(query, list(field_filters.values()))
            rows = await cur.fetchall()
        return [self._row_to_value(row) for row in rows]

    async def adelete(self, key: str) -> None:
        conn = await self._ensure_aconn()
        query = sql.SQL("DELETE FROM {table} WHERE {key_col} = %s").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        await conn.execute(query, (key,))

    async def adelete_many(self, keys: list[str]) -> None:
        if not keys:
            return
        conn = await self._ensure_aconn()
        query = sql.SQL("DELETE FROM {table} WHERE {key_col} = ANY(%s)").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        await conn.execute(query, (keys,))

    async def aclear(self) -> None:
        conn = await self._ensure_aconn()
        query = sql.SQL("DELETE FROM {table}").format(table=self._table_ident)
        await conn.execute(query)

    async def acontains(self, key: str) -> bool:
        conn = await self._ensure_aconn()
        query = sql.SQL("SELECT 1 FROM {table} WHERE {key_col} = %s LIMIT 1").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        async with conn.cursor() as cur:
            await cur.execute(query, (key,))
            return await cur.fetchone() is not None

    async def acontains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        if not keys:
            return [], []
        conn = await self._ensure_aconn()
        query = sql.SQL("SELECT {key_col} FROM {table} WHERE {key_col} = ANY(%s)").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        async with conn.cursor() as cur:
            await cur.execute(query, (keys,))
            existing = {row[0] for row in await cur.fetchall()}
        found = [key for key in keys if key in existing]
        missing = [key for key in keys if key not in existing]
        return found, missing

    async def akeys(self) -> AsyncIterator[str]:
        conn = await self._ensure_aconn()
        query = sql.SQL("SELECT {key_col} FROM {table}").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        async with conn.cursor() as cur:
            await cur.execute(query)
            async for (key,) in cur:
                yield key

    async def aiter_batches(
        self, batch_size: int = 32
    ) -> AsyncIterator[dict[str, dict[str, Any]]]:
        validate_batch_size(batch_size)
        conn = await self._ensure_aconn()
        query = sql.SQL("SELECT * FROM {table}").format(table=self._table_ident)
        async with (
            conn.transaction(),
            conn.cursor(name=f"aiter_batches_{id(self)}") as cur,
        ):
            cur.itersize = batch_size
            await cur.execute(query)
            batch: dict[str, dict[str, Any]] = {}
            async for row in cur:
                batch[row[0]] = self._row_to_value(row)
                if len(batch) >= batch_size:
                    yield batch
                    batch = {}
            if batch:
                yield batch

    async def acount(self) -> int:
        conn = await self._ensure_aconn()
        query = sql.SQL("SELECT COUNT(*) FROM {table}").format(table=self._table_ident)
        async with conn.cursor() as cur:
            await cur.execute(query)
            row = await cur.fetchone()
            return row[0] if row else 0

    async def aclose(self) -> None:
        if self._aconn is not None:
            await self._aconn.close()
            self._aconn = None
        if not self._closed:
            logger.info("Closing Postgres connection for table %s", self._table)
            self._conn.close()
            self._closed = True
```

Update `close()`:

```python
    def close(self) -> None:
        if self._aconn is not None:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(self._aconn.close())
                self._aconn = None
            else:
                msg = (
                    "An async Postgres connection is open and close() was called from "
                    "inside a running event loop; use `await store.aclose()` instead."
                )
                raise RuntimeError(msg)
        if self._closed:
            return
        logger.info("Closing Postgres connection for table %s", self._table)
        self._conn.close()
        self._closed = True
```

Add `async def __aenter__`/`__aexit__` next to the existing `__enter__`:

```python
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
```

Add `_aset_many` to `PostgresStore` (after its `_set_many`):

```python
    async def _aset_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            conn = await self._ensure_aconn()
            query = sql.SQL(
                "INSERT INTO {table} ({key_col}, value) VALUES (%s, %s) "
                "ON CONFLICT ({key_col}) DO UPDATE SET value = EXCLUDED.value"
            ).format(table=self._table_ident, key_col=sql.Identifier(self._key_column))
            async with conn.cursor() as cur:
                await cur.executemany(
                    query, [(key, Jsonb(value)) for key, value in items.items()]
                )
        logger.debug("Added/replaced %d key-value pair(s)", len(items))
```

Add `_aset_many` to `TypedPostgresStore` (after its `_set_many`):

```python
    async def _aset_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            conn = await self._ensure_aconn()
            query = self._build_insert()
            async with conn.cursor() as cur:
                await cur.executemany(
                    query, [self._value_to_row(key, value) for key, value in items.items()]
                )
        logger.debug("Added/replaced %d key-value pair(s)", len(items))
```

- [ ] **Step 4: Delete the redundant async module and test file**

```bash
git rm src/persista/store/async_postgres.py tests/integration/store/test_async_postgres.py
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/integration/store/test_postgres.py -v` (requires Docker via `testcontainers`)
Expected: PASS (or SKIPPED if Docker is unavailable in this environment)

- [ ] **Step 6: Commit**

```bash
git add src/persista/store/postgres.py tests/integration/store/test_postgres.py
git commit -m "feat(store): merge Postgres stores with dual sync/async connections"
```

---

### Task 10: Merge Redis stores

**Files:**
- Modify: `src/persista/store/redis.py` (full rewrite of `BaseRedisStore`; `RedisStore`/`PickleRedisStore` unchanged since `_encode`/`_decode` don't depend on connection mode)
- Delete: `src/persista/store/async_redis.py`
- Modify: `tests/integration/store/test_redis.py` (merge in `tests/integration/store/test_async_redis.py`)
- Delete: `tests/integration/store/test_async_redis.py`

**Interfaces:**
- Consumes: `BaseStore` (Task 1).
- Produces: `BaseRedisStore(BaseStore, MultilineDisplayMixin)` holding both `redis.Redis` (eager) and `redis.asyncio.Redis` (lazy). `redis-py` bundles both under one package, so no fallback branch is needed (unlike SQLite/aiosqlite).

- [ ] **Step 1: Write the failing test**

Read `tests/integration/store/redis_helpers.py` and `tests/integration/store/test_async_redis.py` first to reuse the existing `fakeredis`/`testcontainers` fixture. Merge into `tests/integration/store/test_redis.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_redis_store_aget_aset_round_trip(store) -> None:
    await store.aset("1", {"title": "Intro to Python"})
    assert await store.aget("1") == {"title": "Intro to Python"}


@pytest.mark.asyncio
async def test_redis_store_afilter(store) -> None:
    await store.aset_many({"1": {"author": "Alice"}, "2": {"author": "Bob"}})
    assert await store.afilter(author="Alice") == [{"author": "Alice"}]


@pytest.mark.asyncio
async def test_redis_store_acontains_many(store) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    found, missing = await store.acontains_many(["1", "3"])
    assert found == ["1"]
    assert missing == ["3"]


@pytest.mark.asyncio
async def test_redis_store_akeys_aclear(store) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    assert sorted([key async for key in store.akeys()]) == ["1", "2"]
    await store.aclear()
    assert await store.acount() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/store/test_redis.py -v`
Expected: FAIL — `BaseRedisStore` has no `aget`/`aset`/etc.

- [ ] **Step 3: Rewrite `redis.py`'s `BaseRedisStore`**

Extend imports:

```python
import asyncio
import json
import logging
import pickle
from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin
from coola.utils.batching import batchify

from persista.store.base import BaseStore
from persista.store.validation import normalize_on_conflict, validate_batch_size
from persista.utils.imports import check_redis, is_redis_available

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator, Mapping
    from typing import Self

    from persista.store.types import OnConflict

if is_redis_available():  # pragma: no cover
    import redis
    import redis.asyncio as aredis
```

Add dual-client state to `__init__`:

```python
    def __init__(self, url: str = "redis://localhost:6379/0", **kwargs: Any) -> None:
        check_redis()
        self._url = url
        self._kwargs = kwargs
        self._closed = False
        self._client = redis.Redis.from_url(url, decode_responses=self._decode_responses, **kwargs)
        self._aclient: aredis.Redis | None = None
        self._aclient_lock = asyncio.Lock()

    async def _ensure_aclient(self) -> aredis.Redis:
        async with self._aclient_lock:
            if self._aclient is None:
                self._aclient = aredis.Redis.from_url(
                    self._url, decode_responses=self._decode_responses, **self._kwargs
                )
        return self._aclient
```

Add every `a`-prefixed method after its sync counterpart:

```python
    async def aget(self, key: str) -> dict[str, Any] | None:
        client = await self._ensure_aclient()
        value = await client.get(key)
        return self._decode(value) if value is not None else None

    async def aget_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        if not keys:
            return []
        client = await self._ensure_aclient()
        values = await client.mget(keys)
        return [self._decode(value) if value is not None else None for value in values]

    async def aset(
        self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite"
    ) -> None:
        await self.aset_many({key: value}, on_conflict=on_conflict)

    async def aset_many(
        self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
    ) -> None:
        if not items:
            return
        on_conflict = normalize_on_conflict(on_conflict)
        if on_conflict == "overwrite":
            await self._aset_many(items)
            return

        conflicts = set((await self.acontains_many(list(items)))[0])
        if conflicts and on_conflict == "raise":
            msg = f"Key(s) already exist in the store: {sorted(conflicts)}"
            raise KeyError(msg)

        to_write: dict[str, dict[str, Any]] = {}
        for key, value in items.items():
            if key in conflicts:
                if on_conflict == "skip":
                    continue
                to_write[key] = {**(await self.aget(key) or {}), **value}
                continue
            to_write[key] = value

        await self._aset_many(to_write)

    async def _aset_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            client = await self._ensure_aclient()
            pipe = client.pipeline()
            for key, value in items.items():
                pipe.set(key, self._encode(value))
            pipe.sadd(_KEYS_SET, *items.keys())
            await pipe.execute()
        logger.debug("Added/replaced %d key-value pair(s)", len(items))

    async def afilter(self, **field_filters: Any) -> list[dict[str, Any]]:
        return [
            value
            async for value in self.avalues()
            if all(value.get(name) == expected for name, expected in field_filters.items())
        ]

    async def adelete(self, key: str) -> None:
        client = await self._ensure_aclient()
        pipe = client.pipeline()
        pipe.delete(key)
        pipe.srem(_KEYS_SET, key)
        await pipe.execute()

    async def adelete_many(self, keys: list[str]) -> None:
        if not keys:
            return
        client = await self._ensure_aclient()
        pipe = client.pipeline()
        pipe.delete(*keys)
        pipe.srem(_KEYS_SET, *keys)
        await pipe.execute()

    async def aclear(self) -> None:
        await self.adelete_many([key async for key in self.akeys()])

    async def acontains(self, key: str) -> bool:
        client = await self._ensure_aclient()
        return bool(await client.sismember(_KEYS_SET, key))

    async def acontains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        if not keys:
            return [], []
        client = await self._ensure_aclient()
        flags = await client.smismember(_KEYS_SET, keys)
        found = [key for key, flag in zip(keys, flags, strict=True) if flag]
        missing = [key for key, flag in zip(keys, flags, strict=True) if not flag]
        return found, missing

    async def akeys(self) -> AsyncIterator[str]:
        client = await self._ensure_aclient()
        for key in await client.smembers(_KEYS_SET):
            yield self._key_str(key)

    async def aiter_batches(
        self, batch_size: int = 32
    ) -> AsyncIterator[dict[str, dict[str, Any]]]:
        validate_batch_size(batch_size)
        client = await self._ensure_aclient()
        all_keys = [self._key_str(key) for key in await client.smembers(_KEYS_SET)]
        for batch in batchify(all_keys, size=batch_size):
            values = await client.mget(batch)
            yield {
                key: self._decode(value)
                for key, value in zip(batch, values, strict=True)
                if value is not None
            }

    async def acount(self) -> int:
        client = await self._ensure_aclient()
        return await client.scard(_KEYS_SET)

    async def aclose(self) -> None:
        if self._aclient is not None:
            await self._aclient.aclose()
            self._aclient = None
        if not self._closed:
            logger.info("Closing Redis connection at %s", self._url)
            self._client.close()
            self._closed = True
```

Update `close()`:

```python
    def close(self) -> None:
        if self._aclient is not None:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(self._aclient.aclose())
                self._aclient = None
            else:
                msg = (
                    "An async Redis connection is open and close() was called from "
                    "inside a running event loop; use `await store.aclose()` instead."
                )
                raise RuntimeError(msg)
        if self._closed:
            return
        logger.info("Closing Redis connection at %s", self._url)
        self._client.close()
        self._closed = True
```

Add `async def __aenter__`/`__aexit__` (reopening the async client lazily is unnecessary since `_ensure_aclient` already re-creates it on demand; only the sync client needs eager reopening, matching the existing `__enter__`):

```python
    async def __aenter__(self) -> Self:
        if self._closed:
            self._client = redis.Redis.from_url(
                self._url, decode_responses=self._decode_responses, **self._kwargs
            )
            self._closed = False
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
```

`RedisStore` and `PickleRedisStore` need no changes — their `_encode`/`_decode` hooks are connection-mode-agnostic and are reused as-is by both `_set_many`/`_aset_many`.

- [ ] **Step 4: Delete the redundant async module and test file**

```bash
git rm src/persista/store/async_redis.py tests/integration/store/test_async_redis.py
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/integration/store/test_redis.py -v`
Expected: PASS (or SKIPPED without a live/fake Redis)

- [ ] **Step 6: Commit**

```bash
git add src/persista/store/redis.py tests/integration/store/test_redis.py
git commit -m "feat(store): merge Redis stores with dual sync/async clients"
```

---

### Task 11: Collapse the registry

**Files:**
- Modify: `src/persista/store/registry.py` (full rewrite)
- Modify: `tests/unit/store/test_registry.py` (drop the async-specific tests, keep one dict/one function tested for both sync and async schemes)

**Interfaces:**
- Consumes: every merged store class from Tasks 3-10 (`InMemoryStore`, `NullStore`, `JsonFileStore`, `PickleFileStore`, `SQLiteStore`, `PickleSQLiteStore`, `TypedSQLiteStore`, `DuckDBStore`, `TypedDuckDBStore`, `LmdbStore`, `PickleLmdbStore`, `PostgresStore`, `RedisStore`).
- Produces: `store_from_uri(uri, *, read_only=False) -> BaseStore`, `register_scheme(scheme, store_cls) -> None`. `async_store_from_uri`/`register_async_scheme` are removed.

- [ ] **Step 1: Write the failing test**

Read the existing `tests/unit/store/test_registry.py` first; replace any test that calls `async_store_from_uri`/`register_async_scheme` with a single async-mode assertion using the same `store_from_uri` function:

```python
import pytest

from persista.store import InMemoryStore, register_scheme, store_from_uri


def test_store_from_uri_memory_scheme() -> None:
    store = store_from_uri("memory://")
    assert isinstance(store, InMemoryStore)


@pytest.mark.asyncio
async def test_store_from_uri_result_supports_async_methods() -> None:
    store = store_from_uri("memory://")
    await store.aset("1", {"a": 1})
    assert await store.aget("1") == {"a": 1}


def test_register_scheme_overrides_existing() -> None:
    class _CustomStore(InMemoryStore):
        pass

    register_scheme("memory", _CustomStore)
    try:
        store = store_from_uri("memory://")
        assert isinstance(store, _CustomStore)
    finally:
        register_scheme("memory", InMemoryStore)


def test_store_from_uri_unknown_scheme_raises() -> None:
    with pytest.raises(ValueError, match="No store registered"):
        store_from_uri("bogus://x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/store/test_registry.py -v`
Expected: FAIL if the old file still references `async_store_from_uri`/`register_async_scheme` (import error) — remove those references as part of this same edit.

- [ ] **Step 3: Rewrite `registry.py`**

```python
r"""Provide a generic ``BaseStore`` dispatcher that reconstructs a
store from a URI without knowing its concrete class upfront."""

from __future__ import annotations

__all__ = ["register_scheme", "store_from_uri"]

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from persista.store.duckdb import DuckDBStore, TypedDuckDBStore
from persista.store.file import JsonFileStore, PickleFileStore
from persista.store.in_memory import InMemoryStore
from persista.store.lmdb import LmdbStore, PickleLmdbStore
from persista.store.null import NullStore
from persista.store.postgres import PostgresStore
from persista.store.redis import RedisStore
from persista.store.sqlite import PickleSQLiteStore, SQLiteStore, TypedSQLiteStore

if TYPE_CHECKING:
    from persista.store.base import BaseStore

_SCHEMES: dict[str, type[BaseStore]] = {
    "memory": InMemoryStore,
    "null": NullStore,
    "file+json": JsonFileStore,
    "file+pickle": PickleFileStore,
    "sqlite": SQLiteStore,
    "sqlite+pickle": PickleSQLiteStore,
    "sqlite+typed": TypedSQLiteStore,
    "duckdb": DuckDBStore,
    "duckdb+typed": TypedDuckDBStore,
    "lmdb": LmdbStore,
    "lmdb+pickle": PickleLmdbStore,
    "postgresql": PostgresStore,
    "postgres": PostgresStore,
    "redis": RedisStore,
    "rediss": RedisStore,
}


def register_scheme(scheme: str, store_cls: type[BaseStore]) -> None:
    """Register a store class for a URI scheme used by
    :func:`store_from_uri`.

    Args:
        scheme: The URI scheme to associate with ``store_cls``, e.g.
            ``"memory"``. Overwrites any class already registered for
            this scheme.
        store_cls: The ``BaseStore`` subclass to dispatch to for
            ``scheme``. Must implement ``from_uri``.
    """
    _SCHEMES[scheme] = store_cls


def store_from_uri(uri: str, *, read_only: bool = False) -> BaseStore:
    """Reconstruct a :class:`~persista.store.base.BaseStore` from a URI.

    Dispatches on ``uri``'s scheme to the matching store class's
    :meth:`~persista.store.base.BaseStore.from_uri`. The returned
    store supports both sync and async access. Store classes whose
    scheme is shared with another class (``TypedPostgresStore`` reuses
    ``PostgresStore``'s native ``postgresql://`` scheme,
    ``PickleRedisStore`` reuses ``RedisStore``'s native ``redis://``
    scheme) aren't reachable through this dispatcher -- call
    ``TheClass.from_uri(uri)`` directly for those.

    Args:
        uri: A URI produced by some ``BaseStore`` subclass's
            ``to_uri()``.
        read_only: Forwarded to the matched class's ``from_uri``.

    Returns:
        A new store instance.

    Raises:
        ValueError: If ``uri``'s scheme is not registered.
    """
    scheme = urlsplit(uri).scheme
    store_cls = _SCHEMES.get(scheme)
    if store_cls is None:
        msg = f"No store registered for scheme {scheme!r} (from {uri!r})"
        raise ValueError(msg)
    return store_cls.from_uri(uri, read_only=read_only)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/store/test_registry.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/persista/store/registry.py tests/unit/store/test_registry.py
git commit -m "refactor(store): collapse registry to one scheme dict and one store_from_uri"
```

---

### Task 12: Update `store/__init__.py` exports

**Files:**
- Modify: `src/persista/store/__init__.py` (full rewrite)

**Interfaces:**
- Consumes: every class/function from Tasks 1-11.
- Produces: package `__all__` with no `Async*` names.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/store/test_registry.py` (or a new `tests/unit/store/test_package_exports.py`):

```python
def test_store_package_has_no_async_prefixed_exports() -> None:
    import persista.store as store_pkg

    assert not any(name.startswith("Async") for name in store_pkg.__all__)


def test_store_package_exports_store_from_uri_only() -> None:
    import persista.store as store_pkg

    assert "store_from_uri" in store_pkg.__all__
    assert "async_store_from_uri" not in store_pkg.__all__
    assert "register_scheme" in store_pkg.__all__
    assert "register_async_scheme" not in store_pkg.__all__
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/store/test_registry.py -k package_exports -v`
Expected: FAIL — `__init__.py` still lists `Async*` names and `async_store_from_uri`/`register_async_scheme`.

- [ ] **Step 3: Rewrite `__init__.py`**

```python
r"""Contain stores."""

from __future__ import annotations

__all__ = [
    "BaseDuckDBStore",
    "BaseFileStore",
    "BaseLmdbStore",
    "BasePostgresStore",
    "BaseRedisStore",
    "BaseSQLiteStore",
    "BaseStore",
    "DuckDBStore",
    "InMemoryStore",
    "JsonFileStore",
    "LmdbStore",
    "NullStore",
    "OnConflict",
    "PickleFileStore",
    "PickleLmdbStore",
    "PickleRedisStore",
    "PickleSQLiteStore",
    "PostgresStore",
    "RedisStore",
    "SQLiteStore",
    "TypedDuckDBStore",
    "TypedPostgresStore",
    "TypedSQLiteStore",
    "normalize_on_conflict",
    "register_scheme",
    "store_from_uri",
    "validate_batch_size",
    "validate_field_name",
    "validate_on_conflict",
]

from persista.store.base import BaseStore
from persista.store.duckdb import BaseDuckDBStore, DuckDBStore, TypedDuckDBStore
from persista.store.file import BaseFileStore, JsonFileStore, PickleFileStore
from persista.store.in_memory import InMemoryStore
from persista.store.lmdb import BaseLmdbStore, LmdbStore, PickleLmdbStore
from persista.store.null import NullStore
from persista.store.postgres import BasePostgresStore, PostgresStore, TypedPostgresStore
from persista.store.redis import BaseRedisStore, PickleRedisStore, RedisStore
from persista.store.registry import register_scheme, store_from_uri
from persista.store.sqlite import (
    BaseSQLiteStore,
    PickleSQLiteStore,
    SQLiteStore,
    TypedSQLiteStore,
)
from persista.store.types import OnConflict
from persista.store.validation import (
    normalize_on_conflict,
    validate_batch_size,
    validate_field_name,
    validate_on_conflict,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/store/test_registry.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/persista/store/__init__.py tests/unit/store/test_registry.py
git commit -m "refactor(store): drop Async* exports from persista.store"
```

---

### Task 13: Update `cache/async_cache.py` consumer

**Files:**
- Modify: `src/persista/cache/async_cache.py`
- Test: `tests/unit/cache/test_async_cache.py` (run existing tests; no new tests needed if behavior is unchanged, but add one explicit regression test)

**Interfaces:**
- Consumes: `BaseStore` (Task 1), `InMemoryStore` (Task 4).
- Produces: `AsyncCache.__init__(self, ..., store: BaseStore | None = None)` — same public signature, just retyped; internally calls `store.aget`/`store.aset`/etc. exactly as it already did (those method names are unchanged by the merge).

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/cache/test_async_cache.py`:

```python
import pytest

from persista.cache import AsyncCache
from persista.store import BaseStore, InMemoryStore


def test_async_cache_accepts_base_store_type() -> None:
    store = InMemoryStore()
    cache = AsyncCache(store=store)
    assert isinstance(cache._store, BaseStore)


@pytest.mark.asyncio
async def test_async_cache_default_store_is_in_memory_store() -> None:
    cache = AsyncCache()
    assert isinstance(cache._store, InMemoryStore)
    await cache.set("k", "v")
    assert await cache.get("k") == "v"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/cache/test_async_cache.py -k "base_store_type or default_store_is_in_memory" -v`
Expected: FAIL with `ImportError: cannot import name 'AsyncBaseStore'` (from `async_cache.py`'s current imports) once `store/base.py` no longer exports that name — this failure will actually already be present from Task 1 onward; this task is where it gets fixed.

- [ ] **Step 3: Update `async_cache.py`'s imports and type annotations**

Change:

```python
from persista.store.async_in_memory import AsyncInMemoryStore
```
to:
```python
from persista.store.in_memory import InMemoryStore
```

Change the `TYPE_CHECKING` import:

```python
if TYPE_CHECKING:
    from persista.store.base import AsyncBaseStore
```
to:
```python
if TYPE_CHECKING:
    from persista.store.base import BaseStore
```

Change the constructor:

```python
        store: AsyncBaseStore | None = None,
```
to:
```python
        store: BaseStore | None = None,
```
and
```python
        self._store: AsyncBaseStore = store if store is not None else AsyncInMemoryStore()
```
to:
```python
        self._store: BaseStore = store if store is not None else InMemoryStore()
```

Every call site inside `async_cache.py` already uses `self._store.aget(...)`, `self._store.aset(...)`, etc. (per the original `AsyncBaseStore` interface) — those method names (`aget`/`aset`/`adelete`/...) are unchanged by the merge, so no other call sites need editing. Update the module docstring and any inline prose that says ``AsyncBaseStore`` to say ``BaseStore`` (a `grep -n AsyncBaseStore src/persista/cache/async_cache.py` after the edit should return nothing).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/cache/test_async_cache.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/persista/cache/async_cache.py tests/unit/cache/test_async_cache.py
git commit -m "fix(cache): update AsyncCache to use the merged BaseStore/InMemoryStore"
```

---

### Task 14: Final sweep — full suite, stray references, doc/pyproject cleanup

**Files:**
- Modify: any file a repo-wide grep turns up (see Step 1)
- Modify: `pyproject.toml` doc comment near the `aiosqlite` extra, if one references the old async-only requirement
- Modify: `tests/integration/store/test_consistency_async.py` → merge into `tests/integration/store/test_consistency.py`, then delete
- Modify: `docs/docs/refs/store.md`, `docs/docs/uguide/store.md` (update any `Async*` class references)

**Interfaces:**
- Consumes: everything from Tasks 1-13.
- Produces: a repo with zero references to `AsyncBaseStore`/`Async*Store`/`async_store_from_uri`/`register_async_scheme` outside of historical git log/CHANGELOG entries.

- [ ] **Step 1: Grep for stray references**

```bash
grep -rln "AsyncBaseStore\|AsyncInMemoryStore\|AsyncNullStore\|AsyncSQLiteStore\|AsyncBaseSQLiteStore\|AsyncTypedSQLiteStore\|AsyncPostgresStore\|AsyncBasePostgresStore\|AsyncTypedPostgresStore\|AsyncRedisStore\|AsyncBaseRedisStore\|AsyncPickleRedisStore\|async_store_from_uri\|register_async_scheme" src/ tests/ docs/ --include="*.py" --include="*.md" | grep -v __pycache__
```

Fix every hit found: source files should already be clean after Tasks 1-13; likely remaining hits are `tests/integration/store/test_consistency_async.py`, and prose mentions in `docs/docs/refs/store.md`/`docs/docs/uguide/store.md`.

- [ ] **Step 2: Merge `test_consistency_async.py` into `test_consistency.py`**

Read both files (they cross-check that every backend's store round-trips the same data under the same key across the sync/async pair, per the design's intent to have one class support both modes now). Port each `test_*` function from `test_consistency_async.py` into `test_consistency.py` as an `async def` marked `@pytest.mark.asyncio`, changing sync store construction/method calls (`store.set(...)`, `store.get(...)`) to their async equivalents (`await store.aset(...)`, `await store.aget(...)`) and reusing the same store instance/fixture the merged backend classes now provide for both modes, rather than constructing separate sync/async store instances as the two files did before the merge.

- [ ] **Step 3: Grep again to confirm no stale references remain**

```bash
grep -rln "Async" tests/ src/persista/store src/persista/cache | grep -v "__pycache__"
```

Expected: no matches (or only comments/docstrings explaining the pre-merge history, which should also be cleaned up if found).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit tests/integration -v` (integration tests that need Docker/Postgres/Redis will skip if those services aren't available, per the existing `testcontainers`/`fakeredis` setup)
Expected: PASS (or SKIPPED for integration tests lacking a live service), zero failures, zero collection errors.

- [ ] **Step 5: Commit**

```bash
git rm tests/integration/store/test_consistency_async.py
git add tests/integration/store/test_consistency.py docs/docs/refs/store.md docs/docs/uguide/store.md pyproject.toml
git commit -m "test(store): merge remaining sync/async consistency tests, drop Async* references"
```

---

## Self-Review

**1. Spec coverage:**
- `BaseStore` single ABC with paired sync/`a`-prefixed abstract methods, concrete `set_batches`/`aset_batches`, `values`/`avalues`, single `to_uri`/`from_uri`/`closed`, both context-manager protocols → Task 1.
- `iter_batches`/`aiter_batches` typed `Iterator`/`AsyncIterator` (not `Generator`/`AsyncGenerator`) on the ABC, implementations stay plain generator functions → Task 1, carried through Tasks 3-10 unchanged.
- `AsyncBaseStore`/`Async*Store` removed with no aliases → Tasks 1, 3, 4, 8, 9, 10, 12; Task 14's grep sweep is the final verification gate.
- Category A dual-connection design (SQLite/Postgres/Redis): sync eager, async lazy behind `asyncio.Lock` → Tasks 8, 9, 10.
- SQLite aiosqlite-optional fallback to `asyncio.to_thread` → Task 8 (`is_aiosqlite_available()` branch in every async method, plus the dedicated fallback test).
- Category B `ThreadedAsyncStoreMixin`, including the `keys`/`iter_batches` → `akeys`/`aiter_batches` bridge → Task 2, consumed by Tasks 3-7.
- Close lifecycle for category A (`aclose` awaits async conn then closes sync; `close` closes sync directly and `asyncio.run`s the async conn's close only outside a running loop, else raises `RuntimeError`) → implemented identically in Tasks 8, 9, 10.
- Registry collapse to one `_SCHEMES`/`store_from_uri`/`register_scheme` → Task 11.
- `store/__init__.py` exports updated → Task 12.
- Non-goals (no schema/URI/`OnConflict` changes) → respected throughout; every `_create_table_sql`, encoding, and URI helper is copied verbatim from the pre-merge sync implementation in Tasks 3-10.
- Consumers outside `store/` (`persista/cache/cache.py` already only used sync `BaseStore` methods, no change needed; `persista/cache/async_cache.py` needed retyping) → Task 13.
- Test suite reorganization → Tasks 3, 4, 8, 9, 10 each fold their backend's async test file into the sync one as part of the same task; Task 14 is the final sweep for `test_consistency_async.py` plus a repo-wide grep gate.

**2. Placeholder scan:** No "TBD"/"add appropriate handling"/"similar to Task N" phrasing is used; every step has complete, runnable code. Task 5/6/7's test steps say "matching whatever fixture the file already provides" for the store-per-test fixture name — this is a deliberate, narrow accommodation for fixture names in files not read in full during planning, not a code placeholder; the test bodies themselves are complete. Task 9/10's integration test steps similarly reuse existing container fixtures by name rather than re-deriving them, since those fixtures are already established in `postgres_helpers.py`/`redis_helpers.py`.

**3. Type/signature consistency:** `BaseStore.get`/`aget`, `set_many`/`aset_many`, `iter_batches`/`aiter_batches`, `count`/`acount`, `close`/`aclose`, single `closed` are used identically across Tasks 1-13. `ThreadedAsyncStoreMixin` method names (`aget`, `aget_many`, `aset`, `aset_many`, `afilter`, `adelete`, `adelete_many`, `aclear`, `acontains`, `acontains_many`, `akeys`, `aiter_batches`, `acount`, `aclose`) match exactly what `BaseStore` declares as abstract in Task 1 and what Tasks 3-7 rely on via the mixin. `_set_many`/`_aset_many` hook names introduced in Task 8 (SQLite) and Task 9 (Postgres) are consistent between the base class and every subclass. `store_from_uri`/`register_scheme` signatures in Task 11 match their usage in Task 12's `__init__.py` and Task 14's tests.
