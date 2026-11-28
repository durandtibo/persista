from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from persista.store import JsonCodec, PickleCodec, SQLiteStore
from persista.store.plan import build_plan
from persista.store.sql import (
    SQLStore,
    _is_unicode,
    build_where,
    can_push_down,
    check_sql_codec,
    check_table_layout,
    decode_sql_uri,
    encode_sql_uri,
    select_push_down_fields,
    value_column_type,
)

if TYPE_CHECKING:
    from collections.abc import Generator
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


class StrSubclass(str):
    r"""A subclass of ``str``."""

    __slots__ = ()


class IntSubclass(int):
    r"""A subclass of ``int``."""


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


def test_check_table_layout_error_message_names_the_table() -> None:
    with pytest.raises(ValueError, match=r"The table 'documents' of 'db' does not match"):
        check_table_layout([], codec=JsonCodec(), key_type="TEXT", database="db", table="documents")


@pytest.mark.parametrize(
    ("codec", "value_type"), [(JsonCodec(), "JSONB"), (PickleCodec(), "BYTEA")]
)
def test_check_table_layout_column_types(codec: Codec, value_type: str) -> None:
    columns = [("key", "text", True), ("value", value_type.lower(), False)]
    check_table_layout(
        columns,
        codec=codec,
        key_type="TEXT",
        database="db",
        column_types={"json": "JSONB", "pickle": "BYTEA"},
    )


def test_check_table_layout_column_types_mismatch() -> None:
    with pytest.raises(ValueError, match=r"expected the columns .*value JSONB"):
        check_table_layout(
            COLUMNS,
            codec=JsonCodec(),
            key_type="TEXT",
            database="db",
            column_types={"json": "JSONB"},
        )


def test_check_table_layout_column_types_unsupported_codec() -> None:
    with pytest.raises(ValueError, match=r"A SQL store needs a codec"):
        check_table_layout(
            COLUMNS,
            codec=OtherCodec(),
            key_type="TEXT",
            database="db",
            column_types={"yaml": "JSON"},
        )


def test_check_table_layout_does_not_modify_columns() -> None:
    columns = COLUMNS[::-1]
    check_table_layout(columns, codec=JsonCodec(), key_type="TEXT", database="db")
    assert columns == [("value", "JSON", False), ("key", "TEXT", True)]


###################################
#     Tests for can_push_down     #
###################################


@pytest.mark.parametrize(
    ("codec", "expected"),
    [(JsonCodec(), True), (PickleCodec(), False), (CustomJsonCodec(), False)],
)
def test_can_push_down(codec: Codec, expected: bool) -> None:
    assert can_push_down(codec) is expected


#############################################
#     Tests for select_push_down_fields     #
#############################################


@pytest.mark.parametrize(
    "value",
    [
        "",
        "Alice",
        "1",
        chr(0xE9),
        chr(0x1F600),
        "a' OR '1'='1",
        0,
        1,
        -1,
        2**53 - 1,
        -(2**53 - 1),
    ],
)
def test_select_push_down_fields_selected_value(value: object) -> None:
    assert select_push_down_fields({"a": value}) == {"a": value}


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        1.0,
        float("nan"),
        [1],
        (1,),
        {"a": 1},
        b"a",
        Decimal(1),
        "a" + chr(0) + "b",
        chr(0),
        chr(0xD800),
        2**53,
        -(2**53),
        2**64,
        10**400,
    ],
)
def test_select_push_down_fields_other_value(value: object) -> None:
    assert select_push_down_fields({"a": value}) == {}


@pytest.mark.parametrize(
    "field", ["", "1", "a b", "a-b", "a.b", "a'b", 'a"b', "$", chr(0xE9), "a\n"]
)
def test_select_push_down_fields_unsafe_name(field: str) -> None:
    assert select_push_down_fields({field: 1}) == {}


def test_select_push_down_fields_keeps_order() -> None:
    fields = {"c": 1, "a-b": 2, "a": "x"}
    assert list(select_push_down_fields(fields).items()) == [("c", 1), ("a", "x")]


def test_select_push_down_fields_no_field() -> None:
    assert select_push_down_fields({}) == {}


@pytest.mark.parametrize(
    ("value", "kind"), [(StrSubclass("x"), str), (IntSubclass(3), int)], ids=["str", "int"]
)
def test_select_push_down_fields_converts_subclass(value: object, kind: type) -> None:
    assert type(select_push_down_fields({"a": value})["a"]) is kind


def test_select_push_down_fields_converts_name_subclass() -> None:
    assert type(next(iter(select_push_down_fields({StrSubclass("a"): 1})))) is str


def test_select_push_down_fields_does_not_modify_fields() -> None:
    fields = {"a": 1, "b": None}
    select_push_down_fields(fields)
    assert fields == {"a": 1, "b": None}


#################################
#     Tests for _is_unicode     #
#################################


@pytest.mark.parametrize(
    ("text", "expected"),
    [("", True), ("a", True), (chr(0x1F600), True), (chr(0xD800), False)],
)
def test__is_unicode(text: str, expected: bool) -> None:
    assert _is_unicode(text) is expected


#################################
#     Tests for build_where     #
#################################


def condition(name: str, value: str | int) -> tuple[str, list[str | int]]:
    r"""Return a condition with one parameter."""
    return f"{name.upper()} = ?", [value]


def test_build_where() -> None:
    assert build_where({"a": 1, "b": None, "c": "x", "d-e": "y"}, condition) == (
        "A = ? AND C = ?",
        [1, "x"],
    )


def test_build_where_several_parameters() -> None:
    def between(name: str, value: int) -> tuple[str, list[int]]:
        return f"{name} BETWEEN ? AND ?", [value, value]

    assert build_where({"a": 1, "b": 2}, between) == (
        "a BETWEEN ? AND ? AND b BETWEEN ? AND ?",
        [1, 1, 2, 2],
    )


