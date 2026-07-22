# Store URI Round-Trip (`to_uri` / `from_uri`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every store in `persista.store` a `to_uri()` instance method and a `from_uri(uri, *, read_only=False)` classmethod, so file/database-backed stores can be serialized to a URI and reconstructed from it, and add a generic `store_from_uri` / `async_store_from_uri` dispatcher that picks the right class from the URI's scheme.

**Architecture:** A tiny `persista/store/uri.py` helper (`encode_path_uri`/`decode_path_uri`) is shared by every path-based store family. Each family's `Base*Store` class implements `to_uri`/`from_uri` once, off a `scheme`/`_scheme` class attribute that leaf classes set. `BasePostgresStore`/`BaseRedisStore` reuse their native connection string directly instead of a custom scheme. `InMemoryStore`/`NullStore` return a fixed scheme and always reconstruct empty. A new `persista/store/registry.py` maps schemes to classes for the two dispatcher functions.

**Tech Stack:** Python 3, `urllib.parse` (stdlib), pytest, existing `persista.store` package.

## Global Constraints

- `to_uri`/`from_uri` do NOT preserve `value_schema` (`TypedSQLiteStore`, `TypedDuckDBStore`, `TypedPostgresStore`) or `table` (`Postgres*Store`) — `from_uri` always reconstructs with the default (empty schema / `"store"` table).
- `to_uri`/`from_uri` do NOT preserve any other constructor kwargs (`sqlite3.connect` timeout, DuckDB `read_only` beyond the explicit `read_only` param below, LMDB `map_size`, psycopg/redis connection kwargs, `iden.io` save/load kwargs).
- `from_uri(cls, uri: str, *, read_only: bool = False) -> Self` is the exact signature on every store class (sync and async). `read_only` only has an effect on SQLite (+ Typed/Pickle/async variants), DuckDB (+ Typed), and LMDB (+ Pickle) stores; everywhere else it's accepted and silently ignored.
- Spec doc: `docs/superpowers/specs/2026-07-21-store-uri-round-trip-design.md` (read for the full scheme table and rationale — this plan implements it exactly).
- Run the full test file after each task with `pytest <file> -v` from the repo root (`/Users/thibaut/workspace/code/persista`); the venv's pytest is at `.venv/bin/pytest`.

---

### Task 1: `persista/store/uri.py` — shared URI encode/decode helpers

**Files:**
- Create: `src/persista/store/uri.py`
- Test: `tests/unit/store/test_uri.py`

**Interfaces:**
- Produces: `encode_path_uri(scheme: str, path: str) -> str`, `decode_path_uri(uri: str, *, expected_scheme: str) -> str` — used by every path-based store family in later tasks.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/store/test_uri.py
from __future__ import annotations

import pytest

from persista.store.uri import decode_path_uri, encode_path_uri


def test_encode_decode_round_trip_absolute_path() -> None:
    uri = encode_path_uri("sqlite", "/tmp/foo/bar.db")
    assert decode_path_uri(uri, expected_scheme="sqlite") == "/tmp/foo/bar.db"


def test_encode_decode_round_trip_memory_sentinel() -> None:
    uri = encode_path_uri("sqlite", ":memory:")
    assert decode_path_uri(uri, expected_scheme="sqlite") == ":memory:"


def test_encode_decode_round_trip_relative_path() -> None:
    uri = encode_path_uri("lmdb", "relative/dir")
    assert decode_path_uri(uri, expected_scheme="lmdb") == "relative/dir"


def test_encode_uses_expected_scheme() -> None:
    uri = encode_path_uri("file+json", "/tmp/data")
    assert uri.startswith("file+json:")


def test_decode_rejects_wrong_scheme() -> None:
    uri = encode_path_uri("sqlite", "/tmp/foo.db")
    with pytest.raises(ValueError, match="scheme"):
        decode_path_uri(uri, expected_scheme="duckdb")


def test_encode_decode_round_trip_path_with_special_chars() -> None:
    uri = encode_path_uri("file+pickle", "/tmp/a dir/with?special#chars.db")
    assert decode_path_uri(uri, expected_scheme="file+pickle") == "/tmp/a dir/with?special#chars.db"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/store/test_uri.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'persista.store.uri'`

- [ ] **Step 3: Write the implementation**

```python
# src/persista/store/uri.py
r"""Provide shared URI encode/decode helpers used by the path-based
store families (file, SQLite, DuckDB, LMDB) to implement
``to_uri``/``from_uri``."""

from __future__ import annotations

__all__ = ["decode_path_uri", "encode_path_uri"]

from urllib.parse import quote, unquote, urlsplit, urlunsplit


def encode_path_uri(scheme: str, path: str) -> str:
    """Encode a path/identifier as a URI under the given scheme.

    Args:
        scheme: The URI scheme (e.g. ``"sqlite"``, ``"file+json"``).
        path: The path or identifier to encode (e.g. a filesystem
            path, or the SQLite/DuckDB ``":memory:"`` sentinel).

    Returns:
        A URI string that :func:`decode_path_uri` can invert.
    """
    return urlunsplit((scheme, "", quote(path, safe="/"), "", ""))


