# Testing Helpers

:book: This page describes `persista.testing.fixtures`, which provides `pytest` markers to skip
tests based on whether an optional dependency is installed.

**Prerequisites:** You'll need to know a bit of Python and [`pytest`](https://docs.pytest.org/).
`pytest` must be installed to use these fixtures; `persista.testing` is not a runtime dependency
of `persista` itself.

## Overview

Several `persista` stores and utilities depend on optional packages (`aiosqlite`, `duckdb`,
`faker`, `lmdb`, `psycopg`, `redis`, `requests`, `urllib3`). `persista.testing.fixtures` exposes,
for each of these, a pair of `pytest` markers:

- `<dep>_available`: skip the test unless `<dep>` is installed
- `<dep>_not_available`: skip the test if `<dep>` is installed

For example, `lmdb_available` and `lmdb_not_available` are available for the `lmdb` package, and
similarly for the other optional dependencies.

## Skipping Tests Based on Optional Dependencies

Use `<dep>_available` to only run a test when the corresponding package is installed, for example
a test that exercises `LmdbStore`:

```python
from persista.store import LmdbStore
from persista.testing.fixtures import lmdb_available


@lmdb_available
def test_lmdb_store_set_get(tmp_path):
    store = LmdbStore(tmp_path / "db")
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

Markers are provided for: `aiosqlite`, `duckdb`, `faker`, `lmdb`, `psycopg`, `redis`, `requests`,
and `urllib3`. Import them directly from `persista.testing.fixtures`, for example:

```python
from persista.testing.fixtures import (
    duckdb_available,
    psycopg_available,
    redis_available,
)
```

## API Reference

See the [reference documentation](../refs/testing.md) for the full API.
