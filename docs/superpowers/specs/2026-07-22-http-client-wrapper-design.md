# HTTP client wrapper with retries and optional caching

## Problem

`persista.http.httpx` exposes free functions (`get_response`, `send_request`, etc.)
that retry transient failures, but each call independently decides whether to
create/close an `httpx.Client`, and there is no built-in way to cache
responses. We want a class-based wrapper, closer to `httpx.Client`'s own API,
that keeps the existing retry behavior and adds opt-in response caching backed
by `persista.cache.Cache`.

## Design

### New module: `src/persista/http/client.py`

Two classes, `HttpClient` (sync, wraps `httpx.Client`) and `AsyncHttpClient`
(async, wraps `httpx.AsyncClient`). Both delegate retry/backoff logic to the
existing `send_request` / `send_request_async` functions rather than
duplicating it.

```python
HttpClient(
    timeout: int = 30,
    max_retries: int = 3,
    retry_status_codes: set[int] | frozenset[int] = DEFAULT_RETRY_STATUS_CODES,
    cache: Cache | None = None,
    cacheable_methods: set[str] = frozenset({"GET"}),
    ttl: float | None = None,
    client: httpx.Client | None = None,
)
```

`AsyncHttpClient` mirrors this, taking `cache: AsyncCache | None` and wrapping
`httpx.AsyncClient`.

Request methods: `.get(url, **kwargs)`, `.post(...)`, `.put(...)`,
`.patch(...)`, `.delete(...)`, `.request(method, url, **kwargs)`, matching
`httpx.Client`'s surface. Each forwards to `send_request`
(`send_request_async` for the async class) using the wrapped `httpx.Client`/
`httpx.AsyncClient`, and accepts per-call overrides of `timeout`,
`max_retries`, and `retry_status_codes`.

### Caching (opt-in, off by default)

Caching only activates when `cache` is provided at construction, and only for
HTTP methods in `cacheable_methods` (default `{"GET"}`).

- **Key:** derived via `persista.cache.utils.make_key("<METHOD> <url>", (),
  kwargs, ignore_non_serializable=True)`, so calls with equal method, url, and
  serializable kwargs (`params`, `json`, etc.) share a cache entry.
  Non-serializable kwargs (e.g. `auth` objects) are dropped from the key
  rather than raising, matching `Cache.memoize`'s `ignore_non_serializable`
  behavior.
- **Stored value:** `{"status_code": int, "headers": dict[str, str],
  "content": str}`, with `content` base64-encoded so the entry stays
  JSON-serializable for stores that serialize (SQLite, Redis, etc.), not just
  `InMemoryStore`.
- **On a cache hit:** reconstruct an `httpx.Response(status_code, headers=...,
  content=base64.b64decode(...))` and return it, so callers use `.json()`,
  `.text`, `.status_code` exactly as on a live call.
- **On a cache miss:** perform the (possibly retried) request; if the
  response is a 2xx success, cache it with the configured `ttl` before
  returning. Non-2xx responses are not cached (mirrors `send_request` raising
  `raise_for_status()` on unretried errors — nothing to cache in that path
  anyway).

### Lifecycle

Both classes support use as context managers (`with HttpClient() as c: ...`
/ `async with AsyncHttpClient() as c: ...`), closing the wrapped httpx client
on exit. `.close()` / `await .aclose()` are also available directly.

### Non-goals

- No changes to `persista.http.httpx`'s free functions — they remain as-is
  and are reused internally.
- No cache invalidation beyond TTL expiry (already provided by `Cache`).
- No caching of non-2xx responses or of methods outside `cacheable_methods`.
