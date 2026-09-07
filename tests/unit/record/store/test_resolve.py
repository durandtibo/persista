from __future__ import annotations

import pytest

from persista.record.store import InMemoryRecordStore
from persista.record.store.resolve import resolve_record_store

#############################################
#     Tests for resolve_record_store         #
#############################################


def test_resolve_record_store_passthrough_returns_same_instance() -> None:
    store = InMemoryRecordStore()
    assert resolve_record_store(store) is store


def test_resolve_record_store_from_dict_config() -> None:
    store = resolve_record_store({"_target_": "persista.record.store.InMemoryRecordStore"})
    assert isinstance(store, InMemoryRecordStore)


def test_resolve_record_store_from_dict_config_creates_new_instance_each_call() -> None:
    config = {"_target_": "persista.record.store.InMemoryRecordStore"}
    assert resolve_record_store(config) is not resolve_record_store(config)


def test_resolve_record_store_wrong_type_raises_type_error() -> None:
    with pytest.raises(TypeError):
        resolve_record_store({"_target_": "builtins.dict"})
