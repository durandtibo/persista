import pytest

from persista.store import InMemoryStore, register_scheme, store_from_uri


def test_store_from_uri_memory_scheme() -> None:
    store = store_from_uri("memory://")
    assert isinstance(store, InMemoryStore)


@pytest.mark.asyncio
async def test_store_from_uri_result_supports_async_methods() -> None:
    store = store_from_uri("memory://")
    await store.aset("1", {"a": 1})
    assert await store.aget("1") == {"a": 1}


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
