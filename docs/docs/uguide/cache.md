# Caching

:book: This page describes the `persista.cache` package, which provides caching for values and
function calls, with both synchronous and asynchronous APIs.

**Prerequisites:** You'll need to know a bit of Python, and it helps to be familiar with the
[store user guide](store.md) since caches are backed by a `BaseStore`.

## Overview

The `persista.cache` package provides two related ways to cache data:

- `Cache`: an explicit cache object with `get`/`set`/`clear` methods, backed by any `BaseStore`
  (an in-memory store by default). Every method also has an async counterpart, prefixed with
  `a` (`aget`/`aset`/`aclear`/...), for use with an async backing store.
- `cached` / `async_cached`: decorators that cache the result of a function call using a shared
  default `Cache`

An entry can optionally have an expiration time (TTL). Once a key's TTL has elapsed, `get`
behaves as if the key were never set.

## Using `Cache` Directly

Create a `Cache` and use `set`/`get` like a dictionary, optionally with expiration:

```pycon
>>> from persista.cache import Cache
>>> with Cache(default_ttl=60) as cache:
...     cache.set("greeting", "hello")
...     cache.get("greeting")
...     cache.get("missing") is None
'hello'
True

```

`default_ttl` (in seconds) is used whenever `set` is called without an explicit `ttl`. It
defaults to `None`, meaning entries never expire unless a `ttl` is given. Pass `ttl` to `set` to
override it for a single entry; `ttl=0` evicts the entry instead of storing it:

```pycon
>>> from persista.cache import Cache
>>> with Cache() as cache:
...     cache.set("greeting", "hello")
...     cache.set("short-lived", "value", ttl=30)

```

`contains` checks whether a key is present and unexpired, without returning its value; `delete`
removes a single entry (unlike `set` with `ttl=0`, it doesn't require a value to be given):

```pycon
>>> from persista.cache import Cache
>>> with Cache() as cache:
...     cache.set("greeting", "hello")
...     cache.contains("greeting")
...     cache.delete("greeting")
...     cache.contains("greeting")
True
False

```

`get_many`, `set_many`, `contains_many`, and `delete_many` operate on several keys at once, each
issuing a single batched call to the backing store instead of one call per key — this matters for
stores where each call is a network round trip (e.g. Redis, Postgres). A single `ttl` applies to
every item passed to `set_many`:

```pycon
>>> from persista.cache import Cache
>>> with Cache() as cache:
...     cache.set_many({"a": "hello", "b": "world"}, ttl=60)
...     sorted(cache.get_many(["a", "b", "missing"]).items())
...     cache.contains_many(["a", "missing"])
...     cache.delete_many(["a", "b"])
...     cache.get_many(["a", "b"])
...     cache.try_get_many(["a", "b"])
[('a', 'hello'), ('b', 'world'), ('missing', None)]
[True, False]
{'a': None, 'b': None}
{}

```

`clear` removes every entry:

```pycon
>>> from persista.cache import Cache
>>> with Cache() as cache:
...     cache.set("greeting", "hello")
...     cache.clear()
...     cache.get("greeting") is None
True

```

By default, `Cache` stores entries in an `InMemoryStore`. Pass any other `BaseStore` to persist
cached values, e.g. to share a cache across processes with `RedisStore`:

```python
from persista.cache import Cache
from persista.store import RedisStore

cache = Cache(store=RedisStore("redis://localhost:6379/0"), default_ttl=300)
```

## Distinguishing a Cache Miss from a Cached `None`

`get`/`aget` return `None` both when a key is missing and when the cached value is itself `None`,
so `cache.get("key") is None` alone can't tell the two apart. Pass a `default` (like
`dict.get(key, default)`) to control what's returned on a miss:

```pycon
>>> from persista.cache import Cache
>>> with Cache() as cache:
...     cache.get("missing", "fallback")
'fallback'

```

To actually tell a miss apart from a cached `None`, pass the `MISSING` sentinel as `default` and
compare the result against it with `is`:

```pycon
>>> from persista.cache import Cache, MISSING
>>> with Cache() as cache:
...     cache.set("key", None)
...     cache.get("key", MISSING) is MISSING
...     cache.get("missing", MISSING) is MISSING
False
True

```

`aget` supports the same `default` parameter.

`try_get` returns the same `(hit, value)` pair `get` computes internally, without needing a
sentinel:

```pycon
>>> from persista.cache import Cache
>>> with Cache() as cache:
...     cache.set("key", None)
...     cache.try_get("key")
...     cache.try_get("missing")
(True, None)
(False, None)

```

`atry_get` is the async counterpart.

