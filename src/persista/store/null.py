r"""Provide a no-op implementation of ``BaseStore``."""

from __future__ import annotations

__all__ = ["NullStore"]

import logging
from typing import TYPE_CHECKING, Any

from coola.display import InlineDisplayMixin

from persista.store.base import BaseStore
from persista.store.validation import validate_batch_size
from persista.utils.asyncio import EmptyAsyncIterator

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator, Mapping

    from typing_extensions import Self

    from persista.store.types import OnConflict


logger: logging.Logger = logging.getLogger(__name__)


class NullStore(BaseStore, InlineDisplayMixin):
    """A :class:`~persista.store.base.BaseStore` implementation that
    forgets everything written to it.

    Every :meth:`set`/:meth:`aset`/:meth:`set_many`/:meth:`aset_many`
    call is silently discarded, so :meth:`get`/:meth:`aget` always
    report a miss and the store always reports as empty. This is
    primarily useful for plugging into
    :class:`~persista.cache.cache.Cache` to disable caching without
    changing any calling code: every lookup misses, so
    ``get_or_compute``/``memoize`` always recompute the value.

    There is no I/O to offload here, so the async methods run inline
    rather than through a thread pool.

    Example:
        ```pycon
        >>> from persista.store import NullStore
        >>> from persista.cache import Cache
        >>> cache = Cache(store=NullStore())
        >>> cache.set("greeting", "hello")
        >>> cache.get("greeting") is None
        True

        ```
    """

    def __init__(self) -> None:
        self._closed = False

    def close(self) -> None:
        self._closed = True

    async def aclose(self) -> None:
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    def __enter__(self) -> Self:
        self._closed = False
        return self

    async def __aenter__(self) -> Self:
        self._closed = False
        return self

    def get(self, key: str) -> dict[str, Any] | None:  # noqa: ARG002
        return None

    async def aget(self, key: str) -> dict[str, Any] | None:  # noqa: ARG002
        return None

    def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        return [None] * len(keys)

    async def aget_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        return [None] * len(keys)

    def set(
        self,
        key: str,
        value: dict[str, Any],  # noqa: ARG002
        on_conflict: OnConflict = "overwrite",  # noqa: ARG002
    ) -> None:
        logger.debug("Discarding key-value pair: %s", key)

    async def aset(
        self,
        key: str,
        value: dict[str, Any],  # noqa: ARG002
        on_conflict: OnConflict = "overwrite",  # noqa: ARG002
    ) -> None:
        logger.debug("Discarding key-value pair: %s", key)

    def set_many(
        self,
        items: Mapping[str, dict[str, Any]],
        on_conflict: OnConflict = "overwrite",  # noqa: ARG002
    ) -> None:
        logger.debug("Discarding %d key-value pair(s)", len(items))

    async def aset_many(
        self,
        items: Mapping[str, dict[str, Any]],
        on_conflict: OnConflict = "overwrite",  # noqa: ARG002
    ) -> None:
        logger.debug("Discarding %d key-value pair(s)", len(items))

    def filter(self, **field_filters: Any) -> list[dict[str, Any]]:  # noqa: ARG002
        return []

    async def afilter(self, **field_filters: Any) -> list[dict[str, Any]]:  # noqa: ARG002
        return []

    def delete(self, key: str) -> None:  # noqa: ARG002
        return

    async def adelete(self, key: str) -> None:  # noqa: ARG002
        return

    def delete_many(self, keys: list[str]) -> None:  # noqa: ARG002
        return

    async def adelete_many(self, keys: list[str]) -> None:  # noqa: ARG002
        return

    def clear(self) -> None:
        return

    async def aclear(self) -> None:
        return

    def contains(self, key: str) -> bool:  # noqa: ARG002
        return False

    async def acontains(self, key: str) -> bool:  # noqa: ARG002
        return False

    def contains_many(self, keys: list[str]) -> list[bool]:
        return [False] * len(keys)

    async def acontains_many(self, keys: list[str]) -> list[bool]:
        return [False] * len(keys)

    def keys(self) -> Iterator[str]:
        return iter(())

    def akeys(self) -> AsyncIterator[str]:
        return EmptyAsyncIterator()

    def iter_batches(
        self,
        batch_size: int = 32,
    ) -> Iterator[dict[str, dict[str, Any]]]:
        validate_batch_size(batch_size)
        yield from ()

    def aiter_batches(
        self,
        batch_size: int = 32,
    ) -> AsyncIterator[dict[str, dict[str, Any]]]:
        validate_batch_size(batch_size)
        return EmptyAsyncIterator()

    def count(self) -> int:
        return 0

    async def acount(self) -> int:
        return 0

    def to_uri(self) -> str:
        return "null://"

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> Self:  # noqa: ARG003
        return cls()

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"count": 0}
