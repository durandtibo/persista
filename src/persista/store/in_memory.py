r"""Provide an in-memory implementation of ``BaseStore``."""

from __future__ import annotations

__all__ = ["InMemoryStore"]

from typing import TYPE_CHECKING, Any

from coola.display import InlineDisplayMixin
from coola.utils.batching import batchify

from persista.store.base import BaseStore

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Self

    from persista.store.codec import Codec
    from persista.store.types import Payload, Plan


class InMemoryStore(BaseStore, InlineDisplayMixin):
    """A :class:`~persista.store.BaseStore` implementation backed
    by a plain ``dict``.

    The payloads are held in process memory -- nothing is persisted to
    disk, and closing the store discards its content. This is primarily
    useful for testing, small-scale exploration, or pipelines that don't
    need durability.

    Like the persistent stores, it keeps the payload that the codec
    builds from a value, not the value itself: a value read back is a
    new object, with the types that the codec preserves. With the default
    :class:`~persista.store.JsonCodec`, a value must be representable in
    JSON. Use ``codec=PickleCodec()`` to keep Python types, such as tuples,
    sets, or instances of your classes.

    Async methods (``aget``, ``aset``, ...) run in a worker thread of the
    store.

    Args:
        codec: The codec that turns the values into payloads.
            Defaults to a :class:`~persista.store.JsonCodec`.

    Example:
        ```pycon
        >>> from persista.store import InMemoryStore, PickleCodec
        >>> with InMemoryStore() as store:
        ...     store.set("1", {"text": "hello"})
        ...     store.count()
        ...     store.get("1")
        ...
        1
        {'text': 'hello'}
        >>> with InMemoryStore(codec=PickleCodec()) as store:
        ...     store.set("1", {"point": (1, 2)})
        ...     store.get("1")
        ...
        {'point': (1, 2)}

        ```
    """

    def __init__(self, *, codec: Codec | None = None) -> None:
        super().__init__(codec=codec)
        self._data: dict[str, Payload] = {}

    def to_uri(self) -> str:
        return "memory://"

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> Self:  # noqa: ARG003
        return cls()

    def _open(self) -> None:
        self._data = {}

    def _close(self) -> None:
        # Discard all values: an in-memory store has nothing to
        # persist, so closing (and later reopening) it is equivalent to
        # starting over with a fresh, empty store.
        self._data.clear()

    def _get_many(self, keys: list[str]) -> dict[str, Payload]:
        data = self._data
        return {key: data[key] for key in keys if key in data}

    def _put_many(self, items: dict[str, Payload]) -> None:
        self._data.update(items)

    def _update(self, keys: list[str], plan: Plan) -> None:
        # Atomic because the base holds the lock of the instance.
        self._data.update(plan(self._get_many(keys)))

    def _delete_many(self, keys: list[str]) -> None:
        for key in keys:
            self._data.pop(key, None)

    def _clear(self) -> None:
        self._data.clear()

    def _count(self) -> int:
        return len(self._data)

    def _iter_batches(self, batch_size: int) -> Iterator[dict[str, Payload]]:
        # A snapshot of the keys: the data can change between two batches.
        for keys in batchify(list(self._data), size=batch_size):
            # A key deleted since the snapshot is skipped.
            if batch := self._get_many(list(keys)):
                yield batch

    def _contains_many(self, keys: list[str]) -> set[str]:
        return {key for key in keys if key in self._data}

    def _get_repr_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"closed": self._closed}
        if not self._closed:
            kwargs["count"] = f"{self.count():,}"
        return kwargs
