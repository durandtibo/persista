r"""Provide a no-op implementation of ``AsyncBaseStore``."""

from __future__ import annotations

__all__ = ["AsyncNullStore"]

import logging
from typing import TYPE_CHECKING, Any

from coola.display import InlineDisplayMixin

from persista.store.base import AsyncBaseStore
from persista.utils.asyncio import EmptyAsyncIterator

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from persista.store.types import OnConflict


logger: logging.Logger = logging.getLogger(__name__)


class AsyncNullStore(AsyncBaseStore, InlineDisplayMixin):
    """An :class:`~persista.store.base.AsyncBaseStore` implementation
    that forgets everything written to it.

    Every :meth:`set` / :meth:`set_many` call is silently discarded,
    so :meth:`get` / :meth:`get_many` always report a miss and the
    store always reports as empty. This is primarily useful for
    plugging into :class:`~persista.cache.async_cache.AsyncCache` to
    disable caching without changing any calling code: every lookup
    misses, so ``get_or_compute`` / ``memoize`` always recompute the
    value.

    Example:
        ```pycon
        >>> import asyncio
        >>> from persista.store import AsyncNullStore
        >>> from persista.cache import AsyncCache
        >>> async def main():
        ...     cache = AsyncCache(store=AsyncNullStore())
        ...     await cache.set("greeting", "hello")
        ...     print(await cache.get("greeting"))
        ...
        >>> asyncio.run(main())
        None

        ```
    """

    def __init__(self) -> None:
        self._closed = False

    async def close(self) -> None:
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    async def get(self, key: str) -> dict[str, Any] | None:  # noqa: ARG002
        return None

    async def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        return [None] * len(keys)

    async def set(
        self,
        key: str,
        value: dict[str, Any],  # noqa: ARG002
        on_conflict: OnConflict = "overwrite",  # noqa: ARG002
    ) -> None:
        logger.debug("Discarding key-value pair: %s", key)

    async def set_many(
        self,
        items: Mapping[str, dict[str, Any]],
        on_conflict: OnConflict = "overwrite",  # noqa: ARG002
    ) -> None:
        logger.debug("Discarding %d key-value pair(s)", len(items))

    async def filter(self, **field_filters: Any) -> list[dict[str, Any]]:  # noqa: ARG002
        return []

    async def delete(self, key: str) -> None:  # noqa: ARG002
        return

    async def delete_many(self, keys: list[str]) -> None:  # noqa: ARG002
        return

    async def clear(self) -> None:
        return

    async def contains(self, key: str) -> bool:  # noqa: ARG002
        return False

    async def contains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        return [], list(keys)

    def keys(self) -> AsyncIterator[str]:
        return EmptyAsyncIterator()

    def iter_batches(
        self,
        batch_size: int = 32,  # noqa: ARG002
    ) -> AsyncIterator[dict[str, dict[str, Any]]]:
        return EmptyAsyncIterator()

    async def count(self) -> int:
        return 0

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"count": 0}