@pytest.mark.parametrize("fields", [{}, {"a": None}])
def test_build_where_no_condition(fields: dict) -> None:
    assert build_where(fields, condition) == ("", [])


def test_build_where_condition_error() -> None:
    def failing(name: str, value: str | int) -> tuple[str, list]:
        msg = f"bad field {name}={value}"
        raise ValueError(msg)

    with pytest.raises(ValueError, match=r"bad field a=1"):
        build_where({"a": 1}, failing)


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


@pytest.mark.parametrize(
    ("batch_size", "expected"),
    [(1, [["1"], ["2"], ["3"]]), (2, [["1", "2"], ["3"]]), (3, [["1", "2", "3"]])],
)
def test__iter_key_batches(
    filled_store: SQLiteStore, batch_size: int, expected: list[list[str]]
) -> None:
    assert list(filled_store._iter_key_batches(batch_size)) == expected


def test__iter_key_batches_empty_store(store: SQLiteStore) -> None:
    assert list(store._iter_key_batches(2)) == []


def test__iter_key_batches_does_not_read_the_values(filled_store: SQLiteStore) -> None:
    statements = trace(filled_store)
    list(filled_store._iter_key_batches(2))
    assert statements == [
        "SELECT key FROM store ORDER BY key LIMIT 2",
        "SELECT key FROM store WHERE key > '2' ORDER BY key LIMIT 2",
    ]


def test__iter_key_batches_delete_of_yielded_keys(filled_store: SQLiteStore) -> None:
    visited: list[str] = []
    for batch in filled_store._iter_key_batches(1):
        visited.extend(batch)
        filled_store._delete_many(batch)
    assert visited == ["1", "2", "3"]


def test__iter_key_batches_key_inserted_before_the_position(filled_store: SQLiteStore) -> None:
    visited: list[str] = []
    for batch in filled_store._iter_key_batches(1):
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
        assert store.filter(a=2) == {"2": {"a": 2}}


def test_filter_selects_candidates_with_one_query(filled_store: SQLiteStore) -> None:
    statements = trace(filled_store)
    filled_store.filter(a=2)
    assert statements == ["SELECT key, value FROM store WHERE json_extract(value, '$.a') = 2"]


@pytest.mark.parametrize("fields", [{}, {"a": None}, {"a": 1.0}, {"a-b": 1}, {"a": [1]}])
def test_filter_without_condition_reads_every_row_with_one_query(
    filled_store: SQLiteStore, fields: dict[str, Any]
) -> None:
    statements = trace(filled_store)
    filled_store.filter(**fields)
    assert statements == ["SELECT key, value FROM store"]


def test_filter_applies_predicate_to_candidates(store: SQLiteStore) -> None:
    # SQLite extracts true as the integer 1.
    store.set_many({"1": {"a": 1}, "2": {"a": True}})
    assert store.filter(a=1) == {"1": {"a": 1}}


async def test_afilter(filled_store: SQLiteStore) -> None:
    assert await filled_store.afilter(a=2) == {"2": {"a": 2}}


async def test_afilter_pickle_codec(pickle_store: SQLiteStore) -> None:
    assert await pickle_store.afilter(tags={"b"}) == {"2": {"tags": {"b"}}}


def test_filter_pickle_codec_several_batches(pickle_store: SQLiteStore) -> None:
    pickle_store.set_many({str(i): {"even": i % 2 == 0} for i in range(600)})
    assert len(pickle_store.filter(even=True)) == 300


def test__select_candidates(filled_store: SQLiteStore) -> None:
    assert list(filled_store._select_candidates({"a": 3})) == [{"3": '{"a": 3}'}]


def test__select_candidates_no_field(filled_store: SQLiteStore) -> None:
    assert list(filled_store._select_candidates({})) == [PAYLOADS]


def test__select_candidates_no_match(filled_store: SQLiteStore) -> None:
    assert list(filled_store._select_candidates({"a": 4})) == []


####################################
#     Tests for _safe_database     #
####################################


def test__safe_database() -> None:
    assert SQLStore._safe_database(SQLiteStore()) == ":memory:"


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
    assert filled_store._get_repr_kwargs() == {"database": ":memory:", "closed": False}


def test__get_repr_kwargs_runs_no_query(filled_store: SQLiteStore) -> None:
    statements = trace(filled_store)
    filled_store._get_repr_kwargs()
    assert statements == []


def test__get_repr_kwargs_options(tmp_path: Path) -> None:
    codec = PickleCodec()
    store = SQLiteStore(tmp_path / "a.db", codec=codec, read_only=True, timeout=1.0)
    assert store._get_repr_kwargs() == {
        "database": (tmp_path / "a.db").resolve(),
        "closed": True,
        "codec": codec,
        "read_only": True,
    }


def test_from_uri_of_a_memory_database_gives_a_private_empty_database(
    filled_store: SQLiteStore,
) -> None:
    with SQLiteStore.from_uri(filled_store.to_uri()) as restored:
        restored.set("new", {})
        assert (restored.count(), filled_store.count()) == (1, 3)


@pytest.mark.parametrize(("size", "expected"), [(99, 99), (100, 100), (101, 100), (2000, 100)])
def test_select_push_down_fields_selects_at_most_100_conditions(size: int, expected: int) -> None:
    fields = {f"f{i}": i for i in range(size)}
    assert len(select_push_down_fields(fields)) == expected


def test_filter_many_fields(store: SQLiteStore) -> None:
    fields = {f"f{i}": i for i in range(2000)}
    store.set_many({"match": fields, "other": {**fields, "f1999": 0}})
    assert list(store.filter(**fields)) == ["match"]