## Computing a Value on a Cache Miss with `Cache.get_or_compute`

`get_or_compute` returns the cached value for a key, computing and storing it on a cache miss:

```pycon
>>> from persista.cache import Cache
>>> calls = []
>>> def compute(x):
...     calls.append(x)
...     return x * 2
>>> with Cache() as cache:
...     cache.get_or_compute("key", compute, (4,), {})
...     cache.get_or_compute("key", compute, (4,), {})  # served from the cache
8
8
>>> calls
[4]

```

`aget_or_compute` is the async counterpart, for use with an `async def` function. The backing
store is still accessed synchronously; only the function is awaited:

```pycon
>>> import asyncio
>>> from persista.cache import Cache
>>> calls = []
>>> async def compute(x):
...     calls.append(x)
...     return x * 2
>>> async def main():
...     async with Cache() as cache:
...         print(await cache.aget_or_compute("key", compute, (4,), {}))
...         print(await cache.aget_or_compute("key", compute, (4,), {}))  # cached
>>> asyncio.run(main())
8
8
>>> calls
[4]

```

## Memoizing Functions with `Cache.memoize`

`Cache.memoize` is a decorator that caches a function's return value, keyed on the module and
name of the function and on its arguments. It works on both sync and `async def` functions:

```pycon
>>> from persista.cache import Cache
>>> calls = []
>>> with Cache() as cache:
...
...     @cache.memoize(ttl=60)
...     def square(x):
...         calls.append(x)
...         return x * x
...
...     square(4)
...     square(4)  # served from the cache, not re-computed
16
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
- `ignore_non_serializable`: if `True`, the values of keyword arguments that aren't serializable
  with `strategy` are left out of the key, instead of raising an error. This is useful when a
  function takes an argument that will never be serializable (e.g. a logger or a client instance)
  but shouldn't prevent caching: calls that differ only in the value of that argument then share the
  same cache entry. The argument must be passed by keyword: a positional argument is never left out,
  so a call with a non-serializable positional argument raises an error. This includes `self` when
  a method is decorated.

```pycon
>>> from persista.cache import Cache
>>> calls = []
>>> with Cache() as cache:
...
...     @cache.memoize(ttl=60, strategy="json", ignore_non_serializable=True)
...     def greet(name, client=None):
...         calls.append(name)
...         return f"hello {name}"
...
...     greet("Ann", client=object())
...     greet("Ann", client=object())  # different (non-serializable) client, still a cache hit
'hello Ann'
'hello Ann'
>>> calls
['Ann']

```

## Async Caching with `Cache`'s `a`-prefixed Methods

Every `Cache` method has an async counterpart, prefixed with `a`, for use with an async backing
store (an `InMemoryStore` by default).
`aget`/`aset`/`atry_get`/`acontains`/`aget_many`/`aset_many`/`acontains_many`/`adelete`/`adelete_many`/`aclear`
mirror their sync counterparts but are coroutines, accessing the backing `BaseStore` through its
async (`a`-prefixed) methods:

```pycon
>>> import asyncio
>>> from persista.cache import Cache
>>> async def main():
...     async with Cache(default_ttl=60) as cache:
...         await cache.aset("greeting", "hello")
...         print(await cache.aget("greeting"))
...         await cache.aclear()
...         print(await cache.aget("greeting"))
>>> asyncio.run(main())
hello
None

```

`aget_or_compute` accepts either a sync or an `async def` function directly — awaiting it only
if the result is awaitable. The backing store is always accessed with `await`, via its async
(`a`-prefixed) methods:

```pycon
>>> import asyncio
>>> from persista.cache import Cache
>>> calls = []
>>> def compute(x):  # a plain sync function works too
...     calls.append(x)
...     return x * 2
>>> async def main():
...     async with Cache() as cache:
...         print(await cache.aget_or_compute("key", compute, (4,), {}))
...         print(await cache.aget_or_compute("key", compute, (4,), {}))  # cached
>>> asyncio.run(main())
8
8
>>> calls
[4]

```

`amemoize` decorates `async def` (or sync) functions, always returning a coroutine function:

```pycon
>>> import asyncio
>>> from persista.cache import Cache
>>> calls = []
>>> async def main():
...     async with Cache() as cache:
...
...         @cache.amemoize(ttl=60)
...         async def cube(x):
...             calls.append(x)
...             return x * x * x
...
...         print(await cube(4))
...         print(await cube(4))  # served from the cache, not re-computed
>>> asyncio.run(main())
64
64
>>> calls
[4]

