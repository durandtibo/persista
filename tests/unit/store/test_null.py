from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from persista.store import JsonCodec, NullStore
from persista.store.plan import build_plan

if TYPE_CHECKING:
    from collections.abc import Callable, Generator


@pytest.fixture
def store() -> Generator[NullStore, None, None]:
    with NullStore() as store:
        yield store


###############################
#     Tests for NullStore     #
###############################


def test_null_store_codec(store: NullStore) -> None:
    assert isinstance(store._codec, JsonCodec)


def test_null_store_is_thread_safe() -> None:
    assert NullStore._thread_safe


# --- repr / str ---


def test_repr(store: NullStore) -> None:
    assert repr(store) == "NullStore(closed=False)"


def test_str(store: NullStore) -> None:
    assert str(store) == "NullStore(closed=False)"


def test_repr_before_open() -> None:
    assert repr(NullStore()) == "NullStore(closed=True)"


def test_repr_runs_no_primitive(store: NullStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "_count", MagicMock(side_effect=AssertionError("query")))
    assert repr(store) == "NullStore(closed=False)"


# --- URI ---


def test_to_uri(store: NullStore) -> None:
    assert store.to_uri() == "null://"


def test_from_uri_returns_closed_store() -> None:
    assert NullStore.from_uri("null://").closed


# --- everything written is forgotten ---


@pytest.mark.parametrize("on_conflict", ["raise", "skip", "overwrite", "merge"])
def test_set_is_forgotten(store: NullStore, on_conflict: str) -> None:
    store.set("1", {"a": 1}, on_conflict=on_conflict)
    assert store.get("1") is None


def test_set_twice_with_raise_does_not_raise(store: NullStore) -> None:
    store.set("1", {"a": 1}, on_conflict="raise")
    store.set("1", {"a": 1}, on_conflict="raise")
    assert store.count() == 0


async def test_aset_is_forgotten(store: NullStore) -> None:
    await store.aset("1", {"a": 1})
    assert await store.aget("1") is None


async def test_async_calls_start_no_worker_thread(store: NullStore) -> None:
    await store.aset("1", {"a": 1})
    assert store._executor is None


def test_iteration_yields_nothing(store: NullStore) -> None:
    store.set("1", {"a": 1})
    assert list(store.iter_batches()) == []


async def test_async_iteration_yields_nothing(store: NullStore) -> None:
    assert [key async for key in store.akeys()] == []


def test_filter_returns_nothing(store: NullStore) -> None:
    store.set("1", {"a": 1})
    assert store.filter(a=1) == {}


def test_contains_many_returns_false(store: NullStore) -> None:
    store.set("1", {"a": 1})
    assert store.contains_many(["1", "2"]) == [False, False]


# --- the arguments are checked ---


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda s: s.set("1", {}, on_conflict="bogus"), id="set"),
        pytest.param(lambda s: s.set_many({}, on_conflict="bogus"), id="set_many"),
    ],
)
def test_invalid_on_conflict_raises(
    store: NullStore, operation: Callable[[NullStore], None]
) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        operation(store)


async def test_aset_invalid_on_conflict_raises(store: NullStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        await store.aset("1", {}, on_conflict="bogus")


def test_set_non_json_value_raises(store: NullStore) -> None:
    with pytest.raises(TypeError, match=r"not JSON serializable"):
        store.set("1", {"a": object()})


def test_get_non_str_key_raises(store: NullStore) -> None:
    with pytest.raises(TypeError, match=r"A key must be a str"):
        store.get(1)


def test_closed_store_raises() -> None:
    with pytest.raises(RuntimeError, match=r"NullStore is not open"):
        NullStore().get("1")


# --- primitives ---


def test__open(store: NullStore) -> None:
    store._open()
    assert store._count() == 0


def test__close(store: NullStore) -> None:
    store._close()
    assert store._count() == 0


def test__get_many(store: NullStore) -> None:
    assert store._get_many(["1"]) == {}


def test__put_many(store: NullStore, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="persista.store.null"):
        store._put_many({"1": "{}", "2": "{}"})
    assert "Discarding 2 key-value pair(s)" in caplog.text


def test__update_calls_plan_without_existing_keys(store: NullStore) -> None:
    received: list[dict] = []

    def plan(existing: dict) -> dict:
        received.append(existing)
        return {"1": "{}"}

    store._update(["1"], plan)
    assert received == [{}]


def test__update_with_raise_plan(store: NullStore) -> None:
    store._update(["1"], build_plan({"1": "{}"}, "raise", JsonCodec()))
    assert store._get_many(["1"]) == {}


def test__delete_many(store: NullStore) -> None:
    store._delete_many(["1"])
    assert store._count() == 0


def test__clear(store: NullStore) -> None:
    store._clear()
    assert store._count() == 0


def test__count(store: NullStore) -> None:
    assert store._count() == 0


def test__iter_batches(store: NullStore) -> None:
    assert list(store._iter_batches(2)) == []


def test__contains_many(store: NullStore) -> None:
    assert store._contains_many(["1"]) == set()


def test__get_repr_kwargs(store: NullStore) -> None:
    assert store._get_repr_kwargs() == {"closed": False}
