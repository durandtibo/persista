from __future__ import annotations

import asyncio

import pytest

from persista.store._async_close import close_async_connection_from_sync


class _FakeAsyncConn:
    def __init__(self, *, error_on_close: BaseException | None = None) -> None:
        self.closed = False
        self._error_on_close = error_on_close

    async def close(self) -> None:
        if self._error_on_close is not None:
            raise self._error_on_close
        self.closed = True


def test_close_async_connection_from_sync_none() -> None:
    # ``aconn`` is ``None`` -> no-op.
    close_async_connection_from_sync(None, resource_label="SQLite")


def test_close_async_connection_from_sync_closes_connection() -> None:
    conn = _FakeAsyncConn()
    close_async_connection_from_sync(conn, resource_label="SQLite")
    assert conn.closed


def test_close_async_connection_from_sync_custom_close_method() -> None:
    class _FakeAsyncConnCustom:
        def __init__(self) -> None:
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    conn = _FakeAsyncConnCustom()
    close_async_connection_from_sync(conn, resource_label="Redis", close_method="aclose")
    assert conn.closed


def test_close_async_connection_from_sync_loop_already_closed() -> None:
    # ``asyncio.run`` raises ``RuntimeError`` when the event loop that
    # originally owned the connection is already closed; this should be
    # tolerated and logged rather than propagated.
    conn = _FakeAsyncConn(error_on_close=RuntimeError("Event loop is closed"))
    close_async_connection_from_sync(conn, resource_label="Postgres")


def test_close_async_connection_from_sync_raises_inside_running_loop() -> None:
    conn = _FakeAsyncConn()

    async def _run() -> None:
        close_async_connection_from_sync(conn, resource_label="SQLite")

    with pytest.raises(RuntimeError, match="inside a running event loop"):
        asyncio.run(_run())
