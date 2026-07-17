r"""Provide Redis-backed implementations of ``BaseStore``."""

from __future__ import annotations

__all__ = ["BaseRedisStore", "PickleRedisStore", "RedisStore"]

import json
import logging
import pickle
from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin
from coola.utils.batching import batchify

from persista.store.base import BaseStore
from persista.store.validation import normalize_on_conflict, validate_batch_size
from persista.utils.imports import check_redis, is_redis_available

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator, Mapping
    from typing import Self

    from persista.store.types import OnConflict

if is_redis_available():  # pragma: no cover
    import redis

logger: logging.Logger = logging.getLogger(__name__)

_KEYS_SET = "__keys__"


class BaseRedisStore(BaseStore, MultilineDisplayMixin):
    r"""Define a base class for Redis-backed key-value stores.

    A Redis set at ``__keys__`` tracks the keys currently in the
    store, which allows :meth:`count`, :meth:`keys`, and
    :meth:`contains_many` to avoid scanning the whole keyspace.
    Unlike the SQL-backed stores, Redis has no query language for
    matching on the content of a value, so :meth:`filter` is
    implemented client-side by scanning every value in the store.

    Subclasses only need to implement :meth:`_encode` and
    :meth:`_decode`, which control how a value is serialized to and
    from what is stored in Redis (see :class:`RedisStore` for a JSON
    encoding and :class:`~persista.store.redis_pickle.PickleRedisStore`
    for a pickle encoding).

    Args:
        url: The Redis connection URL passed to
            ``redis.Redis.from_url`` (e.g.
            ``"redis://localhost:6379/0"``).
        **kwargs: Additional keyword arguments to pass to
            ``redis.Redis.from_url``.
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

    def close(self) -> None:
        if self._closed:
            return
        logger.info("Closing Redis connection at %s", self._url)
        self._client.close()
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    def get(self, key: str) -> dict[str, Any] | None:
        value = self._client.get(key)
        return self._decode(value) if value is not None else None

    def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        if not keys:
            return []
        values = self._client.mget(keys)
        return [self._decode(value) if value is not None else None for value in values]

    def set(self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite") -> None:
        self.set_many({key: value}, on_conflict=on_conflict)

    def set_many(
        self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
    ) -> None:
        if not items:
            return
        on_conflict = normalize_on_conflict(on_conflict)
        if on_conflict == "overwrite":
            self._set_many(items)
            return

        conflicts = set(self.contains_many(list(items))[0])
        if conflicts and on_conflict == "raise":
            msg = f"Key(s) already exist in the store: {sorted(conflicts)}"
            raise KeyError(msg)

        to_write: dict[str, dict[str, Any]] = {}
        for key, value in items.items():
            if key in conflicts:
                if on_conflict == "skip":
                    continue
                to_write[key] = {**(self.get(key) or {}), **value}
                continue
            to_write[key] = value

        self._set_many(to_write)

    def _set_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            pipe = self._client.pipeline()
            for key, value in items.items():
                pipe.set(key, self._encode(value))
            pipe.sadd(_KEYS_SET, *items.keys())
            pipe.execute()

        logger.debug("Added/replaced %d key-value pair(s)", len(items))

    def filter(self, **field_filters: Any) -> list[dict[str, Any]]:
        return [
            value
            for value in self.values()
            if all(value.get(name) == expected for name, expected in field_filters.items())
        ]

    def delete(self, key: str) -> None:
        pipe = self._client.pipeline()
        pipe.delete(key)
        pipe.srem(_KEYS_SET, key)
        pipe.execute()

    def delete_many(self, keys: list[str]) -> None:
        if not keys:
            return
        pipe = self._client.pipeline()
        pipe.delete(*keys)
        pipe.srem(_KEYS_SET, *keys)
        pipe.execute()

    def contains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        if not keys:
            return [], []
        flags = self._client.smismember(_KEYS_SET, keys)
        found = [key for key, flag in zip(keys, flags, strict=True) if flag]
        missing = [key for key, flag in zip(keys, flags, strict=True) if not flag]
        return found, missing

    def keys(self) -> Iterator[str]:
        for key in self._client.smembers(_KEYS_SET):
            yield self._key_str(key)

    def iter_batches(
        self, batch_size: int = 32
    ) -> Generator[dict[str, dict[str, Any]], None, None]:
        validate_batch_size(batch_size)
        all_keys = [self._key_str(key) for key in self._client.smembers(_KEYS_SET)]
        for batch in batchify(all_keys, size=batch_size):
            values = self._client.mget(batch)
            yield {
                key: self._decode(value)
                for key, value in zip(batch, values, strict=True)
                if value is not None
            }

    def count(self) -> int:
        return self._client.scard(_KEYS_SET)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"url": self._url, "closed": self._closed}
        if not self._closed:
            kwargs["count"] = self.count()
        return kwargs | self._kwargs

    def __enter__(self) -> Self:
        if self._closed:
            self._client = redis.Redis.from_url(
                self._url, decode_responses=self._decode_responses, **self._kwargs
            )
            self._closed = False
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class RedisStore(BaseRedisStore):
    """A Redis-backed key-value store.

    Persists values to Redis and supports adding, retrieving,
    filtering, and deleting key-value pairs. Each value is stored as
    a JSON string, which provides flexibility for arbitrary value
    fields without requiring a fixed schema, is human-readable
    directly from Redis, and can be read by any Redis client
    regardless of language. This means only JSON-compatible value
    fields (str, int, float, bool, None, list, dict) are supported;
    use :class:`~persista.store.redis_pickle.PickleRedisStore` if you
    need to persist arbitrary Python objects.

    Args:
        url: The Redis connection URL passed to
            ``redis.Redis.from_url`` (e.g.
            ``"redis://localhost:6379/0"``).
        **kwargs: Additional keyword arguments to pass to
            ``redis.Redis.from_url``.

    Example:
        ```pycon
        >>> from persista.store import RedisStore
        >>> store = RedisStore("redis://localhost:6379/0")  # doctest: +SKIP
        >>> store.set_many(
        ...     {
        ...         "1": {"title": "Intro to Python", "author": "Alice", "category": "Programming"},
        ...         "2": {"title": "Advanced Python", "author": "Alice", "category": "Programming"},
        ...         "3": {"title": "History of Rome", "author": "Bob", "category": "History"},
        ...     }
        ... )  # doctest: +SKIP
        >>> len(store.filter(author="Alice"))  # doctest: +SKIP
        2

        ```
    """

    def _encode(self, value: dict[str, Any]) -> str:
        return json.dumps(value)

    def _decode(self, raw: str) -> dict[str, Any]:
        return json.loads(raw)


class PickleRedisStore(BaseRedisStore):
    """A Redis-backed key-value store that serializes values with
    ``pickle`` instead of JSON.

    Unlike :class:`~persista.store.RedisStore`, this store can persist
    arbitrary Python objects within a value's fields (tuples, sets,
    custom classes, etc.), not just JSON-compatible types. The
    tradeoff is that values are opaque binary blobs from outside
    Python (not human-readable, not inspectable from non-Python Redis
    clients), and, since :func:`pickle.loads` can execute arbitrary
    code, this store must never be pointed at a Redis instance that
    isn't fully trusted.

    Args:
        url: The Redis connection URL passed to
            ``redis.Redis.from_url`` (e.g.
            ``"redis://localhost:6379/0"``).
        **kwargs: Additional keyword arguments to pass to
            ``redis.Redis.from_url``.

    Example:
        ```pycon
        >>> from persista.store import PickleRedisStore
        >>> store = PickleRedisStore("redis://localhost:6379/0")  # doctest: +SKIP
        >>> store.set(
        ...     "1", {"title": "Intro to Python", "tags": {"python", "intro"}}
        ... )  # doctest: +SKIP
        >>> store.get("1")  # doctest: +SKIP
        {'title': 'Intro to Python', 'tags': {'python', 'intro'}}

        ```
    """

    _decode_responses = False

    def _encode(self, value: dict[str, Any]) -> bytes:
        return pickle.dumps(value)

    def _decode(self, raw: bytes) -> dict[str, Any]:
        return pickle.loads(raw)  # noqa: S301
