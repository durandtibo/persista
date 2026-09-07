from __future__ import annotations

import re
import uuid

import pytest

from persista.utils.hashing import _NAMESPACE, canonicalize_dict, hash_dict_uuid

UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$")


####################################
#     Tests for canonicalize_dict   #
####################################


def test_canonicalize_dict_returns_str() -> None:
    assert isinstance(canonicalize_dict({"key": "value"}), str)


def test_canonicalize_dict_sorts_keys() -> None:
    assert canonicalize_dict({"b": 1, "a": 2}) == canonicalize_dict({"a": 2, "b": 1})


def test_canonicalize_dict_uses_compact_separators() -> None:
    assert canonicalize_dict({"a": 1, "b": 2}) == '{"a":1,"b":2}'


def test_canonicalize_dict_empty_dict() -> None:
    assert canonicalize_dict({}) == "{}"


def test_canonicalize_dict_different_dicts_different_output() -> None:
    assert canonicalize_dict({"a": 1}) != canonicalize_dict({"a": 2})


def test_canonicalize_dict_non_serializable_raises_without_default() -> None:
    with pytest.raises(TypeError, match=r"Object of type object is not JSON serializable"):
        canonicalize_dict({"obj": object()})


def test_canonicalize_dict_non_serializable_uses_default() -> None:
    assert canonicalize_dict({"obj": object()}, default=str) is not None


def test_canonicalize_dict_default_is_applied() -> None:
    class Foo:
        def __str__(self) -> str:
            return "foo!"

    assert canonicalize_dict({"x": Foo()}, default=str) == '{"x":"foo!"}'


def test_canonicalize_dict_int_key() -> None:
    assert canonicalize_dict({1: "a"}) == '{"1":"a"}'


def test_canonicalize_dict_float_key() -> None:
    assert canonicalize_dict({1.5: "a"}) == '{"1.5":"a"}'


def test_canonicalize_dict_bool_key() -> None:
    assert canonicalize_dict({True: "a", False: "b"}) == '{"false":"b","true":"a"}'


def test_canonicalize_dict_none_key() -> None:
    assert canonicalize_dict({None: "a"}) == '{"null":"a"}'


def test_canonicalize_dict_mixed_key_types_does_not_raise() -> None:
    # Plain json.dumps(..., sort_keys=True) raises TypeError here because it
    # sorts the raw keys (str vs int) before stringifying them.
    assert canonicalize_dict({"b": 1, 2: "a"}) == '{"2":"a","b":1}'


def test_canonicalize_dict_nested_dict_mixed_key_types_does_not_raise() -> None:
    assert canonicalize_dict({"outer": {1: "x", "b": "y"}}) == '{"outer":{"1":"x","b":"y"}}'


def test_canonicalize_dict_key_normalization_can_collide() -> None:
    # 1 and "1" normalize to the same string key; last write wins, matching
    # what json.dumps itself would do for such a collision.
    assert canonicalize_dict({1: "int", "1": "str"}) == '{"1":"str"}'


def test_canonicalize_dict_unsupported_key_type_raises() -> None:
    with pytest.raises(TypeError, match=r"keys must be str, int, float, bool or None, not tuple"):
        canonicalize_dict({(1, 2): "a"})


def test_canonicalize_dict_list_of_dicts_normalizes_nested_keys() -> None:
    assert canonicalize_dict({"items": [{1: "x"}, {"b": 2}]}) == '{"items":[{"1":"x"},{"b":2}]}'


def test_canonicalize_dict_tuple_value_becomes_list() -> None:
    assert canonicalize_dict({"a": (1, 2)}) == '{"a":[1,2]}'


def test_canonicalize_dict_default_can_raise() -> None:
    def default(obj: object) -> str:
        msg = f"cannot serialize {obj!r}"
        raise ValueError(msg)

    with pytest.raises(ValueError, match=r"cannot serialize"):
        canonicalize_dict({"obj": object()}, default=default)


def test_canonicalize_dict_unicode_key_and_value() -> None:
    assert canonicalize_dict({"héllo": "wörld"}) == '{"h\\u00e9llo":"w\\u00f6rld"}'


def test_canonicalize_dict_none_value() -> None:
    assert canonicalize_dict({"a": None}) == '{"a":null}'


