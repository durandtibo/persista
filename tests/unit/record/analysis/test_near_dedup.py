from __future__ import annotations

import math

import pytest

from persista.record import Record
from persista.record.analysis import find_near_duplicate_record_ids
from persista.record.analysis.near_dedup import (
    _base_hash,
    _minhash_signature,
    _union_band,
    _UnionFind,
)

####################################################
#     Tests for find_near_duplicate_record_ids     #
####################################################


def test_find_near_duplicate_record_ids_no_similarity() -> None:
    records = [
        Record(id="a", metadata={"source": "a.pdf"}),
        Record(id="b", metadata={"source": "z.pdf"}),
    ]
    assert find_near_duplicate_record_ids(records, num_hashes=4, num_bands=4) == []


def test_find_near_duplicate_record_ids_identical_metadata_always_grouped() -> None:
    records = [
        Record(id="a", metadata={"source": "a.pdf"}),
        Record(id="b", metadata={"source": "a.pdf"}),
    ]
    assert find_near_duplicate_record_ids(records, num_hashes=8, num_bands=4) == [["a", "b"]]


def test_find_near_duplicate_record_ids_similar_but_not_identical() -> None:
    records = [
        Record(id="a", metadata={"source": "a.pdf", "page": 1, "lang": "en"}),
        Record(id="b", metadata={"source": "a.pdf", "page": 1, "lang": "fr"}),
        Record(id="c", metadata={"source": "z.pdf", "page": 9}),
    ]
    assert find_near_duplicate_record_ids(records, num_hashes=4, num_bands=4) == [["a", "b"]]


def test_find_near_duplicate_record_ids_transitive_grouping() -> None:
    records = [
        Record(id="a", metadata={"x": 1, "y": 1, "z": 1, "w": 1}),
        Record(id="b", metadata={"x": 1, "y": 1, "z": 2, "w": 2}),
        Record(id="c", metadata={"x": 2, "y": 2, "z": 1, "w": 1}),
    ]
    # "b" and "c" share no item: each of them shares two with "a".
    result = find_near_duplicate_record_ids(records, num_hashes=32, num_bands=32)
    assert result == [["a", "b", "c"]]


def test_find_near_duplicate_record_ids_empty_metadata_never_grouped() -> None:
    records = [Record(id="a", metadata={}), Record(id="b", metadata={})]
    assert find_near_duplicate_record_ids(records, num_hashes=8, num_bands=4) == []


def test_find_near_duplicate_record_ids_empty_input() -> None:
    assert find_near_duplicate_record_ids([], num_hashes=8, num_bands=4) == []


def test_find_near_duplicate_record_ids_single_record() -> None:
    records = [Record(id="a", metadata={"source": "a.pdf"})]
    assert find_near_duplicate_record_ids(records, num_hashes=8, num_bands=4) == []


def test_find_near_duplicate_record_ids_invalid_band_count_raises() -> None:
    records = [Record(id="a", metadata={"source": "a.pdf"})]
    with pytest.raises(ValueError, match="must be evenly divisible"):
        find_near_duplicate_record_ids(records, num_hashes=8, num_bands=3)


def test_find_near_duplicate_record_ids_generator_input() -> None:
    def gen() -> object:
        yield Record(id="a", metadata={"source": "a.pdf"})
        yield Record(id="b", metadata={"source": "a.pdf"})

    result = find_near_duplicate_record_ids(gen(), num_hashes=4, num_bands=4)
    assert result == [["a", "b"]]


def test_find_near_duplicate_record_ids_default_args_do_not_raise() -> None:
    records = [Record(id="a", metadata={"source": "a.pdf"})]
    assert find_near_duplicate_record_ids(records) == []


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param({"a": "b=c"}, {"a=b": "c"}, id="separator"),
        pytest.param({"x": 1}, {"x": "1"}, id="int-str"),
        pytest.param({"x": 1}, {"x": True}, id="int-bool"),
        pytest.param({"x": [1]}, {"x": (1,)}, id="list-tuple"),
    ],
)
def test_find_near_duplicate_record_ids_different_items_not_grouped(
    first: dict, second: dict
) -> None:
    records = [Record(id="a", metadata=first), Record(id="b", metadata=second)]
    assert find_near_duplicate_record_ids(records, num_hashes=8, num_bands=4) == []


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param({"x": 1}, {"x": 1.0}, id="int-float"),
        pytest.param({"x": {"a": 1, "b": 2}}, {"x": {"b": 2, "a": 1}}, id="dict-order"),
    ],
)
def test_find_near_duplicate_record_ids_equal_items_grouped(first: dict, second: dict) -> None:
    records = [Record(id="a", metadata=first), Record(id="b", metadata=second)]
    assert find_near_duplicate_record_ids(records, num_hashes=8, num_bands=4) == [["a", "b"]]


