r"""Provide the async clients of a store with a native async driver, one
per event loop.

An async client belongs to the event loop that created it: its
connections cannot be used, or closed, from another loop. A
:class:`LoopClients` therefore keeps one client per event loop, closes
it with its loop, and tells whether a client is still open, which
forbids closing the store synchronously.
"""

from __future__ import annotations

__all__ = ["LoopClient", "LoopClients", "SupportsAclose"]

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

logger: logging.Logger = logging.getLogger(__name__)

ClientT = TypeVar("ClientT", bound="SupportsAclose")


class SupportsAclose(Protocol):
    r"""Define the interface of an async client."""

    async def aclose(self) -> Any:
        r"""Close the client."""


class LoopClient(Generic[ClientT]):
    r"""Hold the async client of one event loop, and count the calls that
    use it.

    Entering the context gives the client. It is only used by the tasks
    of the event loop of the client.

    Args:
        client: The client.
        guard: The async generator that closes the client.

    Example:
        ```pycon
        >>> from unittest.mock import AsyncMock
        >>> from persista.store.loop_clients import LoopClient
        >>> entry = LoopClient("client", guard=AsyncMock())
        >>> with entry as client:
        ...     client
        ...
        'client'

        ```
    """

    def __init__(self, client: ClientT, guard: AsyncGenerator[None]) -> None:
        self.client = client
        self.guard = guard
        # Whether the client is being closed.
        self.closing = False
        self._calls = 0
        self._idle = asyncio.Event()

    def __enter__(self) -> ClientT:
        self._calls += 1
        return self.client

    def __exit__(self, *exc_info: object) -> None:
        self._calls -= 1
        if not self._calls:
            self._idle.set()

    async def wait_until_idle(self) -> None:
        r"""Wait until no call uses the client."""
        while self._calls:
            self._idle.clear()
            await self._idle.wait()


class LoopClients(Generic[ClientT]):
    r"""Keep the async client of each event loop that uses a store.

    The client of a loop is created by the first call of :meth:`get` in
    this loop. It is closed by :meth:`aclose` in its loop, or when its
    loop shuts down its asynchronous generators, which ``asyncio.run``
    does before it returns. The client of a loop that was closed without
    doing so cannot be closed anymore: it is dropped with a warning.

    Args:
        factory: A function that creates a client. It is called in the
            event loop that will use the client, and it must not block.
        owner: The name of the class of the store, used in the messages.
        abandon: A function that releases, without an event loop, what
            it can of the client of a closed loop. By default, nothing is
            done.

    Example:
        ```pycon
        >>> import asyncio
        >>> from unittest.mock import AsyncMock
        >>> from persista.store.loop_clients import LoopClients
        >>> clients = LoopClients(AsyncMock, owner="MyStore")
        >>> async def main():
        ...     with await clients.get() as client:
        ...         pass
        ...     await clients.aclose()
        ...     return client.aclose.await_count
        ...
        >>> asyncio.run(main())
        1

        ```
    """

    def __init__(
        self,
        factory: Callable[[], ClientT],
        *,
        owner: str,
        abandon: Callable[[ClientT], None] | None = None,
    ) -> None:
        self._factory = factory
        self._owner = owner
        self._abandon = abandon
        # The client of each event loop.
        self._entries: dict[asyncio.AbstractEventLoop, LoopClient[ClientT]] = {}

    def __len__(self) -> int:
        return len(self._entries)

    async def get(self) -> LoopClient[ClientT]:
        r"""Return the client of the running event loop, creating it if
        needed.

        Use the result as a context manager, which gives the client and
        tells :meth:`aclose` that a call is using it::

            with await clients.get() as client:
                await client.ping()

        This method does not suspend the task, so the caller can check
        the state of its store just before calling it.

        Returns:
            The client of the loop.

        Raises:
            RuntimeError: If the client of the loop is being closed.
        """
        loop = asyncio.get_running_loop()
        if (entry := self._entries.get(loop)) is not None:
            if entry.closing:
                msg = f"{self._owner} is not open: it is being closed"
                raise RuntimeError(msg)
            return entry
        self._forget_closed_loops()
        client = self._factory()
        guard = self._close_with_loop(client, loop)
        entry = self._entries[loop] = LoopClient(client, guard)
        # Starting the generator registers it with the event loop, which
        # closes it when it shuts down. This does not suspend the task.
        await anext(guard)
        return entry

    def check_none_open(self) -> None:
        r"""Check that no event loop has an open client.

        Raises:
            RuntimeError: If the client of an event loop is open, i.e. the
                loop used it and has neither called :meth:`aclose` nor
                shut down.
        """
        self._forget_closed_loops()
        if self._entries:
            msg = (
                f"An async client of {self._owner} is open: call "
                "`await store.aclose()` in the event loop that used it, instead of close()"
            )
            raise RuntimeError(msg)

    async def aclose(self) -> None:
        r"""Close the client of the running event loop, if there is one.

        The calls that are using the client end first; the calls of
        :meth:`get` made in the meantime raise ``RuntimeError``.
        """
        loop = asyncio.get_running_loop()
        # A loop: another task can create a client while one is closing.
        while (entry := self._entries.get(loop)) is not None:
            # No new call can use the client from now on.
            entry.closing = True
            try:
                await entry.wait_until_idle()
            except BaseException:
                entry.closing = False
                raise
            if self._entries.pop(loop, None) is not None:
                await entry.guard.aclose()

    async def _close_with_loop(
        self, client: ClientT, loop: asyncio.AbstractEventLoop
    ) -> AsyncGenerator[None]:
        r"""Keep a client until this generator is closed.

        An event loop closes the asynchronous generators that are still
        running when it shuts down (``loop.shutdown_asyncgens()``, which
        ``asyncio.run`` calls). This closes the client while its loop can
        still do it.

        Args:
            client: The client to close.
            loop: The event loop of the client.

        Yields:
            ``None``, once.
        """
        try:
            yield
        finally:
            self._entries.pop(loop, None)
            await client.aclose()

    def _forget_closed_loops(self) -> None:
        r"""Drop the clients of the event loops that were closed without
        shutting down their asynchronous generators."""
        for loop in list(self._entries):
            if not loop.is_closed() or (entry := self._entries.pop(loop, None)) is None:
                continue
            logger.warning(
                "An event loop was closed while the async client of a %s was open. "
                "Call aclose() before closing the loop",
                self._owner,
            )
            if self._abandon is not None:
                self._abandon(entry.client)
