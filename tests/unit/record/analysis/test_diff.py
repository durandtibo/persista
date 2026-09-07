from __future__ import annotations

from persista.record import Record
from persista.record.analysis import diff_records

########################################
#     Tests for diff_records     #
########################################


def test_diff_records_no_changes() -> None:
    before = [Record(id="a", metadata={"source": "x"})]
    after = [Record(id="a", metadata={"source": "x"})]
    assert diff_records(before, after) == {"added": [], "removed": [], "changed": []}


def test_diff_records_added() -> None:
    before = [Record(id="a", metadata={"source": "x"})]
    after = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="b", metadata={"source": "y"}),
    ]
    assert diff_records(before, after) == {"added": ["b"], "removed": [], "changed": []}


def test_diff_records_removed() -> None:
    before = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="b", metadata={"source": "y"}),
    ]
    after = [Record(id="a", metadata={"source": "x"})]
    assert diff_records(before, after) == {"added": [], "removed": ["b"], "changed": []}


def test_diff_records_changed() -> None:
    before = [Record(id="a", metadata={"source": "x"})]
    after = [Record(id="a", metadata={"source": "y"})]
    assert diff_records(before, after) == {"added": [], "removed": [], "changed": ["a"]}


def test_diff_records_mixed() -> None:
    before = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="b", metadata={"source": "y"}),
    ]
    after = [
        Record(id="a", metadata={"source": "x", "page": 1}),
        Record(id="c", metadata={"source": "z"}),
    ]
    assert diff_records(before, after) == {
        "added": ["c"],
        "removed": ["b"],
        "changed": ["a"],
    }


def test_diff_records_both_empty() -> None:
    assert diff_records([], []) == {"added": [], "removed": [], "changed": []}


def test_diff_records_before_empty() -> None:
    after = [Record(id="a", metadata={"source": "x"})]
    assert diff_records([], after) == {"added": ["a"], "removed": [], "changed": []}


def test_diff_records_after_empty() -> None:
    before = [Record(id="a", metadata={"source": "x"})]
    assert diff_records(before, []) == {"added": [], "removed": ["a"], "changed": []}


def test_diff_records_generator_input() -> None:
    def gen_before() -> object:
        yield Record(id="a", metadata={"source": "x"})

    def gen_after() -> object:
        yield Record(id="a", metadata={"source": "y"})

    assert diff_records(gen_before(), gen_after()) == {
        "added": [],
        "removed": [],
        "changed": ["a"],
    }
