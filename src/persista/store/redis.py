r"""Provide a Redis-backed implementation of ``BaseStore``, storing
values as JSON."""

from __future__ import annotations

__all__ = ["RedisStore"]

import json
import logging
from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin
from coola.utils.batching import batchify

from persista.store.base import BaseStore
from persista.store.validation import normalize_on_conflict, validate_batch_size
from persista.utils.imports import check_redis, is_redis_available

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator, Mapping

    from typing_extensions import Self

    from persista.store.types import OnConflict

if is_redis_available():  # pragma: no cover
    import redis

logger: logging.Logger = logging.getLogger(__name__)

_KEYS_SET = "__keys__"


class RedisStore(BaseStore, MultilineDisplayMixin):
    """A Redis-backed key-value store.

    Persists values to Redis and supports adding, retrieving,
    filtering, and deleting key-value pairs. Each value is stored as
    a JSON string, which provides flexibility for arbitrary value
    fields without requiring a fixed schema. A Redis set at
    ``__keys__`` tracks the keys currently in the store, which allows
    :meth:`count`, :meth:`keys`, and :meth:`contains_many` to avoid
    scanning the whole keyspace. Unlike the SQL-backed stores, Redis
    has no query language for matching on the content of a value, so
    :meth:`filter` is implemented client-side by scanning every value
    in the store.

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

    def __init__(self, url: str = "redis://localhost:6379/0", **kwargs: Any) -> None:
        check_redis()
        self._url = url
        self._kwargs = kwargs
        self._closed = False
        self._client = redis.Redis.from_url(url, decode_responses=True, **kwargs)

    def close(self) -> None:
        if self._closed:
            return
        logger.info("Closing Redis connection at %s", self._url)
        self._client.close()
        self._closed = True

    def get(self, key: str) -> dict[str, Any] | None:
        value = self._client.get(key)
        return json.loads(value) if value is not None else None

    def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        if not keys:
            return []
        values = self._client.mget(keys)
        return [json.loads(value) if value is not None else None for value in values]

    def set(self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite") -> None:
        self.set_many({key: value}, on_conflict=on_conflict)

    def set_many(
        self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
    ) -> None:
        if not items:
            return
        on_conflict = normalize_on_conflict(on_conflict)

        conflicts = set(self.contains_many(list(items))[0])
        if conflicts and on_conflict == "raise":
            msg = f"Key(s) already exist in the store: {sorted(conflicts)}"
            raise KeyError(msg)

        to_write: dict[str, dict[str, Any]] = {}
        for key, value in items.items():
            if key in conflicts:
                if on_conflict == "skip":
                    continue
                if on_conflict == "merge":
                    to_write[key] = {**(self.get(key) or {}), **value}
                    continue
            to_write[key] = value

        if to_write:
            pipe = self._client.pipeline()
            for key, value in to_write.items():
                pipe.set(key, json.dumps(value))
            pipe.sadd(_KEYS_SET, *to_write.keys())
            pipe.execute()

        logger.debug("Added/replaced %d key-value pair(s)", len(to_write))

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
        yield from self._client.smembers(_KEYS_SET)

    def iter_batches(
        self, batch_size: int = 32
    ) -> Generator[dict[str, dict[str, Any]], None, None]:
        validate_batch_size(batch_size)
        all_keys = list(self._client.smembers(_KEYS_SET))
        for batch in batchify(all_keys, size=batch_size):
            values = self._client.mget(batch)
            yield {
                key: json.loads(value)
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
            self._client = redis.Redis.from_url(self._url, decode_responses=True, **self._kwargs)
            self._closed = False
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
