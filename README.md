# persista


<p align="center">
    <a href="https://github.com/durandtibo/persista/actions/workflows/ci.yaml">
        <img alt="CI" src="https://github.com/durandtibo/persista/actions/workflows/ci.yaml/badge.svg">
    </a>
    <a href="https://github.com/durandtibo/persista/actions/workflows/nightly-tests.yaml">
        <img alt="Nightly Tests" src="https://github.com/durandtibo/persista/actions/workflows/nightly-tests.yaml/badge.svg">
    </a>
    <a href="https://github.com/durandtibo/persista/actions/workflows/nightly-package.yaml">
        <img alt="Nightly Package Tests" src="https://github.com/durandtibo/persista/actions/workflows/nightly-package.yaml/badge.svg">
    </a>
    <a href="https://codecov.io/gh/durandtibo/persista">
        <img alt="Codecov" src="https://codecov.io/gh/durandtibo/persista/branch/main/graph/badge.svg">
    </a>
    <br/>
    <a href="https://durandtibo.github.io/persista/">
        <img alt="Documentation" src="https://github.com/durandtibo/persista/actions/workflows/docs.yaml/badge.svg">
    </a>
    <a href="https://durandtibo.github.io/persista/dev/">
        <img alt="Documentation" src="https://github.com/durandtibo/persista/actions/workflows/docs-dev.yaml/badge.svg">
    </a>
    <br/>
    <a href="https://github.com/psf/black">
        <img  alt="Code style: black" src="https://img.shields.io/badge/code%20style-black-000000.svg">
    </a>
    <a href="https://google.github.io/styleguide/pyguide.html#s3.8-comments-and-docstrings">
        <img  alt="Doc style: google" src="https://img.shields.io/badge/%20style-google-3666d6.svg">
    </a>
    <a href="https://github.com/astral-sh/ruff">
        <img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Ruff" style="max-width:100%;">
    </a>
    <a href="https://github.com/guilatrova/tryceratops">
        <img  alt="try/except style: tryceratops" src="https://img.shields.io/badge/try%2Fexcept%20style-tryceratops%20%F0%9F%A6%96%E2%9C%A8-black">
    </a>
    <br/>
    <a href="https://pypi.org/project/persista/">
        <img alt="PYPI version" src="https://img.shields.io/pypi/v/persista">
    </a>
    <a href="https://pypi.org/project/persista/">
        <img alt="Python" src="https://img.shields.io/pypi/pyversions/persista.svg">
    </a>
    <a href="https://opensource.org/licenses/BSD-3-Clause">
        <img alt="BSD-3-Clause" src="https://img.shields.io/pypi/l/persista">
    </a>
    <br/>
    <a href="https://pepy.tech/project/persista">
        <img  alt="Downloads" src="https://static.pepy.tech/badge/persista">
    </a>
    <a href="https://pepy.tech/project/persista">
        <img  alt="Monthly downloads" src="https://static.pepy.tech/badge/persista/month">
    </a>
    <br/>
</p>

## Overview

`persista` is a lightweight Python library that provides simple, consistent building blocks for
persisting and caching data. It offers a uniform key-value store interface backed by multiple
storage engines (in-memory, SQLite, DuckDB, LMDB, Redis, PostgreSQL) with both sync and async
APIs, plus TTL caching and HTTP fetch utilities.

**Quick Links:**

