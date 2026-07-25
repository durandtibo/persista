from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from coola.equality import objects_are_equal

pytest.importorskip("lmdb")

from persista.store import BaseStore, LmdbStore, PickleLmdbStore
from persista.store.factory import (
    BaseStoreFactory,
    LmdbStoreFactory,
    PickleLmdbStoreFactory,
)

if TYPE_CHECKING:
    from pathlib import Path

_DEFAULT_MAP_SIZE = 1024**3

######################################
#     Tests for LmdbStoreFactory     #
######################################


# --- Inheritance ---


def test_lmdb_store_factory_is_base_store_factory(tmp_path: Path) -> None:
    assert isinstance(LmdbStoreFactory(tmp_path), BaseStoreFactory)


# --- make_store ---


def test_lmdb_store_factory_make_store_returns_base_store(tmp_path: Path) -> None:
    factory = LmdbStoreFactory(tmp_path)
    assert isinstance(factory.make_store(), BaseStore)


def test_lmdb_store_factory_make_store_returns_lmdb_store(tmp_path: Path) -> None:
    factory = LmdbStoreFactory(tmp_path)
    assert isinstance(factory.make_store(), LmdbStore)


# --- _get_repr_kwargs ---


def test_lmdb_store_factory_get_repr_kwargs(tmp_path: Path) -> None:
    factory = LmdbStoreFactory(tmp_path)
    assert objects_are_equal(
        factory._get_repr_kwargs(), {"path": tmp_path, "map_size": _DEFAULT_MAP_SIZE}
    )


# --- __repr__ and __str__ ---


def test_lmdb_store_factory_repr_starts_with_class_name(tmp_path: Path) -> None:
    factory = LmdbStoreFactory(tmp_path)
    assert repr(factory).startswith("LmdbStoreFactory(")


def test_lmdb_store_factory_str_starts_with_class_name(tmp_path: Path) -> None:
    factory = LmdbStoreFactory(tmp_path)
    assert str(factory).startswith("LmdbStoreFactory(")


def test_lmdb_store_factory_repr_contains_map_size(tmp_path: Path) -> None:
    factory = LmdbStoreFactory(tmp_path)
    assert "map_size" in repr(factory)


def test_lmdb_store_factory_str_contains_map_size(tmp_path: Path) -> None:
    factory = LmdbStoreFactory(tmp_path)
    assert "map_size" in str(factory)


############################################
#     Tests for PickleLmdbStoreFactory     #
############################################


# --- Inheritance ---


def test_pickle_lmdb_store_factory_is_base_store_factory(tmp_path: Path) -> None:
    assert isinstance(PickleLmdbStoreFactory(tmp_path), BaseStoreFactory)


# --- make_store ---


def test_pickle_lmdb_store_factory_make_store_returns_base_store(tmp_path: Path) -> None:
    factory = PickleLmdbStoreFactory(tmp_path)
    assert isinstance(factory.make_store(), BaseStore)


def test_pickle_lmdb_store_factory_make_store_returns_pickle_lmdb_store(tmp_path: Path) -> None:
    factory = PickleLmdbStoreFactory(tmp_path)
    assert isinstance(factory.make_store(), PickleLmdbStore)


# --- _get_repr_kwargs ---


def test_pickle_lmdb_store_factory_get_repr_kwargs(tmp_path: Path) -> None:
    factory = PickleLmdbStoreFactory(tmp_path)
    assert objects_are_equal(
        factory._get_repr_kwargs(), {"path": tmp_path, "map_size": _DEFAULT_MAP_SIZE}
    )


# --- __repr__ and __str__ ---


def test_pickle_lmdb_store_factory_repr_starts_with_class_name(tmp_path: Path) -> None:
    factory = PickleLmdbStoreFactory(tmp_path)
    assert repr(factory).startswith("PickleLmdbStoreFactory(")


def test_pickle_lmdb_store_factory_str_starts_with_class_name(tmp_path: Path) -> None:
    factory = PickleLmdbStoreFactory(tmp_path)
    assert str(factory).startswith("PickleLmdbStoreFactory(")
