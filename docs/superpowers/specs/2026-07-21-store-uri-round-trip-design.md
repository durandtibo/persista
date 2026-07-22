# Store URI round-trip (`to_uri` / `from_uri`)

## Goal

Every store in `persista.store` gets two new methods:

- `to_uri(self) -> str` — returns a URI that identifies where the store's
  data lives.
- `from_uri(cls, uri: str, *, read_only: bool = False) -> Self` (classmethod)
  — reconstructs a store from that URI. `read_only` is accepted on every
  class for a uniform signature, but only has an effect on the stores that
  have a native read-only connection mode: `SQLiteStore` (and its `Typed`/
  `Pickle`/async variants), `DuckDBStore`/`TypedDuckDBStore`, and
  `LmdbStore`/`PickleLmdbStore`. Everywhere else (file stores, Postgres,
  Redis, in-memory, null) it's silently ignored — those backends have no
  local notion of a read-only connection.

For stores that persist to a file/directory/database, `store.from_uri(store.to_uri())`
must reconnect to the *same* data (round trip). For the process-local stores
(`InMemoryStore`, `NullStore`, and their async equivalents), `from_uri` returns a
fresh, empty instance — mirroring how re-entering their context manager already
resets them.

Out of scope (explicitly decided during brainstorming):

- Preserving `value_schema` (`TypedSQLiteStore`, `TypedDuckDBStore`,
  `TypedPostgresStore`) or `table` (`PostgresStore` family) in the URI.
  `from_uri` on these always reconstructs with the default schema/table.
- Preserving any other constructor kwargs (`sqlite3.connect` timeout,
  DuckDB `read_only`, LMDB `map_size`, psycopg/redis connection options,
  `iden.io` save/load kwargs). Only the essential connection target is
  round-tripped.

## URI scheme per class

| Class | scheme | example |
|---|---|---|
| `InMemoryStore` / `AsyncInMemoryStore` | `memory` | `memory://` |
| `NullStore` / `AsyncNullStore` | `null` | `null://` |
| `JsonFileStore` | `file+json` | `file+json:///abs/path/to/dir` |
| `PickleFileStore` | `file+pickle` | `file+pickle:///abs/path/to/dir` |
| `SQLiteStore` / `AsyncSQLiteStore` | `sqlite` | `sqlite:///abs/path/to.db` |
| `PickleSQLiteStore` | `sqlite+pickle` | `sqlite+pickle:///abs/path/to.db` |
| `TypedSQLiteStore` / `AsyncTypedSQLiteStore` | `sqlite+typed` | `sqlite+typed:///abs/path/to.db` |
| `DuckDBStore` | `duckdb` | `duckdb:///abs/path/to.duckdb` |
| `TypedDuckDBStore` | `duckdb+typed` | `duckdb+typed:///abs/path/to.duckdb` |
| `LmdbStore` | `lmdb` | `lmdb:///abs/path/to/dir` |
| `PickleLmdbStore` | `lmdb+pickle` | `lmdb+pickle:///abs/path/to/dir` |
| `PostgresStore` / `AsyncPostgresStore` | native (`postgresql`/`postgres`) | `postgresql://user:pass@host/db` |
| `TypedPostgresStore` / `AsyncTypedPostgresStore` | native, same as above | `postgresql://user:pass@host/db` |
| `RedisStore` / `AsyncRedisStore` | native (`redis`/`rediss`) | `redis://localhost:6379/0` |
| `PickleRedisStore` / `AsyncPickleRedisStore` | native, same as above | `redis://localhost:6379/0` |

For SQLite/DuckDB/LMDB/file stores, the special in-memory sentinel `":memory:"`
(SQLite/DuckDB) is encoded like any other path value (percent-encoded) and
decodes back to the literal string `":memory:"` — reconnecting to `:memory:`
never round-trips data (each connection is a fresh empty database), which
matches today's behavior and is not a regression.

## Implementation shape

### `persista/store/uri.py` (new)

Two small helpers used by the path-based families:

```python
def encode_path_uri(scheme: str, path: str) -> str:
    """scheme + a percent-encoded path/identifier, no netloc."""


def decode_path_uri(uri: str, *, expected_scheme: str) -> str:
    """Validate the scheme, return the decoded path/identifier."""
```

Implemented with `urllib.parse.urlsplit`/`urlunsplit`/`quote`/`unquote`, not
tied to filesystem semantics — they just need to be inverses of each other.

### `BaseStore` / `AsyncBaseStore` (`base.py`)

Add two new abstract members mirrored on both classes:

```python
@abstractmethod
def to_uri(self) -> str: ...


@classmethod
@abstractmethod
def from_uri(cls, uri: str, *, read_only: bool = False) -> Self: ...
```

### Family base classes (shared implementation)

