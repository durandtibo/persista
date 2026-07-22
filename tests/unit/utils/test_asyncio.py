from __future__ import annotations

import pytest

from persista.utils.asyncio import EmptyAsyncIterator

########################################
#     Tests for EmptyAsyncIterator     #
########################################


async def test_empty_async_iterator_yields_nothing() -> None:
    assert [item async for item in EmptyAsyncIterator()] == []


async def test_empty_async_iterator_raises_stop_async_iteration() -> None:
    with pytest.raises(StopAsyncIteration):
        await EmptyAsyncIterator().__anext__()


def test_empty_async_iterator_aiter_returns_self() -> None:
    iterator = EmptyAsyncIterator()
    assert iterator.__aiter__() is iterator
