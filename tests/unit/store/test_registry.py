from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from persista.store import (
    InMemoryStore,
    JsonFileStore,
    NullStore,
    register_scheme,
    store_from_uri,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_store_from_uri_memory_scheme() -> None:
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


async def test_store_from_uri_result_supports_async_methods() -> None:
    store = store_from_uri("memory://")
    await store.aset("1", {"a": 1})
    assert await store.aget("1") == {"a": 1}


def test_register_scheme() -> None:
    register_scheme("custom-memory", InMemoryStore)
    try:
        store = store_from_uri("custom-memory://")
        assert isinstance(store, InMemoryStore)
    finally:
        del store_from_uri.__globals__["_SCHEMES"]["custom-memory"]


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
    with pytest.raises(ValueError, match="No store registered"):
        store_from_uri("bogus://x")


def test_store_package_has_no_async_prefixed_exports() -> None:
    import persista.store as store_pkg

    assert not any(name.startswith("Async") for name in store_pkg.__all__)


def test_store_package_exports_store_from_uri_only() -> None:
    import persista.store as store_pkg

    assert "store_from_uri" in store_pkg.__all__
    assert "async_store_from_uri" not in store_pkg.__all__
    assert "register_scheme" in store_pkg.__all__
    assert "register_async_scheme" not in store_pkg.__all__
