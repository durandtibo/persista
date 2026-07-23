# Unified sync + async key-value stores

## Problem

`persista.store` currently ships a fully parallel set of classes for every
backend: a sync class (`SQLiteStore`, `PostgresStore`, `RedisStore`, ...)
implementing `BaseStore`, and a separate async class (`AsyncSQLiteStore`,
`AsyncPostgresStore`, `AsyncRedisStore`, ...) implementing `AsyncBaseStore`.
The two hierarchies duplicate schema/query/encoding logic method-for-method
(see `store/sqlite.py` vs `store/async_sqlite.py`), and callers who want both
sync and async access to the same store have to construct and keep two
separate objects in sync. We want one class per backend (e.g. a single
`SQLiteStore`) that offers both sync and async methods on the same instance.

## Design

### `BaseStore`: single abstract base class

`BaseStore` and `AsyncBaseStore` merge into one ABC. Every operation that
touches the underlying store gets two abstract methods: a sync one (existing
name) and an async twin prefixed with `a` (`aget`, `aset`, `aset_many`,
`adelete`, `adelete_many`, `aclear`, `acontains`, `acontains_many`, `acount`,
`aclose`). `to_uri`/`from_uri` stay single (URI identity doesn't depend on
sync vs. async). `closed` stays a single property reflecting whichever
connection(s) are open.

```python
class BaseStore(ABC):
    @abstractmethod
    def get(self, key: str) -> dict[str, Any] | None: ...
    @abstractmethod
    async def aget(self, key: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]: ...
    @abstractmethod
    async def aget_many(self, keys: list[str]) -> list[dict[str, Any] | None]: ...

    @abstractmethod
    def set(self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite") -> None: ...
    @abstractmethod
    async def aset(self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite") -> None: ...

    @abstractmethod
    def set_many(self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite") -> None: ...
    @abstractmethod
    async def aset_many(self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite") -> None: ...

    def set_batches(self, items, batch_size=32, on_conflict="overwrite") -> None: ...       # concrete, calls set_many
    async def aset_batches(self, items, batch_size=32, on_conflict="overwrite") -> None: ... # concrete, calls aset_many

    @abstractmethod
    def filter(self, **field_filters: Any) -> list[dict[str, Any]]: ...
    @abstractmethod
    async def afilter(self, **field_filters: Any) -> list[dict[str, Any]]: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...
    @abstractmethod
    async def adelete(self, key: str) -> None: ...

    @abstractmethod
    def delete_many(self, keys: list[str]) -> None: ...
    @abstractmethod
    async def adelete_many(self, keys: list[str]) -> None: ...

    @abstractmethod
    def clear(self) -> None: ...
    @abstractmethod
    async def aclear(self) -> None: ...

    @abstractmethod
    def contains(self, key: str) -> bool: ...
    @abstractmethod
    async def acontains(self, key: str) -> bool: ...

    @abstractmethod
    def contains_many(self, keys: list[str]) -> tuple[list[str], list[str]]: ...
    @abstractmethod
    async def acontains_many(self, keys: list[str]) -> tuple[list[str], list[str]]: ...

    @abstractmethod
    def keys(self) -> Iterator[str]: ...
    @abstractmethod
    def akeys(self) -> AsyncIterator[str]: ...

    def values(self, batch_size: int = 32) -> Iterator[dict[str, Any]]: ...       # concrete, built on iter_batches
    def avalues(self, batch_size: int = 32) -> AsyncIterator[dict[str, Any]]: ... # concrete, built on aiter_batches

    @abstractmethod
    def iter_batches(self, batch_size: int = 32) -> Iterator[dict[str, dict[str, Any]]]: ...
    @abstractmethod
    def aiter_batches(self, batch_size: int = 32) -> AsyncIterator[dict[str, dict[str, Any]]]: ...

    @abstractmethod
    def count(self) -> int: ...
    @abstractmethod
    async def acount(self) -> int: ...

    @abstractmethod
    def close(self) -> None: ...
    @abstractmethod
    async def aclose(self) -> None: ...

    @property
    @abstractmethod
    def closed(self) -> bool: ...

    def to_uri(self) -> str: ...
    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> Self: ...

    def __enter__(self) -> Self: return self
    def __exit__(self, *exc_info: object) -> None: self.close()
    async def __aenter__(self) -> Self: return self
    async def __aexit__(self, *exc_info: object) -> None: await self.aclose()
```

`iter_batches`/`aiter_batches` are typed as `Iterator`/`AsyncIterator` (not
`Generator`/`AsyncGenerator`); implementations remain ordinary generator
functions (`yield`), which satisfy those types structurally — this is a
type-hint change only, not an implementation change.

