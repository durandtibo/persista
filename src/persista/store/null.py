r"""Provide a no-op implementation of ``BaseStore``."""

from __future__ import annotations

__all__ = ["NullStore"]

import logging
from typing import TYPE_CHECKING, Any

from coola.display import InlineDisplayMixin

from persista.store.base import BaseStore

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator, Mapping

    from persista.store.types import OnConflict


logger: logging.Logger = logging.getLogger(__name__)


class NullStore(BaseStore, InlineDisplayMixin):
    """A :class:`~persista.store.base.BaseStore` implementation that
    forgets everything written to it.

    Every :meth:`set` / :meth:`set_many` call is silently discarded,
    so :meth:`get` / :meth:`get_many` always report a miss and the
    store always reports as empty. This is primarily useful for
    plugging into :class:`~persista.cache.cache.Cache` to disable
    caching without changing any calling code: every lookup misses,
    so ``get_or_compute`` / ``memoize`` always recompute the value.

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

    @property
    def closed(self) -> bool:
        return self._closed

    def get(self, key: str) -> dict[str, Any] | None:  # noqa: ARG002
        return None

    def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        return [None] * len(keys)

    def set(
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

    def filter(self, **field_filters: Any) -> list[dict[str, Any]]:  # noqa: ARG002
        return []

    def delete(self, key: str) -> None:  # noqa: ARG002
        return

    def delete_many(self, keys: list[str]) -> None:  # noqa: ARG002
        return

    def clear(self) -> None:
        return

    def contains(self, key: str) -> bool:  # noqa: ARG002
        return False

    def contains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        return [], list(keys)

    def keys(self) -> Iterator[str]:
        return iter(())

    def iter_batches(
        self,
        batch_size: int = 32,  # noqa: ARG002
    ) -> Generator[dict[str, dict[str, Any]], None, None]:
        yield from ()

    def count(self) -> int:
        return 0

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"count": 0}
