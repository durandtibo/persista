# `persista`: target state and the changes to reach it

This document describes the design that `persista` should have, then the changes to make to the
current implementation (`main`, `ea051ab`) to get there. It follows the rules stated by the
documentation (the `BaseStore` docstring, the user guides in `docs/docs/uguide/` and `CLAUDE.md`).
Its aim is a library that is easy to maintain: **one implementation of each contract, one way to do
each thing, the same behaviour on every backend**. Breaking changes are accepted, and the future
state is more important than the past one.

Evidence is marked:

- **[verified]**: reproduced by a throw-away probe on `main` (Python 3.14, macOS, scripts kept
  outside the repository).
- **[fake]**: reproduced against `fakeredis`, not a real Redis server.
- **[reading]**: deduced from the code. No PostgreSQL or Redis server was available, so every
  PostgreSQL finding is in this category.

The 3,620 unit tests of `main` pass; the integration tests were not run. Nothing in `src`, `tests`
or `docs/docs` was changed. This document replaces `reviews/persista-review.md` as the plan: its two
open items (the `COUNT(*)` in `repr`, the cache key built from `__qualname__`) are included here.

## 1. Properties

Every design choice below exists to make one of these properties true **by construction** (in one
shared piece of code) instead of by the discipline of each backend or caller.

### 1.1 The package

| Property                                  | Statement                                                                                                                                                                                                                          | Enforced by                                    |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| One contract                              | A caller can change the backend of a store, and so of a cache or a record store, without changing the calling code. The same call gives the same result, except for the documented limits of a backend (section 1.7), which raise. | `BaseStore` public methods, the contract tests |
| Sync and async parity                     | Every operation that touches a backend has a sync method and an `a`-prefixed twin with the same arguments, results and errors.                                                                                                     | `BaseStore`, the contract tests                |
| No silent wrong result                    | An input that cannot be handled raises. It is never dropped, coerced differently per backend, or confused with another input.                                                                                                      | validation in one place                        |
| Explicit lifecycle                        | A constructor does not connect. `open`/`aopen` do. A closed object raises `RuntimeError` on every operation, including with an empty input.                                                                                        | `BaseStore`                                    |
| Optional libraries stay optional and lazy | Outside `testing` (which needs `pytest`), `import persista.<subpackage>` needs no optional library and imports none. A missing library is reported when it is used.                                                                | the `check_*` helpers, an import test          |
| Layered                                   | `utils` ← `store` ← `cache` ← `http`; `store` ← `record`. `testing` is imported by nobody in `src`.                                                                                                                                | `lint-imports`                                 |
| Secrets stay private                      | A password in a URL or connection string never appears in a `repr`, a log message or an error. `to_uri` is the one exception: it returns what is needed to reconnect.                                                              | the stores' `repr`, tests                      |

### 1.2 `persista.store`

| Property             | Statement                                                                                                                                                                                            | Enforced by                      |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| Key domain           | A key is a `str`, compared exactly (case-sensitive). A backend that accepts fewer keys documents it and raises `ValueError` before it writes; its limit does not apply to the other backends.        | `BaseStore`, each backend        |
| Value domain         | A value is a `dict` that the codec of the store can encode (`json` by default, `pickle` on request).                                                                                                 | the codec                        |
| Round trip           | `get(key)` returns `codec.decode(codec.encode(value))`: the same result on every backend that uses the same codec, including the in-memory store. A value that would lose data raises (decision D5). | the codec, applied by the base   |
| Isolation            | Mutating a value that was passed to a store or returned by it never changes the stored value.                                                                                                        | the codec (only payloads stored) |
| Atomic conflicts     | `raise`, `skip` and `merge` are atomic against every other writer of the same data: threads, tasks, instances and processes. With `raise`, a conflict writes nothing.                                | `_update` of each backend        |
| One filter semantics | `filter` matches on the equality of top-level fields with JSON types (`True` is not `1`, `"1"` is not `1`, `1` is `1.0`); `None` matches a null or absent field. Any field name works.               | one Python predicate in the base |
| Stable iteration     | A key present during a whole iteration is yielded exactly once, even if other keys are written or deleted during the iteration. The values in memory are bounded by `batch_size`.                    | each `_iter_batches`             |
| Durable              | No TTL: a value stays until it is deleted or the store is cleared. (`InMemoryStore` and `NullStore` are not persistent.)                                                                             | the base                         |
| Owned data           | A store only reads, counts and clears the data under its own path, table or namespace.                                                                                                               | the constructor arguments        |
| Small extension      | A new backend implements the primitives (about ten methods) and its two URI methods, and inherits validation, codec, conflicts, filtering and async twins.                                           | `BaseStore`                      |

### 1.3 `persista.cache`

| Property       | Statement                                                                                                                                                      | Enforced by            |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- |
| Hit or miss    | A hit returns the stored value (as the codec of the store round-trips it); an expired or absent key is a miss. A cached `None` is distinguishable from a miss. | `Cache`                |
| No false hit   | Two calls share a key only if they are the same function (module and qualified name) with equal arguments of the same types.                                   | the canonical encoding |
| Explicit keys  | An argument that cannot be encoded raises. It is left out of the key only when it is named in `ignore`.                                                        | `memoize`              |
| One TTL rule   | `ttl` (else `default_ttl`) is `None` (never expires), `0` (delete) or positive. A negative or NaN value raises.                                                | one function           |
| Owns its store | `clear` clears the whole store, so a store given to a cache is not shared with other data.                                                                     | documentation          |

### 1.4 `persista.record`

| Property        | Statement                                                                                                                                      | Enforced by            |
| --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- |
| Plain value     | A `Record` is an id and a read-only metadata mapping. It can be compared, hashed, pickled and copied.                                          | `Record`               |
| Thin layer      | `RecordStore` converts records and delegates to a `BaseStore`: same method names, conflict strategies, filter semantics and errors.            | one class              |
| One equality    | Filters, id derivation and duplicate analyses agree on when two metadata values are equal (`1`, `"1"` and `True` differ).                      | the canonical encoding |
| Honest analyses | An analysis that is approximate says so in its name or docstring. An exact result is never replaced by an estimate when the exact one is free. | review, tests          |
| No side effect  | The functions do not modify their input and accept any iterable, consumed once.                                                                | tests                  |

