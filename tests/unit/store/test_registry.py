from __future__ import annotations

import traceback
from typing import TYPE_CHECKING

import pytest

import persista.store as store_pkg
from persista.store import (
    DuckDBStore,
    FileStore,
    InMemoryStore,
    JsonCodec,
    LmdbStore,
    NullStore,
    PickleCodec,
    RedisStore,
    SQLiteStore,
    register_scheme,
    store_from_uri,
)
from persista.store.registry import _SCHEMES
from persista.testing.fixtures import duckdb_available, lmdb_available, redis_available

if TYPE_CHECKING:
    from pathlib import Path

    from persista.store import BaseStore, Codec


def test_store_from_uri_memory_scheme() -> None:
    store = store_from_uri("memory://")
    assert isinstance(store, InMemoryStore)


def test_store_from_uri_null() -> None:
    store = store_from_uri("null://")
    assert isinstance(store, NullStore)


@pytest.mark.parametrize(
    ("cls", "codec"),
    [
        pytest.param(FileStore, JsonCodec(), id="file_json"),
        pytest.param(FileStore, PickleCodec(), id="file_pickle"),
        pytest.param(LmdbStore, JsonCodec(), id="lmdb", marks=lmdb_available),
        pytest.param(LmdbStore, PickleCodec(), id="lmdb_pickle", marks=lmdb_available),
    ],
)
def test_store_from_uri_local_store_keeps_codec(
    tmp_path: Path, cls: type[BaseStore], codec: Codec
) -> None:
    with cls(tmp_path / "data", codec=codec) as original:
        original.set("1", {"a": 1})
        uri = original.to_uri()
    with store_from_uri(uri) as store:
        assert (type(store), type(store._codec), store.get("1")) == (cls, type(codec), {"a": 1})


@pytest.mark.parametrize(
    ("cls", "codec"),
    [
        pytest.param(SQLiteStore, JsonCodec(), id="sqlite"),
        pytest.param(SQLiteStore, PickleCodec(), id="sqlite_pickle"),
        pytest.param(DuckDBStore, JsonCodec(), id="duckdb", marks=duckdb_available),
        pytest.param(DuckDBStore, PickleCodec(), id="duckdb_pickle", marks=duckdb_available),
    ],
)
def test_store_from_uri_sql_store_keeps_codec(
    tmp_path: Path, cls: type[BaseStore], codec: Codec
) -> None:
    with cls(tmp_path / "data.db", codec=codec) as original:
        original.set("1", {"a": 1})
        uri = original.to_uri()
    with store_from_uri(uri) as store:
        assert (type(store), type(store._codec), store.get("1")) == (cls, type(codec), {"a": 1})


async def test_store_from_uri_result_supports_async_methods() -> None:
    store = store_from_uri("memory://")
    await store.aset("1", {"a": 1})
    assert await store.aget("1") == {"a": 1}


def test_register_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    schemes = store_from_uri.__globals__["_SCHEMES"]
    monkeypatch.setitem(schemes, "custom-memory", InMemoryStore)
    store = store_from_uri("custom-memory://")
    assert isinstance(store, InMemoryStore)


def test_register_scheme_overrides_existing() -> None:
    class _CustomStore(InMemoryStore):
        pass

    register_scheme("memory", _CustomStore)
    try:
        store = store_from_uri("memory://")
        assert isinstance(store, _CustomStore)
    finally:
        register_scheme("memory", InMemoryStore)


def test_store_from_uri_unknown_scheme_raises() -> None:
    with pytest.raises(ValueError, match=r"No store registered for scheme 'bogus'"):
        store_from_uri("bogus://x")


def test_store_from_uri_unknown_scheme_hides_the_password() -> None:
    with pytest.raises(ValueError, match=r"No store registered") as info:
        store_from_uri("postgresx://user:s3cret@localhost/db")
    assert "s3cret" not in str(info.value)


@pytest.mark.parametrize("scheme", ["sqlite+typed", "duckdb+typed"])
def test_store_from_uri_typed_scheme_raises(scheme: str, tmp_path: Path) -> None:
    """A typed store could not be rebuilt from its URI, which has no
    schema: its scheme is rejected instead of returning a store that
    cannot read the data."""
    with pytest.raises(ValueError, match=r"No store registered"):
        store_from_uri(f"{scheme}:///{tmp_path.as_posix()}/data.db")


@pytest.mark.parametrize(
    ("kwargs", "expected"), [({"read_only": True}, True), ({}, False)], ids=["true", "default"]
)
def test_store_from_uri_forwards_read_only(
    monkeypatch: pytest.MonkeyPatch, kwargs: dict[str, bool], expected: bool
) -> None:
    received: dict[str, bool] = {}

    class _SpyStore(InMemoryStore):
        @classmethod
        def from_uri(cls, uri: str, *, read_only: bool = False) -> _SpyStore:  # noqa: ARG003
            received["read_only"] = read_only
            return cls()

    schemes = store_from_uri.__globals__["_SCHEMES"]
    monkeypatch.setitem(schemes, "spy", _SpyStore)
    store_from_uri("spy://", **kwargs)
    assert received["read_only"] is expected


def test_store_package_has_no_async_prefixed_exports() -> None:
    assert not any(name.startswith("Async") for name in store_pkg.__all__)


def test_store_package_exports_store_from_uri_only() -> None:
    assert "store_from_uri" in store_pkg.__all__
    assert "async_store_from_uri" not in store_pkg.__all__
    assert "register_scheme" in store_pkg.__all__
    assert "register_async_scheme" not in store_pkg.__all__


@pytest.mark.parametrize("scheme", ["MyScheme", "MYSCHEME", "myscheme"])
def test_register_scheme_ignores_the_case(monkeypatch: pytest.MonkeyPatch, scheme: str) -> None:
    monkeypatch.delitem(_SCHEMES, "myscheme", raising=False)
    monkeypatch.setitem(_SCHEMES, "myscheme", NullStore)
    register_scheme(scheme, InMemoryStore)
    with store_from_uri("MyScheme://") as store:
        assert isinstance(store, InMemoryStore)


@redis_available
@pytest.mark.parametrize(
    "uri", ["redis://localhost:6379/0", "rediss://localhost:6379/0", "unix:///tmp/redis.sock"]
)
def test_store_from_uri_redis_schemes(monkeypatch: pytest.MonkeyPatch, uri: str) -> None:
    monkeypatch.setattr(RedisStore, "open", lambda _store: None)
    assert store_from_uri(uri).to_uri() == uri


@pytest.mark.parametrize(
    "uri",
    [
        "redis://user:s3cret@[bad",
        f"postgresql://user:s3cret@ho{chr(0x2100)}st/db",
    ],
)
def test_store_from_uri_invalid_uri_hides_the_password(uri: str) -> None:
    with pytest.raises(ValueError, match=r"Invalid URI: it cannot be parsed") as info:
        store_from_uri(uri)
    assert "s3cret" not in "".join(traceback.format_exception(info.value))


def test_store_from_uri_builds_the_default_store() -> None:
    uri = InMemoryStore(codec=PickleCodec()).to_uri()
    with store_from_uri(uri) as store:
        assert isinstance(store._codec, JsonCodec)


#########################################
#     Tests for the from_uri kwargs     #
#########################################


def test_in_memory_from_uri_passes_kwargs() -> None:
    codec = PickleCodec()
    assert InMemoryStore.from_uri("memory://", codec=codec)._codec is codec


def test_null_from_uri_rejects_kwargs() -> None:
    with pytest.raises(TypeError, match=r"unexpected keyword argument 'codec'"):
        NullStore.from_uri("null://", codec=PickleCodec())
