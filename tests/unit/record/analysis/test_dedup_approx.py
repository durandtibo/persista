from __future__ import annotations

from persista.record import Record
from persista.record.analysis import count_approx_duplicate_records

######################################################
#     Tests for count_approx_duplicate_records     #
######################################################


def test_count_approx_duplicate_records_no_duplicates() -> None:
    records = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="b", metadata={"source": "y"}),
    ]
    assert count_approx_duplicate_records(records, expected_record_count=100) == 0


def test_count_approx_duplicate_records_one_duplicate() -> None:
    records = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="b", metadata={"source": "x"}),
    ]
    assert count_approx_duplicate_records(records, expected_record_count=100) == 1


def test_count_approx_duplicate_records_multiple_duplicates() -> None:
    records = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="b", metadata={"source": "x"}),
        Record(id="c", metadata={"source": "x"}),
        Record(id="d", metadata={"source": "y"}),
    ]
    assert count_approx_duplicate_records(records, expected_record_count=100) == 2


def test_count_approx_duplicate_records_empty_input() -> None:
    assert count_approx_duplicate_records([], expected_record_count=100) == 0


def test_count_approx_duplicate_records_single_record() -> None:
    records = [Record(id="a", metadata={"source": "x"})]
    assert count_approx_duplicate_records(records, expected_record_count=100) == 0


def test_count_approx_duplicate_records_key_order_ignored() -> None:
    records = [
        Record(id="a", metadata={"source": "x", "page": 1}),
        Record(id="b", metadata={"page": 1, "source": "x"}),
    ]
    assert count_approx_duplicate_records(records, expected_record_count=100) == 1


def test_count_approx_duplicate_records_generator_input() -> None:
    def gen() -> object:
        yield Record(id="a", metadata={"source": "x"})
        yield Record(id="b", metadata={"source": "x"})

    assert count_approx_duplicate_records(gen(), expected_record_count=100) == 1


def test_count_approx_duplicate_records_generator_consumed_only_once() -> None:
    def gen() -> object:
        yield Record(id="a", metadata={"source": "x"})

    g = gen()
    count_approx_duplicate_records(g, expected_record_count=100)
    assert list(g) == []


def test_count_approx_duplicate_records_default_args_do_not_raise() -> None:
    records = [Record(id="a", metadata={"source": "x"})]
    assert count_approx_duplicate_records(records) == 0
