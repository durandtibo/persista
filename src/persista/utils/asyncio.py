r"""Contain asyncio utility classes."""

from __future__ import annotations

__all__ = ["EmptyAsyncIterator"]

from typing import Any


class EmptyAsyncIterator:
    """An async iterator that is always exhausted.

    Useful for implementing async stores/iterables that never yield
    anything (e.g. a no-op store), without resorting to an async
    generator whose ``yield`` line can never be reached.
    """

    def __aiter__(self) -> EmptyAsyncIterator:
        return self

    async def __anext__(self) -> Any:
        raise StopAsyncIteration
