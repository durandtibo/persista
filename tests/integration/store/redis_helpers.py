r"""Shared helpers for Redis-backed integration tests.

Used by ``test_redis.py``, ``test_async_redis.py``, and
``test_consistency.py``, which all need to skip Redis-dependent tests
the same way: when the ``redis`` package isn't installed, or when no
Redis server is reachable at ``REDIS_URL``.
"""

from __future__ import annotations

__all__ = [
    "REDIS_URL",
    "delete_namespaces",
    "redis_server_available",
    "redis_server_reachable",
]

import os

import pytest

from persista.utils.imports import is_redis_available

if is_redis_available():
    import redis

REDIS_URL = os.environ.get("PERSISTA_TEST_REDIS_URL", "redis://localhost:6379/0")


def redis_server_reachable() -> bool:
    r"""Indicate whether a Redis server is reachable at
    ``REDIS_URL``."""
    if not is_redis_available():
        return False
    try:
        with redis.Redis.from_url(REDIS_URL, socket_connect_timeout=1) as client:
            client.ping()
    except redis.exceptions.RedisError:
        return False
    return True


redis_server_available = pytest.mark.skipif(
    not redis_server_reachable(), reason="Requires a reachable Redis server"
)


def delete_namespaces(prefix: str) -> None:
    r"""Delete the Redis keys that start with a prefix, if the server is
    reachable.

    Args:
        prefix: The start of the keys to delete. It must not contain the
            special characters of the Redis patterns.
    """
    if not redis_server_reachable():
        return
    with redis.Redis.from_url(REDIS_URL) as client:
        for key in client.scan_iter(match=f"{prefix}*", count=1000):
            client.delete(key)
