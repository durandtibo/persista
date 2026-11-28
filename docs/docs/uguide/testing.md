# Testing Helpers

:book: This page describes `persista.testing.fixtures`, which provides `pytest` markers to skip
tests based on whether an optional dependency is installed.

**Prerequisites:** You'll need to know a bit of Python and [`pytest`](https://docs.pytest.org/).
`pytest` must be installed to use these fixtures; `persista.testing` is not a runtime dependency
of `persista` itself.

## Overview

Several `persista` stores and utilities depend on optional packages (`duckdb`, `faker`,
`httpx`, `lmdb`, `psycopg`, `redis`, `requests`, `rich`, `urllib3`). `persista.testing.fixtures`
exposes, for each of these, a pair of `pytest` markers:

- `<dep>_available`: skip the test unless `<dep>` is installed
- `<dep>_not_available`: skip the test if `<dep>` is installed

For example, `lmdb_available` and `lmdb_not_available` are available for the `lmdb` package, and
similarly for the other optional dependencies.

## Properties

| Property               | Guarantee                                                                                                                      |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Utilities are a leaf   | `persista.utils` holds the helpers of the other sub-packages and imports none of them.                                         |
| Optional dependencies  | `persista.utils.imports` has `is_<name>_available` and `check_<name>` for every optional library. Neither imports the library. |
| Testing stays in tests | `persista.testing` needs `pytest`, and no library code imports it.                                                             |

A mark tells whether a library is installed, not whether a server that it talks to is reachable.

## Checking for an Optional Dependency

`is_<name>_available` returns whether a library is installed, and `check_<name>` raises
`RuntimeError`, with the command that installs it, if it is not:

```pycon
>>> from persista.utils.imports import check_lmdb, is_lmdb_available
>>> if is_lmdb_available():
...     check_lmdb()

```

## Skipping Tests Based on Optional Dependencies

Use `<dep>_available` to only run a test when the corresponding package is installed, for example
a test that exercises `LmdbStore`:

```python
from persista.store import LmdbStore
from persista.testing.fixtures import lmdb_available


@lmdb_available
def test_lmdb_store_set_get(tmp_path):
    with LmdbStore(tmp_path / "db") as store:
        store.set("1", {"value": 42})
        assert store.get("1") == {"value": 42}
```

Use `<dep>_not_available` for the opposite case, e.g. verifying that a helpful error is raised
when a required optional dependency is missing:

```python
import pytest

from persista.testing.fixtures import lmdb_not_available


@lmdb_not_available
def test_lmdb_store_requires_lmdb():
    with pytest.raises(RuntimeError, match="'lmdb' package is required"):
        from persista.store import LmdbStore

        LmdbStore("/tmp/lmdb_store")
```

## Available Markers

Markers are provided for: `duckdb`, `faker`, `httpx`, `lmdb`, `psycopg`, `redis`, `requests`,
`rich`, and `urllib3`. Import them directly from `persista.testing.fixtures`, for example:

```python
from persista.testing.fixtures import (
    duckdb_available,
    psycopg_available,
    redis_available,
)
```

## API Reference

See the [reference documentation](../refs/testing.md) for the full API.