### 1.5 `persista.http`

| Property      | Statement                                                                                                                                                         | Enforced by        |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ |
| Transparent   | A request behaves as with the wrapped `httpx` client or `requests` session (timeout, headers, authentication), plus retries and, with `httpx`, an optional cache. | the client wrapper |
| Safe retries  | Only idempotent methods are retried unless the caller says otherwise. The delay is bounded and never negative.                                                    | one retry policy   |
| Sound cache   | A cached response is served only for a request with the same method, final URL, headers and body. An authenticated request is not cached.                         | the cache key      |
| Same response | A response from the cache has the same status, content and usable methods (`json`, `raise_for_status`) as the original.                                           | entry conversion   |

### 1.6 `persista.utils` and `persista.testing`

`utils` holds the helpers shared by two or more sub-packages and imports none of them. `testing`
holds the `pytest` marks that skip the tests of a missing optional library.

### 1.7 Not guaranteed, and documented as such

- **Backend limits.** These do not restrict the other backends:

  | Backend         | Limit                                                                                                                |
  | --------------- | -------------------------------------------------------------------------------------------------------------------- |
  | `LmdbStore`     | a key has 1 to 511 UTF-8 bytes: the empty key and a 600-character key fail **[verified]**                            |
  | `FileStore`     | the encoded file name limits the key: 217 ASCII characters or 36 `é` today on macOS **[verified]** (see decision D6) |
  | `PostgresStore` | a key cannot contain NUL, and the primary key index limits its length **[reading]**                                  |

- **URIs** do not describe a whole store (section 4.4).
- **Multi-key writes in `FileStore`** are atomic per file only, and its `raise`, `skip` and `merge`
  are atomic within one instance only.
- **Transactions** across several calls.
- **Cancellation**: cancelling an async call that runs in a thread does not stop the operation.
- **Iteration order**, and whether a key written during an iteration is yielded.
- **Libraries' limits**: LMDB cannot open the same path twice in one process; DuckDB allows one
  writing process.
- **Cache**: concurrent misses on the same key can compute the value several times; there is no size
  limit, and an expired entry stays in the store until its key is read again.
- **Memoized types**: a miss returns the computed value, a hit its codec round trip (a tuple stored
  with the `json` codec comes back as a list).
- **HTTP**: `Cache-Control`, `ETag` and `Vary` are not interpreted.
- **`pickle`**: decoding can execute arbitrary code; use it only with trusted data.

## 2. Constraints

1. **Simple and easy to maintain.** The source is 14,245 lines in 89 modules. The target removes the
   code that repeats a contract (per-backend validation and conflict handling, sync and async copies
   of the same SQL, 33 factory classes) instead of adding code next to it.
2. **Breaking release.** No adapter, alias or deprecation period. The package is in alpha
   (`0.0.4a3`) and the README states that the API is not stable. The release notes list the changes,
   including those of the stored data (section 6).
3. **No slower on the common paths.** `get`, `get_many`, `set_many` and SQL `filter` on `str` and
   `int` fields must pass the benchmark gate of section 8.
4. **`CLAUDE.md` applies**: keyword-only options, validation helpers, guarded imports, one pull
   request per change.

## 3. What differs today

The common cause: `BaseStore` is a list of 33 abstract methods and 4 default ones, so each backend
reimplements validation, conflict handling, filtering, iteration and the async twins. The rules of
section 1 hold only where each copy remembered them.

### 3.1 Stores

