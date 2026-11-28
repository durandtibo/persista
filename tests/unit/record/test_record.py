from __future__ import annotations

import copy
import math
from collections import OrderedDict
from dataclasses import FrozenInstanceError, asdict, astuple
from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType

import pytest

from persista.record import Record
from persista.store import PickleCodec

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
    with pytest.raises(TypeError, match=r"does not support item assignment"):
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


# --- from_metadata: equality of the metadata ---


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param(1, "1", id="int-str"),
        pytest.param(1, True, id="int-bool"),
        pytest.param([1, 2], (1, 2), id="list-tuple"),
        pytest.param({1}, frozenset({1}), id="set-frozenset"),
    ],
)
def test_record_from_metadata_different_types_different_ids(first: object, second: object) -> None:
    assert Record.from_metadata({"x": first}).id != Record.from_metadata({"x": second}).id


@pytest.mark.parametrize(
    ("first", "second"),
    [pytest.param(1, 1.0, id="int-float"), pytest.param(0.0, -0.0, id="zeros")],
)
def test_record_from_metadata_equal_numbers_same_id(first: object, second: object) -> None:
    assert Record.from_metadata({"x": first}).id == Record.from_metadata({"x": second}).id


def test_record_from_metadata_pinned_id() -> None:
    # The ids are stored: they must not change between processes or releases.
    assert (
        Record.from_metadata({"source": "cats.txt", "page": 1}).id
        == "65671470-bf89-5ffd-a51e-78e06c01fd41"
    )


def test_record_from_metadata_of_record_metadata() -> None:
    record = Record.from_metadata({"source": "cats.txt"})
    assert Record.from_metadata(record.metadata) == record


def test_record_from_metadata_does_not_mutate_input() -> None:
    metadata = {"b": 1.0, "a": 2}
    Record.from_metadata(metadata)
    assert repr(metadata) == "{'b': 1.0, 'a': 2}"


def test_record_from_metadata_keeps_values() -> None:
    assert repr(Record.from_metadata({"x": 1.0}).metadata["x"]) == "1.0"


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(datetime(2024, 1, 1, tzinfo=UTC), id="datetime"),
        pytest.param(Decimal(1), id="decimal"),
        pytest.param(OrderedDict(), id="subclass"),
        pytest.param(object(), id="custom"),
    ],
)
def test_record_from_metadata_unsupported_type(value: object) -> None:
    with pytest.raises(TypeError, match=r"Cannot encode an object of type"):
        Record.from_metadata({"x": value})


def test_record_from_metadata_nan() -> None:
    with pytest.raises(ValueError, match=r"Cannot encode NaN by value"):
        Record.from_metadata({"x": math.nan})


def test_record_from_metadata_self_containing_value() -> None:
    value: list[object] = []
    value.append(value)
    with pytest.raises(ValueError, match=r"Cannot encode a list that contains itself"):
        Record.from_metadata({"x": value})


# --- Hash ---


def test_record_hash_is_hash_of_id() -> None:
    assert hash(Record(id="abc", metadata={"tags": ["a"]})) == hash("abc")


def test_record_set_removes_equal_records() -> None:
    records = {Record(id="abc", metadata={"x": 1}), Record(id="abc", metadata={"x": 1})}
    assert records == {Record(id="abc", metadata={"x": 1})}


def test_record_set_keeps_records_with_different_metadata() -> None:
    records = {Record(id="abc", metadata={"x": 1}), Record(id="abc", metadata={"x": 2})}
    assert len(records) == 2


def test_record_dict_key() -> None:
    assert {Record(id="abc"): 1}[Record(id="abc")] == 1


# --- Pickle and copy ---


def nested_record() -> Record:
    return Record(id="abc", metadata={"tags": ["a"], "info": {"year": 2024}, "at": (1, 2)})


def pickle_round_trip(record: Record) -> Record:
    r"""Pickle a record and load it again, with the codec of the
    stores."""
    codec = PickleCodec()
    return codec.decode(codec.encode({"record": record}))["record"]


def test_record_pickle() -> None:
    record = nested_record()
    assert pickle_round_trip(record) == record


def test_record_pickle_returns_a_new_record() -> None:
    record = nested_record()
    assert pickle_round_trip(record) is not record


def test_record_pickle_metadata_is_read_only() -> None:
    assert isinstance(pickle_round_trip(nested_record()).metadata, MappingProxyType)


def test_record_copy() -> None:
    record = nested_record()
    assert copy.copy(record) == record


def test_record_copy_is_shallow() -> None:
    record = nested_record()
    assert copy.copy(record).metadata["tags"] is record.metadata["tags"]


def test_record_copy_metadata_is_read_only() -> None:
    assert isinstance(copy.copy(nested_record()).metadata, MappingProxyType)


def test_record_deepcopy() -> None:
    record = nested_record()
    assert copy.deepcopy(record) == record


def test_record_deepcopy_copies_nested_values() -> None:
    record = nested_record()
    copy.deepcopy(record).metadata["tags"].append("b")
    assert record.metadata["tags"] == ["a"]


def test_record_deepcopy_metadata_is_read_only() -> None:
    assert isinstance(copy.deepcopy(nested_record()).metadata, MappingProxyType)


def test_record_deepcopy_shared_values_stay_shared() -> None:
    shared: list[int] = []
    records = copy.deepcopy(
        [Record(id="a", metadata={"x": shared}), Record(id="b", metadata={"x": shared})]
    )
    assert records[0].metadata["x"] is records[1].metadata["x"]


def test_record_reduce() -> None:
    assert Record(id="abc", metadata={"x": 1}).__reduce__() == (Record, ("abc", {"x": 1}))


# --- Shallow immutability ---


def test_record_nested_values_are_shared_with_the_caller() -> None:
    tags = ["a"]
    assert Record(id="abc", metadata={"tags": tags}).metadata["tags"] is tags


# --- dataclasses ---


def test_record_asdict_is_not_supported() -> None:
    with pytest.raises(TypeError, match=r"cannot pickle 'mappingproxy' object"):
        asdict(Record(id="abc"))


def test_record_astuple_is_not_supported() -> None:
    with pytest.raises(TypeError, match=r"cannot pickle 'mappingproxy' object"):
        astuple(Record(id="abc"))
