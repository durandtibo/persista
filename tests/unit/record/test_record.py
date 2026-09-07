from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import MappingProxyType

import pytest

from persista.record import Record

#########################
#     Tests for Record  #
#########################


# --- Construction ---


def test_record_is_frozen() -> None:
    record = Record(id="abc", metadata={"key": "value"})
    with pytest.raises(FrozenInstanceError, match=r"cannot assign to field 'id'"):
        record.id = "other"


def test_record_default_metadata() -> None:
    record = Record(id="abc")
    assert record.metadata == {}


def test_record_stores_id() -> None:
    record = Record(id="abc", metadata={"key": "value"})
    assert record.id == "abc"


def test_record_stores_metadata() -> None:
    metadata = {"source": "cats.txt", "page": 1}
    record = Record(id="abc", metadata=metadata)
    assert record.metadata == metadata


def test_record_equality() -> None:
    record_a = Record(id="abc", metadata={"source": "cats.txt"})
    record_b = Record(id="abc", metadata={"source": "cats.txt"})
    assert record_a == record_b


def test_record_different_id_not_equal() -> None:
    record_a = Record(id="abc", metadata={"source": "cats.txt"})
    record_b = Record(id="xyz", metadata={"source": "cats.txt"})
    assert record_a != record_b


def test_record_different_metadata_not_equal() -> None:
    record_a = Record(id="abc", metadata={"source": "cats.txt"})
    record_b = Record(id="abc", metadata={"source": "dogs.txt"})
    assert record_a != record_b


# --- Immutability ---


def test_record_metadata_is_mapping_proxy() -> None:
    record = Record(id="abc", metadata={"source": "cats.txt"})
    assert isinstance(record.metadata, MappingProxyType)


def test_record_metadata_assignment_raises_type_error() -> None:
    record = Record(id="abc", metadata={"source": "cats.txt"})
    with pytest.raises(TypeError):
        record.metadata["source"] = "dogs.txt"


def test_record_metadata_mutating_original_dict_does_not_affect_record() -> None:
    metadata = {"source": "cats.txt"}
    record = Record(id="abc", metadata=metadata)
    metadata["source"] = "dogs.txt"
    assert record.metadata == {"source": "cats.txt"}


# --- repr ---


def test_record_repr_renders_metadata_as_plain_dict() -> None:
    record = Record(id="abc", metadata={"source": "cats.txt"})
    assert repr(record) == "Record(id='abc', metadata={'source': 'cats.txt'})"


def test_record_repr_default_metadata() -> None:
    record = Record(id="abc")
    assert repr(record) == "Record(id='abc', metadata={})"


# --- from_metadata ---


def test_record_from_metadata_returns_record() -> None:
    assert isinstance(Record.from_metadata({"source": "cats.txt"}), Record)


def test_record_from_metadata_sets_metadata() -> None:
    metadata = {"source": "cats.txt", "page": 1}
    record = Record.from_metadata(metadata)
    assert record.metadata == metadata


def test_record_from_metadata_sets_id() -> None:
    record = Record.from_metadata({"source": "cats.txt"})
    assert record.id is not None


def test_record_from_metadata_id_is_str() -> None:
    record = Record.from_metadata({"source": "cats.txt"})
    assert isinstance(record.id, str)


def test_record_from_metadata_id_is_stable() -> None:
    metadata = {"source": "cats.txt", "page": 1}
    assert Record.from_metadata(metadata).id == Record.from_metadata(metadata).id


def test_record_from_metadata_different_metadata_different_id() -> None:
    record_a = Record.from_metadata({"source": "cats.txt"})
    record_b = Record.from_metadata({"source": "dogs.txt"})
    assert record_a.id != record_b.id


def test_record_from_metadata_key_order_independent() -> None:
    record_a = Record.from_metadata({"source": "cats.txt", "page": 1})
    record_b = Record.from_metadata({"page": 1, "source": "cats.txt"})
    assert record_a.id == record_b.id


def test_record_from_metadata_empty_dict() -> None:
    record = Record.from_metadata({})
    assert record.id is not None
    assert record.metadata == {}


def test_record_from_metadata_nested_dict_order_independent() -> None:
    record_a = Record.from_metadata({"info": {"year": 2024, "topic": "cats"}})
    record_b = Record.from_metadata({"info": {"topic": "cats", "year": 2024}})
    assert record_a.id == record_b.id


def test_record_not_equal_to_non_record() -> None:
    assert Record(id="abc") != "abc"