@pytest.mark.parametrize(
    ("num_hashes", "num_bands"),
    [(8, 0), (0, 8), (0, 0), (-8, 4), (8, -4), (-8, -4)],
)
def test_find_near_duplicate_record_ids_not_positive_parameters(
    num_hashes: int, num_bands: int
) -> None:
    records = [Record(id="a", metadata={"x": 1})]
    with pytest.raises(ValueError, match=r"must be positive"):
        find_near_duplicate_record_ids(records, num_hashes=num_hashes, num_bands=num_bands)


def test_find_near_duplicate_record_ids_more_bands_than_hashes() -> None:
    with pytest.raises(ValueError, match=r"must be evenly divisible"):
        find_near_duplicate_record_ids([], num_hashes=4, num_bands=8)


def test_find_near_duplicate_record_ids_invalid_parameter_consumes_nothing() -> None:
    records = iter([Record(id="a")])
    with pytest.raises(ValueError, match=r"must be positive"):
        find_near_duplicate_record_ids(records, num_bands=0)
    assert list(records) == [Record(id="a")]


@pytest.mark.parametrize(
    ("value", "error", "message"),
    [
        pytest.param(object(), TypeError, r"Cannot encode an object of type", id="custom"),
        pytest.param(
            bytearray(b"a"), TypeError, r"Cannot encode an object of type", id="bytearray"
        ),
        pytest.param(math.nan, ValueError, r"Cannot encode NaN by value", id="nan"),
    ],
)
def test_find_near_duplicate_record_ids_value_that_cannot_be_compared(
    value: object, error: type[Exception], message: str
) -> None:
    records = [Record(id="a", metadata={"x": value})]
    with pytest.raises(error, match=message):
        find_near_duplicate_record_ids(records)


def test_find_near_duplicate_record_ids_does_not_modify_input() -> None:
    records = [Record(id="a", metadata={"x": [1.0]})]
    find_near_duplicate_record_ids(records)
    assert repr(records) == "[Record(id='a', metadata={'x': [1.0]})]"


################################
#     Tests for _base_hash     #
################################


def test_base_hash() -> None:
    # The first 8 bytes of sha256(b"0:item").
    assert _base_hash(b"item", 0) == 504420247250610125


def test_base_hash_depends_on_seed() -> None:
    assert _base_hash(b"item", 0) != _base_hash(b"item", 1)


def test_base_hash_depends_on_item() -> None:
    assert _base_hash(b"item", 0) != _base_hash(b"other", 0)


########################################
#     Tests for _minhash_signature     #
########################################


def test_minhash_signature_empty_metadata() -> None:
    assert _minhash_signature({}, 3) == (-1, -1, -1)


def test_minhash_signature_length() -> None:
    assert len(_minhash_signature({"x": 1}, 5)) == 5


def test_minhash_signature_is_order_independent() -> None:
    assert _minhash_signature({"a": 1, "b": 2}, 8) == _minhash_signature({"b": 2, "a": 1}, 8)


def test_minhash_signature_is_minimum_over_items() -> None:
    first = _minhash_signature({"a": 1}, 8)
    second = _minhash_signature({"b": 2}, 8)
    assert _minhash_signature({"a": 1, "b": 2}, 8) == tuple(map(min, first, second))


def test_minhash_signature_value_that_cannot_be_compared() -> None:
    with pytest.raises(TypeError, match=r"Cannot encode an object of type"):
        _minhash_signature({"x": object()}, 2)


################################
#     Tests for _UnionFind     #
################################


def test_union_find_initial_roots() -> None:
    union_find = _UnionFind(3)
    assert [union_find.find(i) for i in range(3)] == [0, 1, 2]


def test_union_find_union() -> None:
    union_find = _UnionFind(3)
    union_find.union(0, 1)
    union_find.union(1, 2)
    assert [union_find.find(i) for i in range(3)] == [0, 0, 0]


#################################
#     Tests for _union_band     #
#################################


def test_union_band_merges_identical_bands() -> None:
    union_find = _UnionFind(3)
    _union_band([(1, 2), (1, 2), (1, 3)], 0, 2, union_find)
    assert [union_find.find(i) for i in range(3)] == [1, 1, 2]


def test_union_band_ignores_empty_metadata() -> None:
    union_find = _UnionFind(2)
    _union_band([(-1, -1), (-1, -1)], 0, 2, union_find)
    assert [union_find.find(i) for i in range(2)] == [0, 1]
