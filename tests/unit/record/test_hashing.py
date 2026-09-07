from __future__ import annotations

from types import MappingProxyType

from persista.record.hashing import hash_metadata

##################################
#     Tests for hash_metadata   #
##################################


def test_hash_metadata_returns_bytes() -> None:
    assert isinstance(hash_metadata({"source": "a.pdf"}), bytes)


def test_hash_metadata_is_32_bytes() -> None:
    # SHA-256 digest length.
    assert len(hash_metadata({"source": "a.pdf"})) == 32


def test_hash_metadata_deterministic() -> None:
    metadata = {"source": "a.pdf", "page": 1}
    assert hash_metadata(metadata) == hash_metadata(metadata)


def test_hash_metadata_key_order_independent() -> None:
    assert hash_metadata({"source": "a.pdf", "page": 1}) == hash_metadata(
        {"page": 1, "source": "a.pdf"}
    )


def test_hash_metadata_different_values_different_hash() -> None:
    assert hash_metadata({"source": "a.pdf"}) != hash_metadata({"source": "b.pdf"})


def test_hash_metadata_different_keys_different_hash() -> None:
    assert hash_metadata({"a": 1}) != hash_metadata({"b": 1})


def test_hash_metadata_empty_dict() -> None:
    assert hash_metadata({}) == hash_metadata({})


def test_hash_metadata_non_json_serializable_value_stringified() -> None:
    # Should not raise, and should be stable across calls.
    metadata = {"created": object()}
    assert isinstance(hash_metadata(metadata), bytes)


def test_hash_metadata_nested_dict_key_order_independent() -> None:
    assert hash_metadata({"info": {"year": 2024, "topic": "cats"}}) == hash_metadata(
        {"info": {"topic": "cats", "year": 2024}}
    )


def test_hash_metadata_accepts_mapping_proxy() -> None:
    metadata = {"source": "a.pdf", "page": 1}
    assert hash_metadata(MappingProxyType(metadata)) == hash_metadata(metadata)
