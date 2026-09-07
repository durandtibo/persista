from __future__ import annotations

from persista.record import Record
from persista.record.analysis import compute_value_frequency

########################################
#     Tests for compute_value_frequency     #
########################################


def test_compute_value_frequency_top_values_most_common_first() -> None:
    records = [
        Record(id="a", metadata={"lang": "en"}),
        Record(id="b", metadata={"lang": "en"}),
        Record(id="c", metadata={"lang": "fr"}),
    ]
    result = compute_value_frequency(records)
    assert result["lang"]["top_values"] == [("en", 2), ("fr", 1)]


def test_compute_value_frequency_top_k_limits_results() -> None:
    records = [
        Record(id="a", metadata={"lang": "en"}),
        Record(id="b", metadata={"lang": "fr"}),
        Record(id="c", metadata={"lang": "de"}),
    ]
    result = compute_value_frequency(records, top_k=2)
    assert len(result["lang"]["top_values"]) == 2


def test_compute_value_frequency_distinct_count_estimate() -> None:
    records = [
        Record(id="a", metadata={"lang": "en"}),
        Record(id="b", metadata={"lang": "fr"}),
        Record(id="c", metadata={"lang": "en"}),
    ]
    result = compute_value_frequency(records)
    assert result["lang"]["distinct_count_estimate"] == 2


def test_compute_value_frequency_multiple_keys() -> None:
    records = [
        Record(id="a", metadata={"lang": "en", "page": 1}),
        Record(id="b", metadata={"lang": "fr"}),
    ]
    result = compute_value_frequency(records)
    assert set(result.keys()) == {"lang", "page"}


def test_compute_value_frequency_empty_input() -> None:
    assert compute_value_frequency([]) == {}


def test_compute_value_frequency_unhashable_value() -> None:
    records = [
        Record(id="a", metadata={"tags": ["x", "y"]}),
        Record(id="b", metadata={"tags": ["x", "y"]}),
    ]
    result = compute_value_frequency(records)
    assert result["tags"]["top_values"] == [("['x', 'y']", 2)]


def test_compute_value_frequency_generator_input() -> None:
    def gen() -> object:
        yield Record(id="a", metadata={"lang": "en"})
        yield Record(id="b", metadata={"lang": "en"})

    result = compute_value_frequency(gen())
    assert result["lang"]["top_values"] == [("en", 2)]


def test_compute_value_frequency_cardinality_approximately_correct_for_larger_corpus() -> None:
    records = [Record(id=str(i), metadata={"uid": i}) for i in range(500)]
    result = compute_value_frequency(records)
    estimate = result["uid"]["distinct_count_estimate"]
    # HyperLogLog is approximate; allow a generous tolerance.
    assert 500 * 0.9 <= estimate <= 500 * 1.1
