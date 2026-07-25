from __future__ import annotations

import pytest

from persista.store import BaseStore, InMemoryStore, resolve_store

IN_MEMORY_STORE_TARGET = "persista.store.InMemoryStore"


def _make_store() -> InMemoryStore:
    """Return an InMemoryStore instance for testing."""
    return InMemoryStore()


###################################
#     Tests for resolve_store     #
###################################


# --- Pass-through ---


def test_resolve_store_returns_base_store_instance() -> None:
    assert isinstance(resolve_store(_make_store()), BaseStore)


def test_resolve_store_passthrough_returns_same_instance() -> None:
    store = _make_store()
    assert resolve_store(store) is store


# --- From dict ---


def test_resolve_store_from_dict_returns_base_store() -> None:
    result = resolve_store({"_target_": IN_MEMORY_STORE_TARGET})
    assert isinstance(result, BaseStore)


def test_resolve_store_from_dict_returns_correct_type() -> None:
    result = resolve_store({"_target_": IN_MEMORY_STORE_TARGET})
    assert isinstance(result, InMemoryStore)


# --- Invalid input ---


def test_resolve_store_invalid_type_raises_type_error() -> None:
    with pytest.raises(TypeError, match=r"Received object is not a BaseStore instance"):
        resolve_store("not-a-document-store")
