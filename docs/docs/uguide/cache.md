# TTL Caching

:book: This page describes the `persista.cache` package, which provides time-to-live (TTL)
caching for values and function calls, with both synchronous and asynchronous APIs.

**Prerequisites:** You'll need to know a bit of Python, and it helps to be familiar with the
[store user guide](store.md) since caches are backed by a `BaseStore`/`AsyncBaseStore`.

## Overview

The `persista.cache` package provides two related ways to cache data:

- `TTLCache` / `AsyncTTLCache`: explicit cache objects with `get`/`set`/`clear` methods, backed by
  any `BaseStore`/`AsyncBaseStore` (an in-memory store by default)
- `cached` / `async_cached`: decorators that cache the result of a function call using a shared
  default cache

Every cached entry has an expiration time. Once a key's TTL has elapsed, `get` behaves as if the
key were never set.

## Using `TTLCache` Directly

Create a `TTLCache` and use `set`/`get` like a dictionary with expiration:

```pycon
>>> from persista.cache import TTLCache
>>> cache = TTLCache(default_ttl=60)
>>> cache.set("greeting", "hello")
>>> cache.get("greeting")
'hello'
>>> cache.get("missing") is None
True

```

`default_ttl` (in seconds) is used whenever `set` is called without an explicit `ttl`. Pass `ttl`
to `set` to override it for a single entry:

```pycon
>>> from persista.cache import TTLCache
>>> cache = TTLCache()
>>> cache.set("greeting", "hello")
>>> cache.set("short-lived", "value", ttl=30)

```

`clear` removes every entry:

```pycon
>>> from persista.cache import TTLCache
>>> cache = TTLCache()
>>> cache.set("greeting", "hello")
>>> cache.clear()
>>> cache.get("greeting") is None
True

```

By default, `TTLCache` stores entries in an `InMemoryStore`. Pass any other `BaseStore` to
persist cached values, e.g. to share a cache across processes with `RedisStore`:

```python
from persista.cache import TTLCache
from persista.store import RedisStore

cache = TTLCache(store=RedisStore("redis://localhost:6379/0"), default_ttl=300)
```

## Memoizing Functions with `TTLCache.memoize`

`TTLCache.memoize` is a decorator that caches a function's return value, keyed on the function
name and its arguments:

```pycon
>>> from persista.cache import TTLCache
>>> cache = TTLCache()
>>> calls = []
>>> @cache.memoize(ttl=60)
... def square(x):
...     calls.append(x)
...     return x * x
...
>>> square(4)
16
>>> square(4)  # served from the cache, not re-computed
16
>>> calls
[4]

```

`memoize` also works on `async def` functions, in which case it must be used with an
`AsyncTTLCache` (see below).

## Async Caching with `AsyncTTLCache`

`AsyncTTLCache` mirrors `TTLCache`, but every method is a coroutine and it is backed by an
`AsyncBaseStore` (an `AsyncInMemoryStore` by default):

```pycon
>>> import asyncio
>>> from persista.cache import AsyncTTLCache
>>> async def main():
...     cache = AsyncTTLCache(default_ttl=60)
...     await cache.set("greeting", "hello")
...     print(await cache.get("greeting"))
...     await cache.clear()
...     print(await cache.get("greeting"))
...
>>> asyncio.run(main())
hello
None

```

`AsyncTTLCache.memoize` decorates `async def` functions:

```pycon
>>> import asyncio
>>> from persista.cache import AsyncTTLCache
>>> cache = AsyncTTLCache()
>>> calls = []
>>> @cache.memoize(ttl=60)
... async def square(x):
...     calls.append(x)
...     return x * x
...
>>> async def main():
...     print(await square(4))
...     print(await square(4))  # served from the cache, not re-computed
...
>>> asyncio.run(main())
16
16
>>> calls
[4]

```

## Shared Default Caches: `cached` and `async_cached`

For simple cases, `cached` and `async_cached` avoid creating and threading a `TTLCache` instance
through your code. They use a shared module-level default cache, retrieved with `get_ttl_cache`
/ `get_async_ttl_cache`:

```pycon
>>> from persista.cache import cached
>>> calls = []
>>> @cached(ttl=60)
... def square(x):
...     calls.append(x)
...     return x * x
...
>>> square(4)
16
>>> square(4)  # served from the cache, not re-computed
16
>>> calls
[4]

```

```pycon
>>> import asyncio
>>> from persista.cache import async_cached
>>> calls = []
>>> @async_cached(ttl=60)
... async def square(x):
...     calls.append(x)
...     return x * x
...
>>> async def main():
...     print(await square(4))
...     print(await square(4))  # served from the cache, not re-computed
...
>>> asyncio.run(main())
16
16
>>> calls
[4]

```

Use `set_ttl_cache` / `set_async_ttl_cache` to replace the shared default cache, for example to
change its backend or default TTL globally:

```pycon
>>> from persista.cache import TTLCache
>>> from persista.cache import get_ttl_cache, set_ttl_cache
>>> set_ttl_cache(TTLCache(default_ttl=60))
>>> get_ttl_cache().default_ttl
60

```

## Cache Keys

Internally, `memoize`, `cached`, and `async_cached` derive a cache key from the function's
qualified name and its arguments using `make_key`, which JSON-serializes `(func, args, kwargs)`
with sorted keys and hashes the result. Calls with the same arguments (regardless of keyword
argument order) map to the same key:

```pycon
>>> from persista.cache.utils import make_key
>>> make_key("add", (1, 2), {}) == make_key("add", (1, 2), {})
True
>>> make_key("add", (), {"a": 1, "b": 2}) == make_key("add", (), {"b": 2, "a": 1})
True
>>> make_key("add", (1, 2), {}) == make_key("add", (1, 3), {})
False

```

Because arguments must be JSON-serializable to compute a key, `memoize`/`cached`/`async_cached`
only work on functions whose arguments are JSON-serializable.

## API Reference

See the [reference documentation](../refs/cache.md) for the full API.
