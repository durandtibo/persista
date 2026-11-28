from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from persista.store import InMemoryStore, JsonCodec, PickleCodec
from persista.store.plan import build_plan

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from persista.store import Codec
    from persista.store.types import Payload

PAYLOADS: dict[str, Payload] = {"1": '{"a": 1}', "2": '{"a": 2}', "3": '{"a": 3}'}


@pytest.fixture
def store() -> Generator[InMemoryStore, None, None]:
    with InMemoryStore() as store:
        yield store


@pytest.fixture
def filled_store(store: InMemoryStore) -> InMemoryStore:
    store._put_many(PAYLOADS)
    return store


###################################
#     Tests for InMemoryStore     #
###################################


def test_in_memory_store_default_codec() -> None:
    assert isinstance(InMemoryStore()._codec, JsonCodec)


def test_in_memory_store_custom_codec() -> None:
    codec = PickleCodec()
    assert InMemoryStore(codec=codec)._codec is codec


def test_in_memory_store_codec_is_keyword_only() -> None:
    with pytest.raises(TypeError, match=r"positional argument"):
        InMemoryStore(PickleCodec())


def test_in_memory_store_is_not_thread_safe() -> None:
    assert not InMemoryStore._thread_safe


def test_in_memory_store_has_no_data_property(store: InMemoryStore) -> None:
    # The property exposed the internal dict.
    assert not hasattr(store, "data")


# --- repr / str ---


def test_repr(filled_store: InMemoryStore) -> None:
    assert repr(filled_store) == "InMemoryStore(closed=False)"