```

## Shared Default Caches: `cached` and `async_cached`

For simple cases, `cached` and `async_cached` avoid creating and threading a `Cache` instance
through your code. Both use the same shared module-level default `Cache`, retrieved with
`get_cache` — `cached` through its sync methods, `async_cached` through its async (`a`-prefixed)
methods:

```pycon
>>> from persista.cache import cached
>>> calls = []
>>> @cached(ttl=60)
... def square(x):
...     calls.append(x)
...     return x * x
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
... async def cube(x):
...     calls.append(x)
...     return x * x * x
>>> async def main():
...     print(await cube(4))
...     print(await cube(4))  # served from the cache, not re-computed
>>> asyncio.run(main())
64
64
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
>>> greet("Ann", client=object())
'hello Ann'
>>> greet("Ann", client=object())  # different (non-serializable) client, still a cache hit
'hello Ann'
>>> calls
['Ann']

```

Use `set_cache` to replace the shared default cache, for example to change its backend or
default TTL globally. Since `cached` and `async_cached` both look up the same `get_cache`, this
affects both:

```pycon
>>> from persista.cache import Cache
>>> from persista.cache import get_cache, set_cache
>>> previous = get_cache()
>>> new_cache = Cache(default_ttl=60)
>>> new_cache.open()
>>> set_cache(new_cache)
>>> get_cache().default_ttl
60
>>> set_cache(previous)  # restore the previous default cache

```

## Cache Keys

Internally, `memoize`, `amemoize`, `cached`, and `async_cached` derive a cache key with
`make_call_key`, which identifies the function by its module and qualified name (`__module__` and
`__qualname__`) and passes them with the arguments to `make_key`. Functions with the same name in
different modules therefore have different keys, while two functions with the same module and
qualified name (e.g. two closures returned by the same factory) share their keys. A decorated bound
method is identified by the name of the method, not by its instance, which is not part of its
arguments: decorate it only if the result does not depend on the instance.

`make_key` serializes the name, `args`, and `kwargs` with
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
>>> make_key("add", (1, 2), {}, strategy="json") == make_key("add", (1, 2), {}, strategy="json")
True

```

By default, an argument that isn't serializable with `strategy` raises an error when the key is
computed — meaning the decorated function can't be called with that argument at all. Pass
`ignore_non_serializable=True` to instead leave the values of non-serializable keyword arguments
out of the key:

```pycon
>>> import threading
>>> from persista.cache.utils import make_key
>>> make_key("add", (1,), {"lock": threading.Lock()}, ignore_non_serializable=True) == make_key(
...     "add", (1,), {"lock": threading.Lock()}, ignore_non_serializable=True
... )
True

```

This is useful for arguments that will never be serializable (e.g. a logger or a client instance)
but that shouldn't block caching. The name of the argument stays in the key, but its value does
not, so calls that differ _only_ in such a value are treated as the same call and share a cached
result — make sure that's the behavior you want before enabling it for a given function.

Positional arguments are never left out, because the remaining arguments would shift and different
calls would share a key:

```pycon
>>> import threading
>>> from persista.cache.utils import make_key
>>> make_key("add", (1, threading.Lock()), {}, ignore_non_serializable=True)
Traceback (most recent call last):
...
TypeError: Object of type lock is not JSON serializable...

```

## Building a Cache from a Configuration

`persista` has no factory classes. To describe a cache in a configuration, use `resolve_object` from
[`coola.factory`](https://github.com/durandtibo/coola): the `_target_` key is the fully qualified
name of the class, and the other keys are the arguments of its constructor.
`resolve_object` does not build a configuration nested in another one, so build the store first and
pass it to the cache:

```pycon
>>> from coola.factory import resolve_object
>>> from persista.cache import Cache
>>> from persista.store import BaseStore
>>> config = {
...     "_target_": "persista.cache.Cache",
...     "store": {"_target_": "persista.store.SQLiteStore", "database": ":memory:"},
...     "default_ttl": 60,
... }
>>> store = resolve_object(config["store"], cls=BaseStore)
>>> with resolve_object({**config, "store": store}, cls=Cache) as cache:
...     cache.set("greeting", "hello")
...     print(cache.get("greeting"))
...     print(cache.default_ttl)
hello
60

```

A configuration without a `store` key builds a cache with a new `InMemoryStore`, and needs a single
call: `resolve_object({"_target_": "persista.cache.Cache"}, cls=Cache)`. Only use `resolve_object`
with a configuration from a trusted source, because it imports and calls whatever `_target_` names.
See [building a store from a configuration](store.md#building-a-store-from-a-configuration).

## API Reference

See the [reference documentation](../refs/cache.md) for the full API.
