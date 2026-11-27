from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

import pytest

from persista.store import JsonCodec, PickleCodec, SQLiteStore
from persista.store.plan import build_plan
from persista.store.sql import (
    SQLStore,
    build_where,
    check_sql_codec,
    check_table_layout,
    decode_sql_uri,
    encode_sql_uri,
    value_column_type,
)

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping
    from pathlib import Path

    from persista.store import Codec
    from persista.store.types import Payload

# SQLStore is abstract: its methods are tested through SQLiteStore, which
# needs no optional library.

PAYLOADS: dict[str, Payload] = {"1": '{"a": 1}', "2": '{"a": 2}', "3": '{"a": 3}'}

COLUMNS = [("key", "TEXT", True), ("value", "JSON", False)]


class OtherCodec(JsonCodec):
    r"""A codec with a name that no SQL column type matches."""

    name = "yaml"


class CustomJsonCodec(JsonCodec):
    r"""A custom codec that produces JSON."""


@pytest.fixture
def store() -> Generator[SQLiteStore, None, None]:
    with SQLiteStore() as store:
        yield store


@pytest.fixture
def filled_store(store: SQLiteStore) -> SQLiteStore:
    store._put_many(PAYLOADS)
    return store


@pytest.fixture
def pickle_store() -> Generator[SQLiteStore, None, None]:
    with SQLiteStore(codec=PickleCodec()) as store:
        store.set_many({"1": {"tags": {"a"}}, "2": {"tags": {"b"}}})
        yield store


def trace(store: SQLiteStore) -> list[str]:
    r"""Return the list where the statements of a store are recorded."""
    statements: list[str] = []
    store.connection.set_trace_callback(statements.append)
    return statements


#####################################
#     Tests for check_sql_codec     #
#####################################


@pytest.mark.parametrize("codec", [JsonCodec(), PickleCodec(), CustomJsonCodec()])
def test_check_sql_codec(codec: Codec) -> None:
    check_sql_codec(codec)


def test_check_sql_codec_unsupported_name() -> None:
    with pytest.raises(ValueError, match=r"A SQL store needs a codec named .*not 'yaml'"):
        check_sql_codec(OtherCodec())


#######################################
#     Tests for value_column_type     #
#######################################


@pytest.mark.parametrize(("codec", "expected"), [(JsonCodec(), "JSON"), (PickleCodec(), "BLOB")])
def test_value_column_type(codec: Codec, expected: str) -> None:
    assert value_column_type(codec) == expected


def test_value_column_type_unsupported_codec() -> None:
    with pytest.raises(ValueError, match=r"A SQL store needs a codec"):
        value_column_type(OtherCodec())


########################################
#     Tests for check_table_layout     #
########################################


@pytest.mark.parametrize(
    "columns",
    [
        pytest.param(COLUMNS, id="exact"),
        pytest.param(COLUMNS[::-1], id="other_order"),
        pytest.param([("KEY", "text", True), ("Value", "json", False)], id="other_case"),
    ],
)
def test_check_table_layout(columns: list[tuple[str, str, bool]]) -> None:
    check_table_layout(columns, codec=JsonCodec(), key_type="TEXT", database="db")


@pytest.mark.parametrize(
    "columns",
    [
        pytest.param([], id="no_column"),
        pytest.param([("key", "TEXT", True)], id="no_value"),
        pytest.param([*COLUMNS, ("extra", "JSON", False)], id="extra_column"),
        pytest.param([("id", "TEXT", True), ("value", "JSON", False)], id="other_key_name"),
        pytest.param([("key", "TEXT", True), ("extra", "JSON", False)], id="other_value_name"),
        pytest.param([("key", "TEXT", False), ("value", "JSON", False)], id="no_primary_key"),
        pytest.param([("key", "TEXT", True), ("value", "JSON", True)], id="composite_key"),
        pytest.param([("key", "INTEGER", True), ("value", "JSON", False)], id="key_type"),
        pytest.param([("key", "TEXT", True), ("value", "BLOB", False)], id="value_type"),
    ],
)
def test_check_table_layout_mismatch(columns: list[tuple[str, str, bool]]) -> None:
    with pytest.raises(ValueError, match=r"The table 'store' of 'db' does not match the codec"):
        check_table_layout(columns, codec=JsonCodec(), key_type="TEXT", database="db")


