from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import pytest

from persista.store import PostgresStore, TypedPostgresStore
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
