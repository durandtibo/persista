from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from persista.testing import fixtures
from persista.utils.imports import (
    is_aiosqlite_available,
    is_duckdb_available,
    is_faker_available,
    is_lmdb_available,
    is_psycopg_available,
    is_redis_available,
    is_requests_available,
    is_urllib3_available,
)

if TYPE_CHECKING:
    from collections.abc import Callable

# Maps each pair of exported marker names to the availability check they
# should mirror. ``httpx`` is defined in the module but intentionally not
# part of ``__all__``, so it is included separately below.
PAIRS = {
    "aiosqlite": is_aiosqlite_available,
    "duckdb": is_duckdb_available,
    "faker": is_faker_available,
    "lmdb": is_lmdb_available,
    "psycopg": is_psycopg_available,
    "redis": is_redis_available,
    "requests": is_requests_available,
    "urllib3": is_urllib3_available,
}


def test_all_exports_available_and_not_available_pairs() -> None:
    for name in PAIRS:
        assert f"{name}_available" in fixtures.__all__
        assert f"{name}_not_available" in fixtures.__all__


@pytest.mark.parametrize("name", list(PAIRS.keys()))
def test_available_marker_is_skipif_mark_decorator(name: str) -> None:
    marker = getattr(fixtures, f"{name}_available")
    assert isinstance(marker, pytest.MarkDecorator)
    assert marker.mark.name == "skipif"


@pytest.mark.parametrize("name", list(PAIRS.keys()))
def test_not_available_marker_is_skipif_mark_decorator(name: str) -> None:
    marker = getattr(fixtures, f"{name}_not_available")
    assert isinstance(marker, pytest.MarkDecorator)
    assert marker.mark.name == "skipif"


@pytest.mark.parametrize(("name", "is_available"), list(PAIRS.items()))
def test_available_marker_skip_condition_matches_is_available(
    name: str, is_available: Callable[[], bool]
) -> None:
    marker = getattr(fixtures, f"{name}_available")
    # The skipif condition is computed eagerly at import time.
    assert marker.mark.args[0] is (not is_available())


@pytest.mark.parametrize(("name", "is_available"), list(PAIRS.items()))
def test_not_available_marker_skip_condition_matches_is_available(
    name: str, is_available: Callable[[], bool]
) -> None:
    marker = getattr(fixtures, f"{name}_not_available")
    assert marker.mark.args[0] is is_available()


@pytest.mark.parametrize("name", list(PAIRS.keys()))
def test_available_and_not_available_have_opposite_skip_conditions(name: str) -> None:
    available_marker = getattr(fixtures, f"{name}_available")
    not_available_marker = getattr(fixtures, f"{name}_not_available")
    assert available_marker.mark.args[0] != not_available_marker.mark.args[0]
