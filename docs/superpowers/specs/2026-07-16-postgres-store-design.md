# PostgresStore design

## Goal

Add a Postgres-backed `BaseStore` implementation, following the existing SQL-store pattern
established by `persista/store/sqlite.py` (`BaseSQLiteStore` / `SQLiteStore` / `TypedSQLiteStore`).
The `psycopg` optional dependency and its availability-check helpers
(`persista/utils/imports/psycopg.py`) already exist in the repo but are currently unused by any
store.

## Scope

- `BasePostgresStore` — abstract base with the shared query/connection logic.
- `PostgresStore` — JSONB-only value storage (mirrors `SQLiteStore`).
- `TypedPostgresStore` — typed columns for known `value_schema` fields plus an `extra` JSONB
  overflow column (mirrors `TypedSQLiteStore`).

All three live in a new `src/persista/store/postgres.py`, exported from
`persista/store/__init__.py` alongside the other stores.

## Connection

```python
def __init__(self, conninfo: str, *, table: str = "store", **kwargs: Any) -> None:
```

- `conninfo` is required, no default — there is no in-memory Postgres equivalent to SQLite's
  `":memory:"`.
- `table` defaults to `"store"` but is configurable, since (unlike SQLite's one-file-per-store
  model) multiple Postgres stores commonly share one database and need distinct tables. Validated
  against the same identifier pattern as `validate_field_name` and always interpolated via
  `psycopg.sql.Identifier`, never raw string formatting.
- Calls `check_psycopg()` on init, then `psycopg.connect(conninfo, autocommit=True, **kwargs)` —
  a single plain connection per store instance, no pool (`psycopg_pool` is not added as a
  dependency). `autocommit=True` avoids needing explicit `.commit()` calls after every write,
  since psycopg defaults to `autocommit=False` unlike `sqlite3`.
- `close()` closes the connection and is idempotent, matching `BaseSQLiteStore.close`.
- No `from_path`-equivalent convenience constructor — there's no filesystem path concept for a
  Postgres connection.

## Schema

`PostgresStore`:

```sql
CREATE TABLE IF NOT EXISTS {table} (
    key   TEXT PRIMARY KEY,
    value JSONB NOT NULL
)
```

`TypedPostgresStore`: same typed-columns-plus-`extra` layout as `TypedSQLiteStore`, with `extra`
as `JSONB` instead of `JSON`.

## Query translation (vs. SQLite)

| SQLite | Postgres |
|---|---|
| `?` placeholder | `%s` placeholder |
| `json_extract(value, '$.field') = ?` | `value->>'field' = %s` |
| `INSERT OR REPLACE INTO store VALUES (...)` | `INSERT INTO {table} VALUES (...) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value` (typed variant sets every non-key column via `EXCLUDED`) |
| `key IN (?, ?, ?)` built from placeholders | `key = ANY(%s)` with a list parameter |

`set_many`'s non-`"overwrite"` conflict strategies (`"raise"`, `"skip"`, `"merge"`) reuse the same
`contains_many` + `get` pattern already implemented in `BaseSQLiteStore.set_many`.

## Testing

- **Unit tests** (`tests/unit/store/test_postgres.py`): logic that doesn't require a live
  database — SQL fragment builders, `value_schema` validation, `table` identifier validation —
  using mocks, following the shape of the existing unit test suites.
- **Integration tests** (`tests/integration/store/test_postgres.py`): a real Postgres via
  `testcontainers[postgres]` (new `dev` dependency group entry), exercising the full `BaseStore`
  contract, mirroring `tests/integration/store/test_redis.py`'s structure. Gated by the existing
  `psycopg_available` skip marker (`persista/testing/fixtures.py`) plus a Docker-availability
  check that skips gracefully when Docker isn't present, rather than erroring.

## Packaging

No changes to the `psycopg` optional-dependency group in `pyproject.toml` — `PostgresStore`
reuses it as-is. Add `testcontainers[postgres]` to the `dev` dependency group only.
