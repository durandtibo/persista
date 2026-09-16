# Code Review: `src/persista`

Scope: the full `persista` package (~14k lines across 89 modules) — key-value
stores (in-memory, file, sqlite, postgres, redis, lmdb, duckdb), the `Cache`
layer, the `record`/`record.store`/`record.analysis` subpackages, the HTTP
client wrapper, and shared utils. Cross-referenced against `tests/` (112 test
files) and `pyproject.toml` (ruff/pyright config).

## Summary

The codebase is unusually disciplined for its size: a single `BaseStore`
contract with sync/async twins on one instance, a `ThreadedAsyncStoreMixin`
that derives async-from-sync for drivers with no native async support, a
shared `async_close` helper to avoid re-deriving the "close a lazily-opened
async connection from sync `close()`" logic per backend, and a
`resolve_conflicts`/`aresolve_conflicts` helper shared by every backend's
`set_many`. Validation (`validate_field_name`, `validate_table_name`,
`validate_column_type`) is centralized and consistently used to guard
against SQL injection via user-supplied field/table names. Test coverage is
broad (112 test files for 89 source files). The findings below are mostly
about a few genuine API asymmetries and some duplication that could be
tightened, not correctness fires.

## API Consistency

1. **`BaseRecordStore` doesn't mirror `BaseStore` as closely as its
   docstring claims** (`src/persista/record/store/base.py:20-22` vs.
   `src/persista/store/base.py`). `BaseStore` exposes `on_conflict` on
   `set`/`set_many` (raise/skip/overwrite/merge), a streaming
   `set_batches`/`aset_batches`, and `to_uri`/`from_uri` for
   reconnect-by-URI. `BaseRecordStore.set_many` has no `on_conflict`
   parameter (upsert only, per its docstring at line 43), and there's no
   record-store equivalent of `set_batches` or `to_uri`/`from_uri`. If the
   record-store layer is meant to be a thin wrapper with the same
   semantics as the key-value layer (as the docstring says), callers who
   need "raise on existing id" or streaming ingestion have no way to get it
   here even though the underlying `BaseStore` supports it. Recommend
   either explicitly documenting record stores as upsert-only-by-design (and
   dropping the "mirrors" language), or adding the missing surface.

2. **`RecordStore.filter`/`afilter` always full-scan, even for
   `Typed*RecordStore` variants with real SQL columns**
   (`src/persista/record/store/record.py:99-129`). The docstring is honest
   about this, which is good, but it means the typed backends' main
   selling point (indexable columns) is invisible at the record-store
   layer — `RecordStore.filter` never delegates to `store.filter()`
   (which for `TypedPostgresStore`/`TypedSQLiteStore` *does* push schema
   fields into a `WHERE` clause) and instead re-implements filtering by
   iterating batches in Python. Worth at least offering a fast path that
   calls `self._store.filter(**metadata_filters)` when the underlying
   store supports pushdown, falling back to the scan otherwise.

3. **Postgres advisory-lock conflict handling has no counterpart in
   SQLite/DuckDB/LMDB** (`src/persista/store/postgres.py:272-298`). This
   is very likely intentional (Postgres is the only backend here with
   genuine concurrent multi-process writers), but it's not called out
   anywhere as a documented distinction between backends — a caller who
   picks `"raise"`/`"merge"` for correctness under concurrent writers on,
   say, `SQLiteStore`, gets no equivalent protection and no warning. A one-line
   note in `BaseStore.set_many`'s docstring ("only Postgres guarantees
   atomicity of non-overwrite conflict resolution under concurrent
   writers") would prevent a false sense of safety.

## Duplication / Simplification