| #   | Finding                                                                                                                                                                                                                                                                                                                                              | Status                              |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------- |
| S1  | **`filter` depends on the backend.** DuckDB matches `b="1"` to `1` and `b=1` to `"1"`, and raises `ConversionException` for `b=1` on a boolean. A list value raises in SQLite and matches elsewhere. A field name such as `x-y` raises in SQL stores and works in the others.                                                                        | [verified]                          |
| S2  | **PostgreSQL `filter(field=None)` matches nothing**: it builds `value->>'field' = NULL::text`. The local backends match a null or absent field. `value->>` also makes `"1"` match `1`.                                                                                                                                                               | [reading]                           |
| S3  | **`raise` is not atomic across writers.** Two `SQLiteStore` instances on one file both succeed in 200 of 200 trials (the lock is per instance, with no transaction). On one instance, `set` and `aset` both succeed in 199 of 200 trials (two connections, two locks).                                                                               | [verified]                          |
| S4  | **PostgreSQL conflicts.** Overwrites and deletes take no advisory lock, so they can interleave with a `merge`. Concurrent `aset_many` calls with `raise`/`skip`/`merge` open transactions on the same async connection, which nest or fail.                                                                                                          | [reading]                           |
| S5  | **`SQLiteStore(":memory:")` loses data between sync and async** when `aiosqlite` is installed: the async connection is another database. `set` then `aget` returns `None`, and the reverse.                                                                                                                                                          | [verified]                          |
| S6  | **Event loops.** A `SQLiteStore` whose async lock was contended in one `asyncio.run` raises `RuntimeError: ... bound to a different event loop` in the next one. The Redis and PostgreSQL async clients are also created once and reused.                                                                                                            | [verified] SQLite, [reading] others |
| S7  | **Iteration skips data.** Deleting the yielded keys during `iter_batches` visits 6 of 10 keys on the SQLite and DuckDB stores (`LIMIT ... OFFSET`), 10 of 10 on the others.                                                                                                                                                                          | [verified]                          |
| S8  | **Isolation.** Mutating a value returned by `InMemoryStore.values()` changes the stored value (`get` copies, `iter_batches` does not). The `data` property exposes the internal dict.                                                                                                                                                                | [verified]                          |
| S9  | **Round trip.** A tuple and an `int` key survive `InMemoryStore` and the pickle store, and become a list and a `str` in the JSON stores, where `{1: "int", "1": "str"}` **silently loses one entry**. NaN and infinity are accepted by the local JSON stores (PostgreSQL rejects them). A lone surrogate is stored by SQLite and rejected by DuckDB. | [verified], PostgreSQL [reading]    |
| S10 | **Keys.** `JsonFileStore` merges `"a"` and `"A"` on a case-insensitive file system (macOS). A key that a backend cannot store raises a library error (`OSError`, `BadValsizeError`) instead of `ValueError`, and the limits are not documented.                                                                                                      | [verified]                          |
| S11 | **Closed stores.** `InMemoryStore` and `JsonFileStore` accept `get_many([])` and `delete_many([])` when closed, as does `aget_many([])` of SQLite. An invalid `on_conflict` with empty items raises only in `InMemoryStore`.                                                                                                                         | [verified]                          |
| S12 | **Typed stores diverge.** A `None` field is dropped on read; SQLite returns `True` as `1` and accepts `"abc"` in an `INTEGER` column that DuckDB rejects.                                                                                                                                                                                            | [verified]                          |
| S13 | **Typed stores corrupt data.** Reopening a `TypedSQLiteStore` with the schema in another order swaps the values of two fields. `from_uri` loses the schema: SQLite raises `JSONDecodeError`, DuckDB returns the value without its typed fields. The field names `extra`, `_key_` and, in SQLite, `order` fail with a raw database error.             | [verified]                          |
| S14 | **Redis owns no namespace.** Two stores on one database share the keys, `clear` of one empties the other, and `__keys__` is a forbidden key.                                                                                                                                                                                                         | [fake]                              |
| S15 | **Secrets in `repr` and logs**: the Redis URL and the PostgreSQL factory print the password; Redis logs its URL.                                                                                                                                                                                                                                     | [verified] repr, [reading] log      |
| S16 | **`repr` runs a query** (`COUNT(*)`, `SCARD`, a directory scan) on an open store.                                                                                                                                                                                                                                                                    | [reading]                           |
| S17 | **`open` failures** leak the connection of the PostgreSQL store and leave a DuckDB store marked open.                                                                                                                                                                                                                                                | [reading]                           |
| S18 | **Native async SQLite gives little**: `aiosqlite` is slower for sequential `aget`, equal for concurrent reads, bulk reads and writes, and faster only for iteration in small batches (numbers in section 9.2). Its second connection causes S3, S5, S6 and part of `async_close.py`.                                                                 | [verified]                          |
| S19 | **Eager drivers.** `import persista.store` takes about 120 ms and imports every installed driver (psycopg 37 ms, DuckDB 33 ms, Redis 26 ms).                                                                                                                                                                                                         | [verified]                          |
| S20 | **Duplication.** `_check_open` is written in 8 modules although `check_is_open` exists; the pickle variants are separate classes in 4 backends; `filter_items` exists only on the SQL stores and is found with `getattr`.                                                                                                                            | [reading]                           |
| S21 | **URI limitations are only partly stated.** `value_schema` and `table` are not kept (documented), shared schemes cannot be dispatched (documented), and `SQLiteStore(":memory:").to_uri()` comes back as a shared-cache database instead of a private one.                                                                                           | [reading], `:memory:` [verified]    |

### 3.2 Cache

| #   | Finding                                                                                                                                                                                                                                                                   | Status                                 |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| C1  | **Same qualified name, same key**: two functions `load` of two modules return each other's results.                                                                                                                                                                       | [verified]                             |
| C2  | **`ignore_non_serializable` causes false hits**: arguments are dropped by position, so `f(lock, 1)` and `f(1, lock)` share a key; a memoized method returns the value of another instance (`self` is dropped).                                                            | [verified]                             |
| C3  | **Types are merged**: `g((1, 2))` returns the cached result of `g([1, 2])`. `f(1)` and `f(a=1)` do not share a key although they are the same call.                                                                                                                       | [verified]                             |
| C4  | `is_json_serializable` is cached by equality: after `is_json_serializable(1)`, `Decimal(1)` is reported serializable, and the key computation then raises.                                                                                                                | [verified]                             |
| C5  | **Redundant API**: `get`, `try_get`, `contains` and `MISSING` for one lookup; `memoize`, `amemoize`, `cached` and `async_cached` for one decorator; two key strategies, 5 key helpers, 2 split helpers. `get_or_compute(key, fn, args, kwargs)` takes the call in pieces. | [reading]                              |
| C6  | The default cache is created and opened at import. 1,000 expired entries stay in memory.                                                                                                                                                                                  | [verified] retention, [reading] import |
| C7  | The `pickle` key depends on object identity and set order, so it is not stable across processes.                                                                                                                                                                          | [reading]                              |

### 3.3 HTTP

| #   | Finding                                                                                                                                                                                  | Status                       |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------- |
| H1  | **The cache leaks responses between users.** The key ignores the client's headers: two clients with different `Authorization` headers and one cache get the response of the first.       | [verified]                   |
| H2  | **Wrong responses**: the key ignores `base_url`, and drops a non-JSON argument such as `httpx.QueryParams`, so `p=2` returns the response of `p=1` (the same applies to `bytes` bodies). | [verified], bodies [reading] |
| H3  | **Cached responses are broken**: a gzip response raises `DecodingError` on the hit, and `raise_for_status()` raises `RuntimeError` (no request attached).                                | [verified]                   |
| H4  | **`timeout` is ignored** when a client is given, so `HttpClient(client, timeout=1)` has no effect.                                                                                       | [verified]                   |
| H5  | **`POST` is retried** (4 requests for one call), unlike the `requests` helper, which retries `GET` only.                                                                                 | [verified]                   |
| H6  | `Retry-After: -1` raises `ValueError` from `sleep`; a date value is ignored; the delay has no maximum.                                                                                   | [verified] negative          |
| H7  | **Repetition**: 931 lines of `httpx` functions that differ by the method name, and retry rules that differ from those of the `requests` helper (H5).                                     | [reading]                    |

### 3.4 Records

