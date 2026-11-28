# Migration Guide

:book: This page lists the breaking changes of the redesign of `persista`, for code written for
`persista` 0.0.4a3, and their effect on the data that this version stored. There is no alias, no
deprecation period and no migration code. If you upgrade from an older release, other changes can
apply.

## Stored Data

**Read this section before you upgrade a program that keeps data.** To keep data that the new
version cannot read, read it with the old version and write it with the new one, into a new
location. The two versions cannot be imported in one process, so export the data to a file in
between, or use two environments. Make a copy of your data first.

| Data written by the old version                       | With the new version                                                                       |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `SQLiteStore`, `DuckDBStore`, `LmdbStore` (JSON)      | read as it is                                                                              |
| `PostgresStore`                                       | read as it is; see the two exceptions below                                                |
| `PickleSQLiteStore`, `PickleLmdbStore`                | read with `SQLiteStore(path, codec=PickleCodec())` or `LmdbStore(path, codec=...)`         |
| `JsonFileStore`, `PickleFileStore`                    | read with `FileStore` if the key has no upper-case ASCII letter; other files are not found |
| `RedisStore`, `PickleRedisStore`                      | **not found**: the layout of the Redis keys changed                                        |
| typed tables (`TypedSQLiteStore`, `TypedDuckDBStore`, | **not readable**: opening the table raises `ValueError`                                    |
| `TypedPostgresStore`)                                 |                                                                                            |
| `SQLiteRecordStore`, `DuckDBRecordStore`              | **not readable**: they used typed tables                                                   |
| `RecordStore` over a JSON store                       | read as it is, with the same ids                                                           |
| entries of a `Cache` written with explicit keys       | read if the backing store is read (see the rows above)                                     |
| entries of memoized functions and of the HTTP cache   | **never hit again** (new keys); they stay in the store until it is cleared                 |
| ids made by `Record.from_metadata`                    | stored records keep their ids, but **the same metadata gets a new id**                     |

- **PostgreSQL.** An existing table must have exactly the columns `key TEXT PRIMARY KEY` and
  `value` (`JSONB`, or `BYTEA` with a `PickleCodec`): a table with other columns, which was accepted
  before, is rejected. A key of more than 2692 UTF-8 bytes is listed by `keys` and by the iterations
  and removed by `clear`, but the methods that take a key reject it.
- **NaN and infinity.** A JSON value that the old version stored with `NaN` or an infinity is
  read, but writing it back, also through `on_conflict="merge"`, raises `ValueError`.
- **File stores on a case-insensitive file system** (the default of macOS and Windows). An old file
  such as `User.json` occupies the name of the key `user`: this key reads as missing, and writing it
  raises `ValueError` until the file is renamed or removed.
- **Mixed versions.** Do not let the two versions write the same data at the same time. In
  PostgreSQL, their advisory locks differ, so they do not exclude each other.

## Packaging and Utilities

| Removed                                                    | Replacement                                                  |
| ---------------------------------------------------------- | ------------------------------------------------------------ |
| the `aiosqlite` extra and its helpers and `pytest` marks   | nothing to install: `SQLiteStore` runs its calls in a thread |
| `persista.utils.imports.<name>_available` (the decorators) | `if is_<name>_available():`                                  |
| `persista.utils.imports.raise_<name>_missing_error`        | `check_<name>()`                                             |
| the modules `persista.utils.imports.<name>`                | `persista.utils.imports`, now one module                     |
| `persista.utils.asyncio` (`EmptyAsyncIterator`)            | an async generator of your own                               |

`rich` got the functions `is_rich_available` and `check_rich`, and `persista.testing.fixtures` the
marks `rich_available` and `rich_not_available`. The markers of the other libraries did not change:
`persista.testing.fixtures.lmdb_available` is still a `pytest` mark. Only the decorators of the same
name in `persista.utils.imports` are gone.

```pycon
>>> from persista.utils.imports import check_duckdb, is_duckdb_available
>>> if is_duckdb_available():  # replaces the @duckdb_available decorator
...     pass
>>> check_duckdb()  # raises RuntimeError if duckdb is missing

```