def test_check_table_layout_error_message() -> None:
    with pytest.raises(
        ValueError,
        match=r"expected the columns \(key TEXT PRIMARY KEY, value BLOB\), "
        r"found \(key TEXT PRIMARY KEY, value JSON\)",
    ):
        check_table_layout(COLUMNS, codec=PickleCodec(), key_type="TEXT", database="db")


def test_check_table_layout_does_not_modify_columns() -> None:
    columns = COLUMNS[::-1]
    check_table_layout(columns, codec=JsonCodec(), key_type="TEXT", database="db")
    assert columns == [("value", "JSON", False), ("key", "TEXT", True)]


#################################
#     Tests for build_where     #
#################################


def test_build_where() -> None:
    assert build_where({"a": 1, "b": None, "c": "x"}, str.upper) == (
        "A = ? AND B IS NULL AND C = ?",
        [1, "x"],
    )


def test_build_where_no_field() -> None:
    assert build_where({}, str.upper) == ("", [])


def test_build_where_expression_error() -> None:
    def expression(name: str) -> str:
        msg = f"bad field {name}"
        raise ValueError(msg)

    with pytest.raises(ValueError, match=r"bad field a"):
        build_where({"a": 1}, expression)


####################################
#     Tests for encode_sql_uri     #
####################################


@pytest.mark.parametrize(
    ("codec", "expected"),
    [(JsonCodec(), "sqlite:/data/a%20b.db"), (PickleCodec(), "sqlite+pickle:/data/a%20b.db")],
)
def test_encode_sql_uri(codec: Codec, expected: str) -> None:
    assert encode_sql_uri("sqlite", "/data/a b.db", codec) == expected


####################################
#     Tests for decode_sql_uri     #
####################################


@pytest.mark.parametrize(
    ("uri", "codec_type"),
    [("sqlite:/data/a%20b.db", JsonCodec), ("sqlite+pickle:/data/a%20b.db", PickleCodec)],
)
def test_decode_sql_uri(uri: str, codec_type: type) -> None:
    database, codec = decode_sql_uri(uri, scheme="sqlite")
    assert (database, type(codec)) == ("/data/a b.db", codec_type)


def test_decode_sql_uri_keeps_given_codec() -> None:
    codec = CustomJsonCodec()
    assert decode_sql_uri("sqlite:data.db", scheme="sqlite", codec=codec)[1] is codec


@pytest.mark.parametrize("uri", ["duckdb:data.db", "sqlite+typed:data.db", "data.db"])
def test_decode_sql_uri_other_scheme(uri: str) -> None:
    with pytest.raises(ValueError, match=r"Invalid scheme"):
        decode_sql_uri(uri, scheme="sqlite")


@pytest.mark.parametrize(
    ("uri", "codec"),
    [("sqlite:data.db", PickleCodec()), ("sqlite+pickle:data.db", JsonCodec())],
)
def test_decode_sql_uri_codec_mismatch(uri: str, codec: Codec) -> None:
    with pytest.raises(ValueError, match=r"does not match the scheme"):
        decode_sql_uri(uri, scheme="sqlite", codec=codec)


##############################
#     Tests for SQLStore     #
##############################


def test_sql_store_is_not_thread_safe() -> None:
    assert not SQLStore._thread_safe


def test_sql_store_default_codec() -> None:
    assert isinstance(SQLiteStore()._codec, JsonCodec)


def test_sql_store_unsupported_codec() -> None:
    with pytest.raises(ValueError, match=r"A SQL store needs a codec"):
        SQLiteStore(codec=OtherCodec())


