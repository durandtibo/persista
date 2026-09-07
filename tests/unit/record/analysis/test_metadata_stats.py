from __future__ import annotations

import pytest

from persista.record import Record
from persista.record.analysis import MetadataStats, compute_metadata_stats


@pytest.fixture
def records() -> list[Record]:
    return [
        Record(id="a", metadata={"source": "a.pdf", "page": 1}),
        Record(id="b", metadata={"source": "b.pdf", "page": 2}),
        Record(id="c", metadata={"source": "a.pdf"}),
    ]


@pytest.fixture
def messy_records() -> list[Record]:
    return [
        Record(id="ok", metadata={"source": "a.pdf", "author": "alice"}),
        Record(id="no_meta", metadata={}),
        Record(id="none_value", metadata={"source": None}),
        Record(id="empty_value", metadata={"source": ""}),
        Record(id="mixed_type", metadata={"source": 123}),
    ]


@pytest.fixture
def high_cardinality_records() -> list[Record]:
    return [Record(id=str(i), metadata={"uid": f"uid-{i}"}) for i in range(10)]


############################################
#     Tests for compute_metadata_stats     #
############################################

# --- Return type and non-mutation ---


def test_compute_metadata_stats_returns_dict(records: list[Record]) -> None:
    assert isinstance(compute_metadata_stats(records), dict)


def test_compute_metadata_stats_does_not_mutate_input(records: list[Record]) -> None:
    original_len = len(records)
    compute_metadata_stats(records)
    assert len(records) == original_len


# --- Empty input ---


def test_compute_metadata_stats_empty_list() -> None:
    assert compute_metadata_stats([]) == {
        "count": 0,
        "missing_metadata_count": 0,
        "avg_keys": 0,
        "min_keys": None,
        "max_keys": None,
        "distinct_keys_seen": 0,
        "per_key": {},
    }


def test_compute_metadata_stats_empty_generator() -> None:
    def gen() -> object:
        return
        yield  # pragma: no cover

    assert compute_metadata_stats(gen()) == {
        "count": 0,
        "missing_metadata_count": 0,
        "avg_keys": 0,
        "min_keys": None,
        "max_keys": None,
        "distinct_keys_seen": 0,
        "per_key": {},
    }


# --- Core stats ---


def test_compute_metadata_stats_core_stats(records: list[Record]) -> None:
    assert compute_metadata_stats(records) == {
        "count": 3,
        "missing_metadata_count": 0,
        "avg_keys": pytest.approx(1.6666666666666667),
        "min_keys": 1,
        "max_keys": 2,
        "distinct_keys_seen": 2,
        "per_key": {
            "page": {
                "present_in_records": 2,
                "missing_in_records": 1,
                "value_types": ["int"],
                "none_or_empty_count": 0,
                "unique_values_sample": [1, 2],
                "unique_values_sample_truncated": False,
            },
            "source": {
                "present_in_records": 3,
                "missing_in_records": 0,
                "value_types": ["str"],
                "none_or_empty_count": 0,
                "unique_values_sample": ["a.pdf", "b.pdf"],
                "unique_values_sample_truncated": False,
            },
        },
    }


def test_compute_metadata_stats_single_record() -> None:
    records = [Record(id="1", metadata={"source": "x"})]
    assert compute_metadata_stats(records) == {
        "count": 1,
        "missing_metadata_count": 0,
        "avg_keys": 1,
        "min_keys": 1,
        "max_keys": 1,
        "distinct_keys_seen": 1,
        "per_key": {
            "source": {
                "present_in_records": 1,
                "missing_in_records": 0,
                "value_types": ["str"],
                "none_or_empty_count": 0,
                "unique_values_sample": ["x"],
                "unique_values_sample_truncated": False,
            },
        },
    }


# --- Missing / empty metadata ---


def test_compute_metadata_stats_no_metadata_records() -> None:
    records = [
        Record(id="1", metadata={}),
        Record(id="2", metadata={}),
    ]
    assert compute_metadata_stats(records) == {
        "count": 2,
        "missing_metadata_count": 2,
        "avg_keys": 0,
        "min_keys": 0,
        "max_keys": 0,
        "distinct_keys_seen": 0,
        "per_key": {},
    }


