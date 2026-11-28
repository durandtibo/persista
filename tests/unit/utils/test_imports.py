from __future__ import annotations

import re
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from persista.utils import imports

if TYPE_CHECKING:
    from collections.abc import Generator

MODULE = "persista.utils.imports"

# Each library, and the name that installs it.
LIBRARIES = [
    ("duckdb", "duckdb"),
    ("faker", "faker"),
    ("httpx", "httpx"),
    ("lmdb", "lmdb"),
    ("psycopg", "psycopg[binary]"),
    ("redis", "redis"),
    ("requests", "requests"),
    ("rich", "rich"),
    ("urllib3", "urllib3"),
]
NAMES = [name for name, _ in LIBRARIES]


def clear_caches() -> None:
    r"""Forget which libraries are available."""
    for name in NAMES:
        getattr(imports, f"is_{name}_available").cache_clear()


@pytest.fixture(autouse=True)
def _cache_clear() -> Generator[None, None, None]:
    # Cleared after the test too: a patched answer must not stay cached.
    clear_caches()
    yield
    clear_caches()


##################################
#     Tests for check_<name>     #
##################################


@pytest.mark.parametrize("name", NAMES)
def test_check_with_package(name: str) -> None:
    with patch(f"{MODULE}.is_{name}_available", lambda: True):
        getattr(imports, f"check_{name}")()


@pytest.mark.parametrize("name", NAMES)
def test_check_without_package(name: str) -> None:
    with (
        patch(f"{MODULE}.is_{name}_available", lambda: False),
        pytest.raises(RuntimeError, match=rf"'{name}' package is required but not installed."),
    ):
        getattr(imports, f"check_{name}")()


@pytest.mark.parametrize(("name", "install_name"), LIBRARIES)
def test_check_without_package_gives_install_command(name: str, install_name: str) -> None:
    with (
        patch(f"{MODULE}.is_{name}_available", lambda: False),
        pytest.raises(RuntimeError, match=re.escape(f"pip install {install_name}")),
    ):
        getattr(imports, f"check_{name}")()


#########################################
#     Tests for is_<name>_available     #
#########################################


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("available", [True, False])
def test_is_available(name: str, available: bool) -> None:
    with patch(f"{MODULE}.package_available", lambda package: available and package == name):
        assert getattr(imports, f"is_{name}_available")() is available


@pytest.mark.parametrize("name", NAMES)
def test_is_available_is_cached(name: str) -> None:
    with patch(f"{MODULE}.package_available", return_value=True) as package_available:
        getattr(imports, f"is_{name}_available")()
        getattr(imports, f"is_{name}_available")()
    package_available.assert_called_once_with(name)