| #   | Finding                                                                                                                                                                                                         | Status     |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| R1  | A `Record` cannot be hashed, pickled, deep-copied or passed to `dataclasses.asdict`.                                                                                                                            | [verified] |
| R2  | **Metadata equality is wrong**: `{"x": 1}` and `{"x": "1"}` are exact duplicates and get the same id from `from_metadata`, as do a tuple and a list.                                                            | [verified] |
| R3  | Unhashable values are ignored by the duplicate analyses (two different objects are "duplicates"); near-duplicate detection merges `{"a": "b=c"}` with `{"a=b": "c"}`; `num_bands=0` raises `ZeroDivisionError`. | [verified] |
| R4  | `compute_value_frequency` implements HyperLogLog to estimate a count it holds exactly (the keys of its `Counter`), and the estimate is wrong when `1` and `"1"` are both present.                               | [verified] |
| R5  | `import persista.record.analysis` fails without `rich`, an optional library.                                                                                                                                    | [verified] |
| R6  | `RecordStore.filter` follows the semantics of the backend (S1).                                                                                                                                                 | [verified] |
| R7  | **Layers without content**: an abstract class with one implementation, 5 subclasses that only build a store, 11 factory classes, and no `on_conflict` or `set_batches`.                                         | [reading]  |

### 3.5 Documentation

All **[reading]**: the HTTP guide links to `refs/utils.md` instead of `refs/http.md`; `get_started.md`
gives `inv unit-test` (the task is `inv test.unit`); the README links to a missing
`CONTRIBUTING.md`; the cache guide says both that `aget_or_compute` accesses the store synchronously
and that it awaits it; the store guide says that PostgreSQL stores cannot be reopened (`open`
reconnects) and that `keys` and `values` do not load everything (several backends load all the keys,
SQLite and DuckDB `keys` fetch all rows); the record guide calls the duplicate detection
"byte-for-byte" (R2).

### 3.6 What is right and must not regress

One class per backend with sync and async methods; constructors that do not connect; context managers;
the four conflict strategies; validation of every name placed in SQL, and bound parameters for
values; batched `IN` queries in SQLite; atomic file writes; transactional LMDB conflicts and
`WATCH`-based Redis conflicts; server-side cursors in PostgreSQL; the `Cache` over any store; the
import layering; the guarded optional imports (except R5); the test suite.

## 4. Architecture

```text
persista.http      HttpClient / AsyncHttpClient --------- optional ----.
persista.record    Record, RecordStore, filters, analysis             v
                          |                                     persista.cache   Cache
                          v                                           |
persista.store     BaseStore: validate -> encode -> primitive -> decode
                          |        \__ conflicts, filter predicate, async twins
                          v
                   InMemory  File  SQLite  DuckDB  LMDB  Redis  PostgreSQL  Null
persista.utils     imports, paths, canonical encoding
```

### 4.1 `BaseStore`: public methods in the base, primitives in the backends

The public methods are written once. A backend implements only what depends on it:

```python
class BaseStore(ABC):
    def __init__(self, *, codec: Codec | None = None) -> None: ...

    # Called with the store open, validated and non-empty arguments, and encoded payloads.
    @abstractmethod
    def _open(self) -> None: ...
    @abstractmethod
    def _close(self) -> None: ...
    @abstractmethod
    def _get_many(self, keys: list[str]) -> dict[str, Payload]: ...
    @abstractmethod
    def _put_many(self, items: dict[str, Payload]) -> None: ...
    @abstractmethod
    def _update(self, keys: list[str], plan: Plan) -> None:
        """Atomically: read the present keys, call plan(existing), write its result."""

    @abstractmethod
    def _delete_many(self, keys: list[str]) -> None: ...
    @abstractmethod
    def _clear(self) -> None: ...
    @abstractmethod
    def _count(self) -> int: ...
    @abstractmethod
    def _iter_batches(self, batch_size: int) -> Iterator[dict[str, Payload]]: ...

    # Optional overrides, with a default in the base.
    def _contains_many(self, keys: list[str]) -> set[str]: ...
    def _filter_candidates(self, fields: Mapping[str, Any]) -> Iterator[dict[str, Payload]]: ...
```

Rules of the contract:

1. The base checks that the store is open, validates keys, `on_conflict` and `batch_size`, applies
   the codec to every payload, and returns early on an empty input (after the checks).
2. `open` is idempotent. If `_open` raises, the base calls `_close` and the store stays closed.
3. `plan` is a pure function built by the base from `items` and `on_conflict`: it raises `KeyError`,
   drops the skipped keys or merges. A backend never reads `on_conflict`. It may call `plan` again
   after an optimistic retry. It replaces `resolve_conflicts`, `aresolve_conflicts` and the LMDB
   copy.
4. `_filter_candidates` returns a **superset** of the matches; the base applies the predicate to the
   decoded values. SQL stores push down the `str` and `int` conditions whose field name is a safe
   identifier. A push-down can make `filter` faster but never change its result.
5. The default async primitive runs the sync one in a thread. A backend that is not thread-safe
   has one lock per instance around its primitives, and one worker thread of its own for the async
   calls, so that calls waiting for the store do not fill the default executor of the application.
   Iteration takes the lock per batch, not across a `yield`.
6. Only Redis and PostgreSQL override the async primitives with their native drivers. Their client
   belongs to the event loop that created it and is replaced in another loop. `close()` raises
   `RuntimeError` while an async client is open: call `aclose()`. `async_close.py` is deleted.

Public methods: `get`, `get_many`, `contains`, `contains_many`, `set`, `set_many`, `set_batches`,
`delete`, `delete_many`, `clear`, `filter`, `iter_batches`, `keys`, `values`, `count`, `open`,
`close`, `closed`, `to_uri`, the class method `from_uri`, and the `a`-prefixed twins. One change of
signature: `filter(**fields)` returns `dict[str, dict]` (key to value), which removes
`filter_items`. `on_conflict` becomes keyword-only.

### 4.2 Codec

```python
class Codec(Protocol):
    name: str  # "json" or "pickle": selects the column type of a SQL store

    def encode(self, value: dict[str, Any]) -> str | bytes: ...
    def decode(self, payload: str | bytes) -> dict[str, Any]: ...
```

`JsonCodec` (default, rejects NaN and infinity) and `PickleCodec`. A codec replaces the classes
`PickleFileStore`, `PickleSQLiteStore`, `PickleLmdbStore` and `PickleRedisStore`. A SQL store whose
existing table does not match the codec raises on `open`.

### 4.3 Backends

