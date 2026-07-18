r"""Provide asynchronous Redis-backed implementations of
``AsyncBaseStore``."""

from __future__ import annotations

__all__ = ["AsyncBaseRedisStore", "AsyncPickleRedisStore", "AsyncRedisStore"]

import json
import logging
import pickle
from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin

from persista.store.base import AsyncBaseStore
from persista.store.validation import normalize_on_conflict, validate_batch_size
from persista.utils.imports import check_redis, is_redis_available

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator, Mapping
    from typing import Self

    from persista.store.types import OnConflict

if is_redis_available():  # pragma: no cover
    import redis.asyncio as redis

logger: logging.Logger = logging.getLogger(__name__)

_KEYS_SET = "__keys__"


class AsyncBaseRedisStore(AsyncBaseStore, MultilineDisplayMixin):
    r"""Define a base class for asynchronous Redis-backed key-value
    stores.

    Mirrors :class:`~persista.store.redis.BaseRedisStore`, but runs
    every command through :mod:`redis.asyncio` instead of the blocking
    :mod:`redis` client, so it can be awaited from an async
    application without stalling the event loop on network I/O. A
    Redis set at ``__keys__`` tracks the keys currently in the store,
    which allows :meth:`count`, :meth:`keys`, and
    :meth:`contains_many` to avoid scanning the whole keyspace.
    Unlike the SQL-backed stores, Redis has no query language for
    matching on the content of a value, so :meth:`filter` is
    implemented client-side by scanning every value in the store.

    Subclasses only need to implement :meth:`_encode` and
    :meth:`_decode`, which control how a value is serialized to and
    from what is stored in Redis (see :class:`AsyncRedisStore` for a
    JSON encoding and :class:`AsyncPickleRedisStore` for a pickle
    encoding).

    Args:
        url: The Redis connection URL passed to
            ``redis.asyncio.Redis.from_url`` (e.g.
            ``"redis://localhost:6379/0"``).
        **kwargs: Additional keyword arguments to pass to
            ``redis.asyncio.Redis.from_url``.
    """

    # Encodings that return raw bytes (e.g. pickle) must disable
    # response decoding, otherwise redis-py tries to decode
    # non-UTF-8 bytes as text and raises/corrupts the payload.
    _decode_responses: bool = True

    def __init__(self, url: str = "redis://localhost:6379/0", **kwargs: Any) -> None:
        check_redis()
        self._url = url
        self._kwargs = kwargs
        self._closed = False
        self._client = redis.Redis.from_url(url, decode_responses=self._decode_responses, **kwargs)

    @abstractmethod
    def _encode(self, value: dict[str, Any]) -> Any:
        """Serialize a value to what gets stored in Redis."""

    @abstractmethod
    def _decode(self, raw: Any) -> dict[str, Any]:
        """Deserialize a value read back from Redis."""

    @staticmethod
    def _key_str(key: str | bytes) -> str:
        # Keys are always plain strings (see BaseStore), but the raw
        # Redis client returns bytes when `_decode_responses` is False.
        return key.decode() if isinstance(key, bytes) else key

    async def close(self) -> None:
        if self._closed:
            return
        logger.info("Closing Redis connection at %s", self._url)
        await self._client.aclose()
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    async def get(self, key: str) -> dict[str, Any] | None:
        value = await self._client.get(key)
        return self._decode(value) if value is not None else None

    async def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        if not keys:
            return []
        values = await self._client.mget(keys)
        return [self._decode(value) if value is not None else None for value in values]

    async def set(
        self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite"
    ) -> None:
        await self.set_many({key: value}, on_conflict=on_conflict)

    async def set_many(
        self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
    ) -> None:
        if not items:
            return
        on_conflict = normalize_on_conflict(on_conflict)
        if on_conflict == "overwrite":
            await self._set_many(items)
            return

        conflicts = set((await self.contains_many(list(items)))[0])
        if conflicts and on_conflict == "raise":
            msg = f"Key(s) already exist in the store: {sorted(conflicts)}"
            raise KeyError(msg)

        to_write: dict[str, dict[str, Any]] = {}
        for key, value in items.items():
            if key in conflicts:
                if on_conflict == "skip":
                    continue
                to_write[key] = {**(await self.get(key) or {}), **value}
                continue
            to_write[key] = value

        await self._set_many(to_write)

    async def _set_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            pipe = self._client.pipeline()
            for key, value in items.items():
                pipe.set(key, self._encode(value))
            pipe.sadd(_KEYS_SET, *items.keys())
            await pipe.execute()

        logger.debug("Added/replaced %d key-value pair(s)", len(items))

    async def filter(self, **field_filters: Any) -> list[dict[str, Any]]:
        return [
            value
            async for value in self.values()
            if all(value.get(name) == expected for name, expected in field_filters.items())
        ]

    async def delete(self, key: str) -> None:
        pipe = self._client.pipeline()
        pipe.delete(key)
        pipe.srem(_KEYS_SET, key)
        await pipe.execute()

    async def delete_many(self, keys: list[str]) -> None:
        if not keys:
            return
        pipe = self._client.pipeline()
        pipe.delete(*keys)
        pipe.srem(_KEYS_SET, *keys)
        await pipe.execute()

    async def contains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        if not keys:
            return [], []
        flags = await self._client.smismember(_KEYS_SET, keys)
        found = [key for key, flag in zip(keys, flags, strict=True) if flag]
        missing = [key for key, flag in zip(keys, flags, strict=True) if not flag]
        return found, missing

    async def keys(self) -> AsyncIterator[str]:
        for key in await self._client.smembers(_KEYS_SET):
            yield self._key_str(key)

    async def iter_batches(
        self, batch_size: int = 32
    ) -> AsyncGenerator[dict[str, dict[str, Any]], None]:
        validate_batch_size(batch_size)
        all_keys = [self._key_str(key) for key in await self._client.smembers(_KEYS_SET)]
        for i in range(0, len(all_keys), batch_size):
            batch = all_keys[i : i + batch_size]
            values = await self._client.mget(batch)
            yield {
                key: self._decode(value)
                for key, value in zip(batch, values, strict=True)
                if value is not None
            }

    async def count(self) -> int:
        return await self._client.scard(_KEYS_SET)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        # `count` is intentionally omitted: computing it requires an
        # awaited query, which isn't available from this sync method.
        return {"url": self._url, "closed": self._closed} | self._kwargs

    async def __aenter__(self) -> Self:
        if self._closed:
            self._client = redis.Redis.from_url(
                self._url, decode_responses=self._decode_responses, **self._kwargs
            )
            self._closed = False
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()


