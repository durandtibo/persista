# Caching

:book: This page describes the `persista.cache` package, which provides caching for values and
function calls, with both synchronous and asynchronous APIs.

**Prerequisites:** You'll need to know a bit of Python, and it helps to be familiar with the
[store user guide](store.md) since caches are backed by a `BaseStore`.

## Overview

The `persista.cache` package provides two related ways to cache data:

- `Cache`: an explicit cache object, backed by any `BaseStore` (an in-memory store by default).
  Every method that accesses the store has an async counterpart, prefixed with `a`
  (`aget`/`aset`/`aclear`/...). Its `memoize` method decorates functions.
- `cached`: a decorator that caches the results of a function in a shared default `Cache`

An entry can optionally have an expiration time (TTL). Once the TTL of a key has elapsed, the key
is a miss, as if it had never been set.

| Method                     | Async twin        | What it does                                         |
| -------------------------- | ----------------- | ---------------------------------------------------- |
| `get(key, default=None)`   | `aget`            | the value of a key, or `default`                     |
| `get_many(keys)`           | `aget_many`       | a `dict` of the keys that are hits, and their values |
| `contains(key)`            | `acontains`       | whether a key is a hit                               |
| `set(key, value, ttl=...)` | `aset`            | write a value                                        |
| `set_many(items, ttl=...)` | `aset_many`       | write several values                                 |
| `delete(key)`              | `adelete`         | remove a key                                         |
| `delete_many(keys)`        | `adelete_many`    | remove several keys                                  |
| `clear()`                  | `aclear`          | remove everything in the store                       |
| `get_or_compute(key, fn)`  | `aget_or_compute` | the value of a key, computed and stored on a miss    |
| `memoize(...)`             | (decorates both)  | cache the results of a function                      |

Like a store, a cache must be opened (`open`/`aopen`, or `with`/`async with`) before it is used:
every method that accesses the store raises `RuntimeError` on a closed cache, also with an empty
input.

## Properties

What a cache guarantees, and where each guarantee stops. The
[properties of the package](package.md) apply too.