| Class           | Constructor                                       | `_update` is atomic through               | Iteration                  |
| --------------- | ------------------------------------------------- | ----------------------------------------- | -------------------------- |
| `InMemoryStore` | `(*, codec=None)`                                 | the instance lock                         | snapshot of the keys       |
| `FileStore`     | `(path, *, codec=None)`                           | the instance lock                         | snapshot of the file names |
| `SQLiteStore`   | `(database=":memory:", *, codec, read_only, ...)` | `BEGIN IMMEDIATE`                         | keyset (`key > last`)      |
| `DuckDBStore`   | `(database=":memory:", *, codec, read_only, ...)` | a transaction under the instance lock     | keyset                     |
| `LmdbStore`     | `(path, *, codec, map_size, read_only, ...)`      | a write transaction                       | snapshot of the keys       |
| `RedisStore`    | `(url, *, codec, namespace="persista", ...)`      | `WATCH` / `MULTI`                         | snapshot of the keys set   |
| `PostgresStore` | `(conninfo, *, codec, table="store", ...)`        | transaction and one advisory lock per key | server-side keyset batches |
| `NullStore`     | `()`                                              | nothing to protect                        | empty                      |

- **SQLite and DuckDB** have one connection per instance, so sync and async see the same data
  (S3, S5). `from_path` is replaced by `read_only`, which never creates a file or a directory.
- **FileStore** escapes the upper-case letters of a key in its file name, so that two keys never
  differ only by case (S10, decision D6). A name that is too long raises `ValueError`.
- **Redis** stores `<namespace>:v:<key>` and the set `<namespace>:keys`. There is no reserved key.
- **PostgreSQL**: every write and delete takes the advisory locks of its keys (`clear` locks the
  table), and each async operation uses the connection exclusively (an `asyncio.Lock`), so
  transactions cannot nest (S4).
- `repr` shows the location without credentials and runs no query (S15, S16).
- Each driver is imported in `_open`, after the `check_*` call (S19).

### 4.4 URIs

`to_uri`, `from_uri`, `store_from_uri` and `register_scheme` stay (decision D4). A URI says **where
the data is**, not how the store was configured. The user guide and the docstrings state:

| Limitation                   | Detail                                                                                                                                      |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Constructor options are lost | `table`, `namespace`, `map_size` and the driver arguments are not in the URI. `Class.from_uri(uri, **kwargs)` passes them again.            |
| Codec of the server stores   | The scheme carries the codec of the local stores (`sqlite+pickle`, `file+json`, ...). `redis://` and `postgresql://` do not: pass `codec=`. |
| Dispatch builds the default  | `store_from_uri` uses the class registered for the scheme with its default options. For other options, call `Class.from_uri`.               |
| In-memory data               | `memory://`, `null://` and the `:memory:` databases give a new, empty store.                                                                |
| `read_only`                  | Honoured by SQLite, DuckDB and LMDB; ignored by the others.                                                                                 |
| Credentials                  | The URI of a server store contains the password. Treat it as a secret.                                                                      |
| Machine-specific paths       | A local path is made absolute, so the URI is valid on a machine with the same files.                                                        |

`from_uri` gains `**kwargs`: without it, a Redis store with the pickle codec could no longer be built
from its URI once the pickle classes are gone. With decision D1, the `sqlite+typed` and
`duckdb+typed` schemes disappear.

### 4.5 Removed from `persista.store`

| Removed                                                                                                | Replacement                                         |
| ------------------------------------------------------------------------------------------------------ | --------------------------------------------------- |
| `TypedSQLiteStore`, `TypedDuckDBStore`, `TypedPostgresStore`                                           | the JSON stores (decision D1)                       |
| the 4 `Pickle*Store` classes, `JsonFileStore`                                                          | `codec=PickleCodec()`, `FileStore`                  |
| `Base*Store` of each backend, `ThreadedAsyncStoreMixin`                                                | `BaseStore`                                         |
| `store.factory` (18 classes), `resolve.py`                                                             | `coola.factory.resolve_object` (decision D3)        |
| `async_close.py`, the `aiosqlite` extra                                                                | rule 6 of section 4.1 (decision D2)                 |
| `filter_items`, `split_present_missing`, `get_columns_info`, `show_columns_info`, `InMemoryStore.data` | `filter`, two comprehensions, the native connection |

The native handles stay (`connection`, `client`, `environment`).

### 4.6 Cache

```python
class Cache:
    def __init__(self, store: BaseStore | None = None, *, default_ttl: float | None = None): ...

    # open/close/closed and context managers, then (each with an a-prefixed twin):
    def get(self, key: str, default: Any = None) -> Any: ...
    def get_many(self, keys: list[str]) -> dict[str, Any]: ...  # the hits only
    def contains(self, key: str) -> bool: ...
    def set(self, key: str, value: Any, *, ttl: float | None = DEFAULT) -> None: ...
    def set_many(self, items: Mapping[str, Any], *, ttl: float | None = DEFAULT) -> None: ...
    def delete(self, key: str) -> None: ...
    def delete_many(self, keys: list[str]) -> None: ...
    def clear(self) -> None: ...
    def get_or_compute(
        self, key: str, fn: Callable[[], T], *, ttl: float | None = DEFAULT
    ) -> T: ...

    # one decorator for sync and async functions
    def memoize(self, *, ttl=DEFAULT, ignore: Collection[str] = (), key=None): ...
```

- The key of a memoized call is the hash of the **canonical encoding** of
  `(module, qualified name, bound arguments with defaults)`, so `f(1)` and `f(a=1)` are one call.
- The canonical encoding (`persista.utils.canonical`) is deterministic and tagged by type. It covers
  `None`, `bool`, `int`, `float`, `str`, `bytes`, `list`, `tuple`, `dict`, `set` and `frozenset`
  and raises `TypeError` for anything else. `coola.hashing.hash_object` cannot be used: it gives the
  same hash to `1` and `"1"` and to a tuple and a list **[verified]**.
- Other arguments are handled explicitly: `ignore=("client",)` leaves a parameter out by name, and
  `key=` is a function of the call that returns the key. A method needs one of the two.
- The default cache is `Cache(InMemoryStore(codec=PickleCodec()), default_ttl=300)`, so types are
  kept. It is created on the first `get_cache()`. `cached(...)` is `memoize` on the cache returned by
  `get_cache()` at call time.