def test_compute_metadata_stats_default_metadata() -> None:
    # Record.metadata defaults to an empty dict when not provided.
    records = [Record(id="1")]
    assert compute_metadata_stats(records) == {
        "count": 1,
        "missing_metadata_count": 1,
        "avg_keys": 0,
        "min_keys": 0,
        "max_keys": 0,
        "distinct_keys_seen": 0,
        "per_key": {},
    }


# --- Data quality: types, none/empty values ---


def test_compute_metadata_stats_messy_records(messy_records: list[Record]) -> None:
    # source values arrive in order: "a.pdf", None, "", 123.
    # The sample (n_sample_values=3) fills up with "a.pdf", None, "" - by the
    # time the new distinct value 123 arrives the cap is already reached, so
    # it's excluded and the key is marked truncated.
    assert compute_metadata_stats(messy_records) == {
        "count": 5,
        "missing_metadata_count": 1,
        "avg_keys": pytest.approx(1.0),
        "min_keys": 0,
        "max_keys": 2,
        "distinct_keys_seen": 2,
        "per_key": {
            "author": {
                "present_in_records": 1,
                "missing_in_records": 4,
                "value_types": ["str"],
                "none_or_empty_count": 0,
                "unique_values_sample": ["alice"],
                "unique_values_sample_truncated": False,
            },
            "source": {
                "present_in_records": 4,
                "missing_in_records": 1,
                "value_types": ["NoneType", "int", "str"],
                "none_or_empty_count": 2,
                "unique_values_sample": ["", None, "a.pdf"],
                "unique_values_sample_truncated": True,
            },
        },
    }


# --- n_sample_values behavior ---


def test_compute_metadata_stats_default_n_sample_values_caps_at_three(
    high_cardinality_records: list[Record],
) -> None:
    assert compute_metadata_stats(high_cardinality_records) == {
        "count": 10,
        "missing_metadata_count": 0,
        "avg_keys": 1,
        "min_keys": 1,
        "max_keys": 1,
        "distinct_keys_seen": 1,
        "per_key": {
            "uid": {
                "present_in_records": 10,
                "missing_in_records": 0,
                "value_types": ["str"],
                "none_or_empty_count": 0,
                "unique_values_sample": ["uid-0", "uid-1", "uid-2"],
                "unique_values_sample_truncated": True,
            },
        },
    }


def test_compute_metadata_stats_n_sample_values_none_tracks_all(
    high_cardinality_records: list[Record],
) -> None:
    assert compute_metadata_stats(high_cardinality_records, n_sample_values=None) == {
        "count": 10,
        "missing_metadata_count": 0,
        "avg_keys": 1,
        "min_keys": 1,
        "max_keys": 1,
        "distinct_keys_seen": 1,
        "per_key": {
            "uid": {
                "present_in_records": 10,
                "missing_in_records": 0,
                "value_types": ["str"],
                "none_or_empty_count": 0,
                "unique_values_sample": sorted(f"uid-{i}" for i in range(10)),
                "unique_values_sample_truncated": False,
            },
        },
    }


def test_compute_metadata_stats_n_sample_values_zero(
    high_cardinality_records: list[Record],
) -> None:
    assert compute_metadata_stats(high_cardinality_records, n_sample_values=0) == {
        "count": 10,
        "missing_metadata_count": 0,
        "avg_keys": 1,
        "min_keys": 1,
        "max_keys": 1,
        "distinct_keys_seen": 1,
        "per_key": {
            "uid": {
                "present_in_records": 10,
                "missing_in_records": 0,
                "value_types": ["str"],
                "none_or_empty_count": 0,
                "unique_values_sample": [],
                "unique_values_sample_truncated": True,
            },
        },
    }


def test_compute_metadata_stats_n_sample_values_exact_boundary() -> None:
    records = [Record(id=str(i), metadata={"k": i}) for i in range(3)]
    assert compute_metadata_stats(records, n_sample_values=3) == {
        "count": 3,
        "missing_metadata_count": 0,
        "avg_keys": 1,
        "min_keys": 1,
        "max_keys": 1,
        "distinct_keys_seen": 1,
        "per_key": {
            "k": {
                "present_in_records": 3,
                "missing_in_records": 0,
                "value_types": ["int"],
                "none_or_empty_count": 0,
                "unique_values_sample": [0, 1, 2],
                "unique_values_sample_truncated": False,
            },
        },
    }


