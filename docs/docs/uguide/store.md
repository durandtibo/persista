# Key-Value Stores

:book: This page describes the `persista.store` package, which provides a uniform key-value
store interface backed by several storage engines. This page explains the `BaseStore` interface
(which supports both synchronous and asynchronous usage) and how to use the concrete store
implementations: `InMemoryStore`, `FileStore`, `SQLiteStore`, `DuckDBStore`, `LmdbStore`,
`RedisStore`, `PostgresStore`, and how to store Python objects with `pickle`.

**Prerequisites:** You'll need to know a bit of Python.
For a refresher, see the [Python tutorial](https://docs.python.org/tutorial/).

## Overview

The `persista.store` package provides a single, consistent interface for storing `dict` values
under string keys, regardless of the backend used to persist them:

- `BaseStore`: a single abstract interface that supports both synchronous methods (`get`, `set`,
  ...) and their asynchronous, `a`-prefixed counterparts (`aget`, `aset`, ...) on the same
  instance
- `Codec`, `JsonCodec` and `PickleCodec`: how a value is turned into what a store keeps (see
  [values and codecs](#values-and-codecs))

Both modes expose the same set of operations:

- `get`/`aget`, `get_many`/`aget_many`: read one or several values by key
- `set`/`aset`, `set_many`/`aset_many`, `set_batches`/`aset_batches`: write one, several, or a
  stream of values
- `filter`/`afilter`: retrieve the pairs whose fields are equal to some values (see
  [filtering](#filtering))
- `delete`/`adelete`, `delete_many`/`adelete_many`: remove values
- `clear`/`aclear`: remove all values
- `contains`/`acontains`, `contains_many`/`acontains_many`: check which keys exist
- `keys`/`akeys`, `values`/`avalues`, `iter_batches`/`aiter_batches`: iterate over the store's
  content
- `count`/`acount`: number of entries
- `close`/`aclose`: release underlying resources

Because every store implements the same interface, application code written against `BaseStore`
can be moved between backends — for example using `InMemoryStore` in unit tests and
`PostgresStore` in production — without changes (within the [limits](#limits-of-the-backends) of
each backend), and can freely mix sync and async calls on the same store instance.

## Properties

What every store guarantees, and where each guarantee stops. The
[properties of the package](package.md) apply too.

| Property             | Guarantee                                                                                                                                                                | Limits                                                                                                                                                                                                                                                    |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Key domain           | A key is a `str`, compared exactly (case-sensitive). A backend that accepts fewer keys raises `ValueError` before it writes; its limit applies to it only.               | See [key limits](#key-limits).                                                                                                                                                                                                                            |
| Value domain         | A value is a `dict` that the codec of the store can encode (`JsonCodec` by default, `PickleCodec` on request).                                                           | `PostgresStore` with a `JsonCodec` rejects a NUL character in a string. The libraries limit the size of a value.                                                                                                                                          |
| Round trip           | `get(key)` returns `codec.decode(codec.encode(value))`, the same on every backend that uses the same codec. A value that would lose data raises.                         | `JsonCodec` reads a tuple back as a list, and a subclass of a built-in type as that type. `PostgresStore` with a `JsonCodec` reads `-0.0` back as `0.0` and does not keep the order of the keys of a `dict`.                                              |
| Isolation            | Mutating a value that was passed to a store or returned by it never changes the stored value.                                                                            | None.                                                                                                                                                                                                                                                     |
| Atomic conflicts     | `raise`, `skip` and `merge` are atomic against the other writers of the same data: threads, tasks, instances and processes. With `raise`, a conflict writes nothing.     | `FileStore`: one instance only. SQL stores and `PostgresStore`: not against all the writes made without a store (see [concurrent writes](#concurrent-writes)). `set_batches` is atomic per batch.                                                         |
| One filter semantics | `filter` matches the equality of top-level fields with the types of JSON (`True` is not `1`, `1` is `1.0`); `None` matches a null or absent field. Any field name works. | A list and a tuple are equal. A PostgreSQL integer filter does not select a number that [another program wrote](#indexing-a-filtered-field) with more digits than a float keeps.                                                                          |
| Stable iteration     | A key present during a whole iteration is yielded exactly once, even if other keys are written or deleted. An iteration holds at most `batch_size` values.               | Some backends keep [all the keys](#iterating-over-a-store) in memory. `filter` is not an iteration: it returns all the matches. `FileStore`: if another instance or process writes while the directory is listed, the file system decides what is listed. |
| Durable              | No TTL: a value stays until it is deleted or the store is cleared.                                                                                                       | `InMemoryStore` and `NullStore` are not persistent. A Redis server can evict or lose keys, depending on its configuration. `FileStore` does not flush its files to the disk (`fsync`), so a power failure can lose recent writes.                         |
| Owned data           | A store only reads, counts and clears the data under its own path, table or namespace.                                                                                   | Two stores with the same location share their data. A SQL database file always uses the table `store`.                                                                                                                                                    |
| Small extension      | A new backend implements the primitives (about ten methods) and its two URI methods, and inherits validation, codec, conflicts, filtering and the async twins.           | A backend that is shared between instances must make `_update` atomic itself (see [writing a custom store](#writing-a-custom-store)).                                                                                                                     |

## Limits of the Backends

These limits apply to their backend only.

| Backend         | Limits                                                                                                                                                                                                                |
| --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `FileStore`     | [key length](#key-limits); writes of several keys are atomic per file only; `raise`, `skip` and `merge` are atomic within one instance only                                                                           |
| `SQLiteStore`   | no lone surrogate in a key; a writer gives up after `timeout` seconds; a value nested about 1000 levels deep makes `filter` read every row                                                                            |
| `DuckDBStore`   | no lone surrogate in a key; one process can write to a database                                                                                                                                                       |
| `LmdbStore`     | a key has 1 to 511 UTF-8 bytes; the data is at most `map_size` bytes (`lmdb.MapFullError` beyond); one open store per path in a process                                                                               |
| `RedisStore`    | no lone surrogate in a key; a limited number of connections; `clear` is [not atomic](#concurrency) against the writes of new keys                                                                                     |
| `PostgresStore` | no NUL character and at most 2692 UTF-8 bytes in a key; with a `JsonCodec`, no NUL character in a string, `-0.0` read back as `0.0` and no key order; [only its own writes](#postgresql-concurrent-writes) are locked |
| `NullStore`     | keeps nothing                                                                                                                                                                                                         |

## Not Guaranteed

- **Transactions** across several calls.
- **Cancellation**: cancelling an async call that runs in a thread does not stop the operation.
- **Iteration order**, and whether a key written during an iteration is yielded.
- **URIs** do not describe a whole store (see [limitations of the URIs](#limitations-of-the-uris)).
- **Library errors** are not rewritten.
- **`pickle`**: decoding a payload can execute arbitrary code. Only use `PickleCodec` with trusted
  data.

## Getting Started

### In-Memory Store

`InMemoryStore` keeps data in process memory. It requires no setup and is a good default for tests
and prototyping. Closing it discards its content:

```pycon
>>> from persista.store import InMemoryStore
>>> with InMemoryStore() as store:
...     store.set("1", {"title": "Intro to Python", "author": "Alice"})
...     print(store.count())
...     print(store.get("1"))
1
{'title': 'Intro to Python', 'author': 'Alice'}

```

Constructing a store does not connect to the underlying backend -- every method (other than
`open`/`aopen`) raises `RuntimeError` until the store has been opened, either by calling
`open()`/`aopen()` explicitly or by using it as a context manager, as above. Every store supports
the context manager protocol, which calls `open()` on entry and `close()` automatically on exit --
prefer it over calling `open()`/`close()` manually so the underlying resources are always released.

## Imports, Representation and Secrets

- Importing `persista.store` imports no optional library. The driver of a store (`duckdb`, `lmdb`,
  `redis`, `psycopg`) is imported when a store is first opened (the representation and the URI of a
  `PostgresStore` also use `psycopg` to read the connection string). The constructor of a store whose
  library is not installed raises `RuntimeError`.
- The representation of a store (`repr` and `str`) shows where its data is and whether it is closed.
  It runs no query, so it does not show the number of values (use `count()`), and it does not show
  the arguments of the driver.
- A password never appears in a representation, a log message or an error of `persista`: the URL of
  a server and the parameters of a SQLite `file:` URI that could be secrets are removed. `to_uri` is
  the exception, because it returns what is needed to reconnect. Errors raised by a driver are not
  rewritten.

```pycon
>>> from persista.store import SQLiteStore
>>> SQLiteStore("file:data.db?mode=ro&key=secret", uri=True)
SQLiteStore(
  (database): file:data.db?mode=ro
  (closed): True
)

```

## Values and Codecs

A key is a `str`, and a value is a `dict`. `InMemoryStore` does not keep the object that you give
it: it keeps the _payload_ that its codec builds from the value, and decodes a new object from it on
each read. So mutating a value that you passed to the store, or that the store returned, never
changes the stored value, and a value is read back as `codec.decode(codec.encode(value))`.

The codec is chosen with the `codec` argument:

| Codec                 | Accepted values                          | Read back as                                  |
| --------------------- | ---------------------------------------- | --------------------------------------------- |
| `JsonCodec` (default) | what JSON can represent without any loss | JSON types: a tuple comes back as a list      |
| `PickleCodec`         | any `dict` that can be pickled           | the same types, including sets, `bytes`, etc. |

`JsonCodec` widens some types: a tuple (also a named tuple) is read back as a list, and an instance
of a subclass of `str`, `int`, `float`, `list` or `dict` (for example a `str` enum) as an instance
of the built-in type. It rejects, at any depth, what would be lost or is not portable, and nothing is
written:

| Value                                                      | Error        |
| ---------------------------------------------------------- | ------------ |
| a `dict` key that is not a `str`, such as `1` or `None`    | `TypeError`  |
| an object that JSON cannot represent, such as a `set`      | `TypeError`  |
| `NaN` or infinity                                          | `ValueError` |
| a string with a lone surrogate, which is not valid Unicode | `ValueError` |
| a value that contains itself                               | `ValueError` |

```pycon
>>> from persista.store import InMemoryStore, PickleCodec
>>> with InMemoryStore() as store:
...     store.set("1", {"point": (1, 2)})
...     print(store.get("1"))
...     store.set("2", {1: "one"})
Traceback (most recent call last):
    ...
TypeError: dict keys must be str, not int: 1
>>> with InMemoryStore(codec=PickleCodec()) as store:
...     store.set("1", {"point": (1, 2), 1: "one"})
...     print(store.get("1"))
{'point': (1, 2), 1: 'one'}

```

:warning: Decoding a `pickle` payload can execute arbitrary code. Only use `PickleCodec` with data
from trusted sources.

All the stores take a codec (`NullStore` always uses `JsonCodec`, to check the values it discards).
`PostgresStore` with a `JsonCodec` also rejects a string with a NUL character, which `JSONB` cannot
keep. `JSONB` also reads `-0.0` back as `0.0` and does not keep the order of the keys of a `dict`
(see [PostgreSQL](#postgresql)).

### Setting Multiple Values

`set_many` writes several values in a single call. `filter` retrieves the pairs whose value
matches the given keyword arguments, as a `dict` that maps each key to its value:

```pycon
>>> from persista.store import InMemoryStore
>>> with InMemoryStore() as store:
...     store.set_many(
...         {
...             "1": {
...                 "title": "Intro to Python",
...                 "author": "Alice",
...                 "category": "Programming",
...             },
...             "2": {
...                 "title": "Advanced Python",
...                 "author": "Alice",
...                 "category": "Programming",
...             },
...             "3": {"title": "History of Rome", "author": "Bob", "category": "History"},
...         }
...     )
...     print(sorted(store.filter(author="Alice")))
...     print(len(store.filter(author="Alice", category="Programming")))
...     print(store.filter(category="History"))
['1', '2']
2
{'3': {'title': 'History of Rome', 'author': 'Bob', 'category': 'History'}}

```

### Filtering

`filter` (and `afilter`) combines its keyword arguments with `AND`. Each argument is the name of a
**top-level** field of a value, and the value that this field must be equal to. It returns a
`dict[str, dict]`: the matching values, keyed by their keys, in no guaranteed order. Without an
argument, it returns every pair.

Every backend and every codec give the same result: the values are compared in Python, after they
are decoded, with the types of JSON.

| Filter value         | Matches a field that is...                                                |
| -------------------- | ------------------------------------------------------------------------- |
| `"1"`                | the string `"1"`, not the number `1` (no Unicode normalization)           |
| `1` or `1.0`         | a number equal to 1, not `True` and not `"1"`                             |
| `True`               | `True`, not `1`                                                           |
| `None`               | `None`, or absent from the value                                          |
| `[1, 2]` or `(1, 2)` | an array (list or tuple) with equal items in the same order               |
| `{"a": 1}`           | a `dict` with exactly the same keys and equal values                      |
| `float("nan")`       | nothing: `NaN` is not equal to itself, also inside a list or a `dict`     |
| a set, `bytes`, ...  | an equal object of the same class (only `PickleCodec` keeps these values) |

- The same rules apply inside lists and dicts: `[1]` does not match `[True]`. A key of a nested
  `dict` whose value is `None` is not the same as an absent key.
- Numbers are compared by their exact value: `2**53 + 1` does not match `float(2**53)`.
- Any name can be a field name, including names that are not Python identifiers, passed with `**`:
  `store.filter(**{"user-id": "1", "self": 2})`. A name such as `"a.b"` is the name of one field, not
  a path to a nested field.
- A value that the codec of the store cannot keep (for example a set with `JsonCodec`) matches
  nothing.

```pycon
>>> from persista.store import InMemoryStore
>>> with InMemoryStore() as store:
...     store.set_many({"1": {"user-id": 1}, "2": {"user-id": True}, "3": {"user-id": "1"}})
...     print(store.filter(**{"user-id": 1.0}))
{'1': {'user-id': 1}}

```

The same predicate is available as `persista.store.predicate.matches_filter(value, fields)`.

#### Performance

`filter` returns all the matches in one `dict`, so they must fit in memory. It reads and decodes
every value, in batches, except for the SQL stores (`SQLiteStore`, `DuckDBStore`,
`PostgresStore`) with the `JsonCodec`. Their database first selects the rows that may match, with one
query whose rows are all loaded, and the predicate is then applied to these rows, so this never
changes the result. A condition is applied by the database if:

- the field name is an identifier (ASCII letters, digits and underscores, not starting with a
  digit); and
- the value is a string without a NUL character or a lone surrogate, or an integer (not a `bool`)
  between `-(2**53 - 1)` and `2**53 - 1`.

The other conditions (`None`, booleans, floats, larger integers, lists, dicts, other names) are only
applied in Python. A call with no condition that the database can apply reads the whole table, so
combine such a condition with a string or an integer one on a large table. For example, filter on
`year=2024` rather than `year=2024.0`.

### Handling Conflicts

Every write method accepts a keyword-only `on_conflict` argument controlling what happens when a
key already exists:

- `"overwrite"` (default): replace the existing value
- `"raise"`: raise a `KeyError`, leaving the existing value unchanged
- `"skip"`: leave the existing value unchanged
- `"merge"`: shallow-merge the new value into the existing one; new fields win

```pycon
>>> from persista.store import InMemoryStore
>>> with InMemoryStore() as store:
...     store.set("1", {"title": "Intro to Python", "views": 10})
...     store.set("1", {"views": 11}, on_conflict="merge")
...     print(store.get("1"))
...     store.set("1", {"title": "New title"}, on_conflict="skip")
...     print(store.get("1"))
{'title': 'Intro to Python', 'views': 11}
{'title': 'Intro to Python', 'views': 11}

```

`set_batches` applies `on_conflict` to one batch at a time, against the content of the store: with
`"raise"`, the batches written before a conflict are kept. Each batch is first collected in a
`dict`, so if two pairs of **one batch** have the same key, the last one wins whatever
`on_conflict` is, and `"raise"` does not raise. Pass pairs with distinct keys.

```pycon
>>> from persista.store import InMemoryStore
>>> with InMemoryStore() as store:
...     store.set_batches([("1", {"v": 1}), ("1", {"v": 2})], on_conflict="raise")
...     print(store.get("1"))
{'v': 2}

```

### Deleting and Clearing

```pycon
>>> from persista.store import InMemoryStore
>>> with InMemoryStore() as store:
...     store.set_many({"1": {"a": 1}, "2": {"a": 2}})
...     store.delete("1")
...     print(store.count())
...     store.clear()
...     print(store.count())
1
0

```

### Errors

Every store, including the [custom stores](#writing-a-custom-store), checks its state and the
arguments before doing anything, also when there is nothing to do (for example `get_many([])`):

| Situation                                                          | Error          |
| ------------------------------------------------------------------ | -------------- |
| any operation on a closed store                                    | `RuntimeError` |
| a key that is not a `str`                                          | `TypeError`    |
| a single `str` where a list of keys is expected                    | `TypeError`    |
| an invalid `on_conflict` or `batch_size`                           | `ValueError`   |
| a key that the backend cannot keep (see [key limits](#key-limits)) | `ValueError`   |

```pycon
>>> from persista.store import InMemoryStore
>>> store = InMemoryStore()
>>> store.get_many([])
Traceback (most recent call last):
    ...
RuntimeError: InMemoryStore is not open; call open()/aopen() or use it as a context manager.

```

### Key Limits

A key is a `str`, compared exactly: `"a"` and `"A"` are two keys (an instance of a subclass of
`str` is converted to a plain `str`). Some backends cannot keep every
string. Their limits apply to them only, and every method that takes a key (reads and deletes
included) raises `ValueError` for a key outside them, before anything is read or written:

| Store           | Limit                                                                                                            |
| --------------- | ---------------------------------------------------------------------------------------------------------------- |
| `SQLiteStore`   | no lone surrogate (the error is a `UnicodeEncodeError`, a subclass of `ValueError`)                              |
| `DuckDBStore`   | no lone surrogate                                                                                                |
| `LmdbStore`     | 1 to 511 UTF-8 bytes, so not the empty string; no lone surrogate                                                 |
| `FileStore`     | the file name, with its extension, has at most 255 characters (see [File Store](#file-store)); no lone surrogate |
| `RedisStore`    | no lone surrogate                                                                                                |
| `PostgresStore` | no NUL character and no lone surrogate; at most 2692 UTF-8 bytes (see below)                                     |

`InMemoryStore` and `NullStore` accept every string.

The limit of `PostgresStore` is the largest key that the index of its primary key accepts, whatever
the content of the key, with the default page size of the server. PostgreSQL compresses long index
entries, so a table written by an earlier version can contain a longer key: it is listed by `keys` and
by the iterations, and removed by `clear`, but the methods that take a key reject it.

## File Store

`FileStore` keeps each value in its own file of a directory. It needs no extra library. With the
default `JsonCodec`, the files are JSON files (`.json`) that any tool can read; with
`codec=PickleCodec()`, they are `pickle` files (`.pkl`):

```pycon
>>> import tempfile
>>> from persista.store import FileStore
>>> with tempfile.TemporaryDirectory() as tmpdir, FileStore(tmpdir) as store:
...     store.set("User:1", {"name": "Alice"})
...     store.set("user:1", {"name": "Bob"})
...     print(sorted(path.name for path in store.path.iterdir()))
...     print(store.get("User:1"))
['%55ser%3A1.json', 'user%3A1.json']
{'name': 'Alice'}

```

- **File names.** The name of a file is the percent-encoded key, so a key such as `../a` cannot
  leave the directory. Upper-case ASCII letters are encoded too, so that two keys never differ only
  by the case of their file names, which some file systems (the default ones of macOS and Windows)
  ignore.
- **Key length.** A file name has at most 255 characters. With `JsonCodec`, this allows 250
  characters among `a-z`, `0-9` and `_.-~`; an encoded byte takes 3 characters, so only 83
  upper-case letters or 41 `é`. A file system with a lower limit raises `OSError`.
- **Writes.** A file is written to a temporary file and then renamed, so a reader never sees a
  partial value. A write of several keys is atomic per file only.
- **Concurrency.** `on_conflict="raise"`, `"skip"` and `"merge"` are atomic against the other
  calls on the same instance only, not against another instance or process that writes the same
  directory. Use `SQLiteStore` or `LmdbStore` if several processes write the same data.
- **Other files.** The store only lists, counts and deletes the files whose name is the encoding of
  a key. The two codecs have different extensions, so their stores ignore each other's files.

:warning: Earlier versions had `JsonFileStore` and `PickleFileStore`, replaced by `FileStore(path)`
and `FileStore(path, codec=PickleCodec())`. Their files are read if the key has no upper-case ASCII
letter; the other files are not found. On a file system that ignores case, such a file (for example
`User.json`) occupies the name of the key `user`: this key reads as missing, and writing it raises
`ValueError` until the file is removed. There is no migration code: to keep the data, read it with
the earlier version and write it with the new one, into a new directory.

## SQL-Backed Stores

### SQLite

`SQLiteStore` persists values in a SQLite database, in the table `store` with a `key` column and a
`value` column, which holds JSON by default. It works both with a file path and with `":memory:"`
(a private database that is new and empty each time the store is opened):

```pycon
>>> from persista.store import SQLiteStore
>>> with SQLiteStore(":memory:") as store:
...     store.set_many(
...         {
...             "1": {
...                 "title": "Intro to Python",
...                 "author": "Alice",
...                 "category": "Programming",
...             },
...             "2": {
...                 "title": "Advanced Python",
...                 "author": "Alice",
...                 "category": "Programming",
...             },
...             "3": {"title": "History of Rome", "author": "Bob", "category": "History"},
...         }
...     )
...     print(len(store.filter(author="Alice")))
2

```

To persist to disk, pass a file path instead of `":memory:"`. The file and its parent directories
are created when the store is opened:

```python
from pathlib import Path

from persista.store import SQLiteStore

with SQLiteStore(Path("tmp/data.sqlite")) as store:
    ...
```

The other keyword arguments, such as `timeout`, are passed to `sqlite3.connect`. To use a
[SQLite URI](https://www.sqlite.org/uri.html), pass it with `uri=True`. `isolation_level` and
`autocommit` are not accepted, because the store manages its transactions.

### DuckDB

`DuckDBStore` works the same way as `SQLiteStore` but is backed by [DuckDB](https://duckdb.org/)
(requires the `duckdb` extra). The other keyword arguments are passed to `duckdb.connect`:

```pycon
>>> from persista.store import DuckDBStore
>>> with DuckDBStore(":memory:") as store:
...     store.set_many(
...         {
...             "1": {
...                 "title": "Intro to Python",
...                 "author": "Alice",
...                 "category": "Programming",
...             },
...             "2": {
...                 "title": "Advanced Python",
...                 "author": "Alice",
...                 "category": "Programming",
...             },
...             "3": {"title": "History of Rome", "author": "Bob", "category": "History"},
...         }
...     )
...     print(len(store.filter(author="Alice")))
2

```

### Pickle Values and Read-Only Stores

Pass `codec=PickleCodec()` to store Python types in either SQL store. The `value` column then holds
bytes, so the database cannot read inside the values: `filter` reads and decodes every value.

`read_only=True` opens an existing database without writing to it, and never creates a file or a
directory. It raises if the database has no `store` table, and it cannot be used with an in-memory
database.

```pycon
>>> import tempfile
>>> from persista.store import PickleCodec, SQLiteStore
>>> with tempfile.TemporaryDirectory() as tmpdir:
...     with SQLiteStore(f"{tmpdir}/data.sqlite", codec=PickleCodec()) as store:
...         store.set("1", {"tags": {"python"}})
...     with SQLiteStore(f"{tmpdir}/data.sqlite", codec=PickleCodec(), read_only=True) as store:
...         print(store.get("1"))
{'tags': {'python'}}

```

:warning: Decoding a `pickle` payload can execute arbitrary code. Only use `PickleCodec` with a
trusted database.

A database is tied to its codec: opening a store raises `ValueError` if the existing `store` table
does not have the columns of the codec (`value` is `JSON` for `JsonCodec` and `BLOB` for
`PickleCodec`).

:warning: The typed stores of earlier versions (which `SQLiteRecordStore` and `DuckDBRecordStore`
also used) wrote another table layout, so opening such a table raises `ValueError`. To keep the data,
read it with the earlier version and write it to a new database.

### Concurrent Writes

Each SQL store has one connection, used by both the sync and the async methods. A write with
`on_conflict` set to `"raise"`, `"skip"` or `"merge"` is atomic against the other writers of the
database:

- **SQLite**: the read and the write run in one `BEGIN IMMEDIATE` transaction, which protects them
  from other threads, stores and processes. A writer waits for the others up to `timeout` seconds (5
  by default), then raises `sqlite3.OperationalError`. The stores of one process that share a cache
  (`cache=shared`) wait for each other without time limit.
- **DuckDB**: the read and the write run in one transaction, and the stores of one process that use
  the same database file write one at a time. DuckDB allows only one process to write to a database.
  A write made without a store, for example with `store.connection`, while a store writes the same
  rows can make one of them raise `duckdb.TransactionException`.

### PostgreSQL

`PostgresStore` connects to a PostgreSQL database using a connection string or URI, and stores
values in a configurable `table` (requires the `psycopg` extra):

```python
from persista.store import PostgresStore

with PostgresStore("postgresql://user:pass@localhost/dbname", table="documents") as store:
    store.set_many(
        {
            "1": {"title": "Intro to Python", "author": "Alice"},
            "2": {"title": "Advanced Python", "author": "Alice"},
        }
    )
    len(store.filter(author="Alice"))  # 2
```

- The codec selects the type of the `value` column: `JSONB` for `JsonCodec` (default), which any
  PostgreSQL client can query, and `BYTEA` for `PickleCodec`, which keeps Python types.
- Opening the store creates the table (`key TEXT PRIMARY KEY`, `value`) in the first schema of the
  search path if it does not exist, and raises `ValueError` if an existing table does not have exactly
  these two columns, with the type of the codec.
- The table name has at most 63 letters, digits and underscores, does not start with a digit, and
  its case is significant. The other keyword arguments, such as `connect_timeout`, are passed to
  `psycopg.connect` and to its async equivalent.
- A key cannot contain a NUL character and has at most 2692 UTF-8 bytes (see
  [key limits](#key-limits)).
- With the `JsonCodec`, a string of a value cannot contain a NUL character: the write raises
  `ValueError` and writes nothing. `JSONB` keeps the numbers as decimals, so `-0.0` is read back as
  `0.0`, and it does not keep the order of the keys of a `dict`.
- `repr` shows the host, the port and the database without the credentials, and runs no query.
  Percent-encode the special characters of a username or a password in a URI, and quote the values
  that contain spaces in a keyword/value string: `open` raises `ValueError` for a string it cannot
  read, without quoting it. `to_uri` returns the password: treat the URI as a secret.

:warning: Decoding a `pickle` payload can execute arbitrary code. Only use `PickleCodec` with a
trusted database.

#### PostgreSQL Concurrent Writes

- Each write or delete is one transaction, so a write of several keys is atomic.
- A transaction first takes advisory locks: a shared lock of the table and an exclusive lock of each
  key. A write or a delete of more than 64 keys, and `clear`, take an exclusive lock of the table
  instead, so that the server never runs out of locks: the other writes of this table wait for it.
- So `on_conflict="raise"`, `"skip"` and `"merge"` are atomic against every other write and delete
  made by a `PostgresStore`, including the ones of other processes. A program that writes to the
  table without these locks is not covered.
- Reads take no lock and do not wait for the writes.
- A write waits without time limit for the locks it needs. Set a limit with the options of the server,
  for example `PostgresStore(url, options="-c lock_timeout=5000")`.

#### PostgreSQL Iteration

An iteration reads the pairs in the order of the keys, one query per batch (keyset pagination), and
keeps no transaction open between two batches.

#### PostgreSQL Async Connections

The sync methods use one connection, protected by the lock of the instance. The async methods use a
`psycopg.AsyncConnection` per event loop, without threads. It runs one operation at a time, so the
transactions of concurrent calls cannot nest. It follows the same rules as the async client of
`RedisStore` (see [event loops and closing](#event-loops-and-closing)): another event loop gets its
own connection, `aclose` closes it, and `close` raises `RuntimeError` while it is open. A connection
that the network or the server closed fails the current call, and the next call opens a new one. The
sync connection is not reopened by itself: close the store and open it again, which connects it
anew.

#### PostgreSQL Changes from Earlier Versions

:warning: `BasePostgresStore` was removed. The table of an earlier `PostgresStore` is read as is.
`codec` and `table` are keyword-only arguments. A table with other columns, which was accepted
before, is now rejected when the store is opened.

## Indexing a Filtered Field

`SQLiteStore` and `PostgresStore` keep each value in a single JSON column, so there is no column
to declare for a field. To make `filter` fast on a field of a large store, create an index on the
expression that `filter` uses to select the rows (see [performance](#performance)).
`persista` does not create indexes: run the statement yourself on the native connection of an open
store. Only the conditions on a string or an integer use an index.

### SQLite

`SQLiteStore.filter` reads a field with `json_extract(value, '$.<field>')`, for a string and for an
integer. An index on exactly this expression is used by `filter` and `afilter`:

```pycon
>>> from persista.store import SQLiteStore
>>> with SQLiteStore(":memory:") as store:
...     _ = store.connection.execute(
...         "CREATE INDEX IF NOT EXISTS store_author ON store(json_extract(value, '$.author'))"
...     )
...     store.set("1", {"title": "Intro to Python", "author": "Alice"})
...     print(store.filter(author="Alice"))
...     plan = store.connection.execute(
...         "EXPLAIN QUERY PLAN SELECT * FROM store WHERE json_extract(value, '$.author') = 'Alice'"
...     ).fetchall()
...     print(plan[0][-1])
{'1': {'title': 'Intro to Python', 'author': 'Alice'}}
SEARCH store USING INDEX store_author (<expr>=?)

```

- SQLite uses the index only if the expression is written as above. `value ->> 'author'`, for
  example, is a different expression.
- The index is saved in the database, so it is enough to create it once, with a store that can
  write. SQLite keeps it up to date on every write, which makes writes a little slower.
- One index covers one field. A `filter` on several fields can use the index of one of them.
- SQLite cannot read a value nested about 1000 levels deep or more. If the table contains one,
  `filter` reads every row, and SQLite does not accept it in an indexed table.
- A store with a `PickleCodec` cannot be indexed this way, because SQLite cannot read inside its
  values.

### PostgreSQL

With a `JsonCodec`, `PostgresStore.filter` uses a different expression for the two types of values,
so the index depends on the type of the values that you filter on:

| Filter value | Expression of the query                         | Index                                                      |
| ------------ | ----------------------------------------------- | ---------------------------------------------------------- |
| a string     | `value->>'<field>' = '...'` (the field as text) | one per field: `((value->>'<field>'))`                     |
| an integer   | `value @> '{"<field>": ...}'` (containment)     | one for all the fields: `USING gin (value jsonb_path_ops)` |

The containment operator compares the numbers by their value, so every way of writing an integer
(`7`, `7.0`, `7.00`) is selected. :warning: It does not select a number that another program wrote
with more digits than a float keeps, such as `6.99999999999999999999` (which `get` reads as
`7.0`). `PostgresStore` never writes such a number.

:warning: An entry of the first kind of index (a B-tree) is limited in size: once it exists,
PostgreSQL rejects the write of a value whose field is a long string (a few thousand bytes that do
not compress) with `psycopg.errors.ProgramLimitExceeded`. Index only a field with short strings.

Note the double parentheses of the first index, and replace `store` with the name of your table:

```python
from persista.store import PostgresStore

with PostgresStore("postgresql://user:pass@localhost/dbname") as store:
    store.connection.execute(
        "CREATE INDEX IF NOT EXISTS store_author ON store ((value->>'author'))"
    )
    store.connection.execute(
        "CREATE INDEX IF NOT EXISTS store_numbers ON store USING gin (value jsonb_path_ops)"
    )
    store.filter(author="Alice")  # uses store_author
    store.filter(year=2024)  # uses store_numbers
```

The tests of `persista` check with `EXPLAIN` that PostgreSQL 16 uses these indexes for the queries of
`filter`. The planner chooses a plan from the statistics of the table (it often reads a small table
sequentially), so run `ANALYZE` after a large load, and check the plan on your data, for example
with `EXPLAIN SELECT * FROM store WHERE value->>'author' = 'Alice'`. A store with a `PickleCodec`
cannot be indexed this way.

:warning: Earlier versions compared an integer filter with `value->>'<field>'`: an index on this
expression is no longer used by an integer filter. Create the GIN index instead.

## Embedded and Server-Backed Stores

### LMDB

`LmdbStore` persists values to a memory-mapped [LMDB](https://lmdb.readthedocs.io/) database on
disk, with no separate server process required (requires the `lmdb` extra):

```python
from persista.store import LmdbStore

with LmdbStore("/tmp/lmdb_store") as store:
    store.set_many(
        {
            "1": {
                "title": "Intro to Python",
                "author": "Alice",
                "category": "Programming",
            },
            "2": {
                "title": "Advanced Python",
                "author": "Alice",
                "category": "Programming",
            },
            "3": {"title": "History of Rome", "author": "Bob", "category": "History"},
        }
    )
    len(store.filter(author="Alice"))  # 2
```

- Pass `codec=PickleCodec()` to keep Python types. An environment does not record its codec: reading
  it with the other codec raises a decoding error.
- `map_size` (1 GiB by default) is the maximum size of the data. The other keyword arguments are
  passed to `lmdb.open`, except `readonly` and `create`, which `read_only` replaces.
- `read_only=True` opens an existing environment without writing to it, and never creates a file or
  a directory: opening raises `FileNotFoundError` if the data file or the lock file is missing. An
  environment without a lock file, such as a copy, can be opened with `lock=False` if no process
  writes it.
- A write runs in one LMDB write transaction, so a write of several keys is atomic, and
  `on_conflict="raise"`, `"skip"` and `"merge"` are atomic against the other writers, including
  other processes. A write waits, without time limit, for the write of another process.
- :warning: LMDB cannot open the same path twice in one process: opening a second `LmdbStore` of a
  path raises `lmdb.Error` while the first one is open. Share one store instead.
- A key has 1 to 511 UTF-8 bytes (see [key limits](#key-limits)).

:warning: Decoding a `pickle` payload can execute arbitrary code. Only use `PickleCodec` with a
trusted environment.

:warning: Earlier versions had `PickleLmdbStore`, replaced by
`LmdbStore(path, codec=PickleCodec())`, which reads its data. The data of the earlier `LmdbStore` is
also readable. `map_size` is now a keyword-only argument.

### Redis

`RedisStore` stores values in [Redis](https://redis.io/), through the `redis` extra, with the sync
and the async clients of `redis-py`:

```python
from persista.store import RedisStore

with RedisStore("redis://localhost:6379/0", namespace="documents") as store:
    store.set_many(
        {
            "1": {
                "title": "Intro to Python",
                "author": "Alice",
                "category": "Programming",
            },
            "2": {
                "title": "Advanced Python",
                "author": "Alice",
                "category": "Programming",
            },
            "3": {"title": "History of Rome", "author": "Bob", "category": "History"},
        }
    )
    len(store.filter(author="Alice"))  # 2
```

- Opening the store connects to the server, so a wrong address or password fails in `open`.
- The values are kept as the payloads of the codec: JSON by default, which any Redis client can read.
  Pass `codec=PickleCodec()` to keep Python types. A namespace does not record its codec: reading it
  with the other codec raises a decoding error.
- The other keyword arguments, such as `socket_timeout` or `max_connections`, are passed to
  `redis.Redis.from_url` and to its async equivalent. `decode_responses` is not accepted.
- A key can be any string without a lone surrogate (see [key limits](#key-limits)).
- `repr` shows the URL without its credentials and runs no command, and the logs do not contain the
  password. Percent-encode the special characters of a username or a password. `to_uri` returns the
  URL as given, password included.

:warning: Decoding a `pickle` payload can execute arbitrary code. Only use `PickleCodec` with a
trusted server.

#### Namespaces

A store owns the namespace given by `namespace` (`"persista"` by default) in its Redis database. It
only reads, counts and clears the keys of its namespace, so several stores can share a database, as
long as their namespaces differ. Redis keys are laid out as follows:

| Redis key             | Type   | Content                           |
| --------------------- | ------ | --------------------------------- |
| `<namespace>:v:<key>` | string | the payload of the value of a key |
| `<namespace>:keys`    | set    | the keys of the store             |

A namespace is a non-empty string that does not contain `:v:` and does not end with `:v`, so that
two namespaces never share a Redis key. For example, `app` and `app:cache` are two namespaces.
Do not modify these keys with other programs, and do not use a server that evicts keys
(`maxmemory-policy`) for data that must be kept.

#### Concurrency

- A write of several keys runs in one transaction.
- `on_conflict="raise"`, `"skip"` and `"merge"` are atomic against every other writer, including
  other processes: the store watches the keys (`WATCH`/`MULTI`) and starts again if one of them
  changes before the write. Many writers of the same key therefore slow each other down.
- `clear` is not atomic against concurrent writes. It reads the keys of the namespace, then
  removes them in one transaction: a key that another client creates in between is kept, and a value
  that another client writes in between to one of the keys read is removed.
- A client has a limited number of connections (100 by default with `redis-py` 8). A call that needs
  one more raises `redis.exceptions.MaxConnectionsError`, for example with several hundred `aset`
  calls in one `asyncio.gather`: pass a larger `max_connections`, or limit the concurrency.

#### Event Loops and Closing

The async methods use an async client that belongs to the event loop that created it: another event
loop gets its own client, so a store can be used in several calls of `asyncio.run`. A client is
closed by `aclose` (or `async with`) in its loop, or when its loop shuts down, which `asyncio.run`
does before it returns. `close` raises `RuntimeError` while an async client is open, for example in
a coroutine that called an async method: call `await store.aclose()` instead. `aclose` waits for the
async calls of the loop that are in progress. A loop that you manage yourself must call
`aclose`, or `loop.shutdown_asyncgens()`, before it is closed.

#### Changes from Earlier Versions

:warning: `PickleRedisStore` and `BaseRedisStore` were removed: use
`RedisStore(url, codec=PickleCodec())`. The layout of the Redis keys changed (the values were stored
under the keys themselves, and the keys in the set `__keys__`), so **the data written by an earlier
version is not found**. To keep it, read it with the earlier version and write it with the new one.
The key `__keys__` is no longer reserved.

## Async Usage

Every store also exposes `a`-prefixed asynchronous methods (`aget`, `aset`, `acount`, ...) that are
coroutines (or async iterators), so they must be `await`ed and used from an `async` function. The
same store instance can be used from both sync and async code -- there is no separate async class.
Async methods are available on every store. Those of `RedisStore` and `PostgresStore` use the async
driver of their library (see [event loops and closing](#event-loops-and-closing) for `RedisStore`
and [async connections](#postgresql-async-connections) for `PostgresStore`). The async methods of
`InMemoryStore`, `FileStore`, `SQLiteStore`, `DuckDBStore` and `LmdbStore` run in a worker thread of
the store, one call at a time, so calls that wait for the store do not fill the default executor of
your application. Cancelling an async call that already runs in a thread does not stop it. Iterating
asynchronously takes one thread hop per batch, so a larger `batch_size` is faster.

```pycon
>>> import asyncio
>>> from persista.store import InMemoryStore
>>> async def main():
...     async with InMemoryStore() as store:
...         await store.aset("1", {"text": "hello"})
...         print(await store.acount())
...         print(await store.aget("1"))
>>> asyncio.run(main())
1
{'text': 'hello'}

```

`SQLiteStore`'s async methods behave like their sync counterparts:

```pycon
>>> import asyncio
>>> from persista.store import SQLiteStore
>>> async def main():
...     async with SQLiteStore(":memory:") as store:
...         await store.aset_many(
...             {
...                 "1": {"title": "Intro to Python", "author": "Alice"},
...                 "2": {"title": "Advanced Python", "author": "Alice"},
...                 "3": {"title": "History of Rome", "author": "Bob"},
...             }
...         )
...         result = await store.afilter(author="Alice")
...         print(len(result))
>>> asyncio.run(main())
2

```

`RedisStore` and `PostgresStore` follow the same pattern, connecting to a
running Redis or PostgreSQL server:

```python
import asyncio

from persista.store import PostgresStore


async def main():
    async with PostgresStore("postgresql://user:pass@localhost/dbname") as store:
        await store.aset_many(
            {
                "1": {"title": "Intro to Python", "author": "Alice"},
                "2": {"title": "Advanced Python", "author": "Alice"},
            }
        )
        result = await store.afilter(author="Alice")
        print(len(result))


asyncio.run(main())
```

Using `async with` (as above) calls `aopen()` on entry and `aclose()` automatically on exit.

## Checking Which Keys Exist

`contains_many` checks a batch of keys at once, returning a list of booleans in the same order
as the input, without fetching the values themselves:

```pycon
>>> from persista.store import InMemoryStore
>>> with InMemoryStore() as store:
...     store.set_many({"1": {"a": 1}, "2": {"a": 2}})
...     print(store.contains_many(["1", "2", "3"]))
[True, True, False]

```

Two comprehensions turn those flags into the keys that are present and the missing ones:

```pycon
>>> from persista.store import InMemoryStore
>>> with InMemoryStore() as store:
...     store.set_many({"1": {"a": 1}, "2": {"a": 2}})
...     keys = ["1", "2", "3"]
...     flags = store.contains_many(keys)
...     print([key for key, flag in zip(keys, flags) if flag])
...     print([key for key, flag in zip(keys, flags) if not flag])
['1', '2']
['3']

```

## Iterating Over a Store

`keys`, `values`, and `iter_batches` iterate over a store's content in batches, without loading
all the values into memory at once (some stores load all the keys, see below):

```pycon
>>> from persista.store import InMemoryStore
>>> with InMemoryStore() as store:
...     store.set_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
...     print(sorted(store.keys()))
...     print(sorted(v["a"] for v in store.values()))
['1', '2', '3']
[1, 2, 3]

```

`set_batches` mirrors `set_many` but consumes an iterable of `(key, value)` pairs and writes them
in mini-batches, which is useful when the source data does not fit comfortably in memory:

```pycon
>>> from persista.store import InMemoryStore
>>> with InMemoryStore() as store:
...     store.set_batches((str(i), {"value": i}) for i in range(5))
...     print(store.count())
5

```

With every store, a key that is present during a whole iteration is yielded exactly once, even if you
write or delete keys during the iteration (for example, you can delete each batch after processing
it). The SQL stores and `PostgresStore` read the keys in order and start each batch after the last key
of the previous one (keyset pagination). `InMemoryStore`, `FileStore`, `LmdbStore` and `RedisStore`
take a snapshot of all the keys when the iteration starts, which they keep in memory, so a batch can
be smaller than `batch_size` (`keys` of `RedisStore` can also yield a key deleted during the
iteration). `keys` and `akeys` do not
read the values of the stores that keep data outside the process. A custom store must give the same
guarantee in `_iter_batches`. Closing a store during an iteration raises `RuntimeError`.

## Writing a Custom Store

`BaseStore` implements the public methods once: it checks that the store is open, validates the
arguments, applies the codec, resolves the conflicts, filters, and derives the async methods. A new
backend implements `to_uri`, `from_uri`, and the _primitives_, which are called with the store open,
with validated and non-empty arguments, and with encoded payloads (`str` or `bytes`). It does not
override the other public methods, which are the contract that every store shares. The primitives
are:

| Primitive                   | Role                                                             |
| --------------------------- | ---------------------------------------------------------------- |
| `_open()`, `_close()`       | connect and release; `_close` is also called if `_open` raises   |
| `_get_many(keys)`           | return the payloads of the keys that exist                       |
| `_put_many(items)`          | add or replace payloads                                          |
| `_update(keys, plan)`       | atomically read the existing keys, call `plan`, write its result |
| `_delete_many(keys)`        | delete keys, ignoring the missing ones                           |
| `_clear()`, `_count()`      | delete everything, count the keys                                |
| `_iter_batches(batch_size)` | yield the payloads in batches                                    |

`_contains_many`, `_filter_candidates` and `_iter_key_batches` have a default that you can replace by
a faster one. `_iter_key_batches(batch_size)` yields lists of keys, for `keys`: by default it reads
the values with `_iter_batches`. `_filter_candidates` may yield more pairs than the ones that match,
never fewer: the base applies the filter to the decoded values (see [filtering](#filtering)). Its
argument is the mapping of the expected values given to `filter`.

`from_uri` is a class method with the signature `from_uri(uri, *, read_only=False, **kwargs)`: pass
`kwargs` to the constructor, so that a caller can give the options that the URI does not describe.

```pycon
>>> from persista.store import BaseStore
>>> class DictStore(BaseStore):
...     def __init__(self, *, codec=None):
...         super().__init__(codec=codec)
...         self._data = {}
...
...     def to_uri(self):
...         return "dict://"
...
...     @classmethod
...     def from_uri(cls, uri, *, read_only=False, **kwargs):
...         return cls(**kwargs)
...
...     def _open(self):
...         pass
...
...     def _close(self):
...         pass
...
...     def _get_many(self, keys):
...         return {key: self._data[key] for key in keys if key in self._data}
...
...     def _put_many(self, items):
...         self._data.update(items)
...
...     def _update(self, keys, plan):
...         self._data.update(plan(self._get_many(keys)))
...
...     def _delete_many(self, keys):
...         for key in keys:
...             self._data.pop(key, None)
...
...     def _clear(self):
...         self._data.clear()
...
...     def _count(self):
...         return len(self._data)
...
...     def _iter_batches(self, batch_size):
...         keys = list(self._data)
...         for start in range(0, len(keys), batch_size):
...             if batch := self._get_many(keys[start : start + batch_size]):
...                 yield batch
>>> with DictStore() as store:
...     store.set("1", {"title": "Intro to Python", "views": 1})
...     store.set("1", {"views": 2}, on_conflict="merge")
...     print(store.filter(views=2))
{'1': {'title': 'Intro to Python', 'views': 2}}

```

- By default a backend is considered not thread-safe: the base holds one lock per instance around the
  primitives (for an iteration, while one batch is read), which makes `_update` above atomic against
  the other calls on the same instance, and runs the async calls in one worker thread of the store.
  Data shared with other instances or processes needs a transaction of the backend in `_update`. A
  thread-safe backend sets the class attribute `_thread_safe = True`: no lock is taken, and the async
  calls use the default executor.
- Each data primitive has an async twin (`_aget_many`, `_aput_many`, `_aupdate`,
  `_aiter_key_batches`, ...) which runs the sync one in a thread. A backend with a native async
  driver replaces the twins, and releases the resources that only they use in `_aclose()`. If `close`
  cannot release them, `_check_close()` raises while they are open, and the class attribute
  `_close_in_event_loop = True` makes `aclose` call `close` in the event loop instead of a thread.
  `persista.store.loop_clients.LoopClients` keeps one async client per event loop, as `RedisStore` and
  `PostgresStore` do.

## Store URIs

Every store implements `to_uri()`, which returns a URI identifying where its data lives, and the
matching `from_uri(uri, *, read_only=False, **kwargs)` class method, which reconstructs a store of
the same class from that URI. The new store is not open.

```pycon
>>> from persista.store import SQLiteStore
>>> with SQLiteStore("tmp/data.sqlite") as store:
...     uri = store.to_uri()
>>> with SQLiteStore.from_uri(uri, timeout=10) as reloaded:
...     pass

```

### Limitations of the URIs

A URI says **where the data is**, not how the store was configured.

| Limitation                   | Detail                                                                                                                                                                         |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Constructor options are lost | `table`, `namespace`, `map_size` and the arguments of the drivers are not in the URI. `Class.from_uri(uri, **kwargs)` passes them again.                                       |
| Codec of the server stores   | The scheme carries the codec of the local stores. `redis://` and `postgresql://` URIs do not: pass `codec=`.                                                                   |
| Dispatch builds the default  | `store_from_uri` uses the class registered for the scheme with its default options. For other options, call `Class.from_uri`.                                                  |
| In-memory data               | `memory://`, `null://` and the `:memory:` databases give a new, empty store. `InMemoryStore` is built with the `JsonCodec`, and a `:memory:` database cannot be read-only.     |
| `read_only`                  | Honored by SQLite, DuckDB and LMDB; ignored by the others.                                                                                                                     |
| Credentials                  | The URI of a server store contains the password. Treat it as a secret.                                                                                                         |
| Machine-specific paths       | A local path is made absolute, so the URI is valid on a machine with the same files. A SQLite `file:` URI is kept as it was given, so a relative one depends on the directory. |

The scheme carries the codec of the local stores:

| Store         | `JsonCodec` | `PickleCodec`   |
| ------------- | ----------- | --------------- |
| `FileStore`   | `file+json` | `file+pickle`   |
| `SQLiteStore` | `sqlite`    | `sqlite+pickle` |
| `DuckDBStore` | `duckdb`    | `duckdb+pickle` |
| `LmdbStore`   | `lmdb`      | `lmdb+pickle`   |

The other schemes are `memory`, `null`, `postgresql`, `postgres`, `redis`, `rediss` and `unix` (a
Redis server on a Unix socket).

```pycon
>>> from persista.store import PickleCodec, SQLiteStore
>>> uri = SQLiteStore(":memory:", codec=PickleCodec()).to_uri()
>>> uri
'sqlite+pickle:%3Amemory%3A'
>>> SQLiteStore.from_uri(uri, timeout=10).closed
True

```

### Opening a Store from Any URI

If you don't know the concrete store class ahead of time, `store_from_uri` dispatches on the
URI's scheme to the right class, and returns an **open** store:

```pycon
>>> from persista.store import FileStore, store_from_uri
>>> with FileStore("data") as store:
...     store.set("1", {"title": "Intro to Python"})
...     uri = store.to_uri()
>>> with store_from_uri(uri) as reloaded:
...     print(isinstance(reloaded, FileStore))
...     print(reloaded.get("1"))
True
{'title': 'Intro to Python'}

```

`store_from_uri` builds a store with its default options: for a `redis://` URL, a `RedisStore` with
the `JsonCodec` and the `persista` namespace. For other options, call the `from_uri` method of the
class, for example `RedisStore.from_uri(uri, codec=PickleCodec(), namespace="documents")`.

Use `register_scheme` to register a custom store class (or override a built-in one) under a
given scheme (its case is ignored):

```python
from persista.store import register_scheme, store_from_uri
from my_project.stores import MyCustomStore

register_scheme("mycustom", MyCustomStore)
with store_from_uri("mycustom://...") as store:
    ...
```

## Building a Store from a Configuration

`persista` has no factory classes. To choose a store in a configuration file, describe it with a
`dict` and build it with `resolve_object` from
[`coola.factory`](https://github.com/durandtibo/coola) (`coola` is a dependency of `persista`).
The `_target_` key is the fully qualified name of the class, and the other keys are the arguments of
its constructor:

```pycon
>>> from coola.factory import resolve_object
>>> from persista.store import BaseStore
>>> config = {"_target_": "persista.store.SQLiteStore", "database": ":memory:"}
>>> with resolve_object(config, cls=BaseStore) as store:
...     store.set("1", {"title": "Intro to Python"})
...     print(type(store).__name__)
...     print(store.get("1"))
SQLiteStore
{'title': 'Intro to Python'}

```

- Each call with a `dict` builds a new store. An object that is already an instance of `cls` is
  returned as it is, so a function can accept either a store or its configuration.
- `resolve_object` raises `TypeError` if the `dict` has no `_target_` key, or if the result is not an
  instance of `cls`. Like the constructor, it does not open the store.
- Only the outer `dict` is built: a configuration nested in one of its values is passed to the
  constructor as a plain `dict`. Build the inner object first, as shown for
  [a cache](cache.md#building-a-cache-from-a-configuration) and
  [a record store](record.md#building-a-record-store-from-a-configuration).

:warning: `resolve_object` imports and calls whatever `_target_` names, so a configuration can run
arbitrary code. Only use it with a configuration from a trusted source.

## Choosing a Store

| Store           | Backend                    | Persisted | Pickle values | Async               |
| --------------- | -------------------------- | --------- | ------------- | ------------------- |
| `InMemoryStore` | Python `dict`              | No        | Yes (codec)   | Yes (worker thread) |
| `FileStore`     | One file per value         | Yes       | Yes (codec)   | Yes (worker thread) |
| `SQLiteStore`   | SQLite                     | Yes       | Yes (codec)   | Yes (worker thread) |
| `DuckDBStore`   | DuckDB                     | Yes       | Yes (codec)   | Yes (worker thread) |
| `LmdbStore`     | LMDB                       | Yes       | Yes (codec)   | Yes (worker thread) |
| `RedisStore`    | Redis                      | Yes       | Yes (codec)   | Yes                 |
| `PostgresStore` | PostgreSQL                 | Yes       | Yes (codec)   | Yes                 |
| `NullStore`     | None (discards everything) | No        | N/A           | Yes                 |

Use `InMemoryStore` for tests and prototyping, `FileStore` for values that you want to read as files,
`SQLiteStore`/`DuckDBStore`/`LmdbStore` for local persistence without a server (SQLite can be shared
by several processes, DuckDB allows one writing process), and `RedisStore`/`PostgresStore` when data
needs to be shared across processes or machines. `NullStore` never actually stores anything -- every
`get`/`aget` is a miss -- which is useful for plugging into `Cache` to disable caching entirely
without changing any calling code. It uses `JsonCodec`, so the cached values must be representable
in JSON.

## API Reference

See the [reference documentation](../refs/store.md) for the full API.
