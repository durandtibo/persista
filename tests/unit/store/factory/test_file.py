from __future__ import annotations

from typing import TYPE_CHECKING

from coola.equality import objects_are_equal

from persista.store import BaseStore, JsonFileStore, PickleFileStore
from persista.store.factory import (
    BaseStoreFactory,
    JsonFileStoreFactory,
    PickleFileStoreFactory,
)

if TYPE_CHECKING:
    from pathlib import Path

#########################################
#     Tests for JsonFileStoreFactory     #
#########################################


# --- Inheritance ---


def test_json_file_store_factory_is_base_store_factory(tmp_path: Path) -> None:
    assert isinstance(JsonFileStoreFactory(tmp_path), BaseStoreFactory)


# --- make_store ---


def test_json_file_store_factory_make_store_returns_base_store(tmp_path: Path) -> None:
    factory = JsonFileStoreFactory(tmp_path)
    assert isinstance(factory.make_store(), BaseStore)


def test_json_file_store_factory_make_store_returns_json_file_store(tmp_path: Path) -> None:
    factory = JsonFileStoreFactory(tmp_path)
    assert isinstance(factory.make_store(), JsonFileStore)


def test_json_file_store_factory_make_store_returns_new_instance_each_call(
    tmp_path: Path,
) -> None:
    factory = JsonFileStoreFactory(tmp_path)
    assert factory.make_store() is not factory.make_store()


# --- _get_repr_kwargs ---


def test_json_file_store_factory_get_repr_kwargs(tmp_path: Path) -> None:
    factory = JsonFileStoreFactory(tmp_path)
    assert objects_are_equal(factory._get_repr_kwargs(), {"path": tmp_path})


# --- __repr__ and __str__ ---


def test_json_file_store_factory_repr_starts_with_class_name(tmp_path: Path) -> None:
    factory = JsonFileStoreFactory(tmp_path)
    assert repr(factory).startswith("JsonFileStoreFactory(")


def test_json_file_store_factory_str_starts_with_class_name(tmp_path: Path) -> None:
    factory = JsonFileStoreFactory(tmp_path)
    assert str(factory).startswith("JsonFileStoreFactory(")


def test_json_file_store_factory_repr_contains_path(tmp_path: Path) -> None:
    factory = JsonFileStoreFactory(tmp_path)
    assert "path" in repr(factory)


def test_json_file_store_factory_str_contains_path(tmp_path: Path) -> None:
    factory = JsonFileStoreFactory(tmp_path)
    assert "path" in str(factory)


###########################################
#     Tests for PickleFileStoreFactory     #
###########################################


# --- Inheritance ---


def test_pickle_file_store_factory_is_base_store_factory(tmp_path: Path) -> None:
    assert isinstance(PickleFileStoreFactory(tmp_path), BaseStoreFactory)


# --- make_store ---


def test_pickle_file_store_factory_make_store_returns_base_store(tmp_path: Path) -> None:
    factory = PickleFileStoreFactory(tmp_path)
    assert isinstance(factory.make_store(), BaseStore)


def test_pickle_file_store_factory_make_store_returns_pickle_file_store(tmp_path: Path) -> None:
    factory = PickleFileStoreFactory(tmp_path)
    assert isinstance(factory.make_store(), PickleFileStore)


def test_pickle_file_store_factory_make_store_returns_new_instance_each_call(
    tmp_path: Path,
) -> None:
    factory = PickleFileStoreFactory(tmp_path)
    assert factory.make_store() is not factory.make_store()


# --- _get_repr_kwargs ---


def test_pickle_file_store_factory_get_repr_kwargs(tmp_path: Path) -> None:
    factory = PickleFileStoreFactory(tmp_path)
    assert objects_are_equal(factory._get_repr_kwargs(), {"path": tmp_path})


# --- __repr__ and __str__ ---


def test_pickle_file_store_factory_repr_starts_with_class_name(tmp_path: Path) -> None:
    factory = PickleFileStoreFactory(tmp_path)
    assert repr(factory).startswith("PickleFileStoreFactory(")


def test_pickle_file_store_factory_str_starts_with_class_name(tmp_path: Path) -> None:
    factory = PickleFileStoreFactory(tmp_path)
    assert str(factory).startswith("PickleFileStoreFactory(")


def test_pickle_file_store_factory_repr_contains_path(tmp_path: Path) -> None:
    factory = PickleFileStoreFactory(tmp_path)
    assert "path" in repr(factory)


def test_pickle_file_store_factory_str_contains_path(tmp_path: Path) -> None:
    factory = PickleFileStoreFactory(tmp_path)
    assert "path" in str(factory)
