r"""Provide a no-op implementation of ``BaseStore``."""

from __future__ import annotations

__all__ = ["NullStore"]

import logging
from typing import TYPE_CHECKING, Any

from coola.display import InlineDisplayMixin

from persista.store.base import BaseStore

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Self

    from persista.store.types import Payload, Plan


logger: logging.Logger = logging.getLogger(__name__)


class NullStore(BaseStore, InlineDisplayMixin):
    """A :class:`~persista.store.BaseStore` implementation that
    forgets everything written to it.

    Every value written is discarded, so :meth:`get`/:meth:`aget` always
    report a miss and the store always reports as empty. Because
    nothing is ever stored, ``on_conflict="raise"`` can never
    actually raise ``KeyError`` here, unlike other
    :class:`~persista.store.BaseStore` implementations. The arguments are
    checked like in the other stores: in particular, a value must be
    representable in JSON.

    This is primarily useful for plugging into
    :class:`~persista.cache.cache.Cache` to disable caching without
    changing any calling code: every lookup misses, so
    ``get_or_compute``/``memoize`` always recompute the value. The cached
    values must then be representable in JSON.

    Example:
        ```pycon
        >>> from persista.store import NullStore
        >>> from persista.cache import Cache
        >>> with Cache(store=NullStore()) as cache:
        ...     cache.set("greeting", "hello")
        ...     cache.get("greeting") is None
        ...
        True

        ```
    """

    # There is no data to protect.
    _thread_safe = True

    def __init__(self) -> None:
        super().__init__()

    def to_uri(self) -> str:
        return "null://"

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False, **kwargs: Any) -> Self:
        del uri, read_only
        return cls(**kwargs)

    def _open(self) -> None:
        pass

    def _close(self) -> None:
        pass

    def _get_many(self, keys: list[str]) -> dict[str, Payload]:
        del keys
        return {}

    def _put_many(self, items: dict[str, Payload]) -> None:
        logger.debug("Discarding %d key-value pair(s)", len(items))

    def _update(self, keys: list[str], plan: Plan) -> None:
        del keys
        self._put_many(plan({}))

    def _delete_many(self, keys: list[str]) -> None:
        pass

    def _clear(self) -> None:
        pass

    def _count(self) -> int:
        return 0

    def _iter_batches(self, batch_size: int) -> Iterator[dict[str, Payload]]:
        del batch_size
        yield from ()

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"closed": self._closed}
