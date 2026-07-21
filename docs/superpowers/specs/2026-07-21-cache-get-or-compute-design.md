# `Cache.get_or_compute` / `Cache.memoize` design

## Context

`src/persista/cache/cache.py` has an uncommitted, in-progress rename of
`TTLCache` to `Cache` (adding `ignore_none` and a private `_get` helper),
but it left `set()` referencing a `default_ttl` attribute that `__init__`
no longer sets, and dropped the compute-if-absent behavior that
`memoize` used to provide. This spec finishes that class: a generic,
reusable "check cache, else compute" primitive backed by any
`BaseStore`.

This is separate from, and does not change, `TTLCache`, `AsyncTTLCache`,
or the module-level `cached()` / `async_cached()` decorators in
`interface.py` — those keep working exactly as they do today.

## TTL semantics

`Cache.__init__(store=None, default_ttl: float | None = None, ignore_none: bool = False)`

- `default_ttl=None` (the default): entries never expire unless a call
  site passes an explicit `ttl`.
- On `set()` / `get_or_compute()`, `ttl` uses a private sentinel default
  (not `None`) so it can distinguish "not given → use `default_ttl`"
  from an explicit `ttl=None`:
  - `ttl=None` → entry stored with no expiry, never evicted by time.
  - `ttl=0` → the value is not written to the store at all (a
    pass-through no-cache call).
  - `ttl>0` → entry expires after that many seconds; eviction stays
    lazy, checked on the next `get()` for that key, same as today.
  - `ttl<0` → raises `ValueError`.
- `ignore_none`: if `True`, a cached value of `None` is treated as a
  miss by `_get`/`get_or_compute`, so it gets recomputed instead of
  being served forever.

## API

- `get(key)` — same observable behavior as today, reimplemented on top
  of `_get` to share the expiry/`ignore_none` logic.
- `_get(key) -> tuple[bool, Any]` — internal: `(hit, value)`. Checks
  existence via `self._store.contains_many([key])`, applies expiry and
  `ignore_none`. Used by `get`, `get_or_compute`, and `memoize`.
- `set(key, value, ttl=_UNSET)` — writes `{"value": value,
  "expires_at": expires_at | None}`, or skips the write entirely when
  the resolved ttl is `0`.
- `clear()` — unchanged.
- `get_or_compute(key, fn, *args, ttl=_UNSET, **kwargs) -> Any` — on
  cache hit, return the cached value; on miss, call
  `fn(*args, **kwargs)`, `set()` the result, and return it. This is the
  core primitive.
- `memoize(ttl=_UNSET, strategy="pickle", ignore_non_serializable=False)`
  — a decorator built on `get_or_compute`. Derives the cache key from
  the wrapped function's `__qualname__` plus call arguments via the
  existing `persista.cache.utils.make_key` helper (same approach as
  `interface.py`'s `cached()`). Sync functions only — no `async def`
  support, matching the rest of `Cache`.

## Testing

- TTL semantics: `ttl=None` never expires; `ttl=0` never gets stored;
  `ttl>0` expires and is evicted lazily on `get()`; negative `ttl`
  raises `ValueError`.
- `ignore_none`: cached `None` is a miss when `ignore_none=True`, a hit
  (returning `None`) when `False`.
- `get_or_compute`: miss calls `fn` once and caches the result; a
  second call with the same key is a hit and does not call `fn` again.
- `memoize`: two calls with equal arguments share a cache entry (`fn`
  called once); calls with different arguments get separate entries.
