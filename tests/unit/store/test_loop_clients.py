from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from persista.store.loop_clients import LoopClient, LoopClients

MODULE = "persista.store.loop_clients"


def create_clients(**kwargs: Any) -> LoopClients:
    r"""Return clients whose factory builds a new mock client."""
    return LoopClients(AsyncMock, owner="MyStore", **kwargs)


################################
#     Tests for LoopClient     #
################################


def test_loop_client_enter_gives_the_client() -> None:
    client = MagicMock()
    with LoopClient(client, MagicMock()) as entered:
        assert entered is client


def test_loop_client_not_closing() -> None:
    assert not LoopClient(MagicMock(), MagicMock()).closing


async def test_loop_client_wait_until_idle_without_call() -> None:
    entry = LoopClient(MagicMock(), MagicMock())
    await asyncio.wait_for(entry.wait_until_idle(), timeout=1)
    assert entry._calls == 0


async def test_loop_client_wait_until_idle_waits_for_every_call() -> None:
    entry = LoopClient(MagicMock(), MagicMock())
    entry.__enter__()
    entry.__enter__()
    task = asyncio.ensure_future(entry.wait_until_idle())
    await asyncio.sleep(0)
    entry.__exit__()
    await asyncio.sleep(0)
    waiting = not task.done()
    entry.__exit__()
    await asyncio.wait_for(task, timeout=1)
    assert waiting


async def test_loop_client_wait_until_idle_after_a_previous_idle_time() -> None:
    entry = LoopClient(MagicMock(), MagicMock())
    with entry:
        pass
    entry.__enter__()
    task = asyncio.ensure_future(entry.wait_until_idle())
    await asyncio.sleep(0)
    waiting = not task.done()
    entry.__exit__()
    await asyncio.wait_for(task, timeout=1)
    assert waiting


def test_loop_client_exit_after_an_error() -> None:
    entry = LoopClient(MagicMock(), MagicMock())
    entry.__enter__()
    entry.__exit__(ValueError, ValueError("failed"), None)
    assert entry._calls == 0


#################################
#     Tests for LoopClients     #
#################################


# --- len ---


def test_len_empty() -> None:
    assert len(create_clients()) == 0


async def test_len_with_a_client() -> None:
    clients = create_clients()
    await clients.get()
    assert len(clients) == 1
    await clients.aclose()


# --- get ---


async def test_get_is_reused_in_a_loop() -> None:
    clients = create_clients()
    assert await clients.get() is await clients.get()
    await clients.aclose()


def test_get_creates_one_client_per_loop() -> None:
    clients = create_clients()

    async def client() -> Any:
        return (await clients.get()).client

    assert asyncio.run(client()) is not asyncio.run(client())


async def test_get_being_closed() -> None:
    clients = create_clients()
    entry = await clients.get()
    entry.closing = True
    with pytest.raises(RuntimeError, match=r"MyStore is not open: it is being closed"):
        await clients.get()
    entry.closing = False
    await clients.aclose()


async def test_get_factory_error() -> None:
    clients = LoopClients(MagicMock(side_effect=OSError("no server")), owner="MyStore")
    with pytest.raises(OSError, match=r"no server"):
        await clients.get()
    assert len(clients) == 0


def test_loop_shutdown_closes_the_client() -> None:
    clients = create_clients()

    async def client() -> Any:
        return (await clients.get()).client

    created = asyncio.run(client())
    assert (created.aclose.await_count, len(clients)) == (1, 0)


# --- check_none_open ---


def test_check_none_open_without_client() -> None:
    clients = create_clients()
    clients.check_none_open()
    assert len(clients) == 0


async def test_check_none_open_with_a_client() -> None:
    clients = create_clients()
    await clients.get()
    with pytest.raises(RuntimeError, match=r"An async client of MyStore is open"):
        clients.check_none_open()
    await clients.aclose()


def test_check_none_open_forgets_closed_loops() -> None:
    clients = create_clients()
    loop = asyncio.new_event_loop()
    loop.close()
    clients._entries[loop] = MagicMock()
    clients.check_none_open()
    assert len(clients) == 0


# --- aclose ---


async def test_aclose_closes_the_client() -> None:
    clients = create_clients()
    entry = await clients.get()
    await clients.aclose()
    assert (entry.client.aclose.await_count, len(clients)) == (1, 0)


async def test_aclose_without_client() -> None:
    clients = create_clients()
    await clients.aclose()
    assert len(clients) == 0


async def test_aclose_twice() -> None:
    clients = create_clients()
    entry = await clients.get()
    await asyncio.gather(clients.aclose(), clients.aclose())
    assert entry.client.aclose.await_count == 1


def test_aclose_keeps_the_client_of_another_loop() -> None:
    clients = create_clients()
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(clients.get())
        asyncio.run(clients.aclose())
        assert len(clients) == 1
        loop.run_until_complete(clients.aclose())
    finally:
        loop.close()


async def test_aclose_waits_for_the_calls_that_use_the_client() -> None:
    clients = create_clients()
    entry = await clients.get()
    with entry:
        task = asyncio.ensure_future(clients.aclose())
        await asyncio.sleep(0)
        waiting = not task.done() and not entry.client.aclose.await_count
    await task
    assert (waiting, entry.client.aclose.await_count) == (True, 1)


async def test_concurrent_aclose_close_the_client_once() -> None:
    clients = create_clients()
    entry = await clients.get()
    with entry:
        tasks = [asyncio.ensure_future(clients.aclose()) for _ in range(2)]
        await asyncio.sleep(0)
    await asyncio.gather(*tasks)
    assert entry.client.aclose.await_count == 1


async def test_aclose_cancelled_keeps_the_client_usable() -> None:
    clients = create_clients()
    with await clients.get():
        task = asyncio.ensure_future(clients.aclose())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError, match=r"^$"):
            await task
    assert not (await clients.get()).closing
    await clients.aclose()


# --- _close_with_loop ---


async def test__close_with_loop() -> None:
    clients = create_clients()
    client = AsyncMock()
    loop = asyncio.get_running_loop()
    clients._entries[loop] = MagicMock()
    guard = clients._close_with_loop(client, loop)
    await anext(guard)
    await guard.aclose()
    assert (len(clients), client.aclose.await_count) == (0, 1)


# --- _forget_closed_loops ---


def test__forget_closed_loops(caplog: pytest.LogCaptureFixture) -> None:
    clients = create_clients()
    loop = asyncio.new_event_loop()
    loop.close()
    clients._entries[loop] = MagicMock()
    with caplog.at_level(logging.WARNING, logger=MODULE):
        clients._forget_closed_loops()
    message = (
        "An event loop was closed while the async client of a MyStore was open. "
        "Call aclose() before closing the loop"
    )
    assert (len(clients), caplog.messages) == (0, [message])


def test__forget_closed_loops_abandons_the_client() -> None:
    abandon = MagicMock()
    clients = create_clients(abandon=abandon)
    loop = asyncio.new_event_loop()
    loop.close()
    entry = MagicMock()
    clients._entries[loop] = entry
    clients._forget_closed_loops()
    abandon.assert_called_once_with(entry.client)


def test__forget_closed_loops_keeps_open_loops() -> None:
    abandon = MagicMock()
    clients = create_clients(abandon=abandon)
    loop = asyncio.new_event_loop()
    entry = MagicMock()
    clients._entries[loop] = entry
    try:
        clients._forget_closed_loops()
        assert (clients._entries, abandon.call_count) == ({loop: entry}, 0)
    finally:
        loop.close()
