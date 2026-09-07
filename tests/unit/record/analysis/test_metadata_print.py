from __future__ import annotations

import io

import pytest
from rich.console import Console
from rich.table import Table
from rich.text import Text

from persista.record.analysis import print_metadata_stats_report
from persista.record.analysis.metadata_print import (
    _build_key_flags,
    _build_key_sample,
    _build_overview_line,
    _build_per_key_table,
    _build_summary_table,
    _format_count,
)


@pytest.fixture
def console() -> Console:
    # file=io.StringIO() avoids writing to the real terminal during tests
    return Console(file=io.StringIO(), width=100)


@pytest.fixture
def stats() -> dict:
    return {
        "count": 100,
        "missing_metadata_count": 0,
        "avg_keys": 2.0,
        "min_keys": 2,
        "max_keys": 2,
        "distinct_keys_seen": 2,
        "per_key": {
            "author": {
                "present_in_records": 100,
                "missing_in_records": 0,
                "value_types": ["str"],
                "none_or_empty_count": 0,
                "unique_values_sample": ["Jesse Flowers", "Michelle Miles", "Zachary Taylor"],
                "unique_values_sample_truncated": True,
            },
            "topic": {
                "present_in_records": 100,
                "missing_in_records": 0,
                "value_types": ["str"],
                "none_or_empty_count": 0,
                "unique_values_sample": ["commercial", "kind", "minute"],
                "unique_values_sample_truncated": True,
            },
        },
    }


@pytest.fixture
def dirty_stats() -> dict:
    return {
        "count": 50,
        "missing_metadata_count": 5,
        "avg_keys": 1.2,
        "min_keys": 0,
        "max_keys": 3,
        "distinct_keys_seen": 3,
        "per_key": {
            "source": {
                "present_in_records": 45,
                "missing_in_records": 5,
                "value_types": ["str", "int"],
                "none_or_empty_count": 2,
                "unique_values_sample": ["a.pdf"],
                "unique_values_sample_truncated": False,
            },
        },
    }


@pytest.fixture
def empty_stats() -> dict:
    return {
        "count": 0,
        "missing_metadata_count": 0,
        "avg_keys": 0,
        "min_keys": None,
        "max_keys": None,
        "distinct_keys_seen": 0,
        "per_key": {},
    }


###################################
#     Tests for _format_count     #
###################################


def test_format_count_normal() -> None:
    assert _format_count(3, 1000) == "3 (0.3%)"


def test_format_count_zero_total() -> None:
    assert _format_count(0, 0) == "0 (0.0%)"


def test_format_count_zero_count() -> None:
    assert _format_count(0, 100) == "0 (0.0%)"


def test_format_count_full() -> None:
    assert _format_count(10, 10) == "10 (100.0%)"


##########################################
#     Tests for _build_overview_line     #
##########################################


def test_build_overview_line_returns_text(stats: dict) -> None:
    result = _build_overview_line(stats, 100)
    assert isinstance(result, Text)


def test_build_overview_line_contains_record_count(stats: dict) -> None:
    result = _build_overview_line(stats, 100)
    assert "100 records" in result.plain


def test_build_overview_line_contains_distinct_keys(stats: dict) -> None:
    result = _build_overview_line(stats, 100)
    assert "2 distinct keys" in result.plain


def test_build_overview_line_large_count_uses_separator(stats: dict) -> None:
    result = _build_overview_line(stats, 12000)
    assert "12,000 records" in result.plain


def test_build_overview_line_missing_distinct_keys_defaults_to_zero() -> None:
    result = _build_overview_line({}, 5)
    assert result.plain == "5 records  ·  0 distinct keys"


##########################################
#     Tests for _build_summary_table     #
##########################################


def test_build_summary_table_returns_table(stats: dict) -> None:
    result = _build_summary_table(stats, 100)
    assert isinstance(result, Table)


def test_build_summary_table_missing_optional_keys_does_not_raise() -> None:
    minimal_stats = {
        "avg_keys": 1.0,
        "min_keys": 1,
        "max_keys": 1,
        "missing_metadata_count": 0,
    }
    result = _build_summary_table(minimal_stats, 10)
    assert isinstance(result, Table)


#######################################
#     Tests for _build_key_flags     #
#######################################


def test_build_key_flags_ok_when_clean() -> None:
    info = {"missing_in_records": 0, "value_types": ["str"], "none_or_empty_count": 0}
    assert _build_key_flags(info) == "[green]ok[/green]"


def test_build_key_flags_missing_values() -> None:
    info = {"missing_in_records": 5, "value_types": ["str"], "none_or_empty_count": 0}
    assert "missing values" in _build_key_flags(info)


def test_build_key_flags_mixed_types() -> None:
    info = {"missing_in_records": 0, "value_types": ["str", "int"], "none_or_empty_count": 0}
    assert "mixed types" in _build_key_flags(info)


