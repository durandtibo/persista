r"""Check that importing a subpackage of ``persista`` imports no optional
library, and that a store imports its driver when it needs it.

Each check runs in a fresh interpreter, because ``sys.modules`` keeps
what the other tests have imported.
"""

from __future__ import annotations

import asyncio
import json
import pkgutil
import sys

import pytest

import persista
from persista.testing.fixtures import (
    duckdb_available,
    lmdb_available,
    psycopg_available,
    redis_available,
)

OPTIONAL_LIBRARIES = (
    "duckdb",
    "faker",
    "httpx",
    "lmdb",
    "psycopg",
    "redis",
    "requests",
    "rich",
    "urllib3",
)

# persista.testing needs pytest. persista.record.analysis imports rich.
EXCLUDED = {"persista.testing", "persista.record.analysis"}

SUBPACKAGES = sorted(
    module.name
    for module in pkgutil.walk_packages(persista.__path__, "persista.")
    if module.ispkg and module.name not in EXCLUDED
)


async def imported_libraries(code: str) -> list[str]:
    r"""Run some code in a new interpreter, and return the optional
    libraries that it imported."""
    script = (
        f"import json, sys\n{code}\n"
        f"print(json.dumps([name for name in {OPTIONAL_LIBRARIES!r} if name in sys.modules]))"
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        "-c",
        script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    output, errors = await process.communicate()
    if process.returncode:
        raise RuntimeError(errors.decode())
    return json.loads(output)


##########################
#     Lazy imports     #
##########################


def test_subpackages() -> None:
    assert {"persista.store", "persista.http.httpx"} <= set(SUBPACKAGES)


@pytest.mark.parametrize("subpackage", SUBPACKAGES)
async def test_import_subpackage_imports_no_optional_library(subpackage: str) -> None:
    assert await imported_libraries(f"import {subpackage}") == []


STORES = [
    pytest.param("DuckDBStore()", "duckdb", id="duckdb", marks=duckdb_available),
    pytest.param("LmdbStore(path)", "lmdb", id="lmdb", marks=lmdb_available),
    pytest.param("RedisStore()", "redis", id="redis", marks=redis_available),
    pytest.param(
        "PostgresStore('postgresql://127.0.0.1:1/db', connect_timeout=1)",
        "psycopg",
        id="postgres",
        marks=psycopg_available,
    ),
]

SETUP = """import tempfile
from persista.store import DuckDBStore, LmdbStore, PostgresStore, RedisStore
path = tempfile.mkdtemp() + "/data"
"""


@pytest.mark.parametrize(("store", "library"), STORES)
async def test_constructor_does_not_import_the_driver(store: str, library: str) -> None:
    assert library not in await imported_libraries(f"{SETUP}{store}")


@pytest.mark.parametrize(("store", "library"), STORES)
async def test_open_imports_the_driver(store: str, library: str) -> None:
    # The servers are not reachable: only the import matters.
    code = f"{SETUP}import contextlib\nwith contextlib.suppress(Exception):\n    {store}.open()"
    assert library in await imported_libraries(code)


async def test_in_memory_and_sqlite_stores_import_no_optional_library() -> None:
    code = (
        "from persista.store import InMemoryStore, SQLiteStore\n"
        "for store in (InMemoryStore(), SQLiteStore()):\n"
        "    with store:\n"
        "        store.set('a', {})\n"
        "        store.filter(a=1)\n"
        "        repr(store)"
    )
    assert await imported_libraries(code) == []


@redis_available
async def test_repr_of_a_redis_store_does_not_import_the_driver() -> None:
    code = "from persista.store import RedisStore\nrepr(RedisStore())"
    assert await imported_libraries(code) == []