def decode_path_uri(uri: str, *, expected_scheme: str) -> str:
    """Decode a URI produced by :func:`encode_path_uri`.

    Args:
        uri: The URI to decode.
        expected_scheme: The scheme ``uri`` must have.

    Returns:
        The decoded path/identifier.

    Raises:
        ValueError: If ``uri``'s scheme does not match
            ``expected_scheme``.
    """
    parsed = urlsplit(uri)
    if parsed.scheme != expected_scheme:
        msg = f"Invalid scheme for {uri!r}: expected {expected_scheme!r}, got {parsed.scheme!r}"
        raise ValueError(msg)
    return unquote(parsed.netloc + parsed.path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/store/test_uri.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/persista/store/uri.py tests/unit/store/test_uri.py
git commit -m "Add encode_path_uri/decode_path_uri helpers for store URI round trip"
```

---

### Task 2: Abstract `to_uri`/`from_uri` on `BaseStore` and `AsyncBaseStore`

**Files:**
- Modify: `src/persista/store/base.py`
- Modify: `tests/unit/store/test_base.py` (minimal concrete stub must implement the new abstract methods)
- Modify: `tests/unit/store/test_base_async.py` (same, for the async stub)

**Interfaces:**
- Consumes: nothing new.
- Produces: `BaseStore.to_uri(self) -> str` (abstract), `BaseStore.from_uri(cls, uri: str, *, read_only: bool = False) -> Self` (abstract classmethod). Same pair on `AsyncBaseStore` (`from_uri` stays a regular classmethod, not a coroutine — see class docstring note below; only construction happens, no I/O).

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/store/test_base.py` (after the existing `test_base_store_is_abstract` test):

```python
def test_base_store_is_abstract_missing_to_uri_from_uri() -> None:
    class IncompleteStore(BaseStore):
        def get(self, key): return None
        def get_many(self, keys): return []
        def set(self, key, value, on_conflict="overwrite"): pass
        def set_many(self, items, on_conflict="overwrite"): pass
        def filter(self, **field_filters): return []
        def delete(self, key): pass
        def delete_many(self, keys): pass
        def clear(self): pass
        def contains(self, key): return False
        def contains_many(self, keys): return [], []
        def keys(self): return iter(())
        def iter_batches(self, batch_size=32): yield from ()
        def count(self): return 0
        def close(self): pass
        @property
        def closed(self): return False

    with pytest.raises(TypeError, match="abstract"):
        IncompleteStore()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/store/test_base.py::test_base_store_is_abstract_missing_to_uri_from_uri -v`
Expected: FAIL (no `TypeError` raised, since `to_uri`/`from_uri` don't exist yet as abstract members)

- [ ] **Step 3: Add the abstract methods to `BaseStore` and `AsyncBaseStore`**

In `src/persista/store/base.py`, add to `BaseStore` right after the `closed` property (before `__enter__`):

```python
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
```

Add the mirrored pair to `AsyncBaseStore` in the same relative position (after its `closed` property, before `__aenter__`). Note `from_uri` stays synchronous (not `async def`) even on `AsyncBaseStore`, since building a store is instantiating a client that connects lazily/on first use, not performing I/O:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/store/test_base.py::test_base_store_is_abstract_missing_to_uri_from_uri -v`
Expected: PASS

- [ ] **Step 5: Fix the now-broken concrete stubs in both test files**

`InMemoryTestStore` in `tests/unit/store/test_base.py` and `AsyncInMemoryStore` in `tests/unit/store/test_base_async.py` are concrete subclasses instantiated by fixtures — they'll now fail to instantiate (`TypeError: abstract`). Add to `InMemoryTestStore` (sync, in `test_base.py`):

```python
    def to_uri(self) -> str:
        return "test-memory://"

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> InMemoryTestStore:  # noqa: ARG003
        return cls()
```

Add the same pair (without `async`, per the note above) to `AsyncInMemoryStore` in `test_base_async.py`, adjusting the return type annotation to `AsyncInMemoryStore`.

- [ ] **Step 6: Run the full test_base files to verify nothing else broke**

Run: `.venv/bin/pytest tests/unit/store/test_base.py tests/unit/store/test_base_async.py -v`
Expected: PASS (all tests, including the new one)

- [ ] **Step 7: Commit**

```bash
git add src/persista/store/base.py tests/unit/store/test_base.py tests/unit/store/test_base_async.py
git commit -m "Add abstract to_uri/from_uri to BaseStore and AsyncBaseStore"
```

---

### Task 3: `InMemoryStore` / `AsyncInMemoryStore`

**Files:**
- Modify: `src/persista/store/in_memory.py`
- Modify: `src/persista/store/async_in_memory.py`
- Modify: `tests/unit/store/test_in_memory.py`
- Modify: `tests/unit/store/test_async_in_memory.py`

**Interfaces:**
- Produces: `InMemoryStore.to_uri()` → `"memory://"`; `InMemoryStore.from_uri(uri, *, read_only=False)` → new empty `InMemoryStore`. Same for `AsyncInMemoryStore`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/store/test_in_memory.py`:

```python
def test_to_uri_returns_memory_scheme(store: InMemoryStore) -> None:
    assert store.to_uri() == "memory://"


def test_from_uri_returns_empty_store() -> None:
    store = InMemoryStore.from_uri("memory://")
    assert store.count() == 0


def test_to_uri_from_uri_does_not_carry_data(store: InMemoryStore, items) -> None:
    store.set_many(items)
    reloaded = InMemoryStore.from_uri(store.to_uri())
    assert reloaded.count() == 0
```

Add the async mirror to `tests/unit/store/test_async_in_memory.py` (check that file's existing fixture name/pattern for `store`/`items` first, then add):

```python
async def test_to_uri_returns_memory_scheme(store: AsyncInMemoryStore) -> None:
    assert store.to_uri() == "memory://"


def test_from_uri_returns_empty_store() -> None:
    store = AsyncInMemoryStore.from_uri("memory://")
    assert store.count() == 0
```

(Adjust `store.count()` to `await store.count()` if the async fixture requires awaiting — check the existing async test file's convention for calling `count()` before finalizing.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/store/test_in_memory.py tests/unit/store/test_async_in_memory.py -v -k to_uri`
Expected: FAIL with `AttributeError: 'InMemoryStore' object has no attribute 'to_uri'`

- [ ] **Step 3: Implement in `src/persista/store/in_memory.py`**

Add after the `count` method:

```python
    def to_uri(self) -> str:
        return "memory://"

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> InMemoryStore:  # noqa: ARG003
        return cls()
```

Add `from __future__ import annotations` is already present; add `if TYPE_CHECKING: from typing import Self` is not needed since the return type is the concrete class name directly (already how `InMemoryStore` docstrings reference the class).

- [ ] **Step 4: Implement in `src/persista/store/async_in_memory.py`**

Add after the `count` method:

```python
    def to_uri(self) -> str:
        return "memory://"

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> AsyncInMemoryStore:  # noqa: ARG003
        return cls()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/store/test_in_memory.py tests/unit/store/test_async_in_memory.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add src/persista/store/in_memory.py src/persista/store/async_in_memory.py tests/unit/store/test_in_memory.py tests/unit/store/test_async_in_memory.py
git commit -m "Add to_uri/from_uri to InMemoryStore and AsyncInMemoryStore"
```

---

### Task 4: `NullStore` / `AsyncNullStore`

**Files:**
- Modify: `src/persista/store/null.py`
- Modify: `src/persista/store/async_null.py`
- Modify: `tests/unit/store/test_null.py`
- Modify: `tests/unit/store/test_async_null.py`

**Interfaces:**
- Produces: `NullStore.to_uri()` → `"null://"`; `NullStore.from_uri(uri, *, read_only=False)` → new `NullStore`. Same for `AsyncNullStore`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/store/test_null.py`:

```python
def test_to_uri_returns_null_scheme(store: NullStore) -> None:
    assert store.to_uri() == "null://"


def test_from_uri_returns_new_store() -> None:
    store = NullStore.from_uri("null://")
    assert store.count() == 0
    assert not store.closed
```

Add the async mirror to `tests/unit/store/test_async_null.py` following that file's existing conventions.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/store/test_null.py tests/unit/store/test_async_null.py -v -k to_uri`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Implement in `src/persista/store/null.py`**

Add after the `count` method:

```python
    def to_uri(self) -> str:
        return "null://"

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> NullStore:  # noqa: ARG003
        return cls()
```

- [ ] **Step 4: Implement in `src/persista/store/async_null.py`**

Add after the `count` method:

```python
    def to_uri(self) -> str:
        return "null://"

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> AsyncNullStore:  # noqa: ARG003
        return cls()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/store/test_null.py tests/unit/store/test_async_null.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/persista/store/null.py src/persista/store/async_null.py tests/unit/store/test_null.py tests/unit/store/test_async_null.py
git commit -m "Add to_uri/from_uri to NullStore and AsyncNullStore"
```

---

### Task 5: File stores — `BaseFileStore`, `JsonFileStore`, `PickleFileStore`

**Files:**
- Modify: `src/persista/store/file.py`
- Modify: `tests/unit/store/test_file.py`

**Interfaces:**
- Consumes: `encode_path_uri`, `decode_path_uri` from `persista.store.uri` (Task 1).
- Produces: `BaseFileStore.scheme` (abstract property), `BaseFileStore.to_uri()`/`from_uri()` (concrete, generic). `JsonFileStore.scheme == "file+json"`, `PickleFileStore.scheme == "file+pickle"`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/store/test_file.py`:

```python
def test_to_uri_round_trips_path(tmp_path: Path, store_cls: type[BaseFileStore]) -> None:
    store = store_cls(tmp_path / "db")
    reloaded = store_cls.from_uri(store.to_uri())
    assert reloaded.path == store.path


def test_to_uri_from_uri_preserves_data(
    tmp_path: Path, store_cls: type[BaseFileStore], items: dict[str, dict]
) -> None:
    store = store_cls(tmp_path / "db")
    store.set_many(items)
    reloaded = store_cls.from_uri(store.to_uri())
    assert reloaded.count() == len(items)
    assert reloaded.get("1") == items["1"]


def test_json_file_store_scheme() -> None:
    assert JsonFileStore(__import__("pathlib").Path("/tmp/x")).scheme == "file+json"


def test_pickle_file_store_scheme() -> None:
    assert PickleFileStore(__import__("pathlib").Path("/tmp/x")).scheme == "file+pickle"
```

(Clean up the ad hoc `__import__` calls by adding `from pathlib import Path` to the imports at the top of the file instead, since `Path` is only imported under `TYPE_CHECKING` there currently — move it to a regular import.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/store/test_file.py -v -k to_uri`
Expected: FAIL with `AttributeError: 'JsonFileStore' object has no attribute 'to_uri'`

- [ ] **Step 3: Implement in `src/persista/store/file.py`**

Add the import at the top (alongside the existing `from persista.store.validation import ...` line):

```python
from persista.store.uri import decode_path_uri, encode_path_uri
```

Add to `BaseFileStore`, after the existing `extension` abstract property:

```python
    @property
    @abstractmethod
    def scheme(self) -> str:
        """URI scheme used by :meth:`to_uri`/:meth:`from_uri`."""
```

Add to `BaseFileStore`, after `count` (before `_get_repr_kwargs`):

```python
    def to_uri(self) -> str:
        return encode_path_uri(self.scheme, str(self._path))

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> Self:  # noqa: ARG003
        return cls(decode_path_uri(uri, expected_scheme=cls.scheme))
```

`cls.scheme` needs to work as a plain class attribute access on the class itself (not just an instance), so change `scheme` from a `@property` to a plain class attribute in the two leaf classes (matches how `extension` is used purely on instances elsewhere, but `from_uri` needs it on the class). Update the abstract declaration to a class-level annotation instead of a property:

```python
    #: URI scheme used by :meth:`to_uri`/:meth:`from_uri`.
    scheme: str
```

(Remove the `@property`/`@abstractmethod` pair added above and use this plain annotation instead — it documents the contract without forcing a property, and lets `JsonFileStore.scheme = "file+json"` be a simple class attribute.)

Add to `JsonFileStore`, at the top of the class body (before `extension`):

```python
    scheme = "file+json"
```

Add to `PickleFileStore`, at the top of the class body (before `extension`):

```python
    scheme = "file+pickle"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/store/test_file.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/persista/store/file.py tests/unit/store/test_file.py
git commit -m "Add to_uri/from_uri to file stores"
```

---

### Task 6: SQLite stores (sync) — `BaseSQLiteStore`, `SQLiteStore`, `PickleSQLiteStore`, `TypedSQLiteStore`

**Files:**
- Modify: `src/persista/store/sqlite.py`
- Modify: `tests/unit/store/test_sqlite.py`
- Modify: `tests/unit/store/test_sqlite_pickle.py`

**Interfaces:**
- Consumes: `encode_path_uri`, `decode_path_uri` (Task 1); `BaseSQLiteStore.from_path(path, *, read_only=False, **kwargs)` (already exists).
- Produces: `_scheme` class attribute per leaf (`SQLiteStore._scheme = "sqlite"`, `PickleSQLiteStore._scheme = "sqlite+pickle"`, `TypedSQLiteStore._scheme = "sqlite+typed"`); `BaseSQLiteStore.to_uri()`/`from_uri()` (concrete, generic, `from_uri` delegates to `from_path` for the `read_only` behavior).

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/store/test_sqlite.py` (uses the existing `store_cls`/`store_path`/`items` fixtures parametrized over `[SQLiteStore, TypedSQLiteStore]`):

```python
def test_to_uri_from_uri_round_trips_in_memory_data(
    store_cls: type[BaseSQLiteStore], items: dict[str, dict]
) -> None:
    with store_cls(":memory:") as store:
        store.set_many(items)
        # :memory: never round-trips data -- each connection is a fresh DB.
        with store_cls.from_uri(store.to_uri()) as reloaded:
            assert reloaded.count() == 0


def test_to_uri_from_uri_round_trips_file_data(
    store_path: Path, store_cls: type[BaseSQLiteStore], items: dict[str, dict]
) -> None:
    path = store_path / f"to_uri_{store_cls.__name__}.sqlite"
    with store_cls.from_path(path) as store:
        store.set_many(items)
        uri = store.to_uri()
    with store_cls.from_uri(uri) as reloaded:
        assert reloaded.count() == len(items)


def test_from_uri_read_only_rejects_writes(
    store_path: Path, store_cls: type[BaseSQLiteStore], items: dict[str, dict]
) -> None:
    path = store_path / f"to_uri_ro_{store_cls.__name__}.sqlite"
    with store_cls.from_path(path) as store:
        store.set_many(items)
        uri = store.to_uri()
    with store_cls.from_uri(uri, read_only=True) as reloaded:
        assert reloaded.count() == len(items)
        with pytest.raises(sqlite3.OperationalError):
            reloaded.set("new", {"a": 1})
```

Add to `tests/unit/store/test_sqlite_pickle.py` (check its existing fixture names first, then add an analogous `test_to_uri_from_uri_round_trips_file_data` for `PickleSQLiteStore` using its own `tmp_path`-based fixture pattern).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/store/test_sqlite.py -v -k to_uri`
Expected: FAIL with `AttributeError: type object 'SQLiteStore' has no attribute 'from_uri'`

- [ ] **Step 3: Implement in `src/persista/store/sqlite.py`**

Add the import at the top (alongside the existing `persista.store.validation` import):

```python
from persista.store.uri import decode_path_uri, encode_path_uri
```

Add to `BaseSQLiteStore`, as a class attribute right after `_key_column`:

```python
    #: URI scheme used by :meth:`to_uri`/:meth:`from_uri`.
    _scheme: str = "sqlite"
```

Add to `BaseSQLiteStore`, after `from_path` (before `close`):

```python
    def to_uri(self) -> str:
        return encode_path_uri(self._scheme, str(self._database))

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> Self:
        path = decode_path_uri(uri, expected_scheme=cls._scheme)
        return cls.from_path(path, read_only=read_only)
```

Add `_scheme = "sqlite"` is already the default via the base class attribute, so `SQLiteStore` needs no override. Add to `PickleSQLiteStore`, at the top of the class body (before `__init__`):

```python
    _scheme = "sqlite+pickle"
```

Add to `TypedSQLiteStore`, at the top of the class body (after `_key_column = _KEY_COLUMN`):

```python
    _scheme = "sqlite+typed"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/store/test_sqlite.py tests/unit/store/test_sqlite_pickle.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/persista/store/sqlite.py tests/unit/store/test_sqlite.py tests/unit/store/test_sqlite_pickle.py
git commit -m "Add to_uri/from_uri to SQLite stores"
```

---

### Task 7: SQLite stores (async) — `AsyncBaseSQLiteStore`, `AsyncSQLiteStore`, `AsyncTypedSQLiteStore`

**Files:**
- Modify: `src/persista/store/async_sqlite.py`
- Modify: `tests/unit/store/test_async_sqlite.py`

**Interfaces:**
- Consumes: `encode_path_uri`, `decode_path_uri` (Task 1); `AsyncBaseSQLiteStore.from_path` (already exists, unchanged).
- Produces: same `_scheme` pattern as Task 6, mirrored on the async classes. `from_uri` stays a plain (non-`async`) classmethod — building an `aiosqlite` connection object is not itself awaited (see `AsyncBaseSQLiteStore.__init__`, which just calls `aiosqlite.connect(...)` without awaiting).

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/store/test_async_sqlite.py` (check existing fixture names for the parametrized `store_cls`/`store_path`/`items` first; mirror Task 6's tests, `async def` where a store method is awaited):

```python
async def test_to_uri_from_uri_round_trips_file_data(
    store_path: Path, store_cls: type[AsyncBaseSQLiteStore], items: dict[str, dict]
) -> None:
    path = store_path / f"to_uri_{store_cls.__name__}.sqlite"
    store = await store_cls.from_path(path)
    # AsyncBaseSQLiteStore.from_path is not a coroutine (mirrors the sync
    # one) -- check the class definition; if it is not awaitable, drop the
    # `await` here and above.
    await store.set_many(items)
    uri = store.to_uri()
    await store.close()

    reloaded = store_cls.from_uri(uri)
    assert await reloaded.count() == len(items)
    await reloaded.close()
```

Before finalizing this test, re-check `AsyncBaseSQLiteStore.from_path` in `src/persista/store/async_sqlite.py` (already read during brainstorming: it is a plain `@classmethod`, NOT `async`, since the constructor itself doesn't await). Remove the erroneous `await` in front of `store_cls.from_path(path)` above.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/store/test_async_sqlite.py -v -k to_uri`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Implement in `src/persista/store/async_sqlite.py`**

Add the import at the top:

```python
from persista.store.uri import decode_path_uri, encode_path_uri
```

Add to `AsyncBaseSQLiteStore`, as a class attribute right after `_key_column`:

```python
    #: URI scheme used by :meth:`to_uri`/:meth:`from_uri`.
    _scheme: str = "sqlite"
```

Add to `AsyncBaseSQLiteStore`, after `from_path` (before `close`):

```python
    def to_uri(self) -> str:
        return encode_path_uri(self._scheme, str(self._database))

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> Self:
        path = decode_path_uri(uri, expected_scheme=cls._scheme)
        return cls.from_path(path, read_only=read_only)
```

Add to `AsyncTypedSQLiteStore`, at the top of the class body (after `_key_column = _KEY_COLUMN`):

```python
    _scheme = "sqlite+typed"
```

(`AsyncSQLiteStore` needs no override, inheriting `_scheme = "sqlite"`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/store/test_async_sqlite.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/persista/store/async_sqlite.py tests/unit/store/test_async_sqlite.py
git commit -m "Add to_uri/from_uri to async SQLite stores"
```

---

### Task 8: DuckDB stores — `BaseDuckDBStore`, `DuckDBStore`, `TypedDuckDBStore`

**Files:**
- Modify: `src/persista/store/duckdb.py`
- Modify: `tests/unit/store/test_duckdb.py`

**Interfaces:**
- Consumes: `encode_path_uri`, `decode_path_uri` (Task 1).
- Produces: `_scheme` class attribute (`DuckDBStore._scheme = "duckdb"`, `TypedDuckDBStore._scheme = "duckdb+typed"`); `BaseDuckDBStore.to_uri()`/`from_uri()` passing `read_only=read_only` straight to the constructor.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/store/test_duckdb.py` (uses existing `store_cls`/`store_path`/`items` fixtures parametrized over `[DuckDBStore, TypedDuckDBStore]`):

```python
def test_to_uri_from_uri_round_trips_file_data(
    store_path: Path, store_cls: type[BaseDuckDBStore], items: dict[str, dict]
) -> None:
    path = store_path / f"to_uri_{store_cls.__name__}.duckdb"
    with store_cls(path) as store:
        store.set_many(items)
        uri = store.to_uri()
    with store_cls.from_uri(uri) as reloaded:
        assert reloaded.count() == len(items)


def test_from_uri_read_only(
    store_path: Path, store_cls: type[BaseDuckDBStore], items: dict[str, dict]
) -> None:
    path = store_path / f"to_uri_ro_{store_cls.__name__}.duckdb"
    with store_cls(path) as store:
        store.set_many(items)
        uri = store.to_uri()
    with store_cls.from_uri(uri, read_only=True) as reloaded:
        assert reloaded.count() == len(items)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/store/test_duckdb.py -v -k to_uri`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Implement in `src/persista/store/duckdb.py`**

Add the import at the top:

```python
from persista.store.uri import decode_path_uri, encode_path_uri
```

Add to `BaseDuckDBStore`, as a class attribute right after `_key_column`:

```python
    #: URI scheme used by :meth:`to_uri`/:meth:`from_uri`.
    _scheme: str = "duckdb"
```

Add to `BaseDuckDBStore`, after `show_columns_info` (before `_get_repr_kwargs`):

```python
    def to_uri(self) -> str:
        return encode_path_uri(self._scheme, str(self._path))

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> Self:
        path = decode_path_uri(uri, expected_scheme=cls._scheme)
        return cls(path, read_only=read_only)
```

Add to `TypedDuckDBStore`, at the top of the class body (after `_key_column = _KEY_COLUMN`):

```python
    _scheme = "duckdb+typed"
```

(`DuckDBStore` needs no override, inheriting `_scheme = "duckdb"`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/store/test_duckdb.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/persista/store/duckdb.py tests/unit/store/test_duckdb.py
git commit -m "Add to_uri/from_uri to DuckDB stores"
```

---

### Task 9: LMDB stores — `BaseLmdbStore`, `LmdbStore`, `PickleLmdbStore`

**Files:**
- Modify: `src/persista/store/lmdb.py`
- Modify: `tests/unit/store/test_lmdb.py`

**Interfaces:**
- Consumes: `encode_path_uri`, `decode_path_uri` (Task 1).
- Produces: `_scheme` class attribute (`LmdbStore._scheme = "lmdb"`, `PickleLmdbStore._scheme = "lmdb+pickle"`); `BaseLmdbStore.to_uri()`/`from_uri()` passing `readonly=read_only` to `lmdb.open` via the constructor.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/store/test_lmdb.py` (uses existing `store_cls`/`items` fixtures parametrized over `[LmdbStore, PickleLmdbStore]`):

```python
def test_to_uri_from_uri_round_trips_data(
    tmp_path: Path, store_cls: type[BaseLmdbStore], items: dict[str, dict]
) -> None:
    path = tmp_path / "db"
    with store_cls(path) as store:
        store.set_many(items)
        uri = store.to_uri()
    with store_cls.from_uri(uri) as reloaded:
        assert reloaded.count() == len(items)


def test_from_uri_read_only_rejects_writes(
    tmp_path: Path, store_cls: type[BaseLmdbStore], items: dict[str, dict]
) -> None:
    path = tmp_path / "db"
    with store_cls(path) as store:
        store.set_many(items)
        uri = store.to_uri()
    with store_cls.from_uri(uri, read_only=True) as reloaded:
        assert reloaded.count() == len(items)
        with pytest.raises(lmdb.ReadonlyError):
            reloaded.set("new", {"a": 1})
```

Add `import lmdb` at the top of the test file, guarded the same way the module already guards LMDB usage (after the existing `pytest.importorskip("lmdb")` line, a plain `import lmdb` is safe since that line already skipped the module if unavailable).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/store/test_lmdb.py -v -k to_uri`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Implement in `src/persista/store/lmdb.py`**

Add the import at the top:

```python
from persista.store.uri import decode_path_uri, encode_path_uri
```

Add to `BaseLmdbStore`, as a class attribute right before `__init__`:

```python
    #: URI scheme used by :meth:`to_uri`/:meth:`from_uri`.
    _scheme: str = "lmdb"
```

Add to `BaseLmdbStore`, after `count` (before `_get_repr_kwargs`):

```python
    def to_uri(self) -> str:
        return encode_path_uri(self._scheme, self._path)

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> Self:
        path = decode_path_uri(uri, expected_scheme=cls._scheme)
        return cls(path, readonly=read_only)
```

Add to `PickleLmdbStore`, at the top of the class body (before `_encode`):

```python
    _scheme = "lmdb+pickle"
```

(`LmdbStore` needs no override, inheriting `_scheme = "lmdb"`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/store/test_lmdb.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/persista/store/lmdb.py tests/unit/store/test_lmdb.py
git commit -m "Add to_uri/from_uri to LMDB stores"
```

---

### Task 10: Postgres stores (sync) — `BasePostgresStore`, `PostgresStore`, `TypedPostgresStore`

**Files:**
- Modify: `src/persista/store/postgres.py`
- Modify: `tests/unit/store/test_postgres.py`

**Interfaces:**
- Produces: `BasePostgresStore.to_uri()` → `self._conninfo` (no encoding — it's already a real `postgresql://...` connection string); `BasePostgresStore.from_uri(uri, *, read_only=False)` → `cls(uri)` (`read_only` ignored — no local read-only connection mode).

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/store/test_postgres.py` (uses the existing fake-connection-based `store`/`store_cls` fixtures parametrized over `[PostgresStore, TypedPostgresStore]` — check the exact fixture names in that file before writing, since it mocks `psycopg.connect` rather than using a real server):

```python
def test_to_uri_returns_conninfo_unchanged(store: BasePostgresStore) -> None:
    assert store.to_uri() == store._conninfo  # noqa: SLF001


def test_from_uri_constructs_with_same_conninfo(store_cls: type[BasePostgresStore]) -> None:
    # Reuses the same `psycopg.connect` mock/monkeypatch active for `store_cls`
    # in this test module -- check how the fixture patches the connect call
    # and apply the same patching here rather than hitting a real server.
    conninfo = "postgresql://user:pass@localhost/dbname"
    new_store = store_cls.from_uri(conninfo)
    assert new_store._conninfo == conninfo  # noqa: SLF001


def test_from_uri_ignores_read_only(store_cls: type[BasePostgresStore]) -> None:
    conninfo = "postgresql://user:pass@localhost/dbname"
    new_store = store_cls.from_uri(conninfo, read_only=True)
    assert new_store._conninfo == conninfo  # noqa: SLF001
```

Since `PostgresStore.__init__`/`TypedPostgresStore.__init__` call `psycopg.connect(...)` for real, `test_from_uri_constructs_with_same_conninfo` and `test_from_uri_ignores_read_only` must run under whatever fake-connection patching the rest of that test file already uses (it mocks `psycopg.connect` — read the top of `tests/unit/store/test_postgres.py` for the exact `patch(...)`/fixture mechanism and apply it identically here, rather than assuming a specific mock name).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/store/test_postgres.py -v -k to_uri`
Expected: FAIL with `AttributeError: 'PostgresStore' object has no attribute 'to_uri'`

- [ ] **Step 3: Implement in `src/persista/store/postgres.py`**

Add to `BasePostgresStore`, after `close`/`closed` (before `get`, or anywhere convenient in that class):

```python
    def to_uri(self) -> str:
        return self._conninfo

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> Self:  # noqa: ARG003
        return cls(uri)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/store/test_postgres.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/persista/store/postgres.py tests/unit/store/test_postgres.py
git commit -m "Add to_uri/from_uri to Postgres stores"
```

---

### Task 11: Postgres stores (async) — `AsyncBasePostgresStore`, `AsyncPostgresStore`, `AsyncTypedPostgresStore`

**Files:**
- Modify: `src/persista/store/async_postgres.py`
- Modify: `tests/unit/store/test_async_postgres.py`

**Interfaces:**
- Produces: same as Task 10, mirrored on the async classes. `from_uri` is not `async` (no connection is made until first use — see `AsyncBasePostgresStore.__init__`, which sets `self._conn = None` and only connects lazily in `_ensure_schema`).

- [ ] **Step 1: Write the failing tests**

Mirror Task 10's three tests in `tests/unit/store/test_async_postgres.py`, adjusted for that file's existing async fixture/mocking conventions (check the file before writing — same fake-connection approach as the sync test, adapted for `psycopg.AsyncConnection.connect`).

```python
def test_to_uri_returns_conninfo_unchanged(store: AsyncBasePostgresStore) -> None:
    assert store.to_uri() == store._conninfo  # noqa: SLF001


def test_from_uri_constructs_with_same_conninfo(store_cls: type[AsyncBasePostgresStore]) -> None:
    conninfo = "postgresql://user:pass@localhost/dbname"
    new_store = store_cls.from_uri(conninfo)
    assert new_store._conninfo == conninfo  # noqa: SLF001
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/store/test_async_postgres.py -v -k to_uri`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Implement in `src/persista/store/async_postgres.py`**

Add to `AsyncBasePostgresStore`, after `close`/`closed`:

```python
    def to_uri(self) -> str:
        return self._conninfo

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> Self:  # noqa: ARG003
        return cls(uri)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/store/test_async_postgres.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/persista/store/async_postgres.py tests/unit/store/test_async_postgres.py
git commit -m "Add to_uri/from_uri to async Postgres stores"
```

---

### Task 12: Redis stores (sync) — `BaseRedisStore`, `RedisStore`, `PickleRedisStore`

**Files:**
- Modify: `src/persista/store/redis.py`
- Modify: `tests/unit/store/test_redis.py`

**Interfaces:**
- Produces: `BaseRedisStore.to_uri()` → `self._url`; `BaseRedisStore.from_uri(uri, *, read_only=False)` → `cls(uri)` (`read_only` ignored).

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/store/test_redis.py` (uses the existing `_use_fake_redis`/`store`/`store_cls` fixtures parametrized over `[RedisStore, PickleRedisStore]`):

```python
def test_to_uri_returns_url_unchanged(store: BaseRedisStore) -> None:
    assert store.to_uri() == store._url  # noqa: SLF001


def test_from_uri_constructs_with_same_url(
    monkeypatch: pytest.MonkeyPatch, store_cls: type[BaseRedisStore]
) -> None:
    _use_fake_redis(monkeypatch)
    url = "redis://localhost:6379/0"
    new_store = store_cls.from_uri(url)
    assert new_store._url == url  # noqa: SLF001


def test_from_uri_ignores_read_only(
    monkeypatch: pytest.MonkeyPatch, store_cls: type[BaseRedisStore]
) -> None:
    _use_fake_redis(monkeypatch)
    url = "redis://localhost:6379/0"
    new_store = store_cls.from_uri(url, read_only=True)
    assert new_store._url == url  # noqa: SLF001
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/store/test_redis.py -v -k to_uri`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Implement in `src/persista/store/redis.py`**

Add to `BaseRedisStore`, after `close`/`closed`:

```python
    def to_uri(self) -> str:
        return self._url

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> Self:  # noqa: ARG003
        return cls(uri)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/store/test_redis.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/persista/store/redis.py tests/unit/store/test_redis.py
git commit -m "Add to_uri/from_uri to Redis stores"
```

---

### Task 13: Redis stores (async) — `AsyncBaseRedisStore`, `AsyncRedisStore`, `AsyncPickleRedisStore`

**Files:**
- Modify: `src/persista/store/async_redis.py`
- Modify: `tests/unit/store/test_async_redis.py`

**Interfaces:**
- Produces: same as Task 12, mirrored on the async classes.

- [ ] **Step 1: Write the failing tests**

Mirror Task 12's three tests in `tests/unit/store/test_async_redis.py`, adjusted for that file's existing async fixture/mocking conventions (check the file first for its `_use_fake_redis`-equivalent helper and fixture names).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/store/test_async_redis.py -v -k to_uri`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Implement in `src/persista/store/async_redis.py`**

Add to `AsyncBaseRedisStore`, after `close`/`closed`:

```python
    def to_uri(self) -> str:
        return self._url

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> Self:  # noqa: ARG003
        return cls(uri)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/store/test_async_redis.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/persista/store/async_redis.py tests/unit/store/test_async_redis.py
git commit -m "Add to_uri/from_uri to async Redis stores"
```

---

### Task 14: Generic dispatcher — `persista/store/registry.py`

**Files:**
- Create: `src/persista/store/registry.py`
- Create: `tests/unit/store/test_registry.py`
- Modify: `src/persista/store/__init__.py`

**Interfaces:**
- Consumes: every concrete store class's `.from_uri` (Tasks 3-13).
- Produces: `store_from_uri(uri: str, *, read_only: bool = False) -> BaseStore`, `async_store_from_uri(uri: str, *, read_only: bool = False) -> AsyncBaseStore`, both exported from `persista.store`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/store/test_registry.py
from __future__ import annotations

import pytest

from persista.store import (
    AsyncInMemoryStore,
    AsyncNullStore,
    InMemoryStore,
    JsonFileStore,
    NullStore,
    async_store_from_uri,
    store_from_uri,
)


def test_store_from_uri_memory() -> None:
    store = store_from_uri("memory://")
    assert isinstance(store, InMemoryStore)


def test_store_from_uri_null() -> None:
    store = store_from_uri("null://")
    assert isinstance(store, NullStore)


def test_store_from_uri_file_json(tmp_path) -> None:
    original = JsonFileStore(tmp_path / "db")
    original.set("1", {"a": 1})
    store = store_from_uri(original.to_uri())
    assert isinstance(store, JsonFileStore)
    assert store.get("1") == {"a": 1}


def test_store_from_uri_unknown_scheme_raises() -> None:
    with pytest.raises(ValueError, match="scheme"):
        store_from_uri("not-a-real-scheme://whatever")


def test_async_store_from_uri_memory() -> None:
    store = async_store_from_uri("memory://")
    assert isinstance(store, AsyncInMemoryStore)


def test_async_store_from_uri_null() -> None:
    store = async_store_from_uri("null://")
    assert isinstance(store, AsyncNullStore)


def test_async_store_from_uri_unknown_scheme_raises() -> None:
    with pytest.raises(ValueError, match="scheme"):
        async_store_from_uri("not-a-real-scheme://whatever")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/store/test_registry.py -v`
Expected: FAIL with `ImportError: cannot import name 'store_from_uri' from 'persista.store'`

- [ ] **Step 3: Write the implementation**

```python
# src/persista/store/registry.py
r"""Provide generic ``BaseStore``/``AsyncBaseStore`` dispatchers that
reconstruct a store from a URI without knowing its concrete class
upfront."""

from __future__ import annotations

__all__ = ["async_store_from_uri", "store_from_uri"]

from urllib.parse import urlsplit

from persista.store.async_in_memory import AsyncInMemoryStore
from persista.store.async_null import AsyncNullStore
from persista.store.async_postgres import AsyncPostgresStore
from persista.store.async_redis import AsyncRedisStore
from persista.store.async_sqlite import AsyncSQLiteStore, AsyncTypedSQLiteStore
from persista.store.base import AsyncBaseStore, BaseStore
from persista.store.duckdb import DuckDBStore, TypedDuckDBStore
from persista.store.file import JsonFileStore, PickleFileStore
from persista.store.in_memory import InMemoryStore
from persista.store.lmdb import LmdbStore, PickleLmdbStore
from persista.store.null import NullStore
from persista.store.postgres import PostgresStore
from persista.store.redis import RedisStore
from persista.store.sqlite import PickleSQLiteStore, SQLiteStore, TypedSQLiteStore

_SYNC_SCHEMES: dict[str, type[BaseStore]] = {
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

_ASYNC_SCHEMES: dict[str, type[AsyncBaseStore]] = {
    "memory": AsyncInMemoryStore,
    "null": AsyncNullStore,
    "sqlite": AsyncSQLiteStore,
    "sqlite+typed": AsyncTypedSQLiteStore,
    "postgresql": AsyncPostgresStore,
    "postgres": AsyncPostgresStore,
    "redis": AsyncRedisStore,
    "rediss": AsyncRedisStore,
}


def store_from_uri(uri: str, *, read_only: bool = False) -> BaseStore:
    """Reconstruct a :class:`~persista.store.base.BaseStore` from a URI.

    Dispatches on ``uri``'s scheme to the matching store class's
    :meth:`~persista.store.base.BaseStore.from_uri`. Store classes
    whose scheme is shared with another class (``TypedPostgresStore``
    reuses ``PostgresStore``'s native ``postgresql://`` scheme,
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
    store_cls = _SYNC_SCHEMES.get(scheme)
    if store_cls is None:
        msg = f"No store registered for scheme {scheme!r} (from {uri!r})"
        raise ValueError(msg)
    return store_cls.from_uri(uri, read_only=read_only)


def async_store_from_uri(uri: str, *, read_only: bool = False) -> AsyncBaseStore:
    """Reconstruct an :class:`~persista.store.base.AsyncBaseStore` from a
    URI.

    Mirrors :func:`store_from_uri`, dispatching to the async store
    classes instead.

    Args:
        uri: A URI produced by some ``AsyncBaseStore`` subclass's
            ``to_uri()``.
        read_only: Forwarded to the matched class's ``from_uri``.

    Returns:
        A new store instance.

    Raises:
        ValueError: If ``uri``'s scheme is not registered.
    """
    scheme = urlsplit(uri).scheme
    store_cls = _ASYNC_SCHEMES.get(scheme)
    if store_cls is None:
        msg = f"No async store registered for scheme {scheme!r} (from {uri!r})"
        raise ValueError(msg)
    return store_cls.from_uri(uri, read_only=read_only)
```

- [ ] **Step 4: Export from `src/persista/store/__init__.py`**

Add `"async_store_from_uri"` and `"store_from_uri"` to the `__all__` list (alphabetically sorted, matching the existing style), and add the import line:

```python
from persista.store.registry import async_store_from_uri, store_from_uri
```

(placed alphabetically among the other `from persista.store....` import lines).

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/store/test_registry.py -v`
Expected: PASS (all 7 tests)

- [ ] **Step 6: Run the full unit test suite for the store package**

Run: `.venv/bin/pytest tests/unit/store/ -v`
Expected: PASS (every test in the package, confirming Tasks 1-14 didn't regress anything)

- [ ] **Step 7: Commit**

```bash
git add src/persista/store/registry.py tests/unit/store/test_registry.py src/persista/store/__init__.py
git commit -m "Add store_from_uri/async_store_from_uri generic dispatchers"
```

---

## Self-Review Notes (for whoever executes this plan)

- Several test-writing steps say "check the existing fixture/mocking pattern in this file before finalizing" (Tasks 3, 6, 7, 10, 11, 12, 13) rather than repeating full file contents inline — the async/mocked test files are long and their exact fixture plumbing (`_use_fake_redis`, the fake psycopg connection, async fixture styles) was inspected during brainstorming but shouldn't be duplicated verbatim into every task; read the target file's top ~60 lines immediately before writing that task's test to match its established fixture names exactly.
- `TypedPostgresStore` and `PickleRedisStore` (+ async equivalents) intentionally get `to_uri`/`from_uri` "for free" via inheritance from their `Base*Store` (Tasks 10-13) — no separate task is needed since the base class implementation already covers them (they don't override `__init__`'s connection-string handling).
- Docstring caveat (spec section "Docstring caveat for typed stores"): while doing Task 6 (`TypedSQLiteStore`), Task 8 (`TypedDuckDBStore`), and Task 10 (`TypedPostgresStore`), add one sentence to each class's existing docstring `Args`/description noting that `from_uri` reconstructs with an empty `value_schema`/default `table`, so value fields previously stored in typed columns won't appear in `get`/`filter` results until the caller re-supplies the original `value_schema`/`table` to a fresh construction. Data isn't lost in the database — just not visible through the reconstructed store. This is a doc-only addition alongside each task's `to_uri`/`from_uri` step, not a separate task.
- If a task's test run reveals a fixture name mismatch against what's written above (e.g. the async postgres/redis test files structure their mock differently than guessed), fix the test to match the file's real convention — the important thing verified by the task is the production code in `to_uri`/`from_uri`, not the exact mock plumbing.