def test_compute_metadata_stats_n_sample_values_one_more_than_boundary() -> None:
    records = [Record(id=str(i), metadata={"k": i}) for i in range(4)]
    assert compute_metadata_stats(records, n_sample_values=3) == {
        "count": 4,
        "missing_metadata_count": 0,
        "avg_keys": 1,
        "min_keys": 1,
        "max_keys": 1,
        "distinct_keys_seen": 1,
        "per_key": {
            "k": {
                "present_in_records": 4,
                "missing_in_records": 0,
                "value_types": ["int"],
                "none_or_empty_count": 0,
                "unique_values_sample": [0, 1, 2],
                "unique_values_sample_truncated": True,
            },
        },
    }


def test_compute_metadata_stats_repeated_value_does_not_count_against_cap() -> None:
    # The same value repeated should not itself trigger truncation - only a
    # *new* distinct value arriving once the sample is full does.
    records = [Record(id=str(i), metadata={"k": "a"}) for i in range(4)]
    assert compute_metadata_stats(records, n_sample_values=1) == {
        "count": 4,
        "missing_metadata_count": 0,
        "avg_keys": 1,
        "min_keys": 1,
        "max_keys": 1,
        "distinct_keys_seen": 1,
        "per_key": {
            "k": {
                "present_in_records": 4,
                "missing_in_records": 0,
                "value_types": ["str"],
                "none_or_empty_count": 0,
                "unique_values_sample": ["a"],
                "unique_values_sample_truncated": False,
            },
        },
    }


# --- Unhashable values ---


def test_compute_metadata_stats_unhashable_container_value_marks_truncated() -> None:
    records = [
        Record(id="1", metadata={"tags": ["a", "b"]}),
        Record(id="2", metadata={"tags": ["c"]}),
    ]
    assert compute_metadata_stats(records) == {
        "count": 2,
        "missing_metadata_count": 0,
        "avg_keys": 1,
        "min_keys": 1,
        "max_keys": 1,
        "distinct_keys_seen": 1,
        "per_key": {
            "tags": {
                "present_in_records": 2,
                "missing_in_records": 0,
                "value_types": ["list"],
                "none_or_empty_count": 0,
                "unique_values_sample": [],
                "unique_values_sample_truncated": True,
            },
        },
    }


def test_compute_metadata_stats_unhashable_container_with_n_sample_values_none() -> None:
    records = [Record(id="1", metadata={"tags": ["a", "b"]})]
    assert compute_metadata_stats(records, n_sample_values=None) == {
        "count": 1,
        "missing_metadata_count": 0,
        "avg_keys": 1,
        "min_keys": 1,
        "max_keys": 1,
        "distinct_keys_seen": 1,
        "per_key": {
            "tags": {
                "present_in_records": 1,
                "missing_in_records": 0,
                "value_types": ["list"],
                "none_or_empty_count": 0,
                "unique_values_sample": [],
                "unique_values_sample_truncated": True,
            },
        },
    }


def test_compute_metadata_stats_unhashable_non_container_value_marks_truncated() -> None:
    # bytearray is unhashable but isn't a list/dict/set, so it falls through
    # to the `values.add(value)` / `value not in values` calls, which raise
    # TypeError and are caught to mark the key as truncated.
    records = [Record(id="1", metadata={"blob": bytearray(b"abc")})]
    assert compute_metadata_stats(records) == {
        "count": 1,
        "missing_metadata_count": 0,
        "avg_keys": 1,
        "min_keys": 1,
        "max_keys": 1,
        "distinct_keys_seen": 1,
        "per_key": {
            "blob": {
                "present_in_records": 1,
                "missing_in_records": 0,
                "value_types": ["bytearray"],
                "none_or_empty_count": 0,
                "unique_values_sample": [],
                "unique_values_sample_truncated": True,
            },
        },
    }


# --- Iterator / generator support ---


def test_compute_metadata_stats_generator_input() -> None:
    def gen() -> object:
        yield Record(id="1", metadata={"source": "a"})
        yield Record(id="2", metadata={"source": "b", "page": 1})

    assert compute_metadata_stats(gen()) == {
        "count": 2,
        "missing_metadata_count": 0,
        "avg_keys": pytest.approx(1.5),
        "min_keys": 1,
        "max_keys": 2,
        "distinct_keys_seen": 2,
        "per_key": {
            "page": {
                "present_in_records": 1,
                "missing_in_records": 1,
                "value_types": ["int"],
                "none_or_empty_count": 0,
                "unique_values_sample": [1],
                "unique_values_sample_truncated": False,
            },
            "source": {
                "present_in_records": 2,
                "missing_in_records": 0,
                "value_types": ["str"],
                "none_or_empty_count": 0,
                "unique_values_sample": ["a", "b"],
                "unique_values_sample_truncated": False,
            },
        },
    }


