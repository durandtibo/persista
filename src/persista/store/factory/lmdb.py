r"""Provide factories for LMDB-backed persista BaseStore models."""

from __future__ import annotations

__all__ = ["LmdbStoreFactory", "PickleLmdbStoreFactory"]

from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin

from persista.store.factory.base import BaseStoreFactory
from persista.store.lmdb import _DEFAULT_MAP_SIZE, LmdbStore, PickleLmdbStore

if TYPE_CHECKING:
    from os import PathLike


class LmdbStoreFactory(BaseStoreFactory, MultilineDisplayMixin):
    """A factory that creates a new :class:`~persista.store.LmdbStore`
    instance on each call to :meth:`make_store`.

    Args:
        path: The directory where the LMDB environment is stored.
        map_size: The maximum size in bytes of the memory map. Passed
            to ``lmdb.open``.
        **kwargs: Additional keyword arguments to pass to
            ``lmdb.open``.

    Example:
        ```pycon
        >>> import tempfile
        >>> from persista.store.factory import LmdbStoreFactory
        >>> with tempfile.TemporaryDirectory() as tmpdir:
        ...     factory = LmdbStoreFactory(tmpdir)
        ...     store = factory.make_store()
        ...

        ```
    """

    def __init__(
        self, path: str | PathLike[str], map_size: int = _DEFAULT_MAP_SIZE, **kwargs: Any
    ) -> None:
        self._path = path
        self._map_size = map_size
        self._kwargs = kwargs

    def make_store(self) -> LmdbStore:
        return LmdbStore(self._path, map_size=self._map_size, **self._kwargs)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"path": self._path, "map_size": self._map_size} | self._kwargs


class PickleLmdbStoreFactory(BaseStoreFactory, MultilineDisplayMixin):
    """A factory that creates a new
    :class:`~persista.store.PickleLmdbStore` instance on each call to
    :meth:`make_store`.

    Args:
        path: The directory where the LMDB environment is stored.
        map_size: The maximum size in bytes of the memory map. Passed
            to ``lmdb.open``.
        **kwargs: Additional keyword arguments to pass to
            ``lmdb.open``.

    Example:
        ```pycon
        >>> import tempfile
        >>> from persista.store.factory import PickleLmdbStoreFactory
        >>> with tempfile.TemporaryDirectory() as tmpdir:
        ...     factory = PickleLmdbStoreFactory(tmpdir)
        ...     store = factory.make_store()
        ...

        ```
    """

    def __init__(
        self, path: str | PathLike[str], map_size: int = _DEFAULT_MAP_SIZE, **kwargs: Any
    ) -> None:
        self._path = path
        self._map_size = map_size
        self._kwargs = kwargs

    def make_store(self) -> PickleLmdbStore:
        return PickleLmdbStore(self._path, map_size=self._map_size, **self._kwargs)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"path": self._path, "map_size": self._map_size} | self._kwargs
