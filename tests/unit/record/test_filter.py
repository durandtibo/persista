from __future__ import annotations

import pytest

from persista.record import (
    Record,
    filter_by_metadata,
    filter_by_metadata_range,
    filter_by_metadata_values,
)


@pytest.fixture
def records() -> list[Record]:
    return [
        Record(id="a", metadata={"category": "Science", "page": 1}),
        Record(id="b", metadata={"category": "Cooking", "page": 2}),
        Record(id="c", metadata={"category": "Science", "page": 3}),
        Record(id="d", metadata={"category": "Technology", "page": 4}),
    ]


@pytest.fixture
def page_records() -> list[Record]:
    return [
        Record(id="a", metadata={"page": 1}),
        Record(id="b", metadata={"page": 5}),
        Record(id="c", metadata={"page": 10}),
        Record(id="d", metadata={"page": 15}),
    ]


@pytest.fixture
def category_records() -> list[Record]:
    return [
        Record(id="a", metadata={"category": "Science", "page": 1}),
        Record(id="b", metadata={"category": "Cooking", "page": 2}),
        Record(id="c", metadata={"category": "Technology", "page": 3}),
        Record(id="d", metadata={"category": "Science", "page": 4}),
    ]


##########################################
#     Tests for filter_by_metadata       #
##########################################


# --- Return type and non-mutation ---


def test_filter_by_metadata_returns_list(records: list[Record]) -> None:
    assert isinstance(filter_by_metadata(records, "category", "Science"), list)


def test_filter_by_metadata_does_not_mutate_input(records: list[Record]) -> None:
    original_len = len(records)
    filter_by_metadata(records, "category", "Science")
    assert len(records) == original_len


def test_filter_by_metadata_returns_new_list(records: list[Record]) -> None:
    assert filter_by_metadata(records, "category", "Science") is not records


# --- Filtering ---


def test_filter_by_metadata_matching_records(records: list[Record]) -> None:
    assert filter_by_metadata(records, "category", "Science") == [
        Record(id="a", metadata={"category": "Science", "page": 1}),
        Record(id="c", metadata={"category": "Science", "page": 3}),
    ]


def test_filter_by_metadata_no_match(records: list[Record]) -> None:
    assert filter_by_metadata(records, "category", "Sports") == []


def test_filter_by_metadata_all_match(records: list[Record]) -> None:
    result = filter_by_metadata(records, "category", "Science")
    assert all(r.metadata["category"] == "Science" for r in result)


def test_filter_by_metadata_integer_value() -> None:
    records = [
        Record(id="a", metadata={"page": 1}),
        Record(id="b", metadata={"page": 2}),
        Record(id="c", metadata={"page": 1}),
    ]
    assert filter_by_metadata(records, "page", 1) == [
        Record(id="a", metadata={"page": 1}),
        Record(id="c", metadata={"page": 1}),
    ]


def test_filter_by_metadata_boolean_value() -> None:
    records = [
        Record(id="a", metadata={"published": True}),
        Record(id="b", metadata={"published": False}),
        Record(id="c", metadata={"published": True}),
    ]
    assert filter_by_metadata(records, "published", True) == [
        Record(id="a", metadata={"published": True}),
        Record(id="c", metadata={"published": True}),
    ]


# --- Missing keys ---


def test_filter_by_metadata_missing_key_excluded() -> None:
    records = [
        Record(id="a", metadata={"category": "Science"}),
        Record(id="b"),
    ]
    assert filter_by_metadata(records, "category", "Science") == [
        Record(id="a", metadata={"category": "Science"}),
    ]


def test_filter_by_metadata_all_missing_key_returns_empty() -> None:
    records = [Record(id="a"), Record(id="b")]
    assert filter_by_metadata(records, "category", "Science") == []


# --- Edge cases ---


def test_filter_by_metadata_empty_list() -> None:
    assert filter_by_metadata([], "category", "Science") == []


def test_filter_by_metadata_single_match() -> None:
    assert filter_by_metadata(
        [Record(id="a", metadata={"category": "Science"})],
        "category",
        "Science",
    ) == [Record(id="a", metadata={"category": "Science"})]


