r"""Provide factories for Redis-backed persista BaseStore models."""

from __future__ import annotations

__all__ = ["PickleRedisStoreFactory", "RedisStoreFactory"]

from typing import Any

from coola.display import MultilineDisplayMixin

from persista.store.factory.base import BaseStoreFactory
from persista.store.redis import PickleRedisStore, RedisStore


class RedisStoreFactory(BaseStoreFactory, MultilineDisplayMixin):
    """A factory that creates a new :class:`~persista.store.RedisStore`
    instance on each call to :meth:`make_store`.

    Args:
        url: The Redis connection URL passed to
            ``redis.Redis.from_url``.
        **kwargs: Additional keyword arguments to pass to
            ``redis.Redis.from_url``.

    Example:
        ```pycon
        >>> from persista.store.factory import RedisStoreFactory
        >>> factory = RedisStoreFactory("redis://localhost:6379/0")
        >>> store = factory.make_store()  # doctest: +SKIP

        ```
    """

    def __init__(self, url: str = "redis://localhost:6379/0", **kwargs: Any) -> None:
        self._url = url
        self._kwargs = kwargs

    def make_store(self) -> RedisStore:
        return RedisStore(self._url, **self._kwargs)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"url": self._url} | self._kwargs


class PickleRedisStoreFactory(BaseStoreFactory, MultilineDisplayMixin):
    """A factory that creates a new
    :class:`~persista.store.PickleRedisStore` instance on each call to
    :meth:`make_store`.

    Args:
        url: The Redis connection URL passed to
            ``redis.Redis.from_url``.
        **kwargs: Additional keyword arguments to pass to
            ``redis.Redis.from_url``.

    Example:
        ```pycon
        >>> from persista.store.factory import PickleRedisStoreFactory
        >>> factory = PickleRedisStoreFactory("redis://localhost:6379/0")
        >>> store = factory.make_store()  # doctest: +SKIP

        ```
    """

    def __init__(self, url: str = "redis://localhost:6379/0", **kwargs: Any) -> None:
        self._url = url
        self._kwargs = kwargs

    def make_store(self) -> PickleRedisStore:
        return PickleRedisStore(self._url, **self._kwargs)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"url": self._url} | self._kwargs
