from __future__ import annotations

from persista.record import Record
from persista.record.analysis import compute_schema_shapes

########################################
#     Tests for compute_schema_shapes     #
########################################


def test_compute_schema_shapes_same_shape() -> None:
    records = [
        Record(id="a", metadata={"source": "a.pdf", "page": 1}),
        Record(id="b", metadata={"source": "b.pdf", "page": 2}),
    ]
    assert compute_schema_shapes(records) == {("page", "source"): ["a", "b"]}


def test_compute_schema_shapes_different_shapes() -> None:
    records = [
        Record(id="a", metadata={"source": "a.pdf", "page": 1}),
        Record(id="b", metadata={"source": "b.pdf"}),
    ]
    assert compute_schema_shapes(records) == {
        ("page", "source"): ["a"],
        ("source",): ["b"],
    }


def test_compute_schema_shapes_key_order_ignored() -> None:
    records = [
        Record(id="a", metadata={"source": "a.pdf", "page": 1}),
        Record(id="b", metadata={"page": 2, "source": "b.pdf"}),
    ]
    assert compute_schema_shapes(records) == {("page", "source"): ["a", "b"]}


def test_compute_schema_shapes_empty_metadata() -> None:
    records = [Record(id="a", metadata={})]
    assert compute_schema_shapes(records) == {(): ["a"]}


def test_compute_schema_shapes_empty_input() -> None:
    assert compute_schema_shapes([]) == {}


def test_compute_schema_shapes_generator_input() -> None:
    def gen() -> object:
        yield Record(id="a", metadata={"source": "a.pdf"})
        yield Record(id="b", metadata={"source": "b.pdf"})

    assert compute_schema_shapes(gen()) == {("source",): ["a", "b"]}


def test_compute_schema_shapes_first_seen_order() -> None:
    records = [
        Record(id="a", metadata={"x": 1}),
        Record(id="b", metadata={"y": 1}),
        Record(id="c", metadata={"x": 2}),
    ]
    assert list(compute_schema_shapes(records).keys()) == [("x",), ("y",)]