This is a breaking change: `AsyncBaseStore` and every `Async*Store` class
name are removed. Since the package is pre-1.0, there is no deprecated-alias
period.

### Per-backend implementation: two categories

**Category A — native async driver available: SQLite, Postgres, Redis.**
Each store holds two connections/clients: the existing blocking driver
(`sqlite3.Connection`, `psycopg.Connection`, `redis.Redis`) opened eagerly in
`__init__` for sync methods, and the native async driver
(`aiosqlite.Connection`, `psycopg.AsyncConnection`,
`redis.asyncio.Redis`) opened lazily on first `a*` call for async methods
(`__init__` cannot `await`). Lazy async-connection creation is guarded by an
`asyncio.Lock` so two concurrent first calls don't open two connections.

```python
class BaseSQLiteStore(BaseStore, MultilineDisplayMixin):
    def __init__(self, database: Path | str, **kwargs: Any) -> None:
        self._conn = sqlite3.connect(database, **kwargs)  # eager, sync
        self._ensure_schema()
        self._aconn: aiosqlite.Connection | None = None    # lazy, async
        self._aconn_lock = asyncio.Lock()
        self._aschema_ready = False

    async def _ensure_aconn(self) -> aiosqlite.Connection:
        async with self._aconn_lock:
            if self._aconn is None:
                self._aconn = await aiosqlite.connect(self._database, **self._kwargs)
            if not self._aschema_ready:
                await self._aconn.execute(self._create_table_sql())
                await self._aconn.commit()
                self._aschema_ready = True
        return self._aconn

    def get(self, key: str) -> dict[str, Any] | None: ...      # uses self._conn, unchanged from today
    async def aget(self, key: str) -> dict[str, Any] | None:
        conn = await self._ensure_aconn()
        ...
```

Subclasses (`SQLiteStore`, `TypedSQLiteStore`, `PickleSQLiteStore`,
`PostgresStore`, `TypedPostgresStore`, `RedisStore`, `PickleRedisStore`) keep
today's split of backend-specific hooks (`_row_to_value`,
`_build_filter_condition`, `_set_many`), each now implemented once per mode
(`_set_many` sync / `_aset_many` async) inside a single merged module (e.g.
`store/sqlite.py` absorbs everything currently in `store/async_sqlite.py`).

**Category B — no native async driver: in-memory, null, file, lmdb,
duckdb.** One connection/driver only. Async methods are thin wrappers around
the sync ones via `asyncio.to_thread`:

```python
async def aget(self, key: str) -> dict[str, Any] | None:
    return await asyncio.to_thread(self.get, key)
```

Since every scalar method (`get`/`set`/`set_many`/`delete`/`delete_many`/
`clear`/`contains`/`contains_many`/`count`/`close`) has this identical shape,
a `ThreadedAsyncStoreMixin` provides them once as concrete methods, so
category-B backends only implement the sync side of `BaseStore` plus mix in
this helper. `akeys`/`aiter_batches` need to bridge a sync iterator across a
thread; the mixin provides a small helper (pull each `next()`/batch via
`asyncio.to_thread` and yield it) rather than requiring each backend to
hand-write that loop.

### Close lifecycle

For category-A (dual-connection) backends:
- `aclose()`: awaits the async connection's close (if it was opened); closes
  the sync connection inline afterward (a plain in-memory/socket close is
  cheap enough not to need `to_thread`).
- `close()`: closes the sync connection directly. If the async connection
  was already opened, close it too via `asyncio.run(self._aconn.close())` —
  but only when no event loop is currently running. If `close()` is called
  from inside a running loop while the async connection is open, raise
  `RuntimeError` directing the caller to use `aclose()` instead.
- Both are idempotent, matching today's contract; `closed` is `True` once
  every connection that was ever opened has been closed.

For category-B (single-connection) backends, `close()`/`aclose()` follow the
same direct-call/`to_thread` pattern as every other method.

### Registry simplification

`store/registry.py` collapses from two dicts (`_SYNC_SCHEMES`,
`_ASYNC_SCHEMES`) and two public functions (`store_from_uri`,
`async_store_from_uri`) down to one `_SCHEMES` dict and one
`store_from_uri`/`register_scheme` pair, since every registered class now
supports both sync and async access from the same instance.

## Non-goals

- No change to on-disk formats, table schemas, or URI encoding.
- No change to the `OnConflict` semantics (`raise`/`skip`/`overwrite`/
  `merge`) — `aset`/`aset_many` apply the same rules as `set`/`set_many`.
- No performance work beyond what falls out of the design (e.g. no attempt
  to pool/reuse async connections across store instances).