def test_filter_by_metadata_single_no_match() -> None:
    assert (
        filter_by_metadata(
            [Record(id="a", metadata={"category": "Cooking"})],
            "category",
            "Science",
        )
        == []
    )


def test_filter_by_metadata_preserves_order(records: list[Record]) -> None:
    assert filter_by_metadata(records, "category", "Science") == [
        Record(id="a", metadata={"category": "Science", "page": 1}),
        Record(id="c", metadata={"category": "Science", "page": 3}),
    ]


###############################################
#     Tests for filter_by_metadata_range      #
###############################################


# --- Return type and non-mutation ---


def test_filter_by_metadata_range_returns_list(page_records: list[Record]) -> None:
    assert isinstance(filter_by_metadata_range(page_records, "page", lower=1), list)


def test_filter_by_metadata_range_does_not_mutate_input(page_records: list[Record]) -> None:
    original_len = len(page_records)
    filter_by_metadata_range(page_records, "page", lower=1, upper=10)
    assert len(page_records) == original_len


def test_filter_by_metadata_range_returns_new_list(page_records: list[Record]) -> None:
    assert filter_by_metadata_range(page_records, "page", lower=1) is not page_records


# --- Both bounds ---


def test_filter_by_metadata_range_lower_and_upper(page_records: list[Record]) -> None:
    assert filter_by_metadata_range(page_records, "page", lower=2, upper=8) == [
        Record(id="b", metadata={"page": 5}),
    ]


def test_filter_by_metadata_range_inclusive_lower_bound(page_records: list[Record]) -> None:
    assert filter_by_metadata_range(page_records, "page", lower=5, upper=10) == [
        Record(id="b", metadata={"page": 5}),
        Record(id="c", metadata={"page": 10}),
    ]


def test_filter_by_metadata_range_inclusive_upper_bound(page_records: list[Record]) -> None:
    assert filter_by_metadata_range(page_records, "page", lower=1, upper=5) == [
        Record(id="a", metadata={"page": 1}),
        Record(id="b", metadata={"page": 5}),
    ]


# --- Lower bound only ---


def test_filter_by_metadata_range_lower_only(page_records: list[Record]) -> None:
    assert filter_by_metadata_range(page_records, "page", lower=5) == [
        Record(id="b", metadata={"page": 5}),
        Record(id="c", metadata={"page": 10}),
        Record(id="d", metadata={"page": 15}),
    ]


# --- Upper bound only ---


def test_filter_by_metadata_range_upper_only(page_records: list[Record]) -> None:
    assert filter_by_metadata_range(page_records, "page", upper=5) == [
        Record(id="a", metadata={"page": 1}),
        Record(id="b", metadata={"page": 5}),
    ]


# --- Both bounds None ---


def test_filter_by_metadata_range_no_bounds_returns_records_with_key(
    page_records: list[Record],
) -> None:
    records_with_missing = [*page_records, Record(id="x")]
    assert filter_by_metadata_range(records_with_missing, "page") == [
        Record(id="a", metadata={"page": 1}),
        Record(id="b", metadata={"page": 5}),
        Record(id="c", metadata={"page": 10}),
        Record(id="d", metadata={"page": 15}),
    ]


# --- Missing keys ---


def test_filter_by_metadata_range_missing_key_excluded() -> None:
    records = [
        Record(id="a", metadata={"page": 5}),
        Record(id="b"),
    ]
    assert filter_by_metadata_range(records, "page", lower=1, upper=10) == [
        Record(id="a", metadata={"page": 5}),
    ]


def test_filter_by_metadata_range_all_missing_key_returns_empty() -> None:
    records = [Record(id="a"), Record(id="b")]
    assert filter_by_metadata_range(records, "page", lower=1, upper=10) == []


# --- No match ---


def test_filter_by_metadata_range_no_match(page_records: list[Record]) -> None:
    assert filter_by_metadata_range(page_records, "page", lower=20, upper=30) == []


# --- Edge cases ---


def test_filter_by_metadata_range_empty_list() -> None:
    assert filter_by_metadata_range([], "page", lower=1, upper=10) == []


