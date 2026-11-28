# HTTP Utilities

:book: This page describes the HTTP helpers in `persista.http.httpx` and
`persista.http.requests`, which send requests with automatic retries on top of
[`httpx`](https://www.python-httpx.org/) or [`requests`](https://requests.readthedocs.io/).

**Prerequisites:** You'll need to know a bit of Python. Depending on which helper you use, you
need the `requests` extra (`persista[requests]`) or the `httpx` extra (`persista[httpx]`)
installed.

## Overview

`persista` adds retries to the HTTP library that your project already uses:

- `persista.http.httpx`: `HttpClient` and `AsyncHttpClient`, wrappers around `httpx.Client` and
  `httpx.AsyncClient`, for any HTTP method, with an optional response cache;
- `persista.http.requests`: `fetch_response` and `create_session`, built on `requests`, which
  retry `GET` requests only and have no cache.

## Properties

What the HTTP helpers guarantee, and where each guarantee stops. The
[properties of the package](package.md) apply too.

| Property      | Guarantee                                                                                                                                                                   | Limits                                                                                                                                                                                                                                         |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Transparent   | A request behaves as with the wrapped `httpx` client (timeout, headers, authentication) or `requests` session, plus retries and, with `httpx`, an optional cache.           | A 4xx or 5xx response raises `httpx.HTTPStatusError`. On a cache hit, nothing is sent: the response hooks of the client do not run and its cookies are not updated.                                                                            |
| Safe retries  | Only the idempotent methods are retried unless you say otherwise. The delay is never negative and at most `max_delay`.                                                      | A method that HTTP defines as idempotent may not be on your server. `requests` retries `GET` only, and a session that you provide uses its own settings.                                                                                       |
| Sound cache   | A cached response is served only for a request with the same method, final URL, headers, body and redirect setting. A request with `auth` or URL credentials is not cached. | A request authenticated by a header or a cookie is cached, under a key that contains them. The key does not describe the [transport](#requests-that-are-not-cached) of the client, and `Cache-Control`, `ETag` and `Vary` are not interpreted. |
| Same response | A response from the cache has the same status and content as the original, and its methods (`json`, `raise_for_status`) work.                                               | `history`, `extensions` (so the HTTP version and the reason phrase of the server) and `elapsed` are not kept, repeated headers are joined, and the content is [stored decoded](#responses-from-the-cache).                                     |

## Clients for `httpx`

`HttpClient` has the `get`, `post`, `put`, `patch`, and `delete` methods, and `request` for any
other method. Without a client, the wrapper creates an `httpx.Client` with the default settings of
`httpx` and closes it at the end of the `with` block (or with `close`):

```python
from persista.http.httpx import HttpClient

with HttpClient(max_retries=5) as client:
    response = client.get("https://jsonplaceholder.typicode.com/todos/1", timeout=10)
    response.json()
```

To set a base URL, headers, authentication, a proxy, or a default timeout, give your own client.
The wrapper does not close it:

```python
import httpx

from persista.http.httpx import HttpClient

with httpx.Client(base_url="https://jsonplaceholder.typicode.com", timeout=30) as httpx_client:
    client = HttpClient(httpx_client)
    response = client.post("/todos", json={"title": "example"})
    response.json()
```

A request behaves as with the wrapped client: the arguments of a call (`timeout`, `headers`,
`auth`, `follow_redirects`, ...) are passed to `httpx`, and the settings of the client apply to the
others. The `timeout` applies to each attempt, not to the whole call. A 4xx or 5xx response raises
`httpx.HTTPStatusError`; other responses are returned, including a redirect that is not followed.

### Async Client

`AsyncHttpClient` is the async counterpart. It wraps an `httpx.AsyncClient`, is closed with
`async with` (or `aclose`), and accesses the cache with its async (`a`-prefixed) methods:

```python
import asyncio

from persista.http.httpx import AsyncHttpClient


async def main():
    async with AsyncHttpClient() as client:
        response = await client.get("https://jsonplaceholder.typicode.com/todos/1")
        return response.json()


asyncio.run(main())
```

## Retries

| Argument             | Default                                            | Meaning                                        |
| -------------------- | -------------------------------------------------- | ---------------------------------------------- |
| `max_retries`        | `3`                                                | retries per request; `0` disables them         |
| `retry_status_codes` | `429`, `500`, `502`, `503`, `504`                  | statuses of the responses that are retried     |
| `retry_methods`      | `DELETE`, `GET`, `HEAD`, `OPTIONS`, `PUT`, `TRACE` | methods that are retried                       |
| `max_delay`          | `60.0`                                             | maximum delay between two attempts, in seconds |

They are arguments of the constructors; `max_retries` and `retry_status_codes` can also be
overridden for one call. An invalid value raises `TypeError` or `ValueError`.

### Which Requests Are Retried

A request is sent again after:

- a response whose status is in `retry_status_codes`;
- a transport error (`httpx.TransportError`): a timeout, a network or proxy error, or an invalid
  response of the server. `httpx.UnsupportedProtocol` and `httpx.LocalProtocolError` are not
  retried, and neither are the other errors (for example `httpx.TooManyRedirects`).

Only the methods in `retry_methods` are retried. By default these are the idempotent methods: a
`POST` or `PATCH` request that failed may have been applied by the server, so it is sent once. Add
them if your API accepts it (for example with an idempotency key):

```python
from persista.http.httpx import HttpClient
from persista.http.retry import IDEMPOTENT_METHODS

client = HttpClient(retry_methods=IDEMPOTENT_METHODS | {"POST"})
```

A request whose body can only be read once is never retried: an iterator or a file passed as
`content` or `data`, and any `files` upload. Pass `bytes`, `str`, `json`, or a form (`data` as a
mapping) to allow retries.

After the last attempt, its transport error is raised, or its response is handled like any
response (`httpx.HTTPStatusError` for a 4xx or 5xx status).

### Delay Between Attempts

If the response has a `Retry-After` header, a number of seconds or an HTTP date, the client waits
that long. Otherwise (no response, no header, or a value that cannot be read), it waits
`2 ** (n - 1)` seconds before the retry `n`: 1, 2, 4, ... The delay is always between `0` and
`max_delay`: a negative number or a date in the past gives no delay, and a longer delay is cut to
`max_delay`.

The rules are those of `persista.http.retry.RetryPolicy`.

## Caching

Pass an open `Cache` (see the [caching user guide](cache.md)) to cache successful responses.
Caching is opt-in per HTTP method via `cacheable_methods`, which defaults to `{"GET"}`:

```python
from persista.cache import Cache
from persista.http.httpx import HttpClient

with Cache(default_ttl=60) as cache, HttpClient(cache=cache) as client:
    client.get("https://jsonplaceholder.typicode.com/todos/1")  # fetched and cached
    client.get("https://jsonplaceholder.typicode.com/todos/1")  # served from the cache
```

Only 2xx responses are cached. A client that is closed raises `RuntimeError`, even for a request
whose response is in the cache.

### What Identifies a Cached Response

The cache key is computed from the request that `client.build_request` builds, so a cached response
is served only for a request with the same:

- method;
- final URL, including the `base_url` and the query parameters of the client and of the call;
- headers, including those set on the client and the cookies (of the client and of the call);
- body (`content`, `data`, or `json`);
- redirect setting (`follow_redirects`).

For example, two clients with different `Authorization` headers can share a cache without seeing
each other's responses. A server that sets a cookie changes the next request of the same client,
which is then a cache miss.

### Requests That Are Not Cached

The request is sent, and the cache is neither read nor written, when:

- it has an `auth`, set on the client or passed to the call (pass `auth=None` to disable the `auth`
  of the client for a call), or credentials in its URL (`https://user:password@host`);
- its body is streamed: an iterator or a file passed as `content`, or a `files` upload;
- the client has request event hooks, which can change the request after the key is computed;
- the call passes `extensions`, which can change how the request is sent.

On a cache hit nothing is sent, so the response event hooks of the client are not called and a
`Set-Cookie` header of the cached response does not update its cookies.

The key does not describe the transport of the client (proxy, TLS settings, custom transport), nor
what a subclass of the client adds when it sends a request: do not share a cache between clients
for which these change the response. The `Cache-Control`, `ETag`, and `Vary` headers are not
interpreted.

### Responses From the Cache

A cache hit reconstructs an `httpx.Response` with the status code, headers, and content of the
original, and with the request of the current call, so `json()` and `raise_for_status()` work as
on the original response. The content is stored decoded: the `content-encoding`, `content-length`,
and `transfer-encoding` headers of the original are not kept, and `content-length` is the length of
the decoded content. Transport details are not kept either (for example `history`, `extensions`,
and `elapsed`), and repeated headers are joined into one.

## Fetching with `requests`

`fetch_response` (in `persista.http.requests`) fetches a URL with a `GET` request and returns a
`requests.Response`:

```python
from persista.http.requests import fetch_response

response = fetch_response(
    "https://jsonplaceholder.typicode.com/todos/1",
    timeout=10,
    max_retries=5,
)
response.json()
```

`fetch_response` calls `response.raise_for_status()`, so a 4xx or 5xx response raises a
`requests.HTTPError`. Pass `headers` to set custom request headers, or `session` to reuse an
existing `requests.Session` (otherwise a temporary session is created and closed automatically).
With a `session`, its retry settings apply and the retry arguments of the call are ignored.

`create_session` builds the `requests.Session` that `fetch_response` uses; use it directly if you
need to issue several requests with the same retry behavior:

```pycon
>>> from persista.http.requests import create_session
>>> session = create_session(max_retries=5, max_delay=30)

```

The retries differ from those of the `httpx` clients in these points:

- only `GET` requests are retried, and this cannot be changed;
- the errors that are retried are the connection and read errors of `urllib3`;
- there is no delay before the first retry without a `Retry-After` header, then
  `backoff_factor * (2 ** (n - 1))` seconds before the retry `n`;
- `urllib3` does not know if a streamed body can be read again: do not send a generator as the body
  of a `GET` request;
- there is no cache.

As for `httpx`, the default status codes are `429`, `500`, `502`, `503`, and `504`, a
`Retry-After` header is a number of seconds or an HTTP date, and the delay is between `0` and
`max_delay` (60 seconds by default).

## Credentials in Errors and Logs

The log messages of `persista` show a URL without its username and password; the query string is
kept. The errors of `httpx` and `requests` are not rewritten: their messages (for example the one of
the error raised for a 4xx or 5xx response, which quotes the URL with its password) and the
`request` and `response` objects that they carry can contain the credentials of a URL, and the
request headers. The loggers of these libraries can show URLs too (`httpx` logs each request at the
`INFO` level). Prefer the `auth` argument to credentials in a URL, and take care when you log an
error.

## API Reference

See the [reference documentation](../refs/http.md) for the full API.