| Property       | Guarantee                                                                                                                                                   | Limits                                                                                                                                                                                                     |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Hit or miss    | A hit returns the stored value, as the codec of the store reads it back; an expired or absent key is a miss. A cached `None` can be told apart from a miss. | The expiry uses the wall clock of the machine. A read that finds an expired entry deletes its key, so it can remove a value that another writer stores between the read and the deletion.                  |
| No false hit   | Two memoized calls share a key only if their functions have the same module and qualified name, and their arguments are equal and of the same types.        | **A function is identified by its name only**: closures, lambdas, wrappers made with `functools.wraps` and methods with `ignore=("self",)` can [share results](#limits). A custom `key=` is used as it is. |
| Explicit keys  | An argument that cannot be encoded raises `TypeError`. It is left out of the key only if its parameter is named in `ignore`, or if `key=` computes the key. | None.                                                                                                                                                                                                      |
| One TTL rule   | `ttl` (else `default_ttl`) is `None` (never expires), `0` (delete) or positive. A negative or `NaN` value raises `ValueError`.                              | None.                                                                                                                                                                                                      |
| Owns its store | `clear` clears the whole store.                                                                                                                             | Do not give a cache a store that holds other data: nothing checks it.                                                                                                                                      |

### Not Guaranteed

- Concurrent misses on the same key can compute the value several times.
- There is no size limit, and an expired entry stays in the store until its key is read again.
- A miss of a memoized call returns the computed value, a hit its codec round trip: a tuple stored
  with the `json` codec comes back as a list.
- The limits of the [backing store](store.md#limits-of-the-backends) apply.
- Decoding a `pickle` payload can execute arbitrary code, so only share a store that uses
  `PickleCodec` with trusted writers.
- The keys are written in the log messages at the `DEBUG` level: do not put a secret in a key.

## Using `Cache` Directly

Create a `Cache` and use `set`/`get` like a dictionary:

```pycon
>>> from persista.cache import Cache
>>> with Cache(default_ttl=60) as cache:
...     cache.set("greeting", "hello")
...     cache.get("greeting")
...     cache.get("missing") is None
'hello'
True

```

`contains` checks whether a key is present and unexpired, without returning its value, and
`delete` removes a single entry:

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

`get_many`, `set_many`, and `delete_many` operate on several keys at once, each issuing a single
batched call to the backing store instead of one call per key. This matters for stores where each
call is a network round trip (e.g. Redis, PostgreSQL). `get_many` returns the hits only, and a
single `ttl` applies to every item passed to `set_many`:

```pycon
>>> from persista.cache import Cache
>>> with Cache() as cache:
...     cache.set_many({"a": "hello", "b": "world"}, ttl=60)
...     cache.get_many(["a", "b", "missing"])
...     cache.delete_many(["a", "b"])
...     cache.get_many(["a", "b"])
{'a': 'hello', 'b': 'world'}
{}

```

`clear` removes every entry. It clears the whole backing store, so a cache **owns its store**: do
not give it a store that holds other data.

```pycon
>>> from persista.cache import Cache
>>> with Cache() as cache:
...     cache.set("greeting", "hello")
...     cache.clear()
...     cache.get("greeting") is None
True

```

## Time-to-Live

`default_ttl` (in seconds) applies to every entry written without an explicit `ttl`. It defaults
to `None`. The same rule applies to `default_ttl` and to every `ttl` argument:

| `ttl`             | Effect                                                                |
| ----------------- | --------------------------------------------------------------------- |
| `None`            | the entry never expires                                               |
| `0`               | the value is not written, and an existing entry of the key is deleted |
| a positive number | the entry expires after this number of seconds                        |
| negative or `NaN` | `ValueError`                                                          |

```pycon
>>> from persista.cache import Cache
>>> with Cache(default_ttl=60) as cache:
...     cache.set("greeting", "hello", ttl=None)  # never expires
...     cache.set("greeting", "bonjour", ttl=0)  # deletes the entry
...     cache.contains("greeting")
...     cache.set("greeting", "salut", ttl=-1)
Traceback (most recent call last):
...
ValueError: ttl must be None, 0 or positive, got -1

```

The expiry is a Unix timestamp, so it also applies to the processes that share a persistent store.
It is checked when an entry is read. **An expired entry stays in the store until its key is read
again** (or deleted, overwritten, or the cache cleared): there is no background eviction. A cache
that writes many keys that are never read again therefore grows until it is cleared.

## Values and Stores

By default, `Cache` stores entries in an `InMemoryStore` with the
[`PickleCodec`](store.md#values-and-codecs): any value that can be pickled is cached, a hit returns
it with its types, and each hit returns a new copy. A value that cannot be pickled, such as a lambda,
a generator, a lock, or an instance of a class defined inside a function, raises an error.

```pycon
>>> from persista.cache import Cache
>>> with Cache() as cache:
...     cache.set("point", (1, {2}))
...     cache.get("point")
(1, {2})

```

The codec of the backing store decides which values can be cached. For example, a cache over
`InMemoryStore()`, which uses `JsonCodec`, returns a tuple as a list and rejects a set.
`NullStore`, which disables caching, also uses `JsonCodec`: it rejects the values that JSON cannot
represent, although it does not keep them.

Pass any other `BaseStore` to persist cached values, e.g. to share a cache across processes with
`RedisStore`:

```python
from persista.cache import Cache
from persista.store import RedisStore

cache = Cache(RedisStore("redis://localhost:6379/0", namespace="cache"), default_ttl=300)
```

`clear` clears the whole store, so give a cache a namespace of its own.

After async calls on a cache over a `RedisStore`, close it with `await cache.aclose()` (or
`async with`): `close` raises `RuntimeError` while the async client of the store is open, that is,
until the event loop that used it is closed by `aclose` or shuts down, as it does at the end of
`asyncio.run`. The same holds for a cache given to `AsyncHttpClient`. See
[event loops and closing](store.md#event-loops-and-closing).

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
>>> from persista.cache import MISSING, Cache
>>> with Cache() as cache:
...     cache.set("key", None)
...     cache.get("key", MISSING) is MISSING
...     cache.get("missing", MISSING) is MISSING
False
True

```

With several keys, `get_many` leaves the misses out of its result, so `key in result` tells whether
a key is a hit.

## Computing a Value on a Cache Miss with `Cache.get_or_compute`

`get_or_compute` returns the cached value for a key, computing and storing it on a cache miss. The
function takes no argument: use a `lambda` or `functools.partial` to pass some.

```pycon
>>> from functools import partial
>>> from persista.cache import Cache
>>> calls = []
>>> def compute(x):
...     calls.append(x)
...     return x * 2
>>> with Cache() as cache:
...     cache.get_or_compute("key", partial(compute, 4))
...     cache.get_or_compute("key", partial(compute, 4))  # served from the cache
8
8
>>> calls
[4]

```

`aget_or_compute` is the async counterpart. It accepts a sync or an `async def` function, and
accesses the backing store with its async methods. A sync function is called in the event loop, which
it blocks until it returns:

```pycon
>>> import asyncio
>>> from persista.cache import Cache
>>> async def compute():
...     return 8
>>> async def main():
...     async with Cache() as cache:
...         print(await cache.aget_or_compute("key", compute))
...         print(await cache.aget_or_compute("key", compute))  # cached
>>> asyncio.run(main())
8
8

```

## Memoizing Functions with `Cache.memoize`

`Cache.memoize` is a decorator that caches the results of a function. It works on both sync and
`async def` functions, and the decorated function is of the same kind:

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
...     square(x=4)  # the same call: served from the cache
16
16
>>> calls
[4]

```

```pycon
>>> import asyncio
>>> from persista.cache import Cache
>>> async def main():
...     async with Cache() as cache:
...
...         @cache.memoize(ttl=60)
...         async def cube(x):
...             return x * x * x
...
...         print(await cube(4))
...         print(await cube(4))  # served from the cache, not re-computed
>>> asyncio.run(main())
64
64

```

It takes three keyword-only options: `ttl` (see [Time-to-Live](#time-to-live)), `ignore` and
`key`.

### The Key of a Call

The key of a call is a hash of:

- the module of the function and its qualified name (`__module__` and `__qualname__`);
- its arguments, bound to its parameters, with the default values.

Two ways to write the same call therefore share a result: `f(1)`, `f(a=1)` and, if `2` is the
default of `b`, `f(1, b=2)`. The order of the keyword arguments and of the items of a `dict` or a
`set` does not matter.

The arguments are hashed in a
[canonical encoding](../refs/utils.md) (`persista.utils.canonical`) that is the same in every
process, so processes that share a persistent store share the results. It keeps the types apart:
`1`, `1.0`, `True` and `"1"` are four different arguments, and so are a list and a tuple.

```pycon
>>> from persista.cache import Cache
>>> with Cache() as cache:
...
...     @cache.memoize()
...     def kind(items):
...         return type(items).__name__
...
...     kind([1, 2])
...     kind((1, 2))
'list'
'tuple'

```

The encoding covers `None`, `bool`, `int`, `float`, `str`, `bytes`, `list`, `tuple`, `dict`, `set`
and `frozenset`. Any other argument raises `TypeError`, including an instance of a subclass of these
types (such as a `str` enum or a named tuple). A default value is an argument too.

### Arguments That Cannot Be Encoded

An argument is never left out of the key silently. Name its parameter in `ignore` to leave it out,
for an argument that does not change the result, such as a client or a logger. Calls that only
differ in an ignored argument share a result:

```pycon
>>> from persista.cache import Cache
>>> calls = []
>>> with Cache() as cache:
...
...     @cache.memoize(ignore=("client",))
...     def greet(name, client=None):
...         calls.append(name)
...         return f"hello {name}"
...
...     greet("Ann", client=object())
...     greet("Ann", client=object())  # another client, still a cache hit
'hello Ann'
'hello Ann'
>>> calls
['Ann']

```

`ignore` takes the names of parameters; a name that the function does not have raises
`ValueError` when the function is decorated. The name of a `*args` or `**kwargs` parameter leaves
out all the arguments that it collects (one keyword collected by `**kwargs` cannot be ignored on
its own).

Alternatively, `key` is a function that is called with the arguments of each call and returns the
key. The key is used as is, so make it differ between the functions that share the cache. `ignore`
and `key` cannot be used together.

```pycon
>>> from decimal import Decimal
>>> from persista.cache import Cache
>>> with Cache() as cache:
...
...     @cache.memoize(key=lambda price: f"double:{price}")
...     def double(price):
...         return price * 2
...
...     double(Decimal("1.5"))
...     cache.contains("double:1.5")
Decimal('3.0')
True

```

### Methods

The first argument of a method (`self`, or `cls`) cannot be encoded, so a method needs `ignore` or
`key`. With `ignore=("self",)`, all the instances share the results: use it only if the result does
not depend on the instance. Otherwise, build the key from what identifies the instance:

```pycon
>>> from persista.cache import Cache
>>> cache = Cache()
>>> cache.open()
>>> class Loader:
...     def __init__(self, root):
...         self.root = root
...
...     @cache.memoize(key=lambda self, name: f"Loader.path:{self.root!r}:{name!r}")
...     def path(self, name):
...         return f"{self.root}/{name}"
>>> Loader("a").path("x")
'a/x'
>>> Loader("b").path("x")
'b/x'
>>> cache.close()

```

A callable without a `__qualname__`, such as a `functools.partial`, and a built-in method bound to
an object, such as `some_dict.get`, cannot be identified and need `key`.

### Limits

- A function is identified by its name only. Two functions with the same module and qualified name,
  such as two closures returned by the same function or two lambdas of the same scope, **share their
  results**; so do all the scripts run as `__main__` that share a persistent store. Give such
  functions a `key`.
- A wrapper made with `functools.wraps` has the name of the function that it wraps: memoizing both,
  or two such wrappers of one function, shares their results.
- A bound method, such as `loader.path`, is a method too: the object is an argument. It raises
  `TypeError` without `ignore` or `key`, and with `ignore=("self",)` the bound methods of all the
  objects share their results.
- The code of the function is not part of the key: after a change of the function, a persistent cache
  still returns the old results until they expire or the cache is cleared.
- `-0.0` and `0.0` are different arguments, and every `NaN` is the same one.
- A miss returns the computed result, and a hit what the codec of the store reads back: with the
  `json` codec, a tuple is computed as a tuple and read back as a list.
- Concurrent misses on the same call can run the function several times.
- There is no size limit, and an expired entry stays in the store until its key is read again.

## Shared Default Cache: `cached`

For simple cases, `cached` avoids creating and threading a `Cache` instance through your code. It is
`memoize` on the shared default cache, which `get_cache` returns, and takes the same options:

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

The default cache is created by the first call of `get_cache` (importing `persista.cache` creates
nothing). It keeps its entries in memory for 300 seconds, with the `PickleCodec`.

Use `set_cache` to replace it, for example to change its backend or default TTL globally. `cached`
calls `get_cache` on every call, so this also affects the functions that are already decorated.
`set_cache` does not open the new cache, nor close the previous one:

```pycon
>>> from persista.cache import Cache, get_cache, set_cache
>>> previous = get_cache()
>>> new_cache = Cache(default_ttl=60)
>>> new_cache.open()
>>> set_cache(new_cache)
>>> get_cache().default_ttl
60
>>> set_cache(previous)  # restore the previous default cache

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

A configuration without a `store` key builds a cache with the default store, and needs a single
call: `resolve_object({"_target_": "persista.cache.Cache"}, cls=Cache)`. Only use `resolve_object`
with a configuration from a trusted source, because it imports and calls whatever `_target_` names.
See [building a store from a configuration](store.md#building-a-store-from-a-configuration).

## API Reference

See the [reference documentation](../refs/cache.md) for the full API.