- `BaseFileStore`: add a class attribute `scheme: str` (abstract property,
  alongside the existing `extension`), implement
  `to_uri` → `encode_path_uri(self.scheme, str(self._path))` and `from_uri`
  → `cls(decode_path_uri(uri, expected_scheme=cls.scheme))`. `read_only` is
  accepted but ignored — no native read-only mode.
- `BaseSQLiteStore`: same encode/decode pattern keyed off `self._database`,
  but `from_uri` delegates to the existing `from_path` machinery so
  `read_only=True` reuses the `file:...?mode=ro` URI trick already used by
  `from_path` (the decoded path is passed straight to
  `cls.from_path(path, read_only=read_only)` instead of `cls(path)`).
- `BaseDuckDBStore`: same encode/decode pattern keyed off `self._path`;
  `from_uri` passes `read_only=read_only` straight through to `cls(path,
  read_only=read_only)` (DuckDB's own constructor kwarg).
- `BaseLmdbStore`: same encode/decode pattern keyed off `self._path`;
  `from_uri` passes `readonly=read_only` to `cls(path, readonly=read_only)`
  (`lmdb.open`'s kwarg is spelled `readonly`, no underscore).
- `BasePostgresStore`: `to_uri` → `self._conninfo`; `from_uri` → `cls(uri)`.
  `read_only` accepted but ignored (no local read-only connection mode;
  read-only enforcement there is a matter of the DB role/user in `conninfo`).
- `BaseRedisStore`: `to_uri` → `self._url`; `from_uri` → `cls(uri)`.
  `read_only` accepted but ignored, same reasoning as Postgres.

Leaf classes just set the `scheme`/equivalent class attribute:
`JsonFileStore.scheme = "file+json"`, `PickleFileStore.scheme = "file+pickle"`,
`SQLiteStore._scheme = "sqlite"`, `PickleSQLiteStore._scheme = "sqlite+pickle"`,
`TypedSQLiteStore._scheme = "sqlite+typed"`, and so on for DuckDB/LMDB. No
override needed for Postgres/Redis leaves (base already does the right thing
using `cls`, which naturally becomes the leaf class through inheritance).

### `InMemoryStore` / `NullStore` (+ async)

```python
def to_uri(self) -> str:
    return "memory://"  # or "null://"


@classmethod
def from_uri(cls, uri: str, *, read_only: bool = False) -> Self:
    return cls()
```

`read_only` is accepted but ignored. No validation beyond accepting the
call; nothing meaningful to decode.

### `persista/store/registry.py` (new)

```python
_SYNC_SCHEMES: dict[str, type[BaseStore]] = {...}
_ASYNC_SCHEMES: dict[str, type[AsyncBaseStore]] = {...}


def store_from_uri(uri: str, *, read_only: bool = False) -> BaseStore: ...
def async_store_from_uri(uri: str, *, read_only: bool = False) -> AsyncBaseStore: ...
```

Each looks up `urlsplit(uri).scheme` in its table and calls `.from_uri(uri)`
on the matched class, raising `ValueError` for an unregistered scheme.
`TypedPostgresStore`, `TypedDuckDBStore`, `TypedSQLiteStore`'s scheme differs
from their base counterpart so they *are* registrable there (`sqlite+typed`,
`duckdb+typed`). `TypedPostgresStore` and `PickleRedisStore` share their
scheme with their base class (since Postgres/Redis reuse the native URL) and
are therefore **not** in the registry — only reachable via
`TypedPostgresStore.from_uri(uri)` / `PickleRedisStore.from_uri(uri)`
directly.

Exported from `persista/store/__init__.py` alongside everything else.

## Docstring caveat for typed stores

`TypedSQLiteStore.from_uri`, `TypedDuckDBStore.from_uri`,
`TypedPostgresStore.from_uri` get a one-line docstring note: the returned
store uses an empty `value_schema`, so value fields that were stored in typed
columns won't appear in `get`/`filter` results until the caller re-supplies
the original `value_schema` to a fresh construction. This is a known,
accepted limitation (data isn't lost in the database, just not visible
through this reconstructed store).

## Testing

- Round-trip test per file/db-backed store: create, write data, `to_uri()`,
  `from_uri()`, verify the reconstructed store sees the same data.
- `InMemoryStore`/`NullStore`: `from_uri` produces an empty store regardless
  of input.
- Registry: scheme dispatch for every registered class, plus `ValueError` on
  an unknown scheme.
- Typed stores: confirm `from_uri` round-trips connection target but not
  schema (documented behavior, not a bug).
- `read_only=True`: for SQLite/DuckDB/LMDB, verify the reconstructed store
  can `get`/`filter` existing data but raises/fails on `set`/`delete`/`clear`
  (whatever the underlying driver does for a read-only connection). For
  every other store, verify `read_only=True` is accepted without error and
  has no effect (writes still succeed).
