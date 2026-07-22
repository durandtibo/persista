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
- `persista.http.httpx.get_response`: synchronous `GET`, built on `httpx`
- `persista.http.httpx.get_response_async`: asynchronous `GET`, built on `httpx`
- `persista.http.httpx.send_request`: synchronous, any HTTP method, built on `httpx`
- `persista.http.httpx.send_request_async`: asynchronous, any HTTP method, built on `httpx`

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

`get_response` is in fact a thin wrapper around `send_request` for the `GET` case.

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

All four functions accept a `client` argument to reuse an existing
`httpx.Client`/`httpx.AsyncClient`, and `retry_status_codes` to customize which status codes
trigger a retry.

## API Reference

See the [reference documentation](../refs/utils.md) for the full API.
