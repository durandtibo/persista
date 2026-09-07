from __future__ import annotations

import re

import pytest

from persista.utils.hashing import hash_dict_uuid

UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$")


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