def test_compute_metadata_stats_generator_consumed_only_once() -> None:
    def gen() -> object:
        yield Record(id="1", metadata={"source": "a"})

    g = gen()
    compute_metadata_stats(g)
    assert list(g) == []


def test_compute_metadata_stats_map_iterator() -> None:
    sources = ["a.pdf", "b.pdf", "c.pdf"]
    records_iter = (Record(id=s, metadata={"source": s}) for s in sources)
    assert compute_metadata_stats(records_iter) == {
        "count": 3,
        "missing_metadata_count": 0,
        "avg_keys": 1,
        "min_keys": 1,
        "max_keys": 1,
        "distinct_keys_seen": 1,
        "per_key": {
            "source": {
                "present_in_records": 3,
                "missing_in_records": 0,
                "value_types": ["str"],
                "none_or_empty_count": 0,
                "unique_values_sample": ["a.pdf", "b.pdf", "c.pdf"],
                "unique_values_sample_truncated": False,
            },
        },
    }


# --- Larger scale sanity check ---


def test_compute_metadata_stats_thousand_records() -> None:
    records = [Record(id=str(i), metadata={"source": "x", "idx": i}) for i in range(1000)]
    assert compute_metadata_stats(records) == {
        "count": 1000,
        "missing_metadata_count": 0,
        "avg_keys": 2,
        "min_keys": 2,
        "max_keys": 2,
        "distinct_keys_seen": 2,
        "per_key": {
            "idx": {
                "present_in_records": 1000,
                "missing_in_records": 0,
                "value_types": ["int"],
                "none_or_empty_count": 0,
                "unique_values_sample": [0, 1, 2],
                "unique_values_sample_truncated": True,
            },
            "source": {
                "present_in_records": 1000,
                "missing_in_records": 0,
                "value_types": ["str"],
                "none_or_empty_count": 0,
                "unique_values_sample": ["x"],
                "unique_values_sample_truncated": False,
            },
        },
    }


###################################
#     Tests for MetadataStats     #
###################################


def test_metadata_stats_starts_at_zero() -> None:
    assert MetadataStats().to_dict() == compute_metadata_stats([])


def test_metadata_stats_manual_update_calls() -> None:
    stats = MetadataStats()
    stats.update(Record(id="1", metadata={"source": "a"}))
    stats.update(Record(id="2", metadata={"source": "b", "page": 1}))
    assert stats.to_dict() == {
        "count": 2,
        "missing_metadata_count": 0,
        "avg_keys": pytest.approx(1.5),
        "min_keys": 1,
        "max_keys": 2,
        "distinct_keys_seen": 2,
        "per_key": {
            "page": {
                "present_in_records": 1,
                "missing_in_records": 1,
                "value_types": ["int"],
                "none_or_empty_count": 0,
                "unique_values_sample": [1],
                "unique_values_sample_truncated": False,
            },
            "source": {
                "present_in_records": 2,
                "missing_in_records": 0,
                "value_types": ["str"],
                "none_or_empty_count": 0,
                "unique_values_sample": ["a", "b"],
                "unique_values_sample_truncated": False,
            },
        },
    }


def test_metadata_stats_to_dict_is_idempotent() -> None:
    stats = MetadataStats()
    stats.update(Record(id="1", metadata={"source": "a"}))
    assert stats.to_dict() == stats.to_dict()


def test_metadata_stats_custom_n_sample_values_constructor() -> None:
    stats = MetadataStats(n_sample_values=1)
    stats.update(Record(id="1", metadata={"source": "a"}))
    stats.update(Record(id="2", metadata={"source": "b"}))
    assert stats.to_dict() == {
        "count": 2,
        "missing_metadata_count": 0,
        "avg_keys": 1,
        "min_keys": 1,
        "max_keys": 1,
        "distinct_keys_seen": 1,
        "per_key": {
            "source": {
                "present_in_records": 2,
                "missing_in_records": 0,
                "value_types": ["str"],
                "none_or_empty_count": 0,
                "unique_values_sample": ["a"],
                "unique_values_sample_truncated": True,
            },
        },
    }
