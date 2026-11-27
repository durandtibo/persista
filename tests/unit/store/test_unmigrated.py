from __future__ import annotations

import pytest

from persista.store import (
    BasePostgresStore,
    BaseRedisStore,
    BaseStore,
)
from persista.store.unmigrated import UnmigratedStore

PRIMITIVES = [
    "_open",
    "_close",
    "_get_many",
    "_put_many",
    "_update",
    "_delete_many",
    "_clear",
    "_count",
    "_iter_batches",
]


class UnmigratedTestStore(UnmigratedStore):
    r"""Implement the URI methods only."""

    def to_uri(self) -> str:
        return "test://"

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> UnmigratedTestStore:
        del uri, read_only
        return cls()


#####################################
#     Tests for UnmigratedStore     #
#####################################


@pytest.mark.parametrize("primitive", PRIMITIVES)
def test_unmigrated_store_primitive_raises(primitive: str) -> None:
    with pytest.raises(NotImplementedError, match=r"UnmigratedTestStore does not implement"):
        getattr(UnmigratedTestStore(), primitive)()


def test_unmigrated_store__unmigrated_primitive() -> None:
    with pytest.raises(NotImplementedError, match=r"does not implement the primitives"):
        UnmigratedTestStore()._unmigrated_primitive(["1"], key="1")


def test_unmigrated_store_has_a_placeholder_for_each_abstract_primitive() -> None:
    assert BaseStore.__abstractmethods__ - UnmigratedStore.__abstractmethods__ == set(PRIMITIVES)


@pytest.mark.parametrize(
    "cls",
    [BasePostgresStore, BaseRedisStore],
)
def test_unmigrated_store_subclasses_have_every_primitive(cls: type[BaseStore]) -> None:
    assert not cls.__abstractmethods__ & set(PRIMITIVES)
