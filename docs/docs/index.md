# Home

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

- [User Guide](uguide/store.md)
- [Installation](get_started.md)
- [Features](#features)
- [Contributing](#contributing)

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

See the [user guide](uguide/cache.md) for detailed examples.

## Features

`persista` provides a comprehensive set of utilities for persisting and caching data:

### 🗄️ **Key-Value Stores**

A consistent `BaseStore` interface for storing dict values under string keys, with both
synchronous and `a`-prefixed asynchronous methods on every store:

- Uniform API across backends: `get`/`aget`, `get_many`/`aget_many`, `set`/`aset`,
  `set_many`/`aset_many`, `delete`/`adelete`, `filter`/`afilter`, iteration
- Backends: `InMemoryStore`, `SQLiteStore`, `DuckDBStore`, `LmdbStore`, `RedisStore`, `PostgresStore`
- Typed variants (`TypedSQLiteStore`, `TypedPostgresStore`, ...) and pickle-backed variants
  (`PickleLmdbStore`, `PickleRedisStore`) for non-dict values
- Configurable conflict handling on writes (`"raise"`, `"skip"`, `"overwrite"`, `"merge"`)

[Learn more →](uguide/store.md)

### ⏱️ **TTL Caching**

Time-to-live caching for functions and values, with sync and async variants:

- `Cache`, with sync and async (`a`-prefixed) methods, for explicit cache instances
- `cached` / `async_cached` decorators for caching function calls
- A shared default cache via `get_cache`

[Learn more →](uguide/cache.md)

### 🌐 **HTTP Utilities**

Helpers to fetch HTTP responses with automatic retries, built on top of `requests` or `httpx`:

- `fetch_response` (sync, `requests`); `get_response`/`post_response`/`put_response`/
  `patch_response`/`delete_response`/`send_request` (sync, `httpx`) and their `_async`
  counterparts (async, `httpx`)
- `HttpClient`/`AsyncHttpClient`: class-based wrappers around `httpx.Client`/`httpx.AsyncClient`
  with the same retries, plus optional response caching via a `Cache`

[Learn more →](uguide/http.md)


## Contributing

Contributions are welcome! We appreciate bug fixes, feature additions, documentation improvements,
and more. Please check
the [contributing guidelines](https://github.com/durandtibo/persista/blob/main/CONTRIBUTING.md) for
details on:

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

`persista` is licensed under BSD 3-Clause "New" or "Revised" license available
in [LICENSE](https://github.com/durandtibo/persista/blob/main/LICENSE)
file.
