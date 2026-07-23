from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from persista.store import (
    AsyncInMemoryStore,
    InMemoryStore,
    JsonFileStore,
    NullStore,
    async_store_from_uri,
    register_async_scheme,
    register_scheme,
    store_from_uri,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _reset_registry() -> Generator[None]:
    sync_schemes = dict(store_from_uri.__globals__["_SYNC_SCHEMES"])
    async_schemes = dict(async_store_from_uri.__globals__["_ASYNC_SCHEMES"])
    yield
    store_from_uri.__globals__["_SYNC_SCHEMES"].clear()
    store_from_uri.__globals__["_SYNC_SCHEMES"].update(sync_schemes)
    async_store_from_uri.__globals__["_ASYNC_SCHEMES"].clear()
    async_store_from_uri.__globals__["_ASYNC_SCHEMES"].update(async_schemes)


def test_store_from_uri_memory() -> None:
    store = store_from_uri("memory://")
    assert isinstance(store, InMemoryStore)


def test_store_from_uri_null() -> None:
    store = store_from_uri("null://")
    assert isinstance(store, NullStore)


def test_store_from_uri_file_json(tmp_path: Path) -> None:
    original = JsonFileStore(tmp_path / "db")
    original.set("1", {"a": 1})
    store = store_from_uri(original.to_uri())
    assert isinstance(store, JsonFileStore)
    assert store.get("1") == {"a": 1}


def test_store_from_uri_unknown_scheme_raises() -> None:
    with pytest.raises(ValueError, match="scheme"):
        store_from_uri("not-a-real-scheme://whatever")


def test_async_store_from_uri_memory() -> None:
    store = async_store_from_uri("memory://")
    assert isinstance(store, AsyncInMemoryStore)


def test_async_store_from_uri_unknown_scheme_raises() -> None:
    with pytest.raises(ValueError, match="scheme"):
        async_store_from_uri("not-a-real-scheme://whatever")


def test_register_scheme() -> None:
    register_scheme("custom-memory", InMemoryStore)
    store = store_from_uri("custom-memory://")
    assert isinstance(store, InMemoryStore)


def test_register_scheme_overwrites_existing() -> None:
    register_scheme("memory", NullStore)
    store = store_from_uri("memory://")
    assert isinstance(store, NullStore)


def test_register_async_scheme() -> None:
    register_async_scheme("custom-memory", AsyncInMemoryStore)
    store = async_store_from_uri("custom-memory://")
    assert isinstance(store, AsyncInMemoryStore)
