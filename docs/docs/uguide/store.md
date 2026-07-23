# Key-Value Stores

:book: This page describes the `persista.store` package, which provides a uniform key-value
store interface backed by several storage engines. This page explains the `BaseStore` interface
(which supports both synchronous and asynchronous usage) and how to use the concrete store
implementations: `InMemoryStore`, `SQLiteStore`, `DuckDBStore`, `LmdbStore`, `RedisStore`,
`PostgresStore`, and their "typed"/"pickle" variants.

**Prerequisites:** You'll need to know a bit of Python.
For a refresher, see the [Python tutorial](https://docs.python.org/tutorial/).

## Overview

The `persista.store` package provides a single, consistent interface for storing `dict` values
under string keys, regardless of the backend used to persist them:

- `BaseStore`: a single abstract interface that supports both synchronous methods (`get`, `set`,
  ...) and their asynchronous, `a`-prefixed counterparts (`aget`, `aset`, ...) on the same
  instance

Both modes expose the same set of operations:

- `get`/`aget`, `get_many`/`aget_many`: read one or several values by key
- `set`/`aset`, `set_many`/`aset_many`, `set_batches`/`aset_batches`: write one, several, or a
  stream of values
- `filter`/`afilter`: retrieve values matching field conditions
- `delete`/`adelete`, `delete_many`/`adelete_many`: remove values
- `clear`/`aclear`: remove all values
- `contains_many`/`acontains_many`: check which keys exist
- `keys`/`akeys`, `values`/`avalues`, `iter_batches`/`aiter_batches`: iterate over the store's
  content
- `count`/`acount`: number of entries
- `close`/`aclose`: release underlying resources

Because every store implements the same interface, application code written against `BaseStore`
can be moved between backends — for example using `InMemoryStore` in unit tests and
`PostgresStore` in production — without changes, and can freely mix sync and async calls on the
same store instance.

## Getting Started

### In-Memory Store

`InMemoryStore` keeps data in a plain Python `dict`. It requires no setup and is a good default
for tests and prototyping:

```pycon
>>> from persista.store import InMemoryStore
>>> store = InMemoryStore()
>>> store.set("1", {"title": "Intro to Python", "author": "Alice"})
>>> store.count()
1
>>> store.get("1")
{'title': 'Intro to Python', 'author': 'Alice'}

```

`InMemoryStore` also supports the context manager protocol, which calls `close()` automatically:

```pycon
>>> from persista.store import InMemoryStore
>>> with InMemoryStore() as store:
...     store.set("1", {"title": "Intro to Python"})
...     print(store.get("1"))
...
{'title': 'Intro to Python'}

```

### Setting Multiple Values

`set_many` writes several values in a single call. `filter` retrieves the values whose fields
match the given keyword arguments:

```pycon
>>> from persista.store import InMemoryStore
>>> store = InMemoryStore()
>>> store.set_many(
...     {
...         "1": {"title": "Intro to Python", "author": "Alice", "category": "Programming"},
...         "2": {"title": "Advanced Python", "author": "Alice", "category": "Programming"},
...         "3": {"title": "History of Rome", "author": "Bob", "category": "History"},
...     }
... )
>>> len(store.filter(author="Alice"))
2
>>> len(store.filter(author="Alice", category="Programming"))
2
>>> len(store.filter(category="History"))
1

```

### Handling Conflicts

Every write method accepts an `on_conflict` argument controlling what happens when a key already
exists:

- `"overwrite"` (default): replace the existing value
- `"raise"`: raise a `KeyError`, leaving the existing value unchanged
- `"skip"`: leave the existing value unchanged
- `"merge"`: shallow-merge the new value into the existing one; new fields win

```pycon
>>> from persista.store import InMemoryStore
>>> store = InMemoryStore()
>>> store.set("1", {"title": "Intro to Python", "views": 10})
>>> store.set("1", {"views": 11}, on_conflict="merge")
>>> store.get("1")
{'title': 'Intro to Python', 'views': 11}
>>> store.set("1", {"title": "New title"}, on_conflict="skip")
>>> store.get("1")
{'title': 'Intro to Python', 'views': 11}

```

### Deleting and Clearing

```pycon
>>> from persista.store import InMemoryStore
>>> store = InMemoryStore()
>>> store.set_many({"1": {"a": 1}, "2": {"a": 2}})
>>> store.delete("1")
>>> store.count()
1
>>> store.clear()
>>> store.count()
0

```

## SQL-Backed Stores

### SQLite

`SQLiteStore` persists values in a SQLite database, storing each value as a single JSON column.
It works both with a file path and with `":memory:"`:

```pycon
>>> from persista.store import SQLiteStore
>>> store = SQLiteStore(":memory:")
>>> store.set_many(
...     {
...         "1": {"title": "Intro to Python", "author": "Alice", "category": "Programming"},
...         "2": {"title": "Advanced Python", "author": "Alice", "category": "Programming"},
...         "3": {"title": "History of Rome", "author": "Bob", "category": "History"},
...     }
... )
>>> len(store.filter(author="Alice"))
2

```

To persist to disk, pass a file path instead of `":memory:"`:

```python
from pathlib import Path

from persista.store import SQLiteStore

store = SQLiteStore(Path("tmp/data.sqlite"))
```

### DuckDB

`DuckDBStore` works the same way as `SQLiteStore` but is backed by [DuckDB](https://duckdb.org/)
(requires the `duckdb` extra):

```pycon
>>> from persista.store import DuckDBStore
>>> store = DuckDBStore(":memory:")
>>> store.set_many(
...     {
...         "1": {"title": "Intro to Python", "author": "Alice", "category": "Programming"},
...         "2": {"title": "Advanced Python", "author": "Alice", "category": "Programming"},
...         "3": {"title": "History of Rome", "author": "Bob", "category": "History"},
...     }
... )
>>> len(store.filter(author="Alice"))
2

```

### Typed Stores

`TypedSQLiteStore`, `TypedDuckDBStore`, and `TypedPostgresStore` map selected fields onto native
SQL columns instead of storing the whole value as JSON, using a `value_schema` that maps field
names to SQL types. Fields that are not listed in the schema are still stored (in an `extra` JSON
overflow column), so filtering by those fields still works, but only the fields declared in the
schema can be used efficiently in `filter`/indexes:

```pycon
>>> from persista.store import TypedSQLiteStore
>>> schema = {"author": "TEXT", "year": "INTEGER", "category": "TEXT"}
>>> store = TypedSQLiteStore(":memory:", value_schema=schema)
>>> store.set_many(
...     {
...         "1": {"title": "Intro to Python", "author": "Alice", "category": "Programming"},
...         "2": {"title": "Advanced Python", "author": "Alice", "category": "Programming"},
...         "3": {"title": "History of Rome", "author": "Bob", "category": "History"},
...     }
... )
>>> len(store.filter(author="Alice"))
2

```

### PostgreSQL

`PostgresStore` (and `TypedPostgresStore`) connect to a PostgreSQL database using a connection
string, and store values in a configurable `table` (requires the `psycopg` extra):

```python
from persista.store import PostgresStore

store = PostgresStore("postgresql://user:pass@localhost/dbname", table="documents")
store.set_many(
    {
        "1": {"title": "Intro to Python", "author": "Alice"},
        "2": {"title": "Advanced Python", "author": "Alice"},
    }
)
len(store.filter(author="Alice"))  # 2
```

!!! warning
    Unlike the SQLite, DuckDB, LMDB, and Redis stores, `BasePostgresStore` does not automatically
    reopen a closed connection when re-entering a `with` block. Create a new store instance
    instead of reusing one after `close()`.

## Embedded and Server-Backed Stores

### LMDB

`LmdbStore` persists values to a memory-mapped [LMDB](https://lmdb.readthedocs.io/) database on
disk, with no separate server process required (requires the `lmdb` extra):

```python
from persista.store import LmdbStore

store = LmdbStore("/tmp/lmdb_store")
store.set_many(
    {
        "1": {"title": "Intro to Python", "author": "Alice", "category": "Programming"},
        "2": {"title": "Advanced Python", "author": "Alice", "category": "Programming"},
        "3": {"title": "History of Rome", "author": "Bob", "category": "History"},
    }
)
len(store.filter(author="Alice"))  # 2
```

Use `PickleLmdbStore` to store arbitrary Python objects (not just JSON-serializable `dict`
values) using `pickle` instead of JSON:

```python
from persista.store import PickleLmdbStore

store = PickleLmdbStore("/tmp/lmdb_store")
store.set("1", {"title": "Intro to Python", "tags": {"python", "intro"}})
store.get("1")  # {'title': 'Intro to Python', 'tags': {'python', 'intro'}}
```

!!! warning
    `pickle.loads` can execute arbitrary code. Only use `PickleLmdbStore` (and
    `PickleRedisStore`) with data from trusted sources.

### Redis

`RedisStore` stores values in [Redis](https://redis.io/), encoded as JSON (requires the `redis`
extra):

```python
from persista.store import RedisStore

store = RedisStore("redis://localhost:6379/0")
store.set_many(
    {
        "1": {"title": "Intro to Python", "author": "Alice", "category": "Programming"},
        "2": {"title": "Advanced Python", "author": "Alice", "category": "Programming"},
        "3": {"title": "History of Rome", "author": "Bob", "category": "History"},
    }
)
len(store.filter(author="Alice"))  # 2
```

Use `PickleRedisStore` to store arbitrary Python objects using `pickle` instead of JSON.

## Async Usage

Every store also exposes `a`-prefixed asynchronous methods (`aget`, `aset`, `acount`, ...) that
are coroutines (or async iterators), so they must be `await`ed and used from an `async` function.
The same store instance can be used from both sync and async code -- there is no separate async
class. Async methods are available on every store, including `InMemoryStore`, `SQLiteStore`
(async methods use the `aiosqlite` extra when installed, falling back to a thread otherwise),
`RedisStore`, and `PostgresStore` (requires the `psycopg` extra); `DuckDBStore` and `LmdbStore`
also expose async methods, backed by a thread pool.

```pycon
>>> import asyncio
>>> from persista.store import InMemoryStore
>>> async def main():
...     store = InMemoryStore()
...     await store.aset("1", {"text": "hello"})
...     print(await store.acount())
...     print(await store.aget("1"))
...
>>> asyncio.run(main())
1
{'text': 'hello'}

```

`SQLiteStore` and `TypedSQLiteStore`'s async methods behave like their sync counterparts:

```pycon
>>> import asyncio
>>> from persista.store import SQLiteStore
>>> async def main():
...     store = SQLiteStore(":memory:")
...     await store.aset_many(
...         {
...             "1": {"title": "Intro to Python", "author": "Alice"},
...             "2": {"title": "Advanced Python", "author": "Alice"},
...             "3": {"title": "History of Rome", "author": "Bob"},
...         }
...     )
...     result = await store.afilter(author="Alice")
...     print(len(result))
...     await store.aclose()
...
>>> asyncio.run(main())
2

```

`RedisStore`/`PickleRedisStore` and `PostgresStore`/`TypedPostgresStore` follow the same
pattern, connecting to a running Redis or PostgreSQL server:

```python
import asyncio

from persista.store import PostgresStore


async def main():
    store = PostgresStore("postgresql://user:pass@localhost/dbname")
    await store.aset_many(
        {
            "1": {"title": "Intro to Python", "author": "Alice"},
            "2": {"title": "Advanced Python", "author": "Alice"},
        }
    )
    result = await store.afilter(author="Alice")
    print(len(result))
    await store.aclose()


asyncio.run(main())
```

Also use `async with` to automatically `aclose()` the store:

```pycon
>>> import asyncio
>>> from persista.store import InMemoryStore
>>> async def main():
...     async with InMemoryStore() as store:
...         await store.aset("1", {"text": "hello"})
...         print(await store.aget("1"))
...
>>> asyncio.run(main())
{'text': 'hello'}

```

## Iterating Over a Store

`keys`, `values`, and `iter_batches` iterate over a store's content without loading everything
into memory at once:

```pycon
>>> from persista.store import InMemoryStore
>>> store = InMemoryStore()
>>> store.set_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
>>> sorted(store.keys())
['1', '2', '3']
>>> sorted(v["a"] for v in store.values())
[1, 2, 3]

```

`set_batches` mirrors `set_many` but consumes an iterable of `(key, value)` pairs and writes them
in mini-batches, which is useful when the source data does not fit comfortably in memory:

```pycon
>>> from persista.store import InMemoryStore
>>> store = InMemoryStore()
>>> store.set_batches((str(i), {"value": i}) for i in range(5))
>>> store.count()
5

```

## Store URIs

Every store implements `to_uri()`, which returns a URI identifying where its data lives, and the
matching `from_uri(uri, *, read_only=False)` classmethod, which reconstructs a store of the same
class from that URI:

```pycon
>>> from persista.store import SQLiteStore
>>> store = SQLiteStore("tmp/data.sqlite")
>>> uri = store.to_uri()
>>> uri
'sqlite:tmp/data.sqlite'
>>> reloaded = SQLiteStore.from_uri(uri)
>>> store.close()
>>> reloaded.close()

```

`read_only` is honored by the SQLite, DuckDB, and LMDB stores (and their `Typed`/`Pickle`
variants); it's accepted but ignored everywhere else. `to_uri`/`from_uri` do not preserve
constructor options like `value_schema` (typed stores) or `table` (Postgres stores) -- `from_uri`
always reconstructs with the defaults. `InMemoryStore` and `NullStore` always round-trip to a
fresh, empty store since they carry no reconnection information.

If you don't know the concrete store class ahead of time, `store_from_uri` dispatches on the
URI's scheme to the right class automatically:

```pycon
>>> from persista.store import JsonFileStore, store_from_uri
>>> store = JsonFileStore("data")
>>> store.set("1", {"title": "Intro to Python"})
>>> reloaded = store_from_uri(store.to_uri())
>>> isinstance(reloaded, JsonFileStore)
True
>>> reloaded.get("1")
{'title': 'Intro to Python'}

```

Store classes that share a scheme with another class (`TypedPostgresStore` and `PostgresStore`
both use `postgresql://`, `PickleRedisStore` and `RedisStore` both use `redis://`) aren't
reachable through the dispatcher -- call `TheClass.from_uri(uri)` directly for those.

Use `register_scheme` to register a custom store class (or override a built-in one) under a
given scheme:

```python
from persista.store import register_scheme, store_from_uri
from my_project.stores import MyCustomStore

register_scheme("mycustom", MyCustomStore)
store = store_from_uri("mycustom://...")
```

## Choosing a Store

| Store           | Backend            | Persisted | Typed columns | Pickle values | Async |
|-----------------|---------------------|-----------|----------------|----------------|-------|
| `InMemoryStore` | Python `dict`        | No        | No             | N/A            | Yes   |
| `SQLiteStore`   | SQLite               | Yes       | Yes (`Typed…`) | No             | Yes   |
| `DuckDBStore`   | DuckDB               | Yes       | Yes (`Typed…`) | No             | No    |
| `LmdbStore`     | LMDB                 | Yes       | No             | Yes (`Pickle…`)| No    |
| `RedisStore`    | Redis                | Yes       | No             | Yes (`Pickle…`)| Yes   |
| `PostgresStore` | PostgreSQL           | Yes       | Yes (`Typed…`) | No             | Yes   |
| `NullStore`     | None (discards everything) | No  | No             | N/A            | Yes   |

Use `InMemoryStore` for tests and prototyping, `SQLiteStore`/`DuckDBStore` for local
single-process persistence without a server, and `RedisStore`/`PostgresStore` when data needs to
be shared across processes or machines. `NullStore` never actually stores anything -- every
`get`/`aget` is a miss -- which is useful for plugging into `Cache` to disable caching entirely
without changing any calling code.

## API Reference

See the [reference documentation](../refs/store.md) for the full API.
