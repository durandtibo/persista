# Caching

:book: This page describes the `persista.cache` package, which provides caching for values and
function calls, with both synchronous and asynchronous APIs.

**Prerequisites:** You'll need to know a bit of Python, and it helps to be familiar with the
[store user guide](store.md) since caches are backed by a `BaseStore`/`AsyncBaseStore`.

## Overview

The `persista.cache` package provides two related ways to cache data:

- `Cache` / `AsyncCache`: explicit cache objects with `get`/`set`/`clear` methods, backed by
  any `BaseStore`/`AsyncBaseStore` (an in-memory store by default)
- `cached` / `async_cached`: decorators that cache the result of a function call using a shared
  default cache

An entry can optionally have an expiration time (TTL). Once a key's TTL has elapsed, `get`
behaves as if the key were never set.

## Using `Cache` Directly

Create a `Cache` and use `set`/`get` like a dictionary, optionally with expiration:

```pycon
>>> from persista.cache import Cache
>>> cache = Cache(default_ttl=60)
>>> cache.set("greeting", "hello")
>>> cache.get("greeting")
'hello'
>>> cache.get("missing") is None
True

```

`default_ttl` (in seconds) is used whenever `set` is called without an explicit `ttl`. It
defaults to `None`, meaning entries never expire unless a `ttl` is given. Pass `ttl` to `set` to
override it for a single entry; `ttl=0` evicts the entry instead of storing it:

```pycon
>>> from persista.cache import Cache
>>> cache = Cache()
>>> cache.set("greeting", "hello")
>>> cache.set("short-lived", "value", ttl=30)

```

