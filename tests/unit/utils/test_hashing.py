from __future__ import annotations

import re

import pytest

from persista.utils.hashing import canonicalize_dict, hash_dict_uuid

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


def test_hash_dict_uuid_matches_uuid5_of_canonicalize_dict() -> None:
    # hash_dict_uuid is defined as uuid5 of canonicalize_dict's output under a
    # fixed namespace - this pins that relationship so the two helpers cannot
    # silently drift apart from each other.
    import uuid

    from persista.utils.hashing import _NAMESPACE

    data = {"source": "cats.txt", "page": 1}
    assert hash_dict_uuid(data) == str(uuid.uuid5(_NAMESPACE, canonicalize_dict(data)))