4. **FIXED** -- **`_lock_keys`/`_alock_keys` and the `set_many`/`aset_many` conflict
   dispatch in `postgres.py` are near-identical sync/async pairs**
   (`src/persista/store/postgres.py:262-324`), as are the `get`/`aget`,
   `get_many`/`aget_many`, `filter`/`afilter`, `contains`/`acontains`,
   etc. pairs throughout the file (each pair differs only in `await`/`async
   with`). This mirrors the same pattern in `sqlite.py`/`duckdb.py`. Given
   there's no sync/async-agnostic codegen in play, this is probably an
   accepted cost of the "one class, sync+async twins" design rather than
   an oversight — but if the pattern keeps growing, a small internal code
   generator (docstring-driven, run at test/lint time to check the two stay
   in sync) would catch drift more cheaply than review alone.

5. **FIXED** -- **`ThreadedAsyncStoreMixin.akeys`/`aiter_batches`
   (`src/persista/store/threaded.py:532-548`) duplicate the "sentinel +
   `next()` in a thread" bridging pattern almost verbatim.** Both could
   share one generic helper, e.g. `_athread_iter(sync_iter_factory)`, cutting
   ~10 lines of duplication and one future opportunity to fix the same bug
   in only one place.

6. **`BasePostgresStore.get`/`get_many`/`filter`/`contains`/`contains_many`/
   `keys` and their async twins all repeat `sql.SQL(...).format(table=...,
   key_col=...)` for the same "SELECT ... FROM {table} WHERE {key_col} =
   ..." shape** (`postgres.py:208-466`). A couple of small query-builder
   helpers (`_select_by_key(cols, where)`) would remove a lot of repeated
   `sql.Identifier(self._key_column)` boilerplate without hurting
   readability, and reduce the risk of one variant silently drifting from
   the others when someone touches only the sync or only the async path.

## Testing

7. **No test appears to exercise the Postgres advisory-lock concurrency
   path under actual concurrent writers.** `resolve_conflicts` itself
   is presumably covered directly, but the specific correctness claim in
   `postgres.py:272-278` ("a concurrent set/set_many on any of the same
   keys blocks until this one commits") is the kind of property that's easy
   to silently break in a refactor and hard to catch without a
   dedicated integration test that spins up two overlapping `set_many`
   calls concurrently and asserts one blocks/serializes rather than
   corrupting data. Worth a targeted integration test given
   `testcontainers[postgres]` is already a dev dependency.

8. **`RecordStore.filter`'s full-scan behavior for typed backends
   (finding 2) has no test asserting the current (documented) behavior**,
   i.e. that filtering via `RecordStore` on a `TypedPostgresStore`/
   `TypedSQLiteStore`-backed instance does *not* use the typed columns.
   Adding one now would make it a deliberate, pinned behavior rather than
   something that could silently start doing pushdown (or vice versa)
   without anyone noticing.

## Minor / Nits

9. `BasePostgresStore._get_repr_kwargs` calls `self.count()` on every
   `repr()` call when the store is open (`src/persista/store/postgres.py:522-526`),
   which issues a live `SELECT COUNT(*)` query purely for display purposes.
   For a large table this makes something as innocuous as logging or
   debugging a store instance (e.g. via an f-string in a log line) an
   O(n) database round trip. Consider making this opt-in or cheaper
   (e.g. reflect `pg_class.reltuples` for an approximate count) — worth
   checking whether `SQLiteStore`/`DuckDBStore` have the same pattern
   before fixing just Postgres.

10. `Cache.memoize`/`amemoize` key by `func.__qualname__` only (not
    `__module__`), so two functions with the same qualified name defined
    in different modules collide on cache keys
    (`src/persista/cache/cache.py:1061-1067`, `1153-1161`). This is
    called out as intentional for closures from the same factory, but two
    *unrelated* functions that happen to share a qualname across modules
    (e.g. `pkg_a.foo` and `pkg_b.foo` both named top-level `foo`) would
    silently share cache entries too. Including `__module__` in the key
    would remove this narrower, almost certainly unintended collision
    case while keeping the documented same-factory-closure sharing
    behavior (which is keyed on qualname within the same module anyway).
