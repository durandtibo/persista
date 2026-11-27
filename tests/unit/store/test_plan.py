from __future__ import annotations

import pytest

from persista.store.codec import JsonCodec, PickleCodec
from persista.store.plan import build_plan

ITEMS = {"a": '{"y": 2}', "b": '{"y": 3}'}
EXISTING = {"a": '{"x": 1, "y": 1}'}


################################
#     Tests for build_plan     #
################################


@pytest.mark.parametrize("on_conflict", ["raise", "skip", "overwrite", "merge"])
def test_build_plan_without_conflict(on_conflict: str) -> None:
    assert build_plan(ITEMS, on_conflict, JsonCodec())({}) == ITEMS


def test_build_plan_without_conflict_returns_new_dict() -> None:
    assert build_plan(ITEMS, "raise", JsonCodec())({}) is not ITEMS


def test_build_plan_raise() -> None:
    plan = build_plan(ITEMS, "raise", JsonCodec())
    with pytest.raises(KeyError, match=r"already exist in the store: \['a'\]"):
        plan(EXISTING)


def test_build_plan_raise_lists_sorted_keys() -> None:
    plan = build_plan(ITEMS, "raise", JsonCodec())
    with pytest.raises(KeyError, match=r"\['a', 'b'\]"):
        plan({"b": "{}", "a": "{}"})


def test_build_plan_skip() -> None:
    assert build_plan(ITEMS, "skip", JsonCodec())(EXISTING) == {"b": '{"y": 3}'}


def test_build_plan_skip_every_key() -> None:
    assert build_plan(ITEMS, "skip", JsonCodec())({"a": "{}", "b": "{}"}) == {}


def test_build_plan_overwrite() -> None:
    assert build_plan(ITEMS, "overwrite", JsonCodec())(EXISTING) == ITEMS


def test_build_plan_merge() -> None:
    assert build_plan(ITEMS, "merge", JsonCodec())(EXISTING) == {
        "a": '{"x": 1, "y": 2}',
        "b": '{"y": 3}',
    }


def test_build_plan_merge_is_shallow() -> None:
    plan = build_plan({"a": '{"n": {"y": 2}}'}, "merge", JsonCodec())
    assert plan({"a": '{"n": {"x": 1}}'}) == {"a": '{"n": {"y": 2}}'}


def test_build_plan_merge_uses_codec() -> None:
    codec = PickleCodec()
    plan = build_plan({"a": codec.encode({"y": (2,)})}, "merge", codec)
    merged = plan({"a": codec.encode({1: "x"})})["a"]
    assert codec.decode(merged) == {1: "x", "y": (2,)}


@pytest.mark.parametrize("on_conflict", ["raise", "skip", "overwrite", "merge"])
def test_build_plan_ignores_other_existing_keys(on_conflict: str) -> None:
    assert build_plan(ITEMS, on_conflict, JsonCodec())({"c": "{}"}) == ITEMS


@pytest.mark.parametrize("on_conflict", ["skip", "overwrite", "merge"])
def test_build_plan_can_be_called_again(on_conflict: str) -> None:
    plan = build_plan(ITEMS, on_conflict, JsonCodec())
    assert plan(EXISTING) == plan(EXISTING)


@pytest.mark.parametrize("on_conflict", ["skip", "overwrite", "merge"])
def test_build_plan_does_not_mutate_inputs(on_conflict: str) -> None:
    items = dict(ITEMS)
    existing = dict(EXISTING)
    build_plan(items, on_conflict, JsonCodec())(existing)
    assert (items, existing) == (ITEMS, EXISTING)