- Removed: `try_get`, `try_get_many`, `contains_many`, `amemoize`, `async_cached`, `strategy`,
  `ignore_non_serializable`, the key and split helpers of `cache.utils`, the cache factories and
  `resolve_cache`. `MISSING` stays.

### 4.7 Records

- `Record(id, metadata)`: frozen, metadata copied behind a read-only proxy, hashed by `id`
  (consistent with equality), with `__reduce__` so that pickling and copying work.
  `dataclasses.asdict` is documented as unsupported. `from_metadata` derives the id from the
  canonical encoding.
- `RecordStore(store)` is the only record store. It has the method names of `BaseStore`
  (`set`, `set_many` and `set_batches` with `on_conflict`, `filter`, `iter_batches`, ...);
  `filter` delegates to `store.filter`. Use `RecordStore(SQLiteStore(path))`.
- Removed: `BaseRecordStore`, the 5 backend subclasses, `record.store.factory`, `resolve` and
  `validation`.
- `filter_by_metadata`, `_range`, `_values` and `sort_by_metadata` stay. Equality filters use the
  predicate of the stores.
- `analysis` stays, on the canonical encoding. HyperLogLog is deleted and
  `compute_value_frequency` reports `distinct_count`. `rich` is imported inside
  `print_metadata_stats_report`. Invalid parameters raise `ValueError`. `MetadataStats` becomes
  private.

### 4.8 HTTP

- `HttpClient(client=None, *, max_retries=3, retry_status_codes=..., retry_methods=...,
max_delay=60.0, cache=None, cacheable_methods={"GET"})` and `AsyncHttpClient`. Without a `client`,
  the wrapper creates one and closes it (context manager).
- The sync and async classes share one retry policy: idempotent methods by default, `Retry-After`
  in seconds or as a date, the delay clamped to `[0, max_delay]`.
- A `timeout` is passed to `httpx` with the request, like any other argument.
- The cache key is built from `client.build_request(...)`: method, final URL, all headers (cookies
  included) and body. A request with `auth` (client or call) or a streaming body is not cached. The
  entry drops `content-encoding`, `content-length` and `transfer-encoding`, and the rebuilt response
  has its request.
- `persista.http.requests` stays (decision D8): `create_session` and `fetch_response`. It keeps
  retrying `GET` only, and the retry and delay properties of section 1.5 apply to it. It has no
  cache.
- Removed: the 12 `httpx` module functions, replaced by the two classes.

### 4.9 Utils, testing and packaging

- `utils.imports` becomes one module with `is_<name>_available` and `check_<name>` for `duckdb`,
  `faker`, `httpx`, `lmdb`, `psycopg`, `redis`, `requests`, `rich` and `urllib3`. The unused
  `<name>_available` decorators and `raise_<name>_missing_error` go.
- `utils.asyncio.EmptyAsyncIterator` is deleted (`NullStore` implements primitives only).
- `testing.fixtures` keeps the marks of the remaining libraries.
- The import contracts of `pyproject.toml` do not change.

## 5. Public API after the change

```text
persista.store          BaseStore, Codec, JsonCodec, PickleCodec, OnConflict,
                        InMemoryStore, FileStore, SQLiteStore, DuckDBStore, LmdbStore,
                        RedisStore, PostgresStore, NullStore, store_from_uri, register_scheme
persista.cache          Cache, MISSING, cached, get_cache, set_cache
persista.record         Record, filter_by_metadata, filter_by_metadata_range,
                        filter_by_metadata_values, sort_by_metadata
persista.record.store   RecordStore
persista.record.analysis  (the same functions, without MetadataStats)
persista.record.fake    generate_fake_records
persista.http.httpx     HttpClient, AsyncHttpClient
persista.http.requests  create_session, fetch_response
```

The validation helpers are imported from `persista.store.validation`.

## 6. Effect on stored data

There is no migration code. To keep data, read it with the old version and write it with the new one.
The release notes say:

| Data                                     | Effect                                                                  |
| ---------------------------------------- | ----------------------------------------------------------------------- |
| SQLite, DuckDB, PostgreSQL, LMDB (JSON)  | readable, same table and encoding                                       |
| SQLite, LMDB (pickle)                    | readable with `codec=PickleCodec()`                                     |
| Typed SQL tables                         | not readable                                                            |
| `SQLiteRecordStore`, `DuckDBRecordStore` | not readable (they use typed tables today)                              |
| File stores                              | readable if the key has no upper-case letter; other files are not found |
| Redis                                    | not found (new key layout)                                              |
| Cache entries, ids of `from_metadata`    | cache keys change (cold cache); the same metadata gets a new id         |

## 7. Changes to reach the target state

One branch and one pull request per row (`CLAUDE.md`). Each step leaves `main` releasable, and
updates the tests, the docstrings and the user guide that it affects. Deletions come first so that
the later steps change less code.

| Step | Change                                                                                                                                                                     | Findings                   | Breaking            |
| ---- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------- | ------------------- |
| 1    | **Urgent fixes of the HTTP cache and the cache keys**: complete request key, no caching with `auth`, sound cached response, module in the memoize key, no positional drop. | C1, C2, H1-H3              | cache keys          |
| 2    | **Delete the factories and the `resolve_*` wrappers.**                                                                                                                     | R7                         | yes                 |
| 3    | **Delete the typed stores**; one `RecordStore`, remove its abstract class and subclasses.                                                                                  | S12, S13, R7               | yes                 |
| 4    | **`BaseStore` template**: add the primitives, validation, codec and conflict plan to the base, with `InMemoryStore` and `NullStore`; a contract test per property.         | S8, S9, S11                | yes (custom stores) |
| 5    | **SQLite and DuckDB on the template**: one connection, `BEGIN IMMEDIATE`, keyset iteration; delete `aiosqlite` and `async_close.py` use.                                   | S3, S5-S7, S18             | yes                 |
| 6    | **`FileStore` and LMDB on the template.**                                                                                                                                  | S10                        | yes (file names)    |
| 7    | **Redis on the template**, with the namespace.                                                                                                                             | S6, S14, S15               | yes (key layout)    |
| 8    | **PostgreSQL on the template**, with real-server concurrency tests. Delete the old base paths.                                                                             | S2, S4, S17, S20           | yes                 |
| 9    | **One filter**: the predicate, the safe push-down, the keyed result; lazy driver imports; cheap `repr`; the URI limitations.                                               | S1, S2, S15, S16, S19, S21 | yes                 |
| 10   | **Canonical encoding and the cache API.**                                                                                                                                  | C3-C7                      | yes                 |
| 11   | **Records and analyses** on the canonical encoding.                                                                                                                        | R1-R6                      | yes                 |
| 12   | **HTTP**: two `httpx` classes and one retry policy; delete the module functions; apply the retry properties to `requests`.                                                 | H4-H7                      | yes                 |
| 13   | **Utils, extras, documentation**: one imports module, the Properties tables in the user guides, a migration page, section 3.5.                                             | 3.5                        | yes (imports)       |