def test_repr_runs_no_primitive(
    filled_store: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(filled_store, "_count", MagicMock(side_effect=AssertionError("query")))
    assert repr(filled_store) == "InMemoryStore(closed=False)"


def test_str(filled_store: InMemoryStore) -> None:
    assert str(filled_store) == "InMemoryStore(closed=False)"


def test_repr_before_open() -> None:
    assert repr(InMemoryStore()) == "InMemoryStore(closed=True)"


def test_str_before_open() -> None:
    assert str(InMemoryStore()) == "InMemoryStore(closed=True)"


def test_repr_after_close(store: InMemoryStore) -> None:
    store.close()
    assert repr(store) == "InMemoryStore(closed=True)"


# --- URI ---


def test_to_uri(store: InMemoryStore) -> None:
    assert store.to_uri() == "memory://"


def test_from_uri_returns_closed_store() -> None:
    assert InMemoryStore.from_uri("memory://").closed


def test_from_uri_does_not_carry_data(filled_store: InMemoryStore) -> None:
    with InMemoryStore.from_uri(filled_store.to_uri()) as restored:
        assert restored.count() == 0


# --- lifecycle ---


def test_close_discards_values(filled_store: InMemoryStore) -> None:
    filled_store.close()
    filled_store.open()
    assert filled_store.count() == 0


async def test_aclose_discards_values(filled_store: InMemoryStore) -> None:
    await filled_store.aclose()
    await filled_store.aopen()
    assert filled_store._data == {}
    await filled_store.aclose()


def test_open_while_open_keeps_values(filled_store: InMemoryStore) -> None:
    filled_store.open()
    assert filled_store.count() == 3


def test__open(filled_store: InMemoryStore) -> None:
    filled_store._open()
    assert filled_store._data == {}


def test__close(filled_store: InMemoryStore) -> None:
    filled_store._close()
    assert filled_store._data == {}


def test__close_without_open() -> None:
    store = InMemoryStore()
    store._close()
    assert store._data == {}


# --- primitives ---


def test__get_many(filled_store: InMemoryStore) -> None:
    assert filled_store._get_many(["2", "missing", "1", "2"]) == {
        "2": '{"a": 2}',
        "1": '{"a": 1}',
    }


def test__get_many_empty_store(store: InMemoryStore) -> None:
    assert store._get_many(["1"]) == {}


def test__put_many(filled_store: InMemoryStore) -> None:
    filled_store._put_many({"1": "{}", "4": '{"a": 4}'})
    assert filled_store._data == {**PAYLOADS, "1": "{}", "4": '{"a": 4}'}


def test__put_many_does_not_alias_input(store: InMemoryStore) -> None:
    items: dict[str, Payload] = {"1": "{}"}
    store._put_many(items)
    items["2"] = "{}"
    assert store._data == {"1": "{}"}


def test__update(filled_store: InMemoryStore) -> None:
    plan = build_plan({"1": '{"b": 1}', "4": "{}"}, "merge", JsonCodec())
    filled_store._update(["1", "4"], plan)
    assert filled_store._data == {**PAYLOADS, "1": '{"a": 1, "b": 1}', "4": "{}"}


def test__update_gives_existing_payloads_to_plan(filled_store: InMemoryStore) -> None:
    received: list[dict[str, Payload]] = []

    def plan(existing: dict[str, Payload]) -> dict[str, Payload]:
        received.append(existing)
        return {}

    filled_store._update(["1", "4"], plan)
    assert received == [{"1": '{"a": 1}'}]


def test__update_plan_raises_writes_nothing(filled_store: InMemoryStore) -> None:
    plan = build_plan({"4": "{}", "1": "{}"}, "raise", JsonCodec())
    with pytest.raises(KeyError, match=r"already exist"):
        filled_store._update(["4", "1"], plan)
    assert filled_store._data == PAYLOADS


def test__delete_many(filled_store: InMemoryStore) -> None:
    filled_store._delete_many(["1", "missing", "1", "3"])
    assert filled_store._data == {"2": '{"a": 2}'}


def test__clear(filled_store: InMemoryStore) -> None:
    filled_store._clear()
    assert filled_store._data == {}


@pytest.mark.parametrize(("items", "expected"), [({}, 0), (PAYLOADS, 3)])
def test__count(store: InMemoryStore, items: dict[str, Payload], expected: int) -> None:
    store._put_many(items)
    assert store._count() == expected


def test__contains_many(filled_store: InMemoryStore) -> None:
    assert filled_store._contains_many(["1", "missing", "1", "2"]) == {"1", "2"}


@pytest.mark.parametrize(
    ("batch_size", "expected"),
    [
        (1, [{"1": '{"a": 1}'}, {"2": '{"a": 2}'}, {"3": '{"a": 3}'}]),
        (2, [{"1": '{"a": 1}', "2": '{"a": 2}'}, {"3": '{"a": 3}'}]),
        (3, [PAYLOADS]),
        (10, [PAYLOADS]),
    ],
)
def test__iter_batches(
    filled_store: InMemoryStore, batch_size: int, expected: list[dict[str, Payload]]
) -> None:
    assert list(filled_store._iter_batches(batch_size)) == expected


def test__iter_batches_empty_store(store: InMemoryStore) -> None:
    assert list(store._iter_batches(2)) == []


def test__iter_batches_does_not_yield_new_keys(filled_store: InMemoryStore) -> None:
    iterator = filled_store._iter_batches(2)
    next(iterator)
    filled_store._put_many({"4": "{}"})
    assert list(iterator) == [{"3": '{"a": 3}'}]


def test__iter_batches_yields_current_payload(filled_store: InMemoryStore) -> None:
    iterator = filled_store._iter_batches(2)
    next(iterator)
    filled_store._put_many({"3": "{}"})
    assert list(iterator) == [{"3": "{}"}]


def test__iter_batches_skips_deleted_keys(filled_store: InMemoryStore) -> None:
    iterator = filled_store._iter_batches(1)
    next(iterator)
    filled_store._delete_many(["2"])
    assert list(iterator) == [{"3": '{"a": 3}'}]


def test__iter_batches_deleting_yielded_keys_visits_every_key(
    filled_store: InMemoryStore,
) -> None:
    keys = []
    for batch in filled_store._iter_batches(1):
        keys.extend(batch)
        filled_store._delete_many(list(batch))
    assert keys == ["1", "2", "3"]


def test__get_repr_kwargs(filled_store: InMemoryStore) -> None:
    assert filled_store._get_repr_kwargs() == {"closed": False}


def test__get_repr_kwargs_closed() -> None:
    assert InMemoryStore()._get_repr_kwargs() == {"closed": True}


# --- isolation: mutating a value never changes the stored value ---


@pytest.mark.parametrize("codec", [JsonCodec(), PickleCodec()], ids=["json", "pickle"])
@pytest.mark.parametrize(
    "read",
    [
        pytest.param(lambda s: s.get("1"), id="get"),
        pytest.param(lambda s: s.get_many(["1"])[0], id="get_many"),
        pytest.param(lambda s: s.filter()["1"], id="filter"),
        pytest.param(lambda s: s.filter(n=1)["1"], id="filter_field"),
        pytest.param(lambda s: next(iter(s.values())), id="values"),
        pytest.param(lambda s: next(iter(s.iter_batches()))["1"], id="iter_batches"),
    ],
)
def test_mutating_a_returned_value_does_not_change_the_store(
    codec: Codec, read: Callable[[InMemoryStore], dict[str, Any]]
) -> None:
    with InMemoryStore(codec=codec) as store:
        store.set("1", {"n": 1, "tags": ["a"]})
        read(store)["tags"].append("b")
        assert store.get("1") == {"n": 1, "tags": ["a"]}


async def test_mutating_an_async_iterated_value_does_not_change_the_store(
    store: InMemoryStore,
) -> None:
    store.set("1", {"tags": ["a"]})
    async for value in store.avalues():
        value["tags"].append("b")
    assert store.get("1") == {"tags": ["a"]}


@pytest.mark.parametrize("on_conflict", ["raise", "skip", "overwrite", "merge"])
def test_mutating_a_written_value_does_not_change_the_store(
    store: InMemoryStore, on_conflict: str
) -> None:
    value = {"tags": ["a"]}
    store.set("1", value, on_conflict=on_conflict)
    value["tags"].append("b")
    assert store.get("1") == {"tags": ["a"]}


# --- round trip: the same as the other stores with the same codec ---


def test_json_round_trip_turns_tuple_into_list(store: InMemoryStore) -> None:
    store.set("1", {"point": (1, 2)})
    assert store.get("1") == {"point": [1, 2]}


def test_json_codec_non_str_value_key_raises(store: InMemoryStore) -> None:
    with pytest.raises(TypeError, match=r"keys must be str"):
        store.set("1", {1: "int", "1": "str"})
    assert store.count() == 0


@pytest.mark.parametrize("number", [float("nan"), float("inf")])
def test_json_codec_non_finite_float_raises(store: InMemoryStore, number: float) -> None:
    with pytest.raises(ValueError, match=r"not JSON compliant"):
        store.set("1", {"n": number})
    assert store.count() == 0


def test_json_codec_lone_surrogate_raises(store: InMemoryStore) -> None:
    with pytest.raises(ValueError, match=r"lone surrogate"):
        store.set("1", {"text": chr(0xD800)})
    assert store.count() == 0


def test_pickle_codec_round_trip_keeps_types() -> None:
    value = {"point": (1, 2), "tags": {"a"}, 1: "int", "1": "str"}
    with InMemoryStore(codec=PickleCodec()) as store:
        store.set("1", value)
        assert store.get("1") == value


# --- closed store and invalid arguments, with empty inputs ---


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda s: s.get_many([]), id="get_many"),
        pytest.param(lambda s: s.delete_many([]), id="delete_many"),
        pytest.param(lambda s: s.contains_many([]), id="contains_many"),
        pytest.param(lambda s: s.set_many({}), id="set_many"),
        pytest.param(lambda s: s.set_batches([]), id="set_batches"),
    ],
)
def test_closed_store_with_empty_input_raises(
    operation: Callable[[InMemoryStore], Any],
) -> None:
    with pytest.raises(RuntimeError, match=r"InMemoryStore is not open"):
        operation(InMemoryStore())


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda s: s.aget_many([]), id="aget_many"),
        pytest.param(lambda s: s.adelete_many([]), id="adelete_many"),
        pytest.param(lambda s: s.aset_batches([]), id="aset_batches"),
    ],
)
async def test_closed_store_with_empty_input_raises_async(
    operation: Callable[[InMemoryStore], Any],
) -> None:
    with pytest.raises(RuntimeError, match=r"InMemoryStore is not open"):
        await operation(InMemoryStore())


def test_set_batches_invalid_on_conflict_with_empty_input_raises(
    store: InMemoryStore,
) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        store.set_batches([], on_conflict="bogus")