`contains` checks whether a key is present and unexpired, without returning its value; `delete`
removes a single entry (unlike `set` with `ttl=0`, it doesn't require a value to be given):

```pycon
>>> from persista.cache import Cache
>>> cache = Cache()
>>> cache.set("greeting", "hello")
>>> cache.contains("greeting")
True
>>> cache.delete("greeting")
>>> cache.contains("greeting")
False

```

`clear` removes every entry:

```pycon
>>> from persista.cache import Cache
>>> cache = Cache()
>>> cache.set("greeting", "hello")
>>> cache.clear()
>>> cache.get("greeting") is None
True

```

By default, `Cache` stores entries in an `InMemoryStore`. Pass any other `BaseStore` to persist
cached values, e.g. to share a cache across processes with `RedisStore`:

```python
from persista.cache import Cache
from persista.store import RedisStore

cache = Cache(store=RedisStore("redis://localhost:6379/0"), default_ttl=300)
```

Pass `ignore_none=True` to treat a cached value of `None` as a cache miss rather than a hit, so
it's recomputed instead of being served back forever — useful when the cached function can
legitimately return `None` for a value that isn't ready yet:

```pycon
>>> from persista.cache import Cache
>>> cache = Cache(ignore_none=True)
>>> cache.set("key", None)
>>> cache.get("key") is None  # treated as a miss, not a cached None
True

```

## Computing a Value on a Cache Miss with `Cache.get_or_compute`

`get_or_compute` returns the cached value for a key, computing and storing it on a cache miss:

```pycon
>>> from persista.cache import Cache
>>> cache = Cache()
>>> calls = []
>>> def compute(x):
...     calls.append(x)
...     return x * 2
...
>>> cache.get_or_compute("key", compute, (4,), {})
8
>>> cache.get_or_compute("key", compute, (4,), {})  # served from the cache
8
>>> calls
[4]

```

`aget_or_compute` is the async counterpart, for use with an `async def` function. The backing
store is still accessed synchronously; only the function is awaited:

```pycon
>>> import asyncio
>>> from persista.cache import Cache
>>> cache = Cache()
>>> calls = []
>>> async def compute(x):
...     calls.append(x)
...     return x * 2
...
>>> async def main():
...     print(await cache.aget_or_compute("key", compute, (4,), {}))
...     print(await cache.aget_or_compute("key", compute, (4,), {}))  # cached
...
>>> asyncio.run(main())
8
8
>>> calls
[4]

```

## Memoizing Functions with `Cache.memoize`

`Cache.memoize` is a decorator that caches a function's return value, keyed on the function name
and its arguments. It works on both sync and `async def` functions:

```pycon
>>> from persista.cache import Cache
>>> cache = Cache()
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

`memoize` accepts two options that control how the cache key is computed from a call's arguments,
via `make_key` (see [Cache Keys](#cache-keys) below):

- `strategy`: either `"json"` (the default) or `"pickle"`. `"json"` produces keys that are stable
  across Python versions and processes, but requires every argument to be JSON-serializable.
  `"pickle"` supports a broader range of argument types, at the cost of a key that is only stable
  within a single Python version.
- `ignore_non_serializable`: if `True`, positional arguments and keyword argument values that
  aren't serializable with `strategy` are silently dropped before computing the key, instead of
  raising an error. This is useful when a function takes an argument that will never be
  serializable (e.g. a logger or a client instance) but shouldn't prevent caching — calls that
  differ only in that argument then share the same cache entry.

```pycon
>>> from persista.cache import Cache
>>> cache = Cache()
>>> calls = []
>>> @cache.memoize(ttl=60, strategy="json", ignore_non_serializable=True)
... def greet(name, client=None):
...     calls.append(name)
...     return f"hello {name}"
...
>>> greet("Ann", client=object())
'hello Ann'
>>> greet("Ann", client=object())  # different (non-serializable) client, still a cache hit
'hello Ann'
>>> calls
['Ann']

```

## Async Caching with `AsyncCache`

`AsyncCache` mirrors `Cache`'s `get`/`set`/`contains`/`delete`/`clear`/`memoize` API, but every
method is a coroutine and it is backed by an `AsyncBaseStore` (an `AsyncInMemoryStore` by
default):

```pycon
>>> import asyncio
>>> from persista.cache import AsyncCache
>>> async def main():
...     cache = AsyncCache(default_ttl=60)
...     await cache.set("greeting", "hello")
...     print(await cache.get("greeting"))
...     await cache.clear()
...     print(await cache.get("greeting"))
...
>>> asyncio.run(main())
hello
None

```

One difference from `Cache`: `AsyncCache.get_or_compute` accepts either a sync or an `async def`
function directly — awaiting it only if the result is awaitable — so there's no separate
`aget_or_compute`. The backing store is still always accessed with `await`, since
`AsyncBaseStore` is an async interface:

```pycon
>>> import asyncio
>>> from persista.cache import AsyncCache
>>> cache = AsyncCache()
>>> calls = []
>>> def compute(x):  # a plain sync function works too
...     calls.append(x)
...     return x * 2
...
>>> async def main():
...     print(await cache.get_or_compute("key", compute, (4,), {}))
...     print(await cache.get_or_compute("key", compute, (4,), {}))  # cached
...
>>> asyncio.run(main())
8
8
>>> calls
[4]

```

`AsyncCache.memoize` decorates `async def` functions:

```pycon
>>> import asyncio
>>> from persista.cache import AsyncCache
>>> cache = AsyncCache()
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

For simple cases, `cached` and `async_cached` avoid creating and threading a `Cache` instance
through your code. They use a shared module-level default cache, retrieved with `get_cache` /
`get_async_cache`:

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

`cached` and `async_cached` accept the same `strategy` and `ignore_non_serializable` options as
`Cache.memoize` (see above), since they compute cache keys the same way:

```pycon
>>> from persista.cache import cached
>>> calls = []
>>> @cached(ttl=60, strategy="json", ignore_non_serializable=True)
... def greet(name, client=None):
...     calls.append(name)
...     return f"hello {name}"
...
>>> greet("Ann", client=object())
'hello Ann'
>>> greet("Ann", client=object())  # different (non-serializable) client, still a cache hit
'hello Ann'
>>> calls
['Ann']

```

Use `set_cache` / `set_async_cache` to replace the shared default cache, for example to
change its backend or default TTL globally:

```pycon
>>> from persista.cache import Cache
>>> from persista.cache import get_cache, set_cache
>>> set_cache(Cache(default_ttl=60))
>>> get_cache().default_ttl
60

```

## Cache Keys

Internally, `memoize`, `cached`, and `async_cached` derive a cache key from the function's
qualified name and its arguments using `make_key`, which serializes `(func, args, kwargs)` with
sorted keyword argument keys and hashes the result. Calls with the same arguments (regardless of
keyword argument order) map to the same key:

```pycon
>>> from persista.cache.utils import make_key
>>> make_key("add", (1, 2), {}) == make_key("add", (1, 2), {})
True
>>> make_key("add", (), {"a": 1, "b": 2}) == make_key("add", (), {"b": 2, "a": 1})
True
>>> make_key("add", (1, 2), {}) == make_key("add", (1, 3), {})
False

```

`make_key` supports two serialization strategies, selected with `strategy`:

- `"json"` (the default): serializes with `json` before hashing, so keys are stable across
  Python versions and processes, but every argument must be JSON-serializable (`dict`, `list`,
  `str`, `int`, `float`, `bool`, `None`, and nested combinations thereof).
- `"pickle"`: serializes with `pickle` before hashing. Supports a broader range of argument types
  (e.g. custom objects, `datetime`s) than `"json"`, at the cost of a key that is only stable
  within a single Python version, since pickle's format can change across versions.

```pycon
>>> from persista.cache.utils import make_key
>>> make_key("add", (1, 2), {}, strategy="json") == make_key(
...     "add", (1, 2), {}, strategy="json"
... )
True

```

By default, an argument that isn't serializable with `strategy` raises an error when the key is
computed — meaning the decorated function can't be called with that argument at all. Pass
`ignore_non_serializable=True` to instead silently drop non-serializable positional arguments and
keyword argument values before computing the key:

```pycon
>>> import threading
>>> from persista.cache.utils import make_key
>>> make_key("add", (1, threading.Lock()), {}, ignore_non_serializable=True) == make_key(
...     "add", (1,), {}, ignore_non_serializable=True
... )
True

```

This is useful for arguments that will never be serializable (e.g. a logger or a client instance)
but that shouldn't block caching. Note that since the argument is dropped rather than incorporated
into the key, calls that differ *only* in such an argument are treated as the same call and share
a cached result — make sure that's the behavior you want before enabling it for a given argument.

## API Reference

See the [reference documentation](../refs/cache.md) for the full API.
