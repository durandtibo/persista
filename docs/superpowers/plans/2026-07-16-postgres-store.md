# PostgresStore Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Postgres-backed `BaseStore` implementation (`PostgresStore` + `TypedPostgresStore`), mirroring the existing `sqlite.py` pattern, backed by `psycopg` and tested against a real Postgres via `testcontainers`.

**Architecture:** `BasePostgresStore(BaseStore, MultilineDisplayMixin)` holds one `psycopg.Connection` (autocommit mode) plus a validated table identifier, and implements every `BaseStore` method in terms of four abstract hooks (`_create_table_sql`, `_row_to_value`, `_build_filter_condition`, `_set_many`) — exactly the split `BaseSQLiteStore` uses. `PostgresStore` stores values in one `JSONB` column; `TypedPostgresStore` stores known `value_schema` fields as typed columns plus an `extra JSONB` overflow column.

**Tech Stack:** `psycopg` (already an optional dependency, `persista.utils.imports.psycopg` has the availability guard), `testcontainers[postgres]` (new `dev` dependency, spins up a real Postgres for integration tests).

## Global Constraints

- Optional dependency group stays named `psycopg` in `pyproject.toml` — do not rename or add a `postgres` extra.
- `table` (and, for `TypedPostgresStore`, every `value_schema` column name) must be interpolated into SQL only via `psycopg.sql.Identifier`, never raw string formatting — table name is validated with the same identifier pattern as `validate_field_name`.
- Single plain `psycopg.Connection` per store instance, `autocommit=True`, no connection pool.
- No `from_path`-style convenience constructor — `conninfo` is a required argument with no default.
- Integration tests must skip gracefully (not error) when Docker is unavailable.

---

### Task 1: Add `testcontainers[postgres]` dev dependency and a container-backed test fixture

**Files:**
- Modify: `pyproject.toml` (`[dependency-groups].dev`)
- Create: `tests/integration/store/test_postgres.py`

**Interfaces:**
- Produces: a session-scoped pytest fixture `postgres_container` (in `tests/integration/store/test_postgres.py`) yielding a started `testcontainers.postgres.PostgresContainer`, skipped if Docker is unavailable. A `conninfo(postgres_container) -> str` fixture builds a psycopg-compatible connection string from it. Later tasks depend on both fixture names.

- [ ] **Step 1: Add the dependency**

Edit `pyproject.toml`, in the `dev` group of `[dependency-groups]` (alongside `"fakeredis >=2.36,<3.0"`):

```toml
    "fakeredis >=2.36,<3.0",
    "testcontainers[postgres] >=4.9,<5.0",
```

- [ ] **Step 2: Sync dependencies**

Run: `uv sync`
Expected: installs `testcontainers` and its `postgres` extra without error.

- [ ] **Step 3: Write the container fixtures**

Create `tests/integration/store/test_postgres.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from persista.testing.fixtures import psycopg_available
from persista.utils.imports import is_psycopg_available

if TYPE_CHECKING:
    from collections.abc import Generator

if is_psycopg_available():
    from testcontainers.postgres import PostgresContainer

try:
    from docker.errors import DockerException
except ImportError:  # pragma: no cover
    DockerException = Exception  # type: ignore[assignment,misc]


def _docker_available() -> bool:
    if not is_psycopg_available():
        return False
    try:
        container = PostgresContainer("postgres:16-alpine")
        container.start()
    except DockerException:
        return False
    container.stop()
    return True


docker_available = pytest.mark.skipif(not _docker_available(), reason="Requires Docker")


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture(scope="session")
def conninfo(postgres_container: PostgresContainer) -> str:
    return (
        f"postgresql://{postgres_container.username}:{postgres_container.password}"
        f"@{postgres_container.get_container_host_ip()}"
        f":{postgres_container.get_exposed_port(5432)}"
        f"/{postgres_container.dbname}"
    )


@psycopg_available
@docker_available
def test_conninfo_connects(conninfo: str) -> None:
    import psycopg

    with psycopg.connect(conninfo) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone() == (1,)
```

`_docker_available()` runs once at import/collection time: it is intentionally cheap-but-real (starts and immediately stops a throwaway container) so every test in the module skips cleanly instead of erroring when Docker isn't present, matching the existing `psycopg_available`/`redis_server_available` skip-marker pattern in this test suite.

- [ ] **Step 4: Run the smoke test**