- [Documentation](https://durandtibo.github.io/persista/)
- [Installation](#installation)
- [Features](#features)
- [Contributing](#contributing)
- [License](#license)

## Why persista?

Storage backends have different APIs, and switching between them (e.g. moving from an in-memory
store in tests to Redis or PostgreSQL in production) usually means rewriting code. `persista`
solves this with a single, consistent `BaseStore` interface:

**Store and retrieve values:**

```pycon
>>> from persista.store import InMemoryStore
>>> store = InMemoryStore()
>>> store.set("user:1", {"name": "Alice"})
>>> store.get("user:1")
{'name': 'Alice'}

```

**Swap the backend without changing the calling code:**

```pycon
>>> import tempfile
>>> from pathlib import Path
>>> from persista.store import SQLiteStore
>>> with tempfile.TemporaryDirectory() as tmpdir:
...     with SQLiteStore(Path(tmpdir).joinpath("data.sqlite")) as store:
...         store.set("user:1", {"name": "Alice"})
...         store.get("user:1")
...
{'name': 'Alice'}

```

**Cache expensive calls with a TTL:**

```pycon
>>> from persista.cache import cached
>>> @cached(ttl=60)
... def slow_call(x: int) -> int:
...     return x**2
...
>>> slow_call(4)
16

```

See the [documentation](https://durandtibo.github.io/persista/) for detailed examples.

## Features

`persista` provides a comprehensive set of utilities for persisting and caching data:

### 🗄️ **Key-Value Stores**

A consistent `BaseStore` / `AsyncBaseStore` interface for storing dict values under string keys:

- Uniform API across backends: `get`, `get_many`, `set`, `set_many`, `delete`, `filter`, iteration
- Sync backends: `InMemoryStore`, `SQLiteStore`, `DuckDBStore`, `LmdbStore`, `RedisStore`, `PostgresStore`
- Async backends: `AsyncInMemoryStore`, `AsyncSQLiteStore`, `AsyncRedisStore`, `AsyncPostgresStore`
- Typed variants (`TypedSQLiteStore`, `TypedPostgresStore`, ...) and pickle-backed variants
  (`PickleLmdbStore`, `PickleRedisStore`, `AsyncPickleRedisStore`) for non-dict values
- Configurable conflict handling on writes (`"raise"`, `"skip"`, `"overwrite"`)

### ⏱️ **TTL Caching**

Time-to-live caching for functions and values, with sync and async variants:

- `TTLCache` and `AsyncTTLCache` for explicit cache instances
- `cached` / `async_cached` decorators for caching function calls
- Shared default caches via `get_ttl_cache` / `get_async_ttl_cache`

### 🌐 **HTTP Utilities**

Helpers to fetch HTTP responses with automatic retries, built on top of `requests` or `httpx`:

- `fetch_response` (sync, `requests`) and `fetch_response_async` (async, `httpx`)

## Installation

We highly recommend installing `persista` in
a [virtual environment](https://packaging.python.org/guides/installing-using-pip-and-virtual-environments/)
to avoid dependency conflicts.

### Using uv (recommended)

[`uv`](https://docs.astral.sh/uv/) is a fast Python package installer and resolver:

```shell
uv pip install persista
```

**Install with specific optional dependencies:**

```shell
uv pip install persista[redis,httpx]  # with Redis and httpx support
```

### Using pip

Alternatively, you can use `pip`:

```shell
pip install persista
```

**Install with specific optional dependencies:**

```shell
pip install persista[redis,httpx]  # with Redis and httpx support
```

### Requirements

- **Python**: 3.10 or higher
- **Core dependencies**: [`coola`](https://github.com/durandtibo/coola)

**Optional dependencies**, enabled per-backend:

| Extra       | Enables                              |
|-------------|---------------------------------------|
| `aiosqlite` | Async SQLite store                    |
| `duckdb`    | DuckDB store                          |
| `faker`     | Test data generation helpers          |
| `httpx`     | Async HTTP fetch utilities            |
| `lmdb`      | LMDB store                            |
| `psycopg`   | PostgreSQL store                      |
| `redis`     | Redis store                           |
| `requests`  | Sync HTTP fetch utilities             |
| `rich`      | Rich-formatted output                 |
| `urllib3`   | urllib3-based HTTP utilities          |

For detailed installation instructions, see the [documentation](https://durandtibo.github.io/persista/).

## Contributing

Contributions are welcome! We appreciate bug fixes, feature additions, documentation improvements,
and more. Please check the [contributing guidelines](CONTRIBUTING.md) for details on:

- Setting up the development environment
- Code style and testing requirements
- Submitting pull requests

Whether you're fixing a bug or proposing a new feature, please open an issue first to discuss
your changes.

## API Stability

:warning: **Important**: As `persista` is under active development, its API is not yet stable and may
change between releases. We recommend pinning a specific version in your project’s dependencies to
ensure consistent behavior.

## License

`persista` is licensed under BSD 3-Clause "New" or "Revised" license available in [LICENSE](LICENSE)
file.