class AsyncRedisStore(AsyncBaseRedisStore):
    """An asynchronous Redis-backed key-value store.

    Persists values to Redis and supports adding, retrieving,
    filtering, and deleting key-value pairs. Each value is stored as
    a JSON string, which provides flexibility for arbitrary value
    fields without requiring a fixed schema, is human-readable
    directly from Redis, and can be read by any Redis client
    regardless of language. This means only JSON-compatible value
    fields (str, int, float, bool, None, list, dict) are supported;
    use :class:`AsyncPickleRedisStore` if you need to persist
    arbitrary Python objects. Mirrors
    :class:`~persista.store.redis.RedisStore`, but every method is a
    coroutine, backed by :mod:`redis.asyncio` instead of the blocking
    :mod:`redis` client.

    Args:
        url: The Redis connection URL passed to
            ``redis.asyncio.Redis.from_url`` (e.g.
            ``"redis://localhost:6379/0"``).
        **kwargs: Additional keyword arguments to pass to
            ``redis.asyncio.Redis.from_url``.

    Example:
        ```pycon
        >>> import asyncio
        >>> from persista.store import AsyncRedisStore
        >>> async def main():
        ...     store = AsyncRedisStore("redis://localhost:6379/0")
        ...     await store.set_many(
        ...         {
        ...             "1": {
        ...                 "title": "Intro to Python",
        ...                 "author": "Alice",
        ...                 "category": "Programming",
        ...             },
        ...             "2": {
        ...                 "title": "Advanced Python",
        ...                 "author": "Alice",
        ...                 "category": "Programming",
        ...             },
        ...             "3": {"title": "History of Rome", "author": "Bob", "category": "History"},
        ...         }
        ...     )
        ...     result = await store.filter(author="Alice")
        ...     print(len(result))
        ...     await store.close()
        ...
        >>> asyncio.run(main())  # doctest: +SKIP
        2

        ```
    """

    def _encode(self, value: dict[str, Any]) -> str:
        return json.dumps(value)

    def _decode(self, raw: str) -> dict[str, Any]:
        return json.loads(raw)


class AsyncPickleRedisStore(AsyncBaseRedisStore):
    """An asynchronous Redis-backed key-value store that serializes
    values with ``pickle`` instead of JSON.

    Unlike :class:`AsyncRedisStore`, this store can persist arbitrary
    Python objects within a value's fields (tuples, sets, custom
    classes, etc.), not just JSON-compatible types. The tradeoff is
    that values are opaque binary blobs from outside Python (not
    human-readable, not inspectable from non-Python Redis clients),
    and, since :func:`pickle.loads` can execute arbitrary code, this
    store must never be pointed at a Redis instance that isn't fully
    trusted. Mirrors :class:`~persista.store.redis.PickleRedisStore`,
    but every method is a coroutine, backed by :mod:`redis.asyncio`
    instead of the blocking :mod:`redis` client.

    Args:
        url: The Redis connection URL passed to
            ``redis.asyncio.Redis.from_url`` (e.g.
            ``"redis://localhost:6379/0"``).
        **kwargs: Additional keyword arguments to pass to
            ``redis.asyncio.Redis.from_url``.

    Example:
        ```pycon
        >>> import asyncio
        >>> from persista.store import AsyncPickleRedisStore
        >>> async def main():
        ...     store = AsyncPickleRedisStore("redis://localhost:6379/0")
        ...     await store.set("1", {"title": "Intro to Python", "tags": {"python", "intro"}})
        ...     print(await store.get("1"))
        ...     await store.close()
        ...
        >>> asyncio.run(main())  # doctest: +SKIP
        {'title': 'Intro to Python', 'tags': {'python', 'intro'}}

        ```
    """

    _decode_responses = False

    def _encode(self, value: dict[str, Any]) -> bytes:
        return pickle.dumps(value)

    def _decode(self, raw: bytes) -> dict[str, Any]:
        return pickle.loads(raw)  # noqa: S301
