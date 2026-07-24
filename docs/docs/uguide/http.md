# HTTP Fetch Utilities

:book: This page describes the HTTP helpers in `persista.http.requests` and
`persista.http.httpx`, which fetch a URL with automatic retries on top of
[`requests`](https://requests.readthedocs.io/) or [`httpx`](https://www.python-httpx.org/).

**Prerequisites:** You'll need to know a bit of Python. Depending on which helper you use, you
need the `requests` extra (`persista[requests]`) or the `httpx` extra (`persista[httpx]`)
installed.

## Overview

Fetching data from an HTTP API often needs retry logic for transient failures (rate limiting,
server errors). `persista` provides two equivalent helpers so you can use whichever HTTP client
your project already depends on:

- `persista.http.requests.fetch_response`: synchronous, built on `requests`
- `persista.http.httpx.get_response`/`post_response`/`put_response`/`patch_response`/
  `delete_response`: synchronous, one function per HTTP method, built on `httpx`
- `persista.http.httpx.get_response_async`/`post_response_async`/`put_response_async`/
  `patch_response_async`/`delete_response_async`: asynchronous counterparts, built on `httpx`
- `persista.http.httpx.send_request`/`send_request_async`: synchronous/asynchronous, any HTTP
  method, built on `httpx`
- `persista.http.httpx.HttpClient`/`AsyncHttpClient`: class-based wrappers around
  `httpx.Client`/`httpx.AsyncClient` with the same retry behavior, plus optional response caching

Both retry on connection errors and on a configurable set of HTTP status codes (`429`, `500`,
`502`, `503`, `504` by default), and raise an exception if the final attempt still fails.

## Fetching with `requests`

`fetch_response` (in `persista.http.requests`) fetches a URL and returns a
`requests.Response`, retrying up to `max_retries` times with exponential backoff:

```python
from persista.http.requests import fetch_response

response = fetch_response(
    "https://jsonplaceholder.typicode.com/todos/1",
    timeout=10,
    max_retries=5,
)
response.json()
```

`fetch_response` calls `response.raise_for_status()`, so a non-retryable error status raises a
`requests.HTTPError`. Pass `headers` to set custom request headers, or `session` to reuse an
existing `requests.Session` (otherwise a temporary session is created and closed automatically):

```pycon
>>> from persista.http.requests import create_session
>>> session = create_session(max_retries=5)

```

`create_session` builds a `requests.Session` pre-configured with the retry policy used internally
by `fetch_response`; use it directly if you need to issue several requests with the same retry
behavior.

## Fetching with `httpx`

`get_response` (in `persista.http.httpx`) is the `httpx` equivalent for `GET` requests, returning
an `httpx.Response`:

```python
from persista.http.httpx.method import get_response

response = get_response(
    "https://jsonplaceholder.typicode.com/todos/1",
    timeout=10,
    max_retries=5,
)
response.json()
```

If the server returns a `Retry-After` header, it is honored; otherwise the wait time doubles with
each attempt (`2 ** (attempt - 1)` seconds).

For other HTTP methods, use `send_request`, which takes the method as its first argument:

```python
from persista.http.httpx.method import send_request

response = send_request(
    "POST",
    "https://jsonplaceholder.typicode.com/todos",
    json={"title": "example"},
    timeout=10,
    max_retries=5,
)
response.json()
```

`get_response` is in fact a thin wrapper around `send_request` for the `GET` case. `post_response`,
`put_response`, `patch_response`, and `delete_response` are the equivalent wrappers for their
respective methods.

### Async Fetching

`get_response_async` and `send_request_async` are the coroutine versions, for use with an
`httpx.AsyncClient`:

```python
import asyncio

from persista.http.httpx.method import get_response_async, send_request_async


async def main():
    response = await get_response_async(
        "https://jsonplaceholder.typicode.com/todos/1",
        timeout=10,
        max_retries=5,
    )
    await send_request_async(
        "POST",
        "https://jsonplaceholder.typicode.com/todos",
        json={"title": "example"},
        timeout=10,
        max_retries=5,
    )
    return response.json()


asyncio.run(main())
```

All these functions accept a `client` argument to reuse an existing
`httpx.Client`/`httpx.AsyncClient`, and `retry_status_codes` to customize which status codes
trigger a retry.

## Class-Based Clients with Caching

`HttpClient` and `AsyncHttpClient` wrap an `httpx.Client`/`httpx.AsyncClient` with the same retry
behavior as `send_request`/`send_request_async`, exposed as `get`/`post`/`put`/`patch`/`delete`
methods (plus `request` for an arbitrary method), and add optional response caching:

```python
import httpx

from persista.http.httpx import HttpClient

with httpx.Client() as httpx_client:
    client = HttpClient(client=httpx_client, timeout=10, max_retries=5)
    response = client.get("https://jsonplaceholder.typicode.com/todos/1")
    response.json()
```

Pass a `Cache` (see the [caching user guide](cache.md)) to cache successful responses, keyed on
the method, URL, and request kwargs. Caching is opt-in per HTTP method via `cacheable_methods`,
which defaults to `{"GET"}`:

```python
import httpx

from persista.cache import Cache
from persista.http.httpx import HttpClient

with httpx.Client() as httpx_client:
    client = HttpClient(client=httpx_client, cache=Cache(default_ttl=60))
    client.get("https://jsonplaceholder.typicode.com/todos/1")  # fetched and cached
    client.get("https://jsonplaceholder.typicode.com/todos/1")  # served from the cache
```

A cache hit reconstructs an `httpx.Response` with the same status code, headers, and content as
the original; only 2xx responses are cached. `timeout`, `max_retries`, and `retry_status_codes`
can all be set once at construction and overridden per call.

`AsyncHttpClient` is the async counterpart, wrapping an `httpx.AsyncClient` and caching through
the `Cache`'s async (`a`-prefixed) methods:

```python
import asyncio

import httpx

from persista.http.httpx import AsyncHttpClient


async def main():
    async with httpx.AsyncClient() as httpx_client:
        client = AsyncHttpClient(client=httpx_client)
        response = await client.get("https://jsonplaceholder.typicode.com/todos/1")
        return response.json()


asyncio.run(main())
```

Both classes leave the wrapped `httpx.Client`/`httpx.AsyncClient`'s lifecycle to the caller --
they don't create or close it themselves.

## API Reference

See the [reference documentation](../refs/utils.md) for the full API.
