from __future__ import annotations

import pytest

from persista.store import (
    AsyncInMemoryStore,
    AsyncNullStore,
    InMemoryStore,
    JsonFileStore,
    NullStore,
    async_store_from_uri,
    store_from_uri,
)


def test_store_from_uri_memory() -> None:
    store = store_from_uri("memory://")
    assert isinstance(store, InMemoryStore)


def test_store_from_uri_null() -> None:
    store = store_from_uri("null://")
    assert isinstance(store, NullStore)


def test_store_from_uri_file_json(tmp_path) -> None:
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


def test_async_store_from_uri_null() -> None:
    store = async_store_from_uri("null://")
    assert isinstance(store, AsyncNullStore)


def test_async_store_from_uri_unknown_scheme_raises() -> None:
    with pytest.raises(ValueError, match="scheme"):
        async_store_from_uri("not-a-real-scheme://whatever")