def test_build_key_flags_has_none_empty() -> None:
    info = {"missing_in_records": 0, "value_types": ["str"], "none_or_empty_count": 2}
    assert "has None/empty" in _build_key_flags(info)


def test_build_key_flags_all_combined() -> None:
    info = {"missing_in_records": 1, "value_types": ["str", "int"], "none_or_empty_count": 1}
    result = _build_key_flags(info)
    assert "missing values" in result
    assert "mixed types" in result
    assert "has None/empty" in result
    assert result.count("[yellow]") == 1


def test_build_key_flags_wrapped_in_yellow_when_flagged() -> None:
    info = {"missing_in_records": 1, "value_types": ["str"], "none_or_empty_count": 0}
    result = _build_key_flags(info)
    assert result.startswith("[yellow]")
    assert result.endswith("[/yellow]")


########################################
#     Tests for _build_key_sample     #
########################################


def test_build_key_sample_untruncated() -> None:
    info = {"unique_values_sample": ["a", "b"], "unique_values_sample_truncated": False}
    assert _build_key_sample(info) == "a, b"


def test_build_key_sample_truncated_appends_ellipsis() -> None:
    info = {"unique_values_sample": ["a", "b"], "unique_values_sample_truncated": True}
    assert _build_key_sample(info) == "a, b, …"


def test_build_key_sample_empty_and_truncated() -> None:
    info = {"unique_values_sample": [], "unique_values_sample_truncated": True}
    assert _build_key_sample(info) == "…"


def test_build_key_sample_empty_and_not_truncated() -> None:
    info = {"unique_values_sample": [], "unique_values_sample_truncated": False}
    assert _build_key_sample(info) == ""


def test_build_key_sample_non_string_values_stringified() -> None:
    info = {"unique_values_sample": [1, True, None], "unique_values_sample_truncated": False}
    assert _build_key_sample(info) == "1, True, None"


##########################################
#     Tests for _build_per_key_table     #
##########################################


def test_build_per_key_table_returns_table(stats: dict) -> None:
    result = _build_per_key_table(stats["per_key"], 100)
    assert isinstance(result, Table)


def test_build_per_key_table_empty_dict_returns_table() -> None:
    result = _build_per_key_table({}, 10)
    assert isinstance(result, Table)


def test_build_per_key_table_missing_keys_does_not_raise() -> None:
    sparse_per_key = {
        "x": {
            "present_in_records": 1,
            "missing_in_records": 0,
            "value_types": ["str"],
            "none_or_empty_count": 0,
            "unique_values_sample": [],
            "unique_values_sample_truncated": False,
        }
    }
    result = _build_per_key_table(sparse_per_key, 1)
    assert isinstance(result, Table)


###############################################
#     Tests for print_metadata_stats_report    #
###############################################


def test_print_metadata_stats_report_runs_without_error(stats: dict, console: Console) -> None:
    print_metadata_stats_report(stats, console=console)


def test_print_metadata_stats_report_dirty_runs_without_error(
    dirty_stats: dict, console: Console
) -> None:
    print_metadata_stats_report(dirty_stats, console=console)


def test_print_metadata_stats_report_empty_runs_without_error(
    empty_stats: dict, console: Console
) -> None:
    print_metadata_stats_report(empty_stats, console=console)


def test_print_metadata_stats_report_creates_own_console_if_none_given(
    stats: dict,
) -> None:
    # no console passed -> should fall back to the shared rich console internally
    print_metadata_stats_report(stats)


def test_print_metadata_stats_report_custom_title(stats: dict, console: Console) -> None:
    print_metadata_stats_report(stats, title="Custom Title", console=console)


def test_print_metadata_stats_report_no_per_key_data(console: Console) -> None:
    stats_without_keys = {
        "count": 10,
        "missing_metadata_count": 0,
        "avg_keys": 0,
        "min_keys": 0,
        "max_keys": 0,
        "distinct_keys_seen": 0,
        "per_key": {},
    }
    print_metadata_stats_report(stats_without_keys, console=console)


def test_print_metadata_stats_report_missing_optional_per_key_field(
    console: Console,
) -> None:
    # per_key present but missing_metadata_count/avg_keys/etc all zero -
    # should not raise, since the report is meant to render a clean corpus
    minimal_stats = {
        "count": 5,
        "missing_metadata_count": 0,
        "avg_keys": 1.0,
        "min_keys": 1,
        "max_keys": 1,
        "distinct_keys_seen": 1,
        "per_key": {
            "id": {
                "present_in_records": 5,
                "missing_in_records": 0,
                "value_types": ["str"],
                "none_or_empty_count": 0,
                "unique_values_sample": ["a", "b", "c"],
                "unique_values_sample_truncated": False,
            }
        },
    }
    print_metadata_stats_report(minimal_stats, console=console)


def test_print_metadata_stats_report_does_not_mutate_input(stats: dict, console: Console) -> None:
    original = dict(stats)
    print_metadata_stats_report(stats, console=console)
    assert stats == original
