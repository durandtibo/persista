# Home

<p align="center">
    <a href="https://github.com/durandtibo/persista/actions/workflows/ci.yaml">
        <img alt="CI" src="https://img.shields.io/github/actions/workflow/status/durandtibo/persista/ci.yaml?branch=main&label=CI&logo=github"></a>
    <a href="https://github.com/durandtibo/persista/actions/workflows/nightly-package.yaml">
        <img alt="Nightly Package Tests" src="https://img.shields.io/github/actions/workflow/status/durandtibo/persista/nightly-package.yaml?label=nightly&logo=github"></a>
    <a href="https://codecov.io/gh/durandtibo/persista">
        <img alt="Codecov" src="https://img.shields.io/codecov/c/github/durandtibo/persista?logo=codecov"></a>
    <a href="https://durandtibo.github.io/persista/">
        <img alt="Documentation (stable)" src="https://img.shields.io/badge/docs-stable-blue?logo=readthedocs&logoColor=white"></a>
    <br/>
    <a href="https://pypi.org/project/persista/">
        <img alt="PyPI version" src="https://img.shields.io/pypi/v/persista?logo=pypi&logoColor=white"></a>
    <a href="https://pypi.org/project/persista/">
        <img alt="Python" src="https://img.shields.io/pypi/pyversions/persista?logo=python&logoColor=white"></a>
    <a href="https://opensource.org/licenses/BSD-3-Clause">
        <img alt="BSD-3-Clause" src="https://img.shields.io/pypi/l/persista"></a>
    <br/>
    <a href="https://github.com/astral-sh/ruff">
        <img alt="Ruff" src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json"></a>
    <a href="https://google.github.io/styleguide/pyguide.html#s3.8-comments-and-docstrings">
        <img alt="Doc style: google" src="https://img.shields.io/badge/docstyle-google-3666d6"></a>
    <a href="https://scorecard.dev/viewer/?uri=github.com/durandtibo/persista">
        <img alt="OpenSSF Scorecard" src="https://img.shields.io/ossf-scorecard/github.com/durandtibo/persista?label=openssf%20scorecard"></a>
    <br/>
    <a href="https://pepy.tech/project/persista">
        <img alt="Downloads" src="https://img.shields.io/pepy/dt/persista"></a>
    <a href="https://pepy.tech/project/persista">
        <img alt="Monthly downloads" src="https://img.shields.io/pepy/dm/persista"></a>
    <a href="https://github.com/durandtibo/persista/stargazers">
        <img alt="GitHub stars" src="https://img.shields.io/github/stars/durandtibo/persista?logo=github"></a>
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
>>> with InMemoryStore() as store:
...     store.set("user:1", {"name": "Alice"})
...     store.get("user:1")
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
{'name': 'Alice'}

```

**Cache expensive calls with a TTL:**

```pycon
>>> from persista.cache import cached
>>> @cached(ttl=60)
... def slow_call(x: int) -> int:
...     return x**2
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
- Pickle-backed variants (`PickleSQLiteStore`, `PickleLmdbStore`, ...) for non-dict values
- Codecs for `InMemoryStore`: JSON by default, which rejects the values that would lose data, or
  `pickle` (`InMemoryStore(codec=PickleCodec())`) to keep Python types
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

### 🧾 **Records**

A `Record` container (a stable UUID `id` plus a `metadata` dict) with helpers to filter, sort,
persist, and analyze collections of records:

- `filter_by_metadata`/`filter_by_metadata_range`/`filter_by_metadata_values`,
  `sort_by_metadata`: filter and sort records by metadata
- `RecordStore`: persist records in any `persista.store` backend, with the method names of
  `BaseStore`
- `persista.record.analysis`: exact/near-duplicate detection, id-collision detection, diffing two
  snapshots, orphan-reference checks, schema-shape clustering, value frequency/cardinality, and
  metadata stats/reporting
- `generate_fake_records` for synthetic test data (requires the `faker` extra)

[Learn more →](uguide/record.md)

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