def test_canonicalize_dict_negative_int_key() -> None:
    assert canonicalize_dict({-1: "a"}) == '{"-1":"a"}'


def test_canonicalize_dict_key_sort_order_after_normalization() -> None:
    # Keys sort lexicographically on their *normalized* string form, not
    # their original type/value - "-1" sorts before "1" before "null".
    assert canonicalize_dict({1: "b", -1: "a", None: "c"}) == '{"-1":"a","1":"b","null":"c"}'
    assert canonicalize_dict({1: "b", -1: "a", None: "c"}) == canonicalize_dict(
        {None: "c", 1: "b", -1: "a"}
    )


def test_canonicalize_dict_nan_and_infinity_values() -> None:
    assert canonicalize_dict({"a": float("nan"), "b": float("inf"), "c": float("-inf")}) == (
        '{"a":NaN,"b":Infinity,"c":-Infinity}'
    )


def test_canonicalize_dict_deeply_nested_structure() -> None:
    data = {"a": {"b": {"c": [{"d": 1}, (2, {"e": 3})]}}}
    assert canonicalize_dict(data) == '{"a":{"b":{"c":[{"d":1},[2,{"e":3}]]}}}'


def test_canonicalize_dict_list_of_tuples_with_dict_keys() -> None:
    assert canonicalize_dict({"a": [(1, "x"), (2, "y")]}) == '{"a":[[1,"x"],[2,"y"]]}'


def test_canonicalize_dict_unsupported_key_type_in_nested_dict_raises() -> None:
    with pytest.raises(TypeError, match=r"keys must be str, int, float, bool or None, not tuple"):
        canonicalize_dict({"outer": {(1, 2): "a"}})


def test_canonicalize_dict_unsupported_key_type_in_list_of_dicts_raises() -> None:
    with pytest.raises(
        TypeError, match=r"keys must be str, int, float, bool or None, not frozenset"
    ):
        canonicalize_dict({"items": [{frozenset({1, 2}): "a"}]})


def test_canonicalize_dict_empty_nested_containers() -> None:
    assert canonicalize_dict({"a": {}, "b": [], "c": ()}) == '{"a":{},"b":[],"c":[]}'


def test_canonicalize_dict_large_int_key() -> None:
    assert canonicalize_dict({10**30: "a"}) == '{"1000000000000000000000000000000":"a"}'


###################################
#     Tests for hash_dict_uuid    #
###################################


def test_hash_dict_uuid_returns_str() -> None:
    assert isinstance(hash_dict_uuid({"key": "value"}), str)


def test_hash_dict_uuid_is_valid_uuid_v5() -> None:
    assert UUID_PATTERN.match(hash_dict_uuid({"key": "value"}))


def test_hash_dict_uuid_same_dict_same_hash() -> None:
    data = {"source": "cats.txt", "page": 1}
    assert hash_dict_uuid(data) == hash_dict_uuid(data)


def test_hash_dict_uuid_equal_dicts_same_hash() -> None:
    assert hash_dict_uuid({"source": "cats.txt", "page": 1}) == hash_dict_uuid(
        {"source": "cats.txt", "page": 1}
    )


def test_hash_dict_uuid_key_order_independent() -> None:
    assert hash_dict_uuid({"source": "cats.txt", "page": 1}) == hash_dict_uuid(
        {"page": 1, "source": "cats.txt"}
    )


def test_hash_dict_uuid_different_values_different_hash() -> None:
    assert hash_dict_uuid({"source": "cats.txt"}) != hash_dict_uuid({"source": "dogs.txt"})


def test_hash_dict_uuid_different_keys_different_hash() -> None:
    assert hash_dict_uuid({"source": "cats.txt"}) != hash_dict_uuid({"origin": "cats.txt"})


def test_hash_dict_uuid_empty_dict() -> None:
    assert UUID_PATTERN.match(hash_dict_uuid({}))


def test_hash_dict_uuid_empty_dict_same_hash() -> None:
    assert hash_dict_uuid({}) == hash_dict_uuid({})


def test_hash_dict_uuid_nested_dict_key_order_independent() -> None:
    assert hash_dict_uuid({"info": {"year": 2024, "topic": "cats"}}) == hash_dict_uuid(
        {"info": {"topic": "cats", "year": 2024}}
    )


