from __future__ import annotations

import pytest
from coola.equality import objects_are_equal

fakeredis = pytest.importorskip("fakeredis")

from persista.store import BaseStore, PickleRedisStore, RedisStore  # noqa: E402
from persista.store.factory import (  # noqa: E402
    BaseStoreFactory,
    PickleRedisStoreFactory,
    RedisStoreFactory,
)

MODULE = "persista.store.redis"


@pytest.fixture(autouse=True)
def _fake_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        f"{MODULE}.redis.Redis.from_url",
        lambda *_args, **kwargs: fakeredis.FakeRedis(
            decode_responses=kwargs.get("decode_responses", True)
        ),
    )


######################################
#     Tests for RedisStoreFactory     #
######################################


# --- Inheritance ---


def test_redis_store_factory_is_base_store_factory() -> None:
    assert isinstance(RedisStoreFactory(), BaseStoreFactory)


# --- make_store ---


def test_redis_store_factory_make_store_returns_base_store() -> None:
    factory = RedisStoreFactory()
    assert isinstance(factory.make_store(), BaseStore)


def test_redis_store_factory_make_store_returns_redis_store() -> None:
    factory = RedisStoreFactory()
    assert isinstance(factory.make_store(), RedisStore)


def test_redis_store_factory_make_store_returns_new_instance_each_call() -> None:
    factory = RedisStoreFactory()
    assert factory.make_store() is not factory.make_store()


# --- _get_repr_kwargs ---


def test_redis_store_factory_get_repr_kwargs() -> None:
    factory = RedisStoreFactory("redis://localhost:6379/0")
    assert objects_are_equal(factory._get_repr_kwargs(), {"url": "redis://localhost:6379/0"})


# --- __repr__ and __str__ ---


def test_redis_store_factory_repr_starts_with_class_name() -> None:
    factory = RedisStoreFactory()
    assert repr(factory).startswith("RedisStoreFactory(")


def test_redis_store_factory_str_starts_with_class_name() -> None:
    factory = RedisStoreFactory()
    assert str(factory).startswith("RedisStoreFactory(")


def test_redis_store_factory_repr_contains_url() -> None:
    factory = RedisStoreFactory()
    assert "url" in repr(factory)


def test_redis_store_factory_str_contains_url() -> None:
    factory = RedisStoreFactory()
    assert "url" in str(factory)


############################################
#     Tests for PickleRedisStoreFactory     #
############################################


# --- Inheritance ---


def test_pickle_redis_store_factory_is_base_store_factory() -> None:
    assert isinstance(PickleRedisStoreFactory(), BaseStoreFactory)


# --- make_store ---


def test_pickle_redis_store_factory_make_store_returns_base_store() -> None:
    factory = PickleRedisStoreFactory()
    assert isinstance(factory.make_store(), BaseStore)


def test_pickle_redis_store_factory_make_store_returns_pickle_redis_store() -> None:
    factory = PickleRedisStoreFactory()
    assert isinstance(factory.make_store(), PickleRedisStore)


def test_pickle_redis_store_factory_make_store_returns_new_instance_each_call() -> None:
    factory = PickleRedisStoreFactory()
    assert factory.make_store() is not factory.make_store()


# --- _get_repr_kwargs ---


def test_pickle_redis_store_factory_get_repr_kwargs() -> None:
    factory = PickleRedisStoreFactory("redis://localhost:6379/0")
    assert objects_are_equal(factory._get_repr_kwargs(), {"url": "redis://localhost:6379/0"})


# --- __repr__ and __str__ ---


def test_pickle_redis_store_factory_repr_starts_with_class_name() -> None:
    factory = PickleRedisStoreFactory()
    assert repr(factory).startswith("PickleRedisStoreFactory(")


def test_pickle_redis_store_factory_str_starts_with_class_name() -> None:
    factory = PickleRedisStoreFactory()
    assert str(factory).startswith("PickleRedisStoreFactory(")
