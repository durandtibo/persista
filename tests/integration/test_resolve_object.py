r"""Integration tests of ``coola.factory.resolve_object`` with the
objects of ``persista``.

The user guides document ``resolve_object`` as the way to build a store,
a cache or a record store from a configuration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from coola.factory import resolve_object

from persista.cache import Cache
from persista.record import Record
from persista.record.store import RecordStore
from persista.store import BaseStore, InMemoryStore, PickleCodec, SQLiteStore
from persista.testing.fixtures import (
    duckdb_available,
    lmdb_available,
    psycopg_available,
    redis_available,
)

if TYPE_CHECKING:
    from pathlib import Path

LOCAL_STORES = [
    pytest.param("InMemoryStore", {}, id="in_memory"),
    pytest.param("SQLiteStore", {"database": ":memory:"}, id="sqlite"),
    pytest.param(
        "SQLiteStore", {"database": ":memory:", "codec": PickleCodec()}, id="pickle_sqlite"
    ),
    pytest.param("DuckDBStore", {"database": ":memory:"}, id="duckdb", marks=duckdb_available),
]

DIRECTORY_STORES = [
    pytest.param("FileStore", {}, id="file"),
    pytest.param("FileStore", {"codec": PickleCodec()}, id="pickle_file"),
    pytest.param("LmdbStore", {}, id="lmdb", marks=lmdb_available),
    pytest.param("LmdbStore", {"codec": PickleCodec()}, id="pickle_lmdb", marks=lmdb_available),
]

SERVER_STORES = [
    pytest.param(
        "RedisStore", {"url": "redis://localhost:6379/0"}, id="redis", marks=redis_available
    ),
    pytest.param(
        "PickleRedisStore",
        {"url": "redis://localhost:6379/0"},
        id="pickle_redis",
        marks=redis_available,
    ),
    pytest.param(
        "PostgresStore",
        {"conninfo": "postgresql://user:pass@localhost/dbname"},
        id="postgres",
        marks=psycopg_available,
    ),
]


def make_cache_config() -> dict[str, Any]:
    r"""Return the configuration of a cache with a nested store."""
    return {
        "_target_": "persista.cache.Cache",
        "store": {"_target_": "persista.store.SQLiteStore", "database": ":memory:"},
        "default_ttl": 60,
    }


def make_record_store_config() -> dict[str, Any]:
    r"""Return the configuration of a record store with a nested
    store."""
    return {
        "_target_": "persista.record.store.RecordStore",
        "store": {"_target_": "persista.store.SQLiteStore", "database": ":memory:"},
    }


###############################
#     Tests for BaseStore     #
###############################


@pytest.mark.parametrize(("name", "kwargs"), LOCAL_STORES)
def test_resolve_object_local_store_class(name: str, kwargs: dict[str, Any]) -> None:
    """Test that a configuration builds the local store that it
    names."""
    store = resolve_object({"_target_": f"persista.store.{name}", **kwargs}, cls=BaseStore)
    assert type(store).__name__ == name


@pytest.mark.parametrize(("name", "kwargs"), LOCAL_STORES)
def test_resolve_object_local_store_round_trip(name: str, kwargs: dict[str, Any]) -> None:
    """Test that a local store built from a configuration stores
    values."""
    config = {"_target_": f"persista.store.{name}", **kwargs}
    with resolve_object(config, cls=BaseStore) as store:
        store.set("1", {"name": "Alice"})
        assert store.get("1") == {"name": "Alice"}


@pytest.mark.parametrize(("name", "kwargs"), DIRECTORY_STORES)
def test_resolve_object_directory_store_class(
    name: str, kwargs: dict[str, Any], tmp_path: Path
) -> None:
    """Test that a configuration builds the path-based store that it
    names."""
    config = {"_target_": f"persista.store.{name}", "path": tmp_path / "data", **kwargs}
    assert type(resolve_object(config, cls=BaseStore)).__name__ == name


@pytest.mark.parametrize(("name", "kwargs"), DIRECTORY_STORES)
def test_resolve_object_directory_store_round_trip(
    name: str, kwargs: dict[str, Any], tmp_path: Path
) -> None:
    """Test that a path-based store built from a configuration stores
    values."""
    config = {"_target_": f"persista.store.{name}", "path": tmp_path / "data", **kwargs}
    with resolve_object(config, cls=BaseStore) as store:
        store.set("1", {"name": "Alice"})
        assert store.get("1") == {"name": "Alice"}


@pytest.mark.parametrize(("name", "kwargs"), SERVER_STORES)
def test_resolve_object_server_store_class(name: str, kwargs: dict[str, Any]) -> None:
    """Test that a configuration builds the server store that it
    names."""
    store = resolve_object({"_target_": f"persista.store.{name}", **kwargs}, cls=BaseStore)
    assert type(store).__name__ == name


@pytest.mark.parametrize(("name", "kwargs"), SERVER_STORES)
def test_resolve_object_server_store_not_opened(name: str, kwargs: dict[str, Any]) -> None:
    """Test that a server store built from a configuration is not
    open."""
    store = resolve_object({"_target_": f"persista.store.{name}", **kwargs}, cls=BaseStore)
    assert store.closed


def test_resolve_object_store_class_method(tmp_path: Path) -> None:
    """Test that ``_init_`` selects a class method of a store."""
    path = tmp_path / "data.sqlite"
    with SQLiteStore(path) as store:
        store.set("1", {"name": "Alice"})
    config = {
        "_target_": "persista.store.SQLiteStore",
        "_init_": "from_uri",
        "uri": SQLiteStore(path).to_uri(),
    }
    with resolve_object(config, cls=BaseStore) as reloaded:
        assert reloaded.get("1") == {"name": "Alice"}


def test_resolve_object_store_instance() -> None:
    """Test that a store instance is returned as it is."""
    store = InMemoryStore()
    assert resolve_object(store, cls=BaseStore) is store


def test_resolve_object_store_new_object_per_call() -> None:
    """Test that each call with a configuration builds a new store."""
    config = {"_target_": "persista.store.InMemoryStore"}
    assert resolve_object(config, cls=BaseStore) is not resolve_object(config, cls=BaseStore)


def test_resolve_object_store_missing_target() -> None:
    """Test that a configuration without ``_target_`` is rejected."""
    with pytest.raises(TypeError, match=r"missing the `_target_` key"):
        resolve_object({"database": ":memory:"}, cls=BaseStore)


def test_resolve_object_store_unknown_target() -> None:
    """Test that a target that does not exist is rejected."""
    with pytest.raises(ImportError, match=r"The target object does not exist"):
        resolve_object({"_target_": "persista.store.UnknownStore"}, cls=BaseStore)


def test_resolve_object_store_wrong_type() -> None:
    """Test that an object that is not a store is rejected."""
    with pytest.raises(TypeError, match=r"Received object is not a BaseStore instance"):
        resolve_object({"_target_": "persista.cache.Cache"}, cls=BaseStore)


###########################
#     Tests for Cache     #
###########################


def test_resolve_object_cache_default_store() -> None:
    """Test that a cache built without a store uses an in-memory
    store."""
    with resolve_object({"_target_": "persista.cache.Cache"}, cls=Cache) as cache:
        cache.set("greeting", "hello")
        assert cache.get("greeting") == "hello"


def test_resolve_object_cache_nested_store() -> None:
    """Test that a cache with a nested store writes to that store when
    the store is built first."""
    config = make_cache_config()
    store = resolve_object(config["store"], cls=BaseStore)
    with resolve_object({**config, "store": store}, cls=Cache) as cache:
        cache.set("greeting", "hello")
        assert store.count() == 1


def test_resolve_object_cache_nested_store_round_trip() -> None:
    """Test that a cache with a nested store returns the cached
    values."""
    config = make_cache_config()
    store = resolve_object(config["store"], cls=BaseStore)
    with resolve_object({**config, "store": store}, cls=Cache) as cache:
        cache.set("greeting", "hello")
        assert cache.get("greeting") == "hello"


def test_resolve_object_cache_default_ttl() -> None:
    """Test that the other keys of a cache configuration are passed to
    the constructor."""
    config = make_cache_config()
    store = resolve_object(config["store"], cls=BaseStore)
    assert resolve_object({**config, "store": store}, cls=Cache).default_ttl == 60


def test_resolve_object_cache_config_not_modified() -> None:
    """Test that building a cache does not modify its configuration."""
    config = make_cache_config()
    store = resolve_object(config["store"], cls=BaseStore)
    resolve_object({**config, "store": store}, cls=Cache)
    assert config == make_cache_config()


def test_resolve_object_cache_nested_config_is_not_built() -> None:
    """Test that a nested configuration is not built, so the cache
    cannot be opened."""
    cache = resolve_object(make_cache_config(), cls=Cache)
    with pytest.raises(AttributeError, match=r"'dict' object has no attribute 'open'"):
        cache.open()


#################################
#     Tests for RecordStore     #
#################################


def test_resolve_object_record_store_nested_store() -> None:
    """Test that a record store with a nested store works when the store
    is built first."""
    config = make_record_store_config()
    store = resolve_object(config["store"], cls=BaseStore)
    with resolve_object({**config, "store": store}, cls=RecordStore) as record_store:
        record_store.set_many([Record(id="1", metadata={"author": "Alice"})])
        assert record_store.get("1") == Record(id="1", metadata={"author": "Alice"})


def test_resolve_object_record_store_nested_config_is_not_built() -> None:
    """Test that a nested configuration is not built, so the record
    store cannot be opened."""
    record_store = resolve_object(make_record_store_config(), cls=RecordStore)
    with pytest.raises(AttributeError, match=r"'dict' object has no attribute 'open'"):
        record_store.open()