# --- filter_items ---


def test_filter_items_no_field(filled_store: SQLiteStore) -> None:
    assert filled_store.filter_items() == {"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}}


def test_filter_items_field(filled_store: SQLiteStore) -> None:
    assert filled_store.filter_items(a=2) == {"2": {"a": 2}}


def test_filter_items_no_match(filled_store: SQLiteStore) -> None:
    assert filled_store.filter_items(a=4) == {}


def test_filter_items_empty_store(store: SQLiteStore) -> None:
    assert store.filter_items() == {}


def test_filter_items_pickle_codec(pickle_store: SQLiteStore) -> None:
    assert pickle_store.filter_items(tags={"b"}) == {"2": {"tags": {"b"}}}


def test_filter_items_pickle_codec_several_batches(pickle_store: SQLiteStore) -> None:
    pickle_store.set_many({str(i): {"even": i % 2 == 0} for i in range(600)})
    assert len(pickle_store.filter_items(even=True)) == 300


def test_filter_items_closed_store() -> None:
    with pytest.raises(RuntimeError, match=r"is not open"):
        SQLiteStore().filter_items()


async def test_afilter_items(filled_store: SQLiteStore) -> None:
    assert await filled_store.afilter_items(a=2) == {"2": {"a": 2}}


async def test_afilter_items_pickle_codec(pickle_store: SQLiteStore) -> None:
    assert await pickle_store.afilter_items(tags={"b"}) == {"2": {"tags": {"b"}}}


async def test_afilter_items_closed_store() -> None:
    with pytest.raises(RuntimeError, match=r"is not open"):
        await SQLiteStore().afilter_items()


# --- URI ---


def test_to_uri(tmp_path: Path) -> None:
    path = tmp_path / "data.sqlite"
    assert SQLiteStore(path).to_uri() == encode_sql_uri("sqlite", path.resolve(), JsonCodec())


def test_to_uri_pickle_codec() -> None:
    assert SQLiteStore(codec=PickleCodec()).to_uri() == "sqlite+pickle:%3Amemory%3A"


@pytest.mark.parametrize("codec", [JsonCodec(), PickleCodec()])
def test_from_uri_keeps_codec(codec: Codec) -> None:
    store = SQLiteStore.from_uri(SQLiteStore(codec=codec).to_uri())
    assert type(store._codec) is type(codec)


def test_from_uri_returns_closed_store() -> None:
    assert SQLiteStore.from_uri("sqlite::memory:").closed


def test_from_uri_passes_kwargs() -> None:
    assert SQLiteStore.from_uri("sqlite::memory:", timeout=1.0)._kwargs == {"timeout": 1.0}


def test_from_uri_passes_codec() -> None:
    codec = PickleCodec()
    assert SQLiteStore.from_uri("sqlite+pickle::memory:", codec=codec)._codec is codec


def test_from_uri_codec_mismatch() -> None:
    with pytest.raises(ValueError, match=r"does not match the scheme"):
        SQLiteStore.from_uri("sqlite::memory:", codec=PickleCodec())


def test_from_uri_read_only(tmp_path: Path) -> None:
    store = SQLiteStore.from_uri(SQLiteStore(tmp_path / "a.db").to_uri(), read_only=True)
    assert store._read_only


def test__uri_kwargs() -> None:
    assert SQLStore._uri_kwargs("data.db") == {}


# --- _init_schema ---


@pytest.mark.parametrize(("codec", "value_type"), [(JsonCodec(), "JSON"), (PickleCodec(), "BLOB")])
def test__init_schema_creates_table(codec: Codec, value_type: str) -> None:
    with SQLiteStore(codec=codec) as store:
        assert store._table_columns() == [("key", "TEXT", True), ("value", value_type, False)]


def test__init_schema_keeps_existing_values(filled_store: SQLiteStore) -> None:
    filled_store._init_schema()
    assert filled_store.count() == 3


def test__init_schema_mismatch(store: SQLiteStore) -> None:
    store.connection.execute("DROP TABLE store")
    store.connection.execute("CREATE TABLE store (key TEXT PRIMARY KEY, value TEXT)")
    with pytest.raises(ValueError, match=r"does not match the codec 'json'"):
        store._init_schema()


def test__init_schema_read_only_without_table(store: SQLiteStore) -> None:
    store.connection.execute("DROP TABLE store")
    store._read_only = True
    with pytest.raises(ValueError, match=r"has no table 'store'"):
        store._init_schema()


# --- primitives ---


def test__get_many_one_key(filled_store: SQLiteStore) -> None:
    assert filled_store._get_many(["2"]) == {"2": '{"a": 2}'}


def test__get_many_one_missing_key(filled_store: SQLiteStore) -> None:
    assert filled_store._get_many(["4"]) == {}


def test__get_many(filled_store: SQLiteStore) -> None:
    assert filled_store._get_many(["2", "missing", "1", "2"]) == {
        "2": '{"a": 2}',
        "1": '{"a": 1}',
    }


def test__get_many_several_statements(
    filled_store: SQLiteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(filled_store, "_max_variables", 2)
    assert filled_store._get_many(["1", "2", "3"]) == PAYLOADS


def test__contains_many(filled_store: SQLiteStore) -> None:
    assert filled_store._contains_many(["2", "missing", "1", "2"]) == {"1", "2"}


def test__contains_many_several_statements(
    filled_store: SQLiteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(filled_store, "_max_variables", 2)
    assert filled_store._contains_many(["1", "2", "3", "4"]) == {"1", "2", "3"}


def test__put_many(filled_store: SQLiteStore) -> None:
    filled_store._put_many({"1": "{}", "4": '{"a": 4}'})
    assert filled_store._get_many(["1", "2", "3", "4"]) == {
        **PAYLOADS,
        "1": "{}",
        "4": '{"a": 4}',
    }


def test__put_many_one_item_uses_one_statement(store: SQLiteStore) -> None:
    statements = trace(store)
    store._put_many({"1": "{}"})
    assert statements == ["INSERT OR REPLACE INTO store (key, value) VALUES ('1', '{}')"]


def test__put_many_several_items_uses_one_transaction(store: SQLiteStore) -> None:
    statements = trace(store)
    store._put_many({"1": "{}", "2": "{}"})
    assert [statements[0], statements[-1]] == ["BEGIN IMMEDIATE", "COMMIT"]


def test__put_many_error_writes_nothing(store: SQLiteStore) -> None:
    # The value column is NOT NULL.
    with pytest.raises(sqlite3.IntegrityError, match=r"NOT NULL constraint failed"):
        store._put_many({"1": "{}", "2": None})
    assert store.count() == 0


def test__update(filled_store: SQLiteStore) -> None:
    plan = build_plan({"1": '{"b": 1}', "4": "{}"}, "merge", JsonCodec())
    filled_store._update(["1", "4"], plan)
    assert filled_store._get_many(["1", "2", "3", "4"]) == {
        **PAYLOADS,
        "1": '{"a": 1, "b": 1}',
        "4": "{}",
    }


def test__update_gives_existing_payloads_to_plan(filled_store: SQLiteStore) -> None:
    received: list[dict[str, Payload]] = []

    def plan(existing: dict[str, Payload]) -> dict[str, Payload]:
        received.append(existing)
        return {}

    filled_store._update(["1", "4"], plan)
    assert received == [{"1": '{"a": 1}'}]


def test__update_reads_inside_the_transaction(filled_store: SQLiteStore) -> None:
    statements = trace(filled_store)
    filled_store._update(["4"], lambda _existing: {})
    assert statements == [
        "BEGIN IMMEDIATE",
        "SELECT key, value FROM store WHERE key = '4'",
        "COMMIT",
    ]


def test__update_plan_raises_writes_nothing(filled_store: SQLiteStore) -> None:
    plan = build_plan({"4": "{}", "1": "{}"}, "raise", JsonCodec())
    with pytest.raises(KeyError, match=r"already exist"):
        filled_store._update(["4", "1"], plan)
    assert filled_store.count() == 3


def test__delete_many(filled_store: SQLiteStore) -> None:
    filled_store._delete_many(["1", "missing", "1", "3"])
    assert filled_store._get_many(["1", "2", "3"]) == {"2": '{"a": 2}'}


def test__delete_many_several_statements_in_one_transaction(
    filled_store: SQLiteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(filled_store, "_max_variables", 2)
    statements = trace(filled_store)
    filled_store._delete_many(["1", "2", "3"])
    assert statements == [
        "BEGIN IMMEDIATE",
        "DELETE FROM store WHERE key IN ('1', '2')",
        "DELETE FROM store WHERE key IN ('3')",
        "COMMIT",
    ]


def test__clear(filled_store: SQLiteStore) -> None:
    filled_store._clear()
    assert filled_store.count() == 0


@pytest.mark.parametrize(("items", "expected"), [({}, 0), (PAYLOADS, 3)])
def test__count(store: SQLiteStore, items: dict[str, Payload], expected: int) -> None:
    store._executemany("INSERT INTO store VALUES (?, ?)", list(items.items()))
    assert store._count() == expected


@pytest.mark.parametrize(
    ("batch_size", "expected"),
    [(1, [["1"], ["2"], ["3"]]), (2, [["1", "2"], ["3"]]), (3, [["1", "2", "3"]])],
)
def test__iter_batches(
    filled_store: SQLiteStore, batch_size: int, expected: list[list[str]]
) -> None:
    assert [list(batch) for batch in filled_store._iter_batches(batch_size)] == expected


def test__iter_batches_payloads(filled_store: SQLiteStore) -> None:
    assert list(filled_store._iter_batches(10)) == [PAYLOADS]


def test__iter_batches_empty_store(store: SQLiteStore) -> None:
    assert list(store._iter_batches(2)) == []


def test__iter_batches_empty_string_key(store: SQLiteStore) -> None:
    store._put_many({"": "{}", "a": "{}"})
    assert [list(batch) for batch in store._iter_batches(1)] == [[""], ["a"]]


def test__iter_batches_uses_keyset_pagination(filled_store: SQLiteStore) -> None:
    statements = trace(filled_store)
    list(filled_store._iter_batches(2))
    assert statements == [
        "SELECT key, value FROM store ORDER BY key LIMIT 2",
        "SELECT key, value FROM store WHERE key > '2' ORDER BY key LIMIT 2",
    ]


def test__iter_batches_delete_of_yielded_keys(filled_store: SQLiteStore) -> None:
    visited: list[str] = []
    for batch in filled_store._iter_batches(1):
        visited.extend(batch)
        filled_store._delete_many(list(batch))
    assert visited == ["1", "2", "3"]


def test__iter_batches_key_inserted_before_the_position(filled_store: SQLiteStore) -> None:
    visited: list[str] = []
    for batch in filled_store._iter_batches(1):
        visited.extend(batch)
        filled_store._put_many({"0": "{}"})
    assert visited == ["1", "2", "3"]


# --- filter ---


def test__filter_candidates_json_codec_selects_in_sql(filled_store: SQLiteStore) -> None:
    assert list(filled_store._filter_candidates({"a": 2})) == [{"2": '{"a": 2}'}]


@pytest.mark.parametrize("codec", [PickleCodec(), CustomJsonCodec()])
def test__filter_candidates_other_codec_yields_every_pair(codec: Codec) -> None:
    with SQLiteStore(codec=codec) as store:
        store.set_many({"1": {"a": 1}, "2": {"a": 2}})
        assert [list(batch) for batch in store._filter_candidates({"a": 2})] == [["1", "2"]]


def test_filter_custom_json_codec_applies_predicate() -> None:
    with SQLiteStore(codec=CustomJsonCodec()) as store:
        store.set_many({"1": {"a": 1}, "2": {"a": 2}})
        assert store.filter(a=2) == [{"a": 2}]


@pytest.mark.parametrize(
    ("codec", "fields", "expected"),
    [
        # The database selected the candidates: they are not filtered again.
        pytest.param(JsonCodec(), {"a": 2}, [{"a": 1}, {"a": 2}], id="json"),
        pytest.param(CustomJsonCodec(), {"a": 2}, [{"a": 2}], id="custom"),
    ],
)
def test__matching_values(
    codec: Codec, fields: Mapping[str, Any], expected: list[dict[str, Any]]
) -> None:
    store = SQLiteStore(codec=codec)
    assert store._matching_values({"1": '{"a": 1}', "2": '{"a": 2}'}, fields) == expected


@pytest.mark.parametrize(
    ("codec", "expected"),
    [
        pytest.param(JsonCodec(), {"1": {"a": 1}, "2": {"a": 2}}, id="json"),
        pytest.param(CustomJsonCodec(), {"2": {"a": 2}}, id="custom"),
    ],
)
def test__matching_items(codec: Codec, expected: dict[str, dict[str, Any]]) -> None:
    store = SQLiteStore(codec=codec)
    assert store._matching_items({"1": '{"a": 1}', "2": '{"a": 2}'}, {"a": 2}) == expected


@pytest.mark.parametrize(
    ("codec", "expected"),
    [(JsonCodec(), True), (PickleCodec(), False), (CustomJsonCodec(), False)],
)
def test__filters_in_sql(codec: Codec, expected: bool) -> None:
    assert SQLiteStore(codec=codec)._filters_in_sql() is expected


def test__select_matches(filled_store: SQLiteStore) -> None:
    assert list(filled_store._select_matches({"a": 3})) == [{"3": '{"a": 3}'}]


def test__select_matches_no_field(filled_store: SQLiteStore) -> None:
    assert list(filled_store._select_matches({})) == [PAYLOADS]


def test__select_matches_no_match(filled_store: SQLiteStore) -> None:
    assert list(filled_store._select_matches({"a": 4})) == []


def test__select_matches_invalid_field(store: SQLiteStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid filter field name"):
        list(store._select_matches({"a b": 1}))


# --- helpers ---


@pytest.mark.parametrize(
    ("max_variables", "expected"),
    [
        (None, [["1", "2", "3"]]),
        (3, [["1", "2", "3"]]),
        (2, [["1", "2"], ["3"]]),
        (1, [["1"], ["2"], ["3"]]),
    ],
)
def test__chunks(
    monkeypatch: pytest.MonkeyPatch, max_variables: int | None, expected: list[list[str]]
) -> None:
    store = SQLiteStore()
    monkeypatch.setattr(store, "_max_variables", max_variables)
    assert list(store._chunks(["1", "2", "3"])) == expected


def test__delete_chunk(filled_store: SQLiteStore) -> None:
    filled_store._delete_chunk(["1", "2"])
    assert filled_store._get_many(["1", "2", "3"]) == {"3": '{"a": 3}'}


# --- repr ---


def test__get_repr_kwargs_closed() -> None:
    assert SQLiteStore()._get_repr_kwargs() == {"database": ":memory:", "closed": True}


def test__get_repr_kwargs_open(filled_store: SQLiteStore) -> None:
    assert filled_store._get_repr_kwargs() == {
        "database": ":memory:",
        "closed": False,
        "count": "3",
    }


def test__get_repr_kwargs_options(tmp_path: Path) -> None:
    codec = PickleCodec()
    store = SQLiteStore(tmp_path / "a.db", codec=codec, read_only=True, timeout=1.0)
    assert store._get_repr_kwargs() == {
        "database": (tmp_path / "a.db").resolve(),
        "closed": True,
        "codec": codec,
        "read_only": True,
        "timeout": 1.0,
    }