During steps 4 to 7 the base keeps the public methods overridable, so that the backends move one
at a time. Step 8 makes the template the only path.

## 8. Tests and gates

The conventions of `CLAUDE.md` apply. Each finding gets a regression test that fails on `main`.

- **Contract tests** (`tests/integration/store/test_consistency.py`, extended): one or more tests per
  row of section 1.2, parametrised over every backend and both codecs: the keys (case, and the
  limits of each backend raising `ValueError`), the URI round trip, the round trip and the
  isolation, every method on a closed store with empty input, the filter matrix (types × `None` ×
  unsafe names), deletion during iteration, `repr` without
  secrets.
- **Concurrency** (`tests/integration/`): `raise` and `merge` from two instances of the same data,
  from `set` and `aset` together, against a concurrent overwrite and delete; async use in two event
  loops. Redis and PostgreSQL run against real servers, with no patching.
- **Backends** (unit): only the primitives. The shared behaviour is tested once, in the tests of
  `BaseStore`.
- **Cache and HTTP**: one test per false hit of sections 3.2 and 3.3, with `httpx.MockTransport` for
  the unit tests and an integration test with a local server.
- **Imports**: a test that `import persista.<subpackage>` loads no optional library, and the CI jobs
  without optional dependencies.
- **Benchmarks** (`tests/benchmarks/`): add LMDB and DuckDB, async `get`, and a `filter` on 100,000
  rows before step 4. A step that slows `get`, `get_many`, `set_many` or an SQL `filter` by more
  than 10 % on the median is not merged. The codec adds a copy to `InMemoryStore` reads in place of
  `deepcopy`; measure it in step 4.
- Coverage of 100 % of the changed code, and `ruff`, `ty`, `pyright` and `lint-imports` clean.

## 9. Decisions

### 9.1 Overview

| #   | Question                              | Status  | Answer or recommendation                                                                                       |
| --- | ------------------------------------- | ------- | -------------------------------------------------------------------------------------------------------------- |
| D1  | Keep the typed stores?                | open    | Recommended: **no** (section 9.2).                                                                             |
| D2  | Keep native async SQLite?             | open    | Recommended: **no** (section 9.3).                                                                             |
| D3  | Keep the factory classes?             | open    | Recommended: **no**, `resolve_object({"_target_": ...})` builds any object. Check the dependent projects.      |
| D4  | Keep the store URIs?                  | decided | **Yes**, with their limitations stated (section 4.4).                                                          |
| D5  | JSON values that change or lose data? | open    | Recommended: **normalise tuples, reject what loses data** (section 9.4).                                       |
| D6  | File names of `FileStore`?            | open    | Recommended: **escape upper case** (section 9.5).                                                              |
| D7  | A key limit shared by all backends?   | decided | **No.** The limit of one backend does not restrict the others; interchangeability in every case is not a goal. |
| D8  | Keep `requests` support?              | decided | **Yes** (section 4.8).                                                                                         |
| D9  | Keep `record.analysis` in `persista`? | open    | Recommended: **yes**, it is small, pure and depends only on `Record`.                                          |
| D10 | Keep the SQL filter push-down?        | open    | Recommended: **yes**, as a pre-filter (rule 4 of section 4.1): large tables stay fast, results stay right.     |
| D11 | Retry `POST` and `PATCH`?             | open    | Recommended: **not by default** (H5); the caller adds them to `retry_methods`.                                 |

The measurements below are medians of one run on an Apple M1 **[verified]**. They compare options;
the absolute numbers depend on the machine.

### 9.2 D1: typed stores

A typed store puts the fields of `value_schema` in SQL columns and the others in an `extra` JSON
column. What it gives, on `filter(author=...)` returning 100 of 100,000 rows:

| Backend | JSON store | Typed store | JSON store with an expression index | Typed store with an index |
| ------- | ---------- | ----------- | ----------------------------------- | ------------------------- |
| SQLite  | 26.9 ms    | 5.0 ms      | 0.15 ms                             | 0.21 ms                   |
| DuckDB  | 6.3 ms     | 1.1 ms      | not measured                        | not measured              |

- **SQLite**: an index on the JSON field is as fast as an indexed column, and needs no library code:
  `store.connection.execute("CREATE INDEX i ON store(json_extract(value, '$.author'))")`. The query
  plan of today's filter expression uses it. The push-down expression must then stay stable.
- **PostgreSQL**: an expression index on `(value->>'author')` should serve the same purpose
  **[reading]**.
- **DuckDB**: this is the real loss. A column scan is about 6 times faster than parsing JSON, and the
  analytical use of DuckDB (aggregations on columns from SQL) becomes less convenient.
- **External SQL**: today another tool can query plain columns; with JSON it must extract fields.

| Option                              | Work                                                                                                                                                                                                                  | Gain and cost                                                        |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| A. Remove (recommended)             | delete 3 classes; document the expression index                                                                                                                                                                       | one table layout and one SQL path per backend; slower DuckDB filters |
| B. Keep and fix                     | check the existing table against the schema on `open`; quote and reserve names; keep `None` apart from absent; return booleans; validate the types the same way everywhere; handle the schema in URIs (S12, S13, S21) | keeps columns; a schema change still needs a migration by the user   |
| C. Remove, then add `indexes=(...)` | A, plus one option that creates the expression indexes                                                                                                                                                                | fast SQLite and PostgreSQL filters without a schema; no DuckDB gain  |