Run: `uv run pytest tests/integration/store/test_postgres.py -v`
Expected: `test_conninfo_connects` PASSES if Docker is running locally, or the whole module SKIPS with "Requires Docker" if it isn't. Either outcome is acceptable — do not proceed until you've seen one of these two outcomes (not an error/traceback).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock tests/integration/store/test_postgres.py
git commit -m "test: add testcontainers-backed Postgres fixture for integration tests"
```

---

### Task 2: Add `validate_table_name` and reuse it for identifier validation

**Files:**
- Modify: `src/persista/store/validation.py`
- Test: `tests/unit/store/test_validation.py`

**Interfaces:**
- Produces: `validate_table_name(name: str) -> None` in `persista.store.validation`, raising `ValueError` on an invalid identifier. Task 3 calls this from `BasePostgresStore.__init__`.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/store/test_validation.py` (create the file if it doesn't exist yet, following the existing test-file header style: `from __future__ import annotations`, `import pytest`, imports from `persista.store.validation`):

```python
from persista.store.validation import validate_table_name


def test_validate_table_name_accepts_valid_identifier() -> None:
    validate_table_name("store")
    validate_table_name("_my_table_2")


def test_validate_table_name_rejects_invalid_identifier() -> None:
    with pytest.raises(ValueError, match=r"Invalid table name"):
        validate_table_name("store; DROP TABLE store;--")


def test_validate_table_name_rejects_leading_digit() -> None:
    with pytest.raises(ValueError, match=r"Invalid table name"):
        validate_table_name("2store")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/store/test_validation.py -v`
Expected: FAIL with `ImportError: cannot import name 'validate_table_name'`

- [ ] **Step 3: Implement `validate_table_name`**

In `src/persista/store/validation.py`, add `"validate_table_name"` to `__all__` (alphabetically), and add the function after `validate_field_name`:

```python
def validate_table_name(name: str) -> None:
    """Validate that a value is safe to interpolate into SQL as a table
    name.

    Args:
        name: The table name to validate.

    Raises:
        ValueError: If ``name`` is not a valid identifier (letters,
            digits, underscores, not starting with a digit).
    """
    if not _FIELD_NAME_PATTERN.match(name):
        msg = f"Invalid table name: {name!r}. Table names must match {_FIELD_NAME_PATTERN.pattern!r}"
        raise ValueError(msg)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/store/test_validation.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/persista/store/validation.py tests/unit/store/test_validation.py
git commit -m "feat: add validate_table_name for safe SQL identifier interpolation"
```

---

### Task 3: Implement `BasePostgresStore` and `PostgresStore` (JSONB-only variant)

**Files:**
- Create: `src/persista/store/postgres.py`
- Modify: `src/persista/store/__init__.py`
- Modify: `tests/integration/store/test_postgres.py`

**Interfaces:**
- Consumes: `check_psycopg`, `is_psycopg_available` from `persista.utils.imports` (same names `redis.py` uses for `redis`); `normalize_on_conflict`, `validate_batch_size`, `validate_field_name`, `validate_table_name` from `persista.store.validation`; `BaseStore` from `persista.store.base`; `OnConflict` from `persista.store.types`.
- Produces: `BasePostgresStore(conninfo: str, *, table: str = "store", **kwargs)` with abstract hooks `_create_table_sql() -> psycopg.sql.Composed`, `_row_to_value(row: tuple) -> dict`, `_build_filter_condition(key: str) -> psycopg.sql.Composable`, `_set_many(items: Mapping[str, dict]) -> None`; concrete `PostgresStore(conninfo, *, table="store", **kwargs)`. Task 4 subclasses `BasePostgresStore` the same way.

- [ ] **Step 1: Write the failing integration tests**

Append to `tests/integration/store/test_postgres.py` (after the Step-4 smoke test from Task 1, before nothing else exists yet):

```python
import uuid
from typing import Any

from persista.store import PostgresStore


@pytest.fixture
def table_name() -> str:
    return f"store_{uuid.uuid4().hex}"


@pytest.fixture
def store(conninfo: str, table_name: str) -> Generator[PostgresStore, None, None]:
    with PostgresStore(conninfo, table=table_name) as store:
        yield store


@pytest.fixture
def items() -> dict[str, dict[str, Any]]:
    return {
        "1": {"title": "Intro to Python", "author": "Alice", "category": "Programming"},
        "2": {"title": "Advanced Python", "author": "Alice", "category": "Programming"},
        "3": {"title": "History of Rome", "author": "Bob", "category": "History"},
    }


@psycopg_available
@docker_available
class TestPostgresStore:
    def test_init_creates_table(self, store: PostgresStore) -> None:
        assert store.count() == 0

    def test_set_and_get(self, store: PostgresStore) -> None:
        store.set("1", {"text": "hello"})
        assert store.get("1") == {"text": "hello"}

    def test_get_missing_key_returns_none(self, store: PostgresStore) -> None:
        assert store.get("missing") is None

    def test_get_many(self, store: PostgresStore, items: dict[str, dict[str, Any]]) -> None:
        store.set_many(items)
        result = store.get_many(["1", "3", "missing"])
        assert result == [items["1"], items["3"], None]

    def test_set_on_conflict_raise(self, store: PostgresStore) -> None:
        store.set("1", {"text": "original"})
        with pytest.raises(KeyError, match=r"1"):
            store.set("1", {"text": "updated"}, on_conflict="raise")
        assert store.get("1") == {"text": "original"}

    def test_set_on_conflict_skip(self, store: PostgresStore) -> None:
        store.set("1", {"text": "original"})
        store.set("1", {"text": "updated"}, on_conflict="skip")
        assert store.get("1") == {"text": "original"}

    def test_set_on_conflict_overwrite(self, store: PostgresStore) -> None:
        store.set("1", {"text": "original"})
        store.set("1", {"text": "updated"}, on_conflict="overwrite")
        assert store.get("1") == {"text": "updated"}

    def test_set_on_conflict_merge(self, store: PostgresStore) -> None:
        store.set("1", {"text": "original", "author": "Alice"})
        store.set("1", {"text": "updated"}, on_conflict="merge")
        assert store.get("1") == {"text": "updated", "author": "Alice"}

    def test_set_many_upserts(self, store: PostgresStore, items: dict[str, dict[str, Any]]) -> None:
        store.set_many(items)
        assert store.count() == 3
        store.set_many({"1": {"title": "Intro to Python, 2nd ed.", "author": "Alice"}})
        assert store.count() == 3
        assert store.get("1") == {"title": "Intro to Python, 2nd ed.", "author": "Alice"}

    def test_set_batches(self, store: PostgresStore, items: dict[str, dict[str, Any]]) -> None:
        store.set_batches(items.items(), batch_size=2)
        assert store.count() == 3

    def test_filter_no_args_returns_all(
        self, store: PostgresStore, items: dict[str, dict[str, Any]]
    ) -> None:
        store.set_many(items)
        assert len(store.filter()) == 3

    def test_filter_single_field(
        self, store: PostgresStore, items: dict[str, dict[str, Any]]
    ) -> None:
        store.set_many(items)
        assert len(store.filter(author="Alice")) == 2

    def test_filter_multiple_fields(
        self, store: PostgresStore, items: dict[str, dict[str, Any]]
    ) -> None:
        store.set_many(items)
        result = store.filter(author="Alice", category="Programming")
        assert len(result) == 2

    def test_filter_rejects_unsafe_field_name(self, store: PostgresStore) -> None:
        with pytest.raises(ValueError, match=r"Invalid filter field name"):
            store.filter(**{"bad; DROP TABLE store;--": "x"})

    def test_delete(self, store: PostgresStore) -> None:
        store.set("1", {"text": "hello"})
        store.delete("1")
        assert store.get("1") is None
        assert store.count() == 0

    def test_delete_missing_key_is_noop(self, store: PostgresStore) -> None:
        store.delete("missing")
        assert store.count() == 0

    def test_delete_many(self, store: PostgresStore, items: dict[str, dict[str, Any]]) -> None:
        store.set_many(items)
        store.delete_many(["1", "2"])
        assert store.count() == 1
        assert store.get("3") is not None

    def test_contains_many(self, store: PostgresStore, items: dict[str, dict[str, Any]]) -> None:
        store.set_many(items)
        found, missing = store.contains_many(["1", "3", "missing"])
        assert sorted(found) == ["1", "3"]
        assert missing == ["missing"]

    def test_keys(self, store: PostgresStore, items: dict[str, dict[str, Any]]) -> None:
        store.set_many(items)
        assert sorted(store.keys()) == ["1", "2", "3"]

    def test_values(self, store: PostgresStore, items: dict[str, dict[str, Any]]) -> None:
        store.set_many(items)
        assert sorted(store.values(), key=lambda v: v["title"]) == sorted(
            items.values(), key=lambda v: v["title"]
        )

    def test_iter_batches(self, store: PostgresStore, items: dict[str, dict[str, Any]]) -> None:
        store.set_many(items)
        batches = list(store.iter_batches(batch_size=2))
        assert sum(len(b) for b in batches) == 3
        assert all(len(b) <= 2 for b in batches)

    def test_count(self, store: PostgresStore, items: dict[str, dict[str, Any]]) -> None:
        assert store.count() == 0
        store.set_many(items)
        assert store.count() == 3

    def test_close_is_idempotent(self, store: PostgresStore) -> None:
        store.close()
        store.close()

    def test_repr(self, store: PostgresStore) -> None:
        assert repr(store).startswith("PostgresStore(")

    def test_two_stores_different_tables_are_isolated(self, conninfo: str, table_name: str) -> None:
        with (
            PostgresStore(conninfo, table=table_name) as store_a,
            PostgresStore(conninfo, table=f"{table_name}_other") as store_b,
        ):
            store_a.set("1", {"text": "a"})
            assert store_b.get("1") is None
            assert store_b.count() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/store/test_postgres.py -v`
Expected: FAIL with `ImportError: cannot import name 'PostgresStore' from 'persista.store'` (or module skip if Docker is unavailable — if so, temporarily run with Docker available to validate this task).

- [ ] **Step 3: Implement `BasePostgresStore` and `PostgresStore`**

Create `src/persista/store/postgres.py`:

```python
r"""Provide a Postgres-backed implementation of ``BaseStore``, storing
values as JSONB."""

from __future__ import annotations

__all__ = ["BasePostgresStore", "PostgresStore"]

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
    from collections.abc import Generator, Iterator, Mapping
    from typing import Self

    from persista.store.types import OnConflict

if is_psycopg_available():  # pragma: no cover
    import psycopg
    from psycopg import sql

logger: logging.Logger = logging.getLogger(__name__)


class BasePostgresStore(BaseStore, MultilineDisplayMixin):
    r"""Define a base class for Postgres-backed key-value stores.

    A single table (named by the ``table`` argument, ``"store"`` by
    default) backs every value; the primary key column is named by
    :attr:`_key_column`. :meth:`get`, :meth:`get_many`, :meth:`filter`,
    and :meth:`iter_batches` all query the full row and hand it to
    :meth:`_row_to_value` to turn it back into a value dict, which is
    what lets subclasses differ in how a value is laid out across
    columns (a single JSONB column vs. typed columns plus a JSONB
    overflow column) without duplicating any of the surrounding query
    logic. This mirrors :class:`~persista.store.sqlite.BaseSQLiteStore`.

    Subclasses only need to implement :meth:`_create_table_sql`,
    :meth:`_row_to_value`, :meth:`_build_filter_condition`, and
    :meth:`_set_many` (see :class:`PostgresStore` for a JSONB-only
    layout and :class:`~persista.store.postgres.TypedPostgresStore`
    for an optionally typed one).

    Args:
        conninfo: The connection string/DSN passed to
            ``psycopg.connect`` (e.g.
            ``"postgresql://user:pass@localhost/dbname"``).
        table: The name of the table backing this store. Must be a
            valid SQL identifier (letters, digits, underscores, not
            starting with a digit).
        **kwargs: Additional keyword arguments to pass to
            ``psycopg.connect``.
    """

    #: Name of the table's primary key column.
    _key_column: str = "key"

    def __init__(self, conninfo: str, *, table: str = "store", **kwargs: Any) -> None:
        check_psycopg()
        validate_table_name(table)
        self._conninfo = conninfo
        self._table = table
        self._kwargs = kwargs
        self._closed = False
        self._conn = psycopg.connect(conninfo, autocommit=True, **kwargs)
        self._conn.execute(self._create_table_sql())

    @property
    def _table_ident(self) -> sql.Identifier:
        return sql.Identifier(self._table)

    @abstractmethod
    def _create_table_sql(self) -> sql.Composed:
        """Return the ``CREATE TABLE IF NOT EXISTS`` statement for this
        store's schema."""

    @abstractmethod
    def _row_to_value(self, row: tuple[Any, ...]) -> dict[str, Any]:
        """Convert a raw ``SELECT * FROM {table}`` row back to a value
        dict."""

    @abstractmethod
    def _build_filter_condition(self, key: str) -> sql.Composable:
        """Build the SQL condition fragment (with a single ``%s``
        placeholder) that matches value field ``key`` against a bound
        parameter."""

    @abstractmethod
    def _set_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        """Write ``items`` to the table, replacing any existing row for
        the same key."""

    def close(self) -> None:
        if self._closed:
            return
        logger.info("Closing Postgres connection for table %s", self._table)
        self._conn.close()
        self._closed = True

    def get(self, key: str) -> dict[str, Any] | None:
        query = sql.SQL("SELECT * FROM {table} WHERE {key_col} = %s").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        with self._conn.cursor() as cur:
            cur.execute(query, (key,))
            row = cur.fetchone()
        return self._row_to_value(row) if row else None

    def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        if not keys:
            return []
        query = sql.SQL("SELECT * FROM {table} WHERE {key_col} = ANY(%s)").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        with self._conn.cursor() as cur:
            cur.execute(query, (keys,))
            rows = cur.fetchall()
        by_key = {row[0]: self._row_to_value(row) for row in rows}
        return [by_key.get(key) for key in keys]

    def set(self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite") -> None:
        self.set_many({key: value}, on_conflict=on_conflict)

    def set_many(
        self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
    ) -> None:
        if not items:
            return
        on_conflict = normalize_on_conflict(on_conflict)
        if on_conflict == "overwrite":
            self._set_many(items)
            return

        conflicts = set(self.contains_many(list(items))[0])
        if conflicts and on_conflict == "raise":
            msg = f"Key(s) already exist in the store: {sorted(conflicts)}"
            raise KeyError(msg)

        to_write: dict[str, dict[str, Any]] = {}
        for key, value in items.items():
            if key in conflicts:
                if on_conflict == "skip":
                    continue
                to_write[key] = {**(self.get(key) or {}), **value}
                continue
            to_write[key] = value

        self._set_many(to_write)

    def filter(self, **field_filters: Any) -> list[dict[str, Any]]:
        if not field_filters:
            query = sql.SQL("SELECT * FROM {table}").format(table=self._table_ident)
            with self._conn.cursor() as cur:
                cur.execute(query)
                rows = cur.fetchall()
            return [self._row_to_value(row) for row in rows]

        conditions = [self._build_filter_condition(key) for key in field_filters]
        where = sql.SQL(" AND ").join(conditions)
        query = sql.SQL("SELECT * FROM {table} WHERE {where}").format(
            table=self._table_ident, where=where
        )
        with self._conn.cursor() as cur:
            cur.execute(query, list(field_filters.values()))
            rows = cur.fetchall()
        return [self._row_to_value(row) for row in rows]

    def delete(self, key: str) -> None:
        query = sql.SQL("DELETE FROM {table} WHERE {key_col} = %s").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        self._conn.execute(query, (key,))

    def delete_many(self, keys: list[str]) -> None:
        if not keys:
            return
        query = sql.SQL("DELETE FROM {table} WHERE {key_col} = ANY(%s)").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        self._conn.execute(query, (keys,))

    def contains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        if not keys:
            return [], []
        query = sql.SQL("SELECT {key_col} FROM {table} WHERE {key_col} = ANY(%s)").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        with self._conn.cursor() as cur:
            cur.execute(query, (keys,))
            existing = {row[0] for row in cur.fetchall()}
        found = [key for key in keys if key in existing]
        missing = [key for key in keys if key not in existing]
        return found, missing

    def keys(self) -> Iterator[str]:
        query = sql.SQL("SELECT {key_col} FROM {table}").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        with self._conn.cursor() as cur:
            cur.execute(query)
            for (key,) in cur.fetchall():
                yield key

    def iter_batches(
        self, batch_size: int = 32
    ) -> Generator[dict[str, dict[str, Any]], None, None]:
        validate_batch_size(batch_size)
        query = sql.SQL("SELECT * FROM {table}").format(table=self._table_ident)
        with self._conn.cursor(name=f"iter_batches_{id(self)}") as cur:
            cur.itersize = batch_size
            cur.execute(query)
            for batch in batchify(cur, size=batch_size):
                yield {row[0]: self._row_to_value(row) for row in batch}

    def count(self) -> int:
        query = sql.SQL("SELECT COUNT(*) FROM {table}").format(table=self._table_ident)
        with self._conn.cursor() as cur:
            cur.execute(query)
            return cur.fetchone()[0]

    def _get_repr_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"table": self._table, "closed": self._closed}
        if not self._closed:
            kwargs["count"] = self.count()
        return kwargs | self._kwargs

    def __enter__(self) -> Self:
        return self


_CREATE_TABLE = sql.SQL(
    """
    CREATE TABLE IF NOT EXISTS {table} (
        key   TEXT PRIMARY KEY,
        value JSONB NOT NULL
    )
    """
)


class PostgresStore(BasePostgresStore):
    """A Postgres-backed key-value store.

    Persists values to a Postgres database and supports adding,
    retrieving, filtering, and deleting key-value pairs. Each value is
    stored as a JSONB column, which provides flexibility for arbitrary
    value fields without requiring a fixed schema.

    Args:
        conninfo: The connection string/DSN passed to
            ``psycopg.connect`` (e.g.
            ``"postgresql://user:pass@localhost/dbname"``).
        table: The name of the table backing this store.
        **kwargs: Additional keyword arguments to pass to
            ``psycopg.connect``.

    Example:
        ```pycon
        >>> from persista.store import PostgresStore
        >>> store = PostgresStore("postgresql://user:pass@localhost/dbname")  # doctest: +SKIP
        >>> store.set_many(  # doctest: +SKIP
        ...     {
        ...         "1": {"title": "Intro to Python", "author": "Alice"},
        ...         "2": {"title": "Advanced Python", "author": "Alice"},
        ...     }
        ... )
        >>> len(store.filter(author="Alice"))  # doctest: +SKIP
        2

        ```
    """

    def _create_table_sql(self) -> sql.Composed:
        return _CREATE_TABLE.format(table=self._table_ident)

    def _row_to_value(self, row: tuple[Any, ...]) -> dict[str, Any]:
        return row[1]

    def _build_filter_condition(self, key: str) -> sql.Composable:
        validate_field_name(key)
        return sql.SQL("value->>{field} = %s").format(field=sql.Literal(key))

    def _set_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            query = sql.SQL(
                "INSERT INTO {table} ({key_col}, value) VALUES (%s, %s) "
                "ON CONFLICT ({key_col}) DO UPDATE SET value = EXCLUDED.value"
            ).format(table=self._table_ident, key_col=sql.Identifier(self._key_column))
            with self._conn.cursor() as cur:
                cur.executemany(query, list(items.items()))

        logger.debug("Added/replaced %d key-value pair(s)", len(items))
```

Notes on choices made here vs. `sqlite.py`:
- `value->>{field}` uses `sql.Literal(key)` (not `sql.Identifier`) because the JSON key is a string literal argument to `->>`, not a SQL identifier — `validate_field_name` still gates which strings are allowed before that.
- `iter_batches` uses a *named* (server-side) cursor so results stream from Postgres in `itersize` chunks instead of being buffered client-side all at once, preserving the "avoid loading the whole store into memory" contract documented on `BaseStore.iter_batches`. `psycopg`'s JSONB columns are adapted directly to Python `dict`/`list`/etc., so `_row_to_value` for `PostgresStore` is just `row[1]` — no `json.loads` needed, unlike `sqlite.py`.
- There's no `__exit__`/context-manager re-open behavior to override: `BaseStore.__exit__` (which calls `close()`) is inherited as-is; only `__enter__` is redefined here (trivially, to satisfy the `Self` return type) since, unlike `BaseSQLiteStore`, a closed `BasePostgresStore` is not designed to be reopened — build a new instance instead.

- [ ] **Step 4: Export from `persista.store`**

In `src/persista/store/__init__.py`, add `"BasePostgresStore"` and `"PostgresStore"` to `__all__` (alphabetically — after `"BaseDuckDBStore"` and before `"BaseRedisStore"`, and after `"OnConflict"` and before `"PickleRedisStore"` respectively), and add the import:

```python
from persista.store.postgres import BasePostgresStore, PostgresStore
```

placed alphabetically after the `persista.store.in_memory` import and before `persista.store.redis`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/integration/store/test_postgres.py -v`
Expected: PASS (or module SKIP if Docker unavailable — if skipped, you must still validate this task by running with Docker available at least once before moving on).

- [ ] **Step 6: Run the full test suite to check for regressions**

Run: `uv run pytest tests/unit -v`
Expected: PASS, no regressions in unrelated stores.

- [ ] **Step 7: Commit**

```bash
git add src/persista/store/postgres.py src/persista/store/__init__.py tests/integration/store/test_postgres.py
git commit -m "feat: add PostgresStore, a Postgres-backed BaseStore implementation"
```

---

### Task 4: Implement `TypedPostgresStore`

**Files:**
- Modify: `src/persista/store/postgres.py`
- Modify: `src/persista/store/__init__.py`
- Modify: `tests/integration/store/test_postgres.py`

**Interfaces:**
- Consumes: `BasePostgresStore` from Task 3 (same abstract-hook contract).
- Produces: `TypedPostgresStore(conninfo: str, *, table: str = "store", value_schema: dict[str, str] | None = None, **kwargs)`, added to `BasePostgresStore.__all__` re-export.

- [ ] **Step 1: Write the failing integration tests**

Append to `tests/integration/store/test_postgres.py`:

```python
from persista.store import TypedPostgresStore


@pytest.fixture
def typed_store_no_schema(conninfo: str, table_name: str) -> Generator[TypedPostgresStore, None, None]:
    with TypedPostgresStore(conninfo, table=table_name) as store:
        yield store


@pytest.fixture
def typed_store(conninfo: str, table_name: str) -> Generator[TypedPostgresStore, None, None]:
    with TypedPostgresStore(
        conninfo,
        table=table_name,
        value_schema={"author": "TEXT", "year": "INTEGER", "category": "TEXT"},
    ) as store:
        yield store


@psycopg_available
@docker_available
class TestTypedPostgresStore:
    def test_no_schema_stores_everything_in_extra(self, typed_store_no_schema: TypedPostgresStore) -> None:
        typed_store_no_schema.set("1", {"title": "Intro to Python", "author": "Alice"})
        assert typed_store_no_schema.get("1") == {"title": "Intro to Python", "author": "Alice"}

    def test_schema_field_rejects_reserved_key_column(self, conninfo: str, table_name: str) -> None:
        with pytest.raises(ValueError, match=r"reserved key column name"):
            TypedPostgresStore(conninfo, table=table_name, value_schema={"_KEY_": "TEXT"})

    def test_known_fields_and_extra_round_trip(self, typed_store: TypedPostgresStore) -> None:
        value = {
            "title": "Intro to Python",
            "author": "Alice",
            "year": 2022,
            "category": "Programming",
        }
        typed_store.set("1", value)
        assert typed_store.get("1") == value

    def test_filter_on_typed_column(self, typed_store: TypedPostgresStore) -> None:
        typed_store.set_many(
            {
                "1": {"title": "Intro to Python", "author": "Alice", "year": 2022},
                "2": {"title": "History of Rome", "author": "Bob", "year": 2021},
            }
        )
        assert len(typed_store.filter(author="Alice")) == 1

    def test_filter_on_extra_field(self, typed_store: TypedPostgresStore) -> None:
        typed_store.set("1", {"title": "Intro to Python", "author": "Alice", "publisher": "OReilly"})
        assert len(typed_store.filter(publisher="OReilly")) == 1

    def test_set_on_conflict_merge_preserves_typed_and_extra_fields(
        self, typed_store: TypedPostgresStore
    ) -> None:
        typed_store.set("1", {"author": "Alice", "year": 2022, "publisher": "OReilly"})
        typed_store.set("1", {"year": 2023}, on_conflict="merge")
        assert typed_store.get("1") == {"author": "Alice", "year": 2023, "publisher": "OReilly"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/store/test_postgres.py -v -k TypedPostgresStore`
Expected: FAIL with `ImportError: cannot import name 'TypedPostgresStore'`.

- [ ] **Step 3: Implement `TypedPostgresStore`**

Append to `src/persista/store/postgres.py`, and update `__all__` at the top of the file to `__all__ = ["BasePostgresStore", "PostgresStore", "TypedPostgresStore"]`:

```python
_KEY_COLUMN = "_KEY_"


class TypedPostgresStore(BasePostgresStore):
    """A Postgres-backed key-value store with an optional typed value
    schema.

    Persists values to a Postgres database and supports adding,
    retrieving, and filtering by value fields. An optional
    ``value_schema`` maps known value field names to Postgres types.
    Known fields are stored as typed columns for fast, index-friendly
    queries. Any value fields not in the schema are stored in an
    ``extra`` JSONB overflow column, so nothing is lost. Mirrors
    :class:`~persista.store.sqlite.TypedSQLiteStore`.

    Args:
        conninfo: The connection string/DSN passed to
            ``psycopg.connect``.
        table: The name of the table backing this store.
        value_schema: Optional mapping of value field names to
            Postgres type strings (e.g. ``{"author": "TEXT", "year":
            "INTEGER"}``). Fields in the schema get native typed
            columns; all other value fields go into the ``extra``
            JSONB overflow column. Defaults to ``None``, which stores
            every value field as JSONB only.
        **kwargs: Additional keyword arguments to pass to
            ``psycopg.connect``.

    Example:
        ```pycon
        >>> from persista.store import TypedPostgresStore
        >>> schema = {"author": "TEXT", "year": "INTEGER"}
        >>> store = TypedPostgresStore(  # doctest: +SKIP
        ...     "postgresql://user:pass@localhost/dbname", value_schema=schema
        ... )
        >>> store.set_many(  # doctest: +SKIP
        ...     {
        ...         "1": {"title": "Intro to Python", "author": "Alice", "year": 2022},
        ...         "2": {"title": "History of Rome", "author": "Bob", "year": 2021},
        ...     }
        ... )
        >>> len(store.filter(author="Alice"))  # doctest: +SKIP
        1

        ```
    """

    _key_column = _KEY_COLUMN

    def __init__(
        self,
        conninfo: str,
        *,
        table: str = "store",
        value_schema: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        value_schema = value_schema or {}
        if _KEY_COLUMN in value_schema:
            msg = f"value_schema must not contain the reserved key column name {_KEY_COLUMN!r}"
            raise ValueError(msg)
        self._schema: dict[str, str] = value_schema
        super().__init__(conninfo, table=table, **kwargs)

    def _create_table_sql(self) -> sql.Composed:
        typed_cols = sql.SQL("").join(
            sql.SQL(", {col} {dtype}").format(col=sql.Identifier(name), dtype=sql.SQL(dtype))
            for name, dtype in self._schema.items()
        )
        return sql.SQL(
            "CREATE TABLE IF NOT EXISTS {table} ({key_col} TEXT PRIMARY KEY{typed_cols}, extra JSONB)"
        ).format(table=self._table_ident, key_col=sql.Identifier(_KEY_COLUMN), typed_cols=typed_cols)

    def _row_to_value(self, row: tuple[Any, ...]) -> dict[str, Any]:
        # row layout: key, [schema cols...], extra
        schema_vals = dict(zip(self._schema.keys(), row[1 : 1 + len(self._schema)], strict=True))
        extra = row[1 + len(self._schema)]
        value = {k: v for k, v in schema_vals.items() if v is not None}
        if extra:
            value.update(extra)
        return value

    def _build_filter_condition(self, key: str) -> sql.Composable:
        if key in self._schema:
            return sql.SQL("{col} = %s").format(col=sql.Identifier(key))
        validate_field_name(key)
        return sql.SQL("extra->>{field} = %s").format(field=sql.Literal(key))

    def _set_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            query = self._build_insert()
            with self._conn.cursor() as cur:
                cur.executemany(query, [self._value_to_row(key, value) for key, value in items.items()])

        logger.debug("Added/replaced %d key-value pair(s)", len(items))

    def _build_insert(self) -> sql.Composed:
        col_names = [_KEY_COLUMN, *self._schema.keys(), "extra"]
        columns = sql.SQL(", ").join(sql.Identifier(name) for name in col_names)
        placeholders = sql.SQL(", ").join(sql.Placeholder() * len(col_names))
        update_cols = sql.SQL(", ").join(
            sql.SQL("{col} = EXCLUDED.{col}").format(col=sql.Identifier(name))
            for name in [*self._schema.keys(), "extra"]
        )
        return sql.SQL(
            "INSERT INTO {table} ({columns}) VALUES ({placeholders}) "
            "ON CONFLICT ({key_col}) DO UPDATE SET {update_cols}"
        ).format(
            table=self._table_ident,
            columns=columns,
            placeholders=placeholders,
            key_col=sql.Identifier(_KEY_COLUMN),
            update_cols=update_cols,
        )

    def _value_to_row(self, key: str, value: dict[str, Any]) -> tuple[Any, ...]:
        known = [value.get(k) for k in self._schema]
        extra = {k: v for k, v in value.items() if k not in self._schema}
        return (key, *known, extra or None)
```

`sql.Placeholder() * len(col_names)` builds a tuple of `%s` placeholders (`psycopg.sql.Composable` supports `*` repetition, matching how `sql.SQL(", ").join(...)` is used elsewhere in this file).

- [ ] **Step 4: Export from `persista.store`**

In `src/persista/store/__init__.py`: add `"TypedPostgresStore"` to `__all__` (after `"TypedDuckDBStore"`, before `"TypedSQLiteStore"`), and update the postgres import line from Task 3 to:

```python
from persista.store.postgres import BasePostgresStore, PostgresStore, TypedPostgresStore
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/integration/store/test_postgres.py -v`
Expected: PASS (or module SKIP if Docker unavailable — validate with Docker available before moving on).

- [ ] **Step 6: Run the full test suite**

Run: `uv run pytest tests/unit -v`
Expected: PASS, no regressions.

- [ ] **Step 7: Commit**

```bash
git add src/persista/store/postgres.py src/persista/store/__init__.py tests/integration/store/test_postgres.py
git commit -m "feat: add TypedPostgresStore, a typed-column variant of PostgresStore"
```

---

### Task 5: Full-suite verification

**Files:** None (verification only).

- [ ] **Step 1: Run the complete unit test suite**

Run: `uv run pytest tests/unit -v`
Expected: PASS, zero failures.

- [ ] **Step 2: Run the complete integration test suite (requires Docker running)**

Run: `uv run pytest tests/integration -v`
Expected: PASS. Postgres-related tests SKIP only if Docker is genuinely unavailable in this environment — if so, note that in the task result rather than treating it as done.

- [ ] **Step 3: Run linting**

Run: `uv run ruff check src/persista/store/postgres.py src/persista/store/validation.py src/persista/store/__init__.py tests/integration/store/test_postgres.py tests/unit/store/test_validation.py`
Expected: No errors. Fix any that appear (e.g. import ordering, docstring convention) before proceeding.

- [ ] **Step 4: Run type checking**

Run: `uv run pyright src/persista/store/postgres.py`
Expected: No errors.

- [ ] **Step 5: Final commit if lint/type fixes were needed**

```bash
git add -A
git commit -m "fix: address lint/type issues in PostgresStore"
```

(Skip this step if Steps 3–4 required no changes.)