def test_filter_by_metadata_range_exact_match() -> None:
    assert filter_by_metadata_range(
        [Record(id="a", metadata={"page": 5})],
        "page",
        lower=5,
        upper=5,
    ) == [Record(id="a", metadata={"page": 5})]


###################################################
#     Tests for filter_by_metadata_values         #
###################################################


# --- Return type and non-mutation ---


def test_filter_by_metadata_values_returns_list(category_records: list[Record]) -> None:
    assert isinstance(filter_by_metadata_values(category_records, "category", {"Science"}), list)


def test_filter_by_metadata_values_does_not_mutate_input(category_records: list[Record]) -> None:
    original_len = len(category_records)
    filter_by_metadata_values(category_records, "category", {"Science"})
    assert len(category_records) == original_len


def test_filter_by_metadata_values_returns_new_list(category_records: list[Record]) -> None:
    assert (
        filter_by_metadata_values(category_records, "category", {"Science"}) is not category_records
    )


# --- Filtering ---


def test_filter_by_metadata_values_single_value(category_records: list[Record]) -> None:
    assert filter_by_metadata_values(category_records, "category", {"Science"}) == [
        Record(id="a", metadata={"category": "Science", "page": 1}),
        Record(id="d", metadata={"category": "Science", "page": 4}),
    ]


def test_filter_by_metadata_values_multiple_values(category_records: list[Record]) -> None:
    assert filter_by_metadata_values(category_records, "category", {"Science", "Technology"}) == [
        Record(id="a", metadata={"category": "Science", "page": 1}),
        Record(id="c", metadata={"category": "Technology", "page": 3}),
        Record(id="d", metadata={"category": "Science", "page": 4}),
    ]


def test_filter_by_metadata_values_all_values(category_records: list[Record]) -> None:
    assert (
        filter_by_metadata_values(
            category_records, "category", {"Science", "Cooking", "Technology"}
        )
        == category_records
    )


def test_filter_by_metadata_values_no_match(category_records: list[Record]) -> None:
    assert filter_by_metadata_values(category_records, "category", {"Sports"}) == []


def test_filter_by_metadata_values_integer_values() -> None:
    records = [
        Record(id="a", metadata={"page": 1}),
        Record(id="b", metadata={"page": 2}),
        Record(id="c", metadata={"page": 3}),
    ]
    assert filter_by_metadata_values(records, "page", {1, 3}) == [
        Record(id="a", metadata={"page": 1}),
        Record(id="c", metadata={"page": 3}),
    ]


# --- Missing keys ---


def test_filter_by_metadata_values_missing_key_excluded() -> None:
    records = [
        Record(id="a", metadata={"category": "Science"}),
        Record(id="b"),
    ]
    assert filter_by_metadata_values(records, "category", {"Science"}) == [
        Record(id="a", metadata={"category": "Science"}),
    ]


def test_filter_by_metadata_values_all_missing_key_returns_empty() -> None:
    records = [Record(id="a"), Record(id="b")]
    assert filter_by_metadata_values(records, "category", {"Science"}) == []


# --- Edge cases ---


def test_filter_by_metadata_values_empty_list() -> None:
    assert filter_by_metadata_values([], "category", {"Science"}) == []


def test_filter_by_metadata_values_empty_set(category_records: list[Record]) -> None:
    assert filter_by_metadata_values(category_records, "category", set()) == []


def test_filter_by_metadata_values_single_record_match() -> None:
    records = [Record(id="a", metadata={"category": "Science"})]
    assert filter_by_metadata_values(records, "category", {"Science"}) == [
        Record(id="a", metadata={"category": "Science"}),
    ]


def test_filter_by_metadata_values_single_record_no_match() -> None:
    records = [Record(id="a", metadata={"category": "Cooking"})]
    assert filter_by_metadata_values(records, "category", {"Science"}) == []


def test_filter_by_metadata_values_preserves_order(category_records: list[Record]) -> None:
    assert filter_by_metadata_values(category_records, "category", {"Science", "Cooking"}) == [
        Record(id="a", metadata={"category": "Science", "page": 1}),
        Record(id="b", metadata={"category": "Cooking", "page": 2}),
        Record(id="d", metadata={"category": "Science", "page": 4}),
    ]
