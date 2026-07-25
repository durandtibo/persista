r"""Provide factories for file-based persista BaseStore models."""

from __future__ import annotations

__all__ = ["JsonFileStoreFactory", "PickleFileStoreFactory"]

from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin

from persista.store.factory.base import BaseStoreFactory
from persista.store.file import JsonFileStore, PickleFileStore

if TYPE_CHECKING:
    from os import PathLike


class JsonFileStoreFactory(BaseStoreFactory, MultilineDisplayMixin):
    """A factory that creates a new
    :class:`~persista.store.JsonFileStore` instance on each call to
    :meth:`make_store`.

    Args:
        path: The directory where value files are stored.
        **kwargs: Additional keyword arguments to pass to
            ``iden.io.save_json``.

    Example:
        ```pycon
        >>> from persista.store.factory import JsonFileStoreFactory
        >>> factory = JsonFileStoreFactory("/tmp/file_store")  # doctest: +SKIP
        >>> store = factory.make_store()  # doctest: +SKIP

        ```
    """

    def __init__(self, path: str | PathLike[str], **kwargs: Any) -> None:
        self._path = path
        self._kwargs = kwargs

    def make_store(self) -> JsonFileStore:
        return JsonFileStore(self._path, **self._kwargs)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"path": self._path} | self._kwargs


class PickleFileStoreFactory(BaseStoreFactory, MultilineDisplayMixin):
    """A factory that creates a new
    :class:`~persista.store.PickleFileStore` instance on each call to
    :meth:`make_store`.

    Args:
        path: The directory where value files are stored.
        **kwargs: Additional keyword arguments to pass to
            ``iden.io.save_pickle``.

    Example:
        ```pycon
        >>> from persista.store.factory import PickleFileStoreFactory
        >>> factory = PickleFileStoreFactory("/tmp/file_store")  # doctest: +SKIP
        >>> store = factory.make_store()  # doctest: +SKIP

        ```
    """

    def __init__(self, path: str | PathLike[str], **kwargs: Any) -> None:
        self._path = path
        self._kwargs = kwargs

    def make_store(self) -> PickleFileStore:
        return PickleFileStore(self._path, **self._kwargs)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"path": self._path} | self._kwargs