Choose B if DuckDB filters or external SQL queries on columns are real uses. Otherwise A, and C only
when someone needs it.

### 9.3 D2: native async SQLite

`aiosqlite` is not asynchronous I/O: it runs `sqlite3` in a background thread. The choice is between
its thread and second connection, and a thread around the sync methods. On a file database of 10,000
rows:

| Operation                            | `aiosqlite` | Thread around the sync method |
| ------------------------------------ | ----------- | ----------------------------- |
| 1,000 sequential `aget`              | 68.5 ms     | 45.1 ms                       |
| 1,000 concurrent `aget`              | 52.7 ms     | 50.2 ms                       |
| `aget_many` of 10,000 keys           | 17.2 ms     | 16.4 ms                       |
| 200 `aset`                           | 83.7 ms     | 89.7 ms                       |
| `aiter_batches(32)` over 10,000 rows | 17.6 ms     | 54.3 ms                       |

- **For removal**: one connection and one lock, so S3 (sync against async), S5 and the SQLite part of
  S6 disappear by construction; each method has one implementation instead of two; one extra less.
- **Against**: iteration in small batches is 3 times slower, because each batch is a thread hop and
  today's query uses `OFFSET`. Keyset iteration (step 5) removes the second cost, not the first; a
  larger default batch for async iteration reduces it. This was not measured.
- **Thread pool**: `asyncio.to_thread` uses the default executor (12 workers on this machine), shared
  with the application. Rule 5 of section 4.1 gives the store its own worker.
- **Keeping it** requires a shared in-memory database, a write lock and transaction across both
  connections, one connection per event loop, and `async_close.py`.

### 9.4 D5: JSON values

What the JSON stores do today with a value that JSON cannot represent **[verified]** on SQLite and
DuckDB:

| Written                                  | Read back                      | Data lost                |
| ---------------------------------------- | ------------------------------ | ------------------------ |
| a tuple                                  | a list                         | the type                 |
| a `str` subclass, such as a `str` enum   | a `str`                        | the type                 |
| `{1: "a"}`, `{True: "a"}`, `{None: "a"}` | keys `"1"`, `"true"`, `"null"` | the key type             |
| `{1: "int", "1": "str"}`                 | `{"1": "str"}`                 | **an entry**             |
| NaN, infinity                            | the same, not valid JSON       | portability (PostgreSQL) |
| a lone surrogate                         | SQLite: same; DuckDB: raises   | consistency              |
| a set, `bytes`                           | `TypeError`                    | none                     |

| Option                                                                  | Behaviour                                                       | Cost per write                                        |
| ----------------------------------------------------------------------- | --------------------------------------------------------------- | ----------------------------------------------------- |
| A. Normalise                                                            | as today, with NaN and infinity rejected; one entry can be lost | none                                                  |
| B. Normalise tuples and subclasses, reject non-`str` keys (recommended) | nothing is lost; a type may be widened                          | a walk: +0.7 µs small value, +0.5 ms for 1,000 rows   |
| C. Strict: reject everything that does not come back equal              | a value read equals the value written                           | the same walk; callers must convert tuples themselves |

The walk is a pure Python prototype. For scale, `set` on an in-memory SQLite takes 4 µs for the
small value and 268 µs for the 1,000-row value, so B adds about 17% and 180% there, much less
relative to a write that commits to disk. This would fail the benchmark gate of section 8 for large
values.

I recommend B because section 1.1 promises that nothing is silently lost; this replaces the earlier
recommendation to only normalise. Choose A if write speed matters more, and list the lost entry in
section 1.7.

### 9.5 D6: file names of `FileStore`

Today the name is the percent-encoded key plus the extension. It has two problems: `a` and `A` are
one file on macOS, and the length is limited (217 ASCII characters, 36 `é`, because the temporary
file of the atomic write adds a suffix). With D7, a length limit is acceptable.

| Option                               | Case bug | Key length        | `keys()` for 10,000 files | File names  | Existing files                     |
| ------------------------------------ | -------- | ----------------- | ------------------------- | ----------- | ---------------------------------- |
| A. Escape upper case (recommended)   | fixed    | limited, as today | 54 ms (list the names)    | readable    | readable without upper case in key |
| B. Hash of the key, key in the file  | fixed    | unlimited         | 476 ms (read every file)  | opaque      | not readable                       |
| C. A, with a hash for long keys only | fixed    | unlimited         | between the two           | two formats | as A                               |

With A, `User:1` becomes `%55ser%3A1.json`. A probe on sample keys confirms that the names stay
distinct when the case is ignored and decode to the original keys. Each upper-case letter takes 3
characters, so such keys have a lower limit. This replaces the earlier recommendation (B), which was
motivated by the shared key limit that D7 rejects.

## 10. Not covered

- A query language (ranges, `OR`, nested fields), pagination of `filter` results, and counting with
  filters.
- TTL in the stores, a size limit or LRU eviction in the cache, protection against concurrent
  computation of one key.
- New backends, synchronous replication, encryption.
- Cache semantics of HTTP (`Cache-Control`, revalidation).
- A public contract test suite in `persista.testing` for third-party stores.
- The CI workflows and the release process, which this review did not examine.

## Appendix: expected effect on the size of the source

Rough estimates from the code to delete and the template; the gate is the behaviour of sections 1 and
8, not the size.

| Part                  | Lines today | Expected after | Why                                                  |
| --------------------- | ----------- | -------------- | ---------------------------------------------------- |
| `store` (no factory)  | 5,517       | about 2,700    | one copy of the contract, no typed or pickle classes |
| factories (all)       | 1,495       | 0              | removed                                              |
| `cache` (no factory)  | 1,977       | about 700      | one lookup, one decorator                            |
| `record` (no factory) | 2,660       | about 1,500    | one record store, no HyperLogLog                     |
| `http`                | 1,488       | about 600      | two classes, the `requests` helpers                  |
| `utils` and `testing` | 1,095       | about 400      | one imports module                                   |

The docstrings are a large part of these numbers: a public method documented once in the base is
inherited by every backend.