def test_hash_dict_uuid_integer_values() -> None:
    assert UUID_PATTERN.match(hash_dict_uuid({"page": 1}))


def test_hash_dict_uuid_boolean_values() -> None:
    assert UUID_PATTERN.match(hash_dict_uuid({"published": True}))


def test_hash_dict_uuid_non_serialisable_raises() -> None:
    with pytest.raises(TypeError, match=r"Object of type object is not JSON serializable"):
        hash_dict_uuid({"obj": object()})


def test_hash_dict_uuid_mixed_key_types_does_not_raise() -> None:
    assert UUID_PATTERN.match(hash_dict_uuid({"b": 1, 2: "a"}))


def test_hash_dict_uuid_nested_dict_mixed_key_types_does_not_raise() -> None:
    assert UUID_PATTERN.match(hash_dict_uuid({"outer": {1: "x", "b": "y"}}))


def test_hash_dict_uuid_unsupported_key_type_raises() -> None:
    with pytest.raises(TypeError, match=r"keys must be str, int, float, bool or None, not tuple"):
        hash_dict_uuid({(1, 2): "a"})


def test_hash_dict_uuid_non_serialisable_uses_default() -> None:
    assert UUID_PATTERN.match(hash_dict_uuid({"obj": object()}, default=str))


def test_hash_dict_uuid_default_changes_hash() -> None:
    class Foo:
        def __str__(self) -> str:
            return "foo!"

    assert hash_dict_uuid({"x": Foo()}, default=str) == hash_dict_uuid({"x": "foo!"})


def test_hash_dict_uuid_default_can_raise() -> None:
    def default(obj: object) -> str:
        msg = f"cannot serialize {obj!r}"
        raise ValueError(msg)

    with pytest.raises(ValueError, match=r"cannot serialize"):
        hash_dict_uuid({"obj": object()}, default=default)


def test_hash_dict_uuid_unicode_key_and_value() -> None:
    assert UUID_PATTERN.match(hash_dict_uuid({"héllo": "wörld"}))


def test_hash_dict_uuid_none_value() -> None:
    assert UUID_PATTERN.match(hash_dict_uuid({"a": None}))


def test_hash_dict_uuid_negative_int_key() -> None:
    assert UUID_PATTERN.match(hash_dict_uuid({-1: "a"}))


def test_hash_dict_uuid_key_type_does_not_affect_hash() -> None:
    # 1 and "1" normalize to the same string key, so these two dicts
    # canonicalize (and hash) identically.
    assert hash_dict_uuid({1: "a"}) == hash_dict_uuid({"1": "a"})


def test_hash_dict_uuid_nan_value_is_deterministic() -> None:
    assert hash_dict_uuid({"a": float("nan")}) == hash_dict_uuid({"a": float("nan")})


def test_hash_dict_uuid_deeply_nested_structure() -> None:
    data = {"a": {"b": {"c": [{"d": 1}, (2, {"e": 3})]}}}
    assert hash_dict_uuid(data) == hash_dict_uuid(data)


def test_hash_dict_uuid_unsupported_key_type_in_nested_dict_raises() -> None:
    with pytest.raises(TypeError, match=r"keys must be str, int, float, bool or None, not tuple"):
        hash_dict_uuid({"outer": {(1, 2): "a"}})


def test_hash_dict_uuid_empty_nested_containers() -> None:
    assert UUID_PATTERN.match(hash_dict_uuid({"a": {}, "b": [], "c": ()}))


def test_hash_dict_uuid_list_vs_tuple_value_same_hash() -> None:
    # Tuples normalize to lists before serialisation, so a list and an
    # equivalent tuple value hash the same.
    assert hash_dict_uuid({"a": [1, 2]}) == hash_dict_uuid({"a": (1, 2)})


def test_hash_dict_uuid_matches_uuid5_of_canonicalize_dict() -> None:
    # hash_dict_uuid is defined as uuid5 of canonicalize_dict's output under a
    # fixed namespace - this pins that relationship so the two helpers cannot
    # silently drift apart from each other.
    data = {"source": "cats.txt", "page": 1}
    assert hash_dict_uuid(data) == str(uuid.uuid5(_NAMESPACE, canonicalize_dict(data)))