Importing a subpackage of `persista` (except `persista.testing`) imports no optional library: a
driver is imported when it is first used.

## Stores

### Removed Classes, Functions and Modules

| Removed                                                               | Replacement                                                  |
| --------------------------------------------------------------------- | ------------------------------------------------------------ |
| `JsonFileStore(path)`                                                 | `FileStore(path)`                                            |
| `PickleFileStore(path)`                                               | `FileStore(path, codec=PickleCodec())`                       |
| `PickleSQLiteStore(database)`                                         | `SQLiteStore(database, codec=PickleCodec())`                 |
| `PickleLmdbStore(path)`                                               | `LmdbStore(path, codec=PickleCodec())`                       |
| `PickleRedisStore(url)`                                               | `RedisStore(url, codec=PickleCodec())`                       |
| `TypedSQLiteStore`, `TypedDuckDBStore`, `TypedPostgresStore`          | the JSON stores, with an [expression index][index] if needed |
| `BaseFileStore`, `BaseSQLiteStore`, `BaseDuckDBStore`,                | `BaseStore`                                                  |
| `BaseLmdbStore`, `BaseRedisStore`, `BasePostgresStore`                | `BaseStore`                                                  |
| `SQLiteStore.from_path(path, read_only=True)`                         | `SQLiteStore(path, read_only=True)`                          |
| `filter_items`, `afilter_items`, `SQLFilterStore`                     | `filter`, `afilter`                                          |
| `get_columns_info`, `show_columns_info`                               | the native `connection`                                      |
| `InMemoryStore.data`                                                  | `get`, `keys`, `iter_batches`                                |
| `split_present_missing` (`persista.store.keys`)                       | two comprehensions over `contains_many`                      |
| `resolve_conflicts`, `aresolve_conflicts`                             | the base class resolves the conflicts                        |
| `validate_value_schema`, `validate_column_type`                       | nothing: there is no value schema                            |
| `ThreadedAsyncStoreMixin`, `athread_iter` (`persista.store.threaded`) | `BaseStore`, which derives the async methods                 |
| `persista.store.async_close`                                          | `await store.aclose()`                                       |
| `persista.store.factory`, `resolve_store`                             | [`coola.factory.resolve_object`](#factories)                 |
| the validation functions imported from `persista.store`               | import them from `persista.store.validation`                 |

[index]: uguide/store.md#indexing-a-filtered-field

```pycon
>>> from persista.store import InMemoryStore, PickleCodec, SQLiteStore
>>> from persista.store.validation import validate_batch_size  # not from persista.store
>>> with SQLiteStore(":memory:", codec=PickleCodec()) as store:  # PickleSQLiteStore
...     store.set("1", {"tags": {"python"}})
...     store.get("1")
{'tags': {'python'}}
>>> with InMemoryStore() as store:  # split_present_missing
...     store.set("1", {})
...     keys = ["1", "2"]
...     flags = store.contains_many(keys)
...     present = [key for key, flag in zip(keys, flags) if flag]
...     missing = [key for key, flag in zip(keys, flags) if not flag]
...     print(present, missing)
['1'] ['2']

```

### Calls That Changed

- `on_conflict` is keyword-only in `set`, `set_many`, `set_batches` and their async twins.
- `filter` and `afilter` return a `dict` that maps each key to its value, not a list of values. Use
  `list(store.filter(...).values())` for the old result.
- The options added to the constructors (`codec`, `read_only`, `namespace`) are keyword-only, as are
  `codec` and `table` of `PostgresStore` and `map_size` of `LmdbStore`. `url` is the only positional
  argument of `RedisStore`.

```pycon
>>> from persista.store import InMemoryStore
>>> with InMemoryStore() as store:
...     store.set("1", {"author": "Alice"})
...     store.set("1", {"author": "Bob"}, on_conflict="skip")
...     print(store.filter(author="Alice"))
...     print(list(store.filter(author="Alice").values()))
{'1': {'author': 'Alice'}}
[{'author': 'Alice'}]

```

### Values

- Every store, **including `InMemoryStore` and `NullStore`**, passes the values through a codec,
  `JsonCodec` by default. `InMemoryStore` kept any object before: it now rejects what JSON cannot
  represent. Use `InMemoryStore(codec=PickleCodec())` to keep Python types, also for the store that
  you give to a `Cache` or a `RecordStore`.
- A tuple is read back as a list, and a subclass of a built-in type as that type. A `dict` key that
  is not a `str` (which was converted to a string by some stores), a set, `bytes` or a value that is
  not a `dict` raises `TypeError`. `NaN`, infinity, a lone surrogate and a value that contains
  itself raise `ValueError`. A write checks every value before it writes anything.
- A store never returns or keeps your object: mutating it does not change the stored value.

### Errors and Lifecycle

- A key that is not a `str`, or a single `str` where a list of keys is expected, raises `TypeError`.
- Every operation on a closed store raises `RuntimeError`, also with an empty input. So does an
  iteration whose store is closed while it runs.
- A key that a backend cannot keep raises `ValueError` on every operation, reads and deletes
  included (see [key limits](uguide/store.md#key-limits)).
- The async methods of `InMemoryStore`, `FileStore`, `SQLiteStore`, `DuckDBStore` and `LmdbStore`
  run one at a time, in a worker thread of the store.
- `repr` and `str` show no number of values, run no query, hide the credentials and leave out the
  arguments of the drivers.

### Filtering

`filter` now gives the same result on every backend, with the types of JSON: `True` no longer
matches `1`, and `"1"` no longer matches `1`. `None` matches a null or absent field. Lists, tuples
and dicts are compared item by item, `NaN` matches nothing, and any name can be a field name. The
SQL stores only apply the conditions on a string or an integer in the database: used alone, the
other conditions read the whole table. A PostgreSQL index on `value->>'field'` is no longer used by
an integer filter: create a [GIN index](uguide/store.md#indexing-a-filtered-field).

### Backends

- **SQLite.** One connection serves the sync and the async methods. `":memory:"` is a private
  database, also through its URI. `isolation_level` and `autocommit` are rejected. A writer waits
  for the others up to `timeout` (5 seconds by default), then raises `sqlite3.OperationalError`.
- **SQLite and DuckDB.** `read_only=True` never creates a file or a directory, raises if there is no
  `store` table, and is rejected for an in-memory database. The parent directories are created by
  `open`, not by the constructor. An existing table with another layout raises `ValueError`. DuckDB
  raises `ValueError` for a key with a lone surrogate.
- **File.** Upper-case ASCII letters are escaped in the file names. A file name has at most 255
  characters. The extra keyword arguments, `extension` and `scheme` are gone.
- **LMDB.** `readonly` and `create` are rejected (use `read_only`), the path is made absolute, and
  opening a read-only store raises `FileNotFoundError` if a file of the environment is missing.
- **Redis.** A store owns a `namespace` (`"persista"` by default), and the key `__keys__` is no
  longer reserved. `decode_responses` is rejected, and the native `client` returns `bytes`. `open`
  connects (`PING`). `close` raises `RuntimeError` while an async client is open: call `aclose`.
  `clear` removes the keys that exist when it starts.
- **PostgreSQL.** A table name has at most 63 characters. A malformed connection string raises
  `ValueError`. `close` raises `RuntimeError` while an async connection is open, also when leaving a
  sync `with` block after async calls: use `aclose`. Writes and deletes take advisory locks, so a
  write can wait; a write of more than 64 keys and `clear` block the other writes of the table.

### URIs

- The schemes `sqlite+typed` and `duckdb+typed` are gone; `duckdb+pickle` and `unix` are new.
- `from_uri` accepts keyword arguments for the constructor, such as `namespace` or `codec`.
  `store_from_uri` still uses the default options.
- The scheme given to `register_scheme` ignores its case, and the errors no longer quote the URI.

### Custom Stores

A subclass of `BaseStore` no longer implements the public methods. It calls `super().__init__()`,
implements `to_uri`, `from_uri(uri, *, read_only=False, **kwargs)` and the primitives, which receive
checked keys and encoded payloads. See [writing a custom
store](uguide/store.md#writing-a-custom-store).

## Factories

All the factory classes (`persista.store.factory`, `persista.cache.factory`,
`persista.record.store.factory`) and the functions `resolve_store`, `resolve_cache` and
`resolve_record_store` are removed. Use `resolve_object` of `coola.factory`, or the constructors. A
configuration that names a removed class fails with `ImportError`, and a nested configuration is not
built: build the store first.

```pycon
>>> from coola.factory import resolve_object
>>> from persista.cache import Cache
>>> from persista.store import BaseStore
>>> store = resolve_object(  # resolve_store(config)
...     {"_target_": "persista.store.SQLiteStore", "database": ":memory:"}, cls=BaseStore
... )
>>> cache = resolve_object(  # resolve_cache(config)
...     {"_target_": "persista.cache.Cache", "store": store}, cls=Cache
... )

```

## Cache

| Removed or changed                                     | Replacement                                                   |
| ------------------------------------------------------ | ------------------------------------------------------------- |
| `try_get(key)`                                         | `get(key, MISSING)`, compared with `is MISSING`               |
| `try_get_many(keys)`                                   | `get_many(keys)`, which returns the hits only                 |
| `get_many(keys, default=d)`                            | `{key: hits.get(key, d) for key in keys}`                     |
| `contains_many(keys)`                                  | `[key in hits for key in keys]`, with `hits = get_many(keys)` |
| `get_or_compute(key, fn, args, kwargs)`                | `get_or_compute(key, functools.partial(fn, ...))`             |
| `amemoize`, `async_cached`                             | `memoize`, `cached`, which also decorate `async def`          |
| `strategy=`, `ignore_non_serializable=`                | `ignore=("name",)` or `key=function`                          |
| `default_ttl` and `ttl` given by position              | keyword arguments                                             |
| `persista.cache.utils` (`make_key`, the split helpers) | `ignore=`, `key=`; `persista.utils.canonical.hash_canonical`  |
| `resolve_cache`, `persista.cache.factory`              | [`resolve_object`](#factories)                                |

```pycon
>>> from functools import partial
>>> from persista.cache import MISSING, Cache
>>> with Cache(default_ttl=60) as cache:
...     cache.set("a", None, ttl=None)
...     cache.get("a", MISSING) is MISSING  # try_get
...     hits = cache.get_many(["a", "b"])
...     print(hits)
...     print({key: hits.get(key, 0) for key in ["a", "b"]})  # get_many with a default
...     print([key in hits for key in ["a", "b"]])  # contains_many
...     cache.get_or_compute("square", partial(pow, 3, 2))
...
...     @cache.memoize(ignore=("client",))
...     def greet(name, client=None):
...         return f"hello {name}"
...
...     greet("Ann", client=object())
False
{'a': None}
{'a': None, 'b': 0}
[True, False]
9
'hello Ann'

```

Behaviour changes:

- The arguments of a memoized call, defaults included, must be of the types of the [canonical
  encoding](uguide/cache.md#the-key-of-a-call): an object of another type raises `TypeError` unless
  its parameter is in `ignore`, or `key` is given. A method, bound or not, needs one of the two. An
  argument is never dropped silently.
- A key contains the module of the function. `f(1)` and `f(a=1)` share a result; a list and a tuple
  do not. Two closures or lambdas with the same qualified name still share their results.
- The default cache, of `Cache()` and of `get_cache()`, pickles its values instead of copying them,
  so a value that cannot be pickled raises. It is created by the first call of `get_cache()`.
- A `NaN` TTL raises `ValueError`, an infinite one means that the entry never expires, and the bulk
  methods raise on a closed cache also with an empty input.

## Records

| Removed or changed                                                           | Replacement                               |
| ---------------------------------------------------------------------------- | ----------------------------------------- |
| `InMemoryRecordStore()`                                                      | `RecordStore(InMemoryStore())`            |
| `SQLiteRecordStore(database)`, `DuckDBRecordStore(database)`                 | `RecordStore(SQLiteStore(database))`, ... |
| `TypedSQLiteRecordStore`, `TypedDuckDBRecordStore`                           | `RecordStore` over a JSON store           |
| `BaseRecordStore`                                                            | `RecordStore`                             |
| `persista.record.store.check_is_open`, `check_is_closed`                     | `persista.store.validation`               |
| `resolve_record_store`, `persista.record.store.factory`                      | [`resolve_object`](#factories)            |
| `compute_value_frequency(..., hll_precision=...)`, `distinct_count_estimate` | `distinct_count`, which is exact          |
| `MetadataStats`                                                              | `compute_metadata_stats`                  |

```pycon
>>> from persista.record import Record
>>> from persista.record.analysis import compute_value_frequency
>>> from persista.record.store import RecordStore
>>> from persista.store import InMemoryStore
>>> with RecordStore(InMemoryStore()) as store:  # InMemoryRecordStore()
...     store.set(Record(id="1", metadata={"lang": "en"}))
...     compute_value_frequency(store.values())
{'lang': {'top_values': [('en', 1)], 'distinct_count': 1}}

```

Behaviour changes:

- `Record.from_metadata` derives the id from the canonical encoding, so **the same metadata gets a
  new id**. It tells `1`, `"1"` and `True` apart, and a list from a tuple; `1` and `1.0` are one
  value.
- `from_metadata` and the analyses that compare values raise `TypeError` for a `datetime`, a
  `Decimal`, a subclass of a built-in type or another object, and `ValueError` for `NaN`. Invalid
  parameters of an analysis raise `ValueError`.
- `filter_by_metadata(records, key, None)` also keeps the records without the key, and `True` no
  longer matches `1`. A `str` given as the accepted values of `filter_by_metadata_values` is read as
  its characters.
- A `Record` can be hashed, pickled and copied.
- `RecordStore.set_many` resolves the records of one list that share an `id` with `on_conflict`.
  `filter` has the [semantics of the stores](#filtering).
- `persista.record.analysis` can be imported without `rich`, which only
  `print_metadata_stats_report` needs.

## HTTP

The module functions of `persista.http.httpx` (`send_request`, `get_response`, `post_response`,
`put_response`, `patch_response`, `delete_response` and their `_async` versions) are removed. Use
`HttpClient` and `AsyncHttpClient`:

| Old                                        | New                                                            |
| ------------------------------------------ | -------------------------------------------------------------- |
| `get_response(url)`                        | `HttpClient().get(url)`, in a `with` block                     |
| `send_request(method, url, client=client)` | `HttpClient(client).request(method, url)`                      |
| `await get_response_async(url)`            | `await AsyncHttpClient().get(url)`, in an `async with` block   |
| `HttpClient(client, timeout=10)`           | `HttpClient(httpx.Client(timeout=10))`, or `timeout=` per call |

```pycon
>>> import httpx
>>> from persista.http.httpx import HttpClient
>>> transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
>>> with httpx.Client(transport=transport, timeout=10) as client:
...     # send_request("GET", url, client=client, timeout=10)
...     HttpClient(client).get("https://example.com").json()
...     HttpClient(client).request("GET", "https://example.com", timeout=5).status_code
{'ok': True}
200

```

Behaviour changes:

- The client is optional. The one that the wrapper creates has the default timeout of `httpx` (5
  seconds, previously 30). A `timeout` of a call is passed to `httpx`, also when a client is given,
  and `timeout=None` disables it.
- Only the idempotent methods are retried by default, also after a connection error: a `POST` or a
  `PATCH` request is sent once. Add them with `retry_methods`.
- A 3xx response that is not followed is returned instead of raising. A request on a closed client
  raises, also when its response is cached. Invalid retry arguments raise.
- `Retry-After` accepts a date; a negative number or a past date gives no delay, a value that cannot
  be read gives the exponential delay, and every delay is at most `max_delay` (60 seconds).
- The cache key covers the method, the final URL, all the headers, the body and the redirect
  setting. A request with `auth`, credentials in its URL, a streamed body, request event hooks or
  `extensions` is not cached. A cached response has no `content-encoding`, `content-length` of the
  original or `transfer-encoding` header.
- `persista.http.requests`: only `GET` requests are retried, and a status is only retried if it is
  in `retry_status_codes`, also when the response has a `Retry-After` header (413, and unlisted 429
  or 503, were retried before). `create_session` and `fetch_response` have a `max_delay`.
