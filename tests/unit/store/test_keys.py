from __future__ import annotations

import logging

import pytest

from persista.store import split_present_missing

logger = logging.getLogger(__name__)


############################
#     split_present_missing    #
############################


def test_split_present_missing_all_present() -> None:
    assert split_present_missing(["a", "b"], [True, True]) == (["a", "b"], [])


def test_split_present_missing_all_missing() -> None:
    assert split_present_missing(["a", "b"], [False, False]) == ([], ["a", "b"])


def test_split_present_missing_mixed() -> None:
    assert split_present_missing(["a", "b", "c"], [True, False, True]) == (
        ["a", "c"],
        ["b"],
    )


def test_split_present_missing_empty() -> None:
    assert split_present_missing([], []) == ([], [])


def test_split_present_missing_mismatched_length_raises() -> None:
    with pytest.raises(ValueError, match="shorter"):
        split_present_missing(["a", "b"], [True])
