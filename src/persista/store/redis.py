r"""Provide a Redis-backed implementation of ``BaseStore``."""

from __future__ import annotations

__all__ = ["RedisStore"]

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit

from coola.display import MultilineDisplayMixin
from coola.utils.batching import batchify

from persista.store.base import BaseStore
from persista.store.validation import check_is_open, validate_namespace
from persista.utils.imports import check_redis, is_redis_available

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Iterable, Iterator, Mapping
    from typing import Self

    from persista.store.codec import Codec
    from persista.store.types import Payload, Plan

if TYPE_CHECKING or is_redis_available():  # pragma: no cover
    import redis
    import redis.asyncio as aredis
    from redis import exceptions as redis_exceptions

logger: logging.Logger = logging.getLogger(__name__)

# The schemes of the URLs that redis-py accepts.
_URL_SCHEMES = frozenset({"redis", "rediss", "unix"})

# Number of keys that filter() and keys() read at a time.
_SCAN_BATCH_SIZE = 256

# Number of keys that one command of clear() deletes.
_DELETE_BATCH_SIZE = 1000


class RedisStore(BaseStore, MultilineDisplayMixin):
    r"""A Redis-backed key-value store.

    A store owns a namespace of a Redis database. It keeps the value of
    a key in the Redis string ``<namespace>:v:<key>``, and its keys in
    the Redis set ``<namespace>:keys``. Stores with different namespaces
    share nothing, so ``clear`` and ``count`` only concern the namespace of
    the store. Any key can be used, but it must be valid Unicode: every
    method that takes a key raises ``ValueError`` for a key with a lone
    surrogate, before anything is read or written. Other programs must
    not modify the Redis keys of the namespace. There is no time-to-live,
    so a Redis server that evicts keys (``maxmemory-policy``) can lose
    data.

    A value is kept as the payload of the codec: with the default
    :class:`~persista.store.JsonCodec`, as UTF-8 JSON that any Redis
    client can read; with a :class:`~persista.store.PickleCodec`, as
    opaque bytes that keep Python types. :meth:`filter` reads and decodes
    every value, since Redis cannot query inside the values.

    A write of several keys runs in one transaction. A write with
    ``on_conflict`` set to ``"raise"``, ``"skip"`` or ``"merge"`` watches the
    keys (``WATCH``/``MULTI``) and starts again if another client changes one
    of them before the write, so it is atomic against every other writer,
    including other processes. :meth:`clear` removes, in one transaction,
    every key that exists when it starts: a key that another client
    creates during the call is kept.

    An iteration reads the list of the keys when it starts, then their
    values in batches. It skips the keys deleted in the meantime and does
    not yield the keys created after it started. :meth:`keys` can yield a
    key that was deleted in the meantime.

    A namespace does not record its codec: reading it with the other
    codec raises a decoding error, so open it with the codec that wrote
    it.

    The sync methods use a ``redis.Redis`` client, and the async methods a
    ``redis.asyncio.Redis`` client, without threads. An async client is
    created by the first async call in an event loop, belongs to that
    loop, and is only used by it: another event loop gets its own client.
    It is closed by :meth:`aclose` in its loop, or when its loop shuts
    down its asynchronous generators, which ``asyncio.run`` does before it
    returns. :meth:`close` raises ``RuntimeError`` while an async client is
    open: call ``await store.aclose()`` instead.

    A client has a limited number of connections (``max_connections``,
    whose default depends on the version of ``redis-py``: 100 in version
    8). A call that needs one more raises
    ``redis.exceptions.MaxConnectionsError``: give a larger
    ``max_connections``, or limit the number of concurrent calls (for
    example more than 100 ``aget`` calls in one ``asyncio.gather``).

    Args:
        url: The Redis connection URL (e.g.
            ``"redis://localhost:6379/0"``), as accepted by
            ``redis.Redis.from_url``.
        codec: The codec of the values. Defaults to a
            :class:`~persista.store.JsonCodec`. Decoding a pickle payload
            can execute arbitrary code: only use a
            :class:`~persista.store.PickleCodec` with a trusted server.
        namespace: The prefix of the Redis keys that the store owns. It
            must not be empty, contain ``":v:"`` or end with ``":v"``, so
            that two namespaces never share a Redis key.
        **kwargs: Additional keyword arguments of
            ``redis.Redis.from_url`` and of its async equivalent, such as
            ``socket_timeout`` or ``max_connections``. An option in the
            query string of the URL takes precedence.

    Raises:
        RuntimeError: If the ``redis`` package is not installed.
        TypeError: If ``namespace`` is not a ``str``.
        ValueError: If ``namespace`` is invalid, or if ``decode_responses``
            is given (the store reads the payloads as bytes).

    Example:
        ```pycon
        >>> from persista.store import RedisStore
        >>> with RedisStore("redis://localhost:6379/0") as store:  # doctest: +SKIP
        ...     store.set_many(
        ...         {
        ...             "1": {
        ...                 "title": "Intro to Python",
        ...                 "author": "Alice",
        ...                 "category": "Programming",
        ...             },
        ...             "2": {
        ...                 "title": "Advanced Python",
        ...                 "author": "Alice",
        ...                 "category": "Programming",
        ...             },
        ...             "3": {"title": "History of Rome", "author": "Bob", "category": "History"},
        ...         }
        ...     )
        ...     len(store.filter(author="Alice"))
        ...
        2

        ```

        A pickle codec keeps Python types, and each namespace has its own
        keys:

        ```pycon
        >>> from persista.store import PickleCodec, RedisStore
        >>> with RedisStore(codec=PickleCodec(), namespace="tags") as store:  # doctest: +SKIP
        ...     store.set("1", {"tags": {"python"}})
        ...     store.get("1")
        ...
        {'tags': {'python'}}

        ```
    """

    # The clients of redis-py can be used by several threads at once.
    _thread_safe = True

    def __init__(
        self,
        url: str = "redis://localhost:6379/0",
        *,
        codec: Codec | None = None,
        namespace: str = "persista",
        **kwargs: Any,
    ) -> None:
        check_redis()
        validate_namespace(namespace)
        if "decode_responses" in kwargs or "decode_responses" in parse_qs(urlsplit(url).query):
            msg = (
                "RedisStore reads the payloads as bytes: it does not accept decode_responses, "
                "as an argument or in the URL"
            )
            raise ValueError(msg)
        super().__init__(codec=codec)
        self._url = url
        self._namespace = namespace
        self._value_prefix = f"{namespace}:v:".encode()
        self._keys_set = f"{namespace}:keys".encode()
        self._kwargs = kwargs
        self._client: redis.Redis | None = None
        # The async client of each event loop.
        self._aclients: dict[asyncio.AbstractEventLoop, _LoopClient] = {}

    @property
    def namespace(self) -> str:
        r"""The prefix of the Redis keys that the store owns."""
        return self._namespace

    @property
    def client(self) -> redis.Redis:
        r"""Return the underlying sync Redis client.

        This is not part of the regular store API. It is meant for
        debugging or running specific commands. The store must be open.
        The client returns ``bytes``.

        Raises:
            RuntimeError: If the store is not open.
        """
        if self._client is None:
            msg = f"{type(self).__name__} is not open."
            raise RuntimeError(msg)
        return self._client

    def close(self) -> None:
        r"""Close the store and release its connections.

        Calling ``close()`` on a closed store does nothing.

        Raises:
            RuntimeError: If an async client is open, i.e. an event loop
                used an async method and has neither called
                :meth:`aclose` nor shut down. The store stays open: call
                ``await store.aclose()`` in that event loop.
        """
        with self._lock:
            self._forget_closed_loops()
            if self._aclients:
                msg = (
                    f"An async client of {type(self).__name__} is open: call "
                    "`await store.aclose()` in the event loop that used it, instead of close()"
                )
                raise RuntimeError(msg)
            super().close()

    async def aclose(self) -> None:
        r"""Close the async client of the running event loop, then the
        store.

        The async calls of this loop that are using the client end first;
        the calls made in the meantime raise ``RuntimeError``.

        Raises:
            RuntimeError: If the async client of another event loop is
                open. The store stays open.
        """
        await self._aclose()
        # Not in a thread: no other task of this loop can create a new
        # async client before the store is closed.
        self.close()

    def to_uri(self) -> str:
        r"""Return the URL of the Redis server.

        The URL is the one given to the constructor, so it contains the
        password if there is one: treat it as a secret. It does not
        describe the namespace, the codec or the other arguments.

        Returns:
            The URL.
        """
        return self._url

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False, **kwargs: Any) -> Self:
        r"""Reconstruct a store from a URI produced by :meth:`to_uri`.

        The URI does not describe the namespace, the codec or the other
        arguments of the constructor: pass them again.

        Args:
            uri: A Redis connection URL.
            read_only: Ignored, since a Redis connection has no read-only
                mode.
            **kwargs: The keyword arguments of the constructor, such as
                ``codec`` or ``namespace``.

        Returns:
            A new store instance, not opened.
        """
        del read_only
        return cls(uri, **kwargs)

    ######################
    #     Primitives     #
    ######################

    def _open(self) -> None:
        _check_url(self._url)
        self._client = redis.Redis.from_url(self._url, **self._kwargs)
        # Connect now, so that a wrong address or password fails here. A
        # user who may not run PING is connected and authenticated.
        with contextlib.suppress(redis_exceptions.NoPermissionError):
            self._client.ping()

    def _close(self) -> None:
        if self._client is None:
            return
        logger.info("Closing Redis connection at %s", _redact_url(self._url))
        self._client.close()
        self._client = None

    def _get_many(self, keys: list[str]) -> dict[str, Payload]:
        # The shortest path for the most frequent read.
        if len(keys) == 1:
            key = keys[0]
            payload = self.client.get(self._value_prefix + _encode_key(key))
            return {} if payload is None else {key: payload}
        names = self._value_names(_encode_keys(keys))
        return _present(keys, self.client.mget(names))

    def _put_many(self, items: dict[str, Payload]) -> None:
        rows = self._encode_rows(items)
        with self.client.pipeline() as pipe:
            self._queue_put(pipe, rows)
            pipe.execute()
        logger.debug("Added/replaced %d key-value pair(s)", len(items))

    def _update(self, keys: list[str], plan: Plan) -> None:
        names = self._value_names(_encode_keys(keys))
        while True:
            with self.client.pipeline() as pipe:
                try:
                    # The transaction fails if one of these keys changes
                    # between this command and its execution.
                    pipe.watch(*names)
                    items = plan(_present(keys, pipe.mget(names)))
                    pipe.multi()
                    self._queue_put(pipe, self._encode_rows(items))
                    pipe.execute()
                except redis.WatchError:
                    continue
                return

    def _delete_many(self, keys: list[str]) -> None:
        raw_keys = _encode_keys(keys)
        with self.client.pipeline() as pipe:
            self._queue_delete(pipe, raw_keys)
            pipe.execute()

    def _clear(self) -> None:
        raw_keys = self._snapshot_keys()
        # One transaction, which removes each value together with its
        # entry in the set: a key created meanwhile keeps both.
        with self.client.pipeline() as pipe:
            for batch in batchify(raw_keys, size=_DELETE_BATCH_SIZE):
                self._queue_delete(pipe, batch)
            pipe.execute()

    def _count(self) -> int:
        return self.client.scard(self._keys_set)

    def _contains_many(self, keys: list[str]) -> set[str]:
        flags = self.client.smismember(self._keys_set, _encode_keys(keys))
        return {key for key, flag in zip(keys, flags, strict=True) if flag}

    def _iter_batches(self, batch_size: int) -> Iterator[dict[str, Payload]]:
        for raw_keys in batchify(self._snapshot_keys(), size=batch_size):
            values = self.client.mget(self._value_names(raw_keys))
            # A key deleted since the snapshot is skipped.
            if batch := _present(_decode_keys(raw_keys), values):
                yield batch

    def _iter_key_batches(self, batch_size: int) -> Iterator[list[str]]:
        for raw_keys in batchify(self._snapshot_keys(), size=batch_size):
            yield _decode_keys(raw_keys)

    ############################
    #     Async primitives     #
    ############################

    async def _aget_many(self, keys: list[str]) -> dict[str, Payload]:
        if len(keys) == 1:
            key = keys[0]
            name = self._value_prefix + _encode_key(key)
            with await self._async_client() as client:
                payload = await client.get(name)
            return {} if payload is None else {key: payload}
        names = self._value_names(_encode_keys(keys))
        with await self._async_client() as client:
            values = await client.mget(names)
        return _present(keys, values)

    async def _aput_many(self, items: dict[str, Payload]) -> None:
        rows = self._encode_rows(items)
        with await self._async_client() as client:
            async with client.pipeline() as pipe:
                self._queue_put(pipe, rows)
                await pipe.execute()
        logger.debug("Added/replaced %d key-value pair(s)", len(items))

    async def _aupdate(self, keys: list[str], plan: Plan) -> None:
        names = self._value_names(_encode_keys(keys))
        with await self._async_client() as client:
            while True:
                async with client.pipeline() as pipe:
                    try:
                        await pipe.watch(*names)
                        items = plan(_present(keys, await pipe.mget(names)))
                        pipe.multi()
                        self._queue_put(pipe, self._encode_rows(items))
                        await pipe.execute()
                    except redis.WatchError:
                        continue
                    return

    async def _adelete_many(self, keys: list[str]) -> None:
        raw_keys = _encode_keys(keys)
        with await self._async_client() as client:
            async with client.pipeline() as pipe:
                self._queue_delete(pipe, raw_keys)
                await pipe.execute()

    async def _aclear(self) -> None:
        with await self._async_client() as client:
            raw_keys = _encode_members(await client.smembers(self._keys_set))
            async with client.pipeline() as pipe:
                for batch in batchify(raw_keys, size=_DELETE_BATCH_SIZE):
                    self._queue_delete(pipe, batch)
                await pipe.execute()

    async def _acount(self) -> int:
        with await self._async_client() as client:
            return await client.scard(self._keys_set)

    async def _acontains_many(self, keys: list[str]) -> set[str]:
        raw_keys = _encode_keys(keys)
        with await self._async_client() as client:
            flags = await client.smismember(self._keys_set, raw_keys)
        return {key for key, flag in zip(keys, flags, strict=True) if flag}

    async def _aiter_batches(self, batch_size: int) -> AsyncGenerator[dict[str, Payload]]:
        for raw_keys in batchify(await self._asnapshot_keys(), size=batch_size):
            # Asked again for each batch: the store may have been closed.
            with await self._async_client() as client:
                values = await client.mget(self._value_names(raw_keys))
            if batch := _present(_decode_keys(raw_keys), values):
                yield batch
                check_is_open(self)

    def _afilter_candidates(self, fields: Mapping[str, Any]) -> AsyncGenerator[dict[str, Payload]]:
        del fields
        return self._aiter_batches(_SCAN_BATCH_SIZE)

    async def _aiter_key_batches(self, batch_size: int) -> AsyncGenerator[list[str]]:
        for raw_keys in batchify(await self._asnapshot_keys(), size=batch_size):
            yield _decode_keys(raw_keys)
            check_is_open(self)

    async def _aclose(self) -> None:
        loop = asyncio.get_running_loop()
        # A loop: another task can create a client while one is closing.
        while (entry := self._aclients.get(loop)) is not None:
            # No new call can use the client from now on.
            entry.closing = True
            try:
                await entry.wait_until_idle()
            except BaseException:
                entry.closing = False
                raise
            if self._aclients.pop(loop, None) is not None:
                await entry.guard.aclose()

    ###########################
    #     Template helpers    #
    ###########################

    def _snapshot_keys(self) -> list[bytes]:
        r"""Read all the keys of the namespace.

        Returns:
            The encoded keys, in no particular order.
        """
        return _encode_members(self.client.smembers(self._keys_set))

    async def _asnapshot_keys(self) -> list[bytes]:
        r"""Async equivalent of :meth:`_snapshot_keys`.

        Returns:
            The encoded keys, in no particular order.
        """
        with await self._async_client() as client:
            return _encode_members(await client.smembers(self._keys_set))

    async def _async_client(self) -> _LoopClient:
        r"""Return the async client of the running event loop, creating
        it if needed.

        Use it as a context manager, which gives the client and tells
        :meth:`aclose` that a call is using it::

            with await self._async_client() as client:
                await client.ping()

        Returns:
            The client of the loop.

        Raises:
            RuntimeError: If the store is closed or being closed.
        """
        check_is_open(self)
        loop = asyncio.get_running_loop()
        if (entry := self._aclients.get(loop)) is not None:
            if entry.closing:
                msg = f"{type(self).__name__} is not open: it is being closed"
                raise RuntimeError(msg)
            return entry
        self._forget_closed_loops()
        client = aredis.Redis.from_url(self._url, **self._kwargs)
        guard = self._close_with_loop(client, loop)
        entry = self._aclients[loop] = _LoopClient(client, guard)
        # Starting the generator registers it with the event loop, which
        # closes it when it shuts down. This does not suspend the task.
        await anext(guard)
        return entry

    async def _close_with_loop(
        self, client: aredis.Redis, loop: asyncio.AbstractEventLoop
    ) -> AsyncGenerator[None]:
        r"""Keep an async client until this generator is closed.

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
            self._aclients.pop(loop, None)
            await client.aclose()

    def _forget_closed_loops(self) -> None:
        r"""Drop the async clients of the event loops that were closed
        without shutting down their asynchronous generators.

        Such a client cannot be closed anymore.
        """
        for loop in list(self._aclients):
            if loop.is_closed() and self._aclients.pop(loop, None) is not None:
                logger.warning(
                    "An event loop was closed while the async Redis client of a %s was open. "
                    "Call aclose() before closing the loop",
                    type(self).__name__,
                )

    def _value_names(self, raw_keys: Iterable[bytes]) -> list[bytes]:
        r"""Return the Redis keys of the values of some keys.

        Args:
            raw_keys: The keys, encoded.

        Returns:
            The Redis keys, in the same order.
        """
        return list(map(self._value_prefix.__add__, raw_keys))

    def _encode_rows(self, items: Mapping[str, Payload]) -> dict[bytes, Payload]:
        r"""Encode the keys of some payloads.

        Args:
            items: The payloads, keyed by their unique key.

        Returns:
            The payloads, keyed by their encoded key.

        Raises:
            ValueError: If a key contains a lone surrogate.
        """
        return dict(zip(_encode_keys(list(items)), items.values(), strict=True))

    def _queue_put(self, pipe: Any, rows: Mapping[bytes, Payload]) -> None:
        r"""Add the commands that write some values to a transaction.

        Args:
            pipe: A sync or async pipeline, which buffers the commands.
            rows: The payloads, keyed by their encoded key. Nothing is
                added if it is empty.
        """
        if not rows:
            return
        prefix = self._value_prefix
        pipe.mset(
            {
                prefix + raw_key: payload.encode() if isinstance(payload, str) else payload
                for raw_key, payload in rows.items()
            }
        )
        pipe.sadd(self._keys_set, *rows)

    def _queue_delete(self, pipe: Any, raw_keys: Iterable[bytes]) -> None:
        r"""Add the commands that delete some keys to a transaction.

        Args:
            pipe: A sync or async pipeline, which buffers the commands.
            raw_keys: The encoded keys. It must not be empty.
        """
        raw_keys = list(raw_keys)
        pipe.delete(*self._value_names(raw_keys))
        pipe.srem(self._keys_set, *raw_keys)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "url": _redact_url(self._url),
            "namespace": self._namespace,
            "closed": self.closed,
        }
        if self._codec.name != "json":
            kwargs["codec"] = self._codec
        return kwargs


class _LoopClient:
    r"""Hold the async client of one event loop, and count the calls that
    use it.

    Entering the context gives the client. It is only used by the tasks
    of the event loop of the client.

    Args:
        client: The client.
        guard: The async generator that closes the client.
    """

    def __init__(self, client: aredis.Redis, guard: AsyncGenerator[None]) -> None:
        self.client = client
        self.guard = guard
        # Whether the client is being closed.
        self.closing = False
        self._calls = 0
        self._idle = asyncio.Event()

    def __enter__(self) -> aredis.Redis:
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


def _encode_key(key: str) -> bytes:
    r"""Encode a key as Redis keeps it.

    Args:
        key: The key.

    Returns:
        The key in UTF-8.

    Raises:
        ValueError: If the key contains a lone surrogate.
    """
    try:
        return key.encode()
    except UnicodeEncodeError as exc:
        msg = f"A key of RedisStore must be valid Unicode, but it has a lone surrogate: {key!r}"
        raise ValueError(msg) from exc


def _encode_keys(keys: list[str]) -> list[bytes]:
    r"""Encode several keys as Redis keeps them.

    Args:
        keys: The keys.

    Returns:
        The keys in UTF-8, in the same order.

    Raises:
        ValueError: If a key contains a lone surrogate.
    """
    # Fast path: encode all the keys at once.
    with contextlib.suppress(UnicodeEncodeError):
        return list(map(str.encode, keys))
    # A key is invalid: encode them one by one to report it.
    return [_encode_key(key) for key in keys]


def _encode_members(members: Iterable[bytes | str]) -> list[bytes]:
    r"""Return the members of a Redis set as bytes.

    The clients of the store return ``bytes``, but redis-py types a
    member as ``bytes`` or ``str``.

    Args:
        members: The members read from Redis.

    Returns:
        The members. A ``str`` is encoded in UTF-8.
    """
    return [member.encode() if isinstance(member, str) else member for member in members]


def _decode_keys(raw_keys: Iterable[bytes]) -> list[str]:
    r"""Decode the keys read from Redis.

    Args:
        raw_keys: The keys in UTF-8.

    Returns:
        The keys, in the same order.
    """
    return [raw_key.decode() for raw_key in raw_keys]


def _present(keys: list[str], values: list[Any]) -> dict[str, Payload]:
    r"""Associate keys with the values that exist.

    Args:
        keys: The keys that were read.
        values: The value of each key, in the same order, or ``None`` for a
            missing key.

    Returns:
        The value of each key that exists.
    """
    return {key: value for key, value in zip(keys, values, strict=True) if value is not None}


def _check_url(url: str) -> None:
    r"""Check that the host and the port of a URL can be read.

    The error of redis-py for such a URL can quote a part of the
    password, which this error does not.

    Args:
        url: A Redis connection URL.

    Raises:
        ValueError: If the host or the port of ``url`` cannot be read.
    """
    try:
        _ = urlsplit(url).port
    except ValueError:
        msg = (
            "Invalid Redis URL: its host or port cannot be read. Percent-encode the special "
            "characters of the username and of the password"
        )
        # The original error is hidden because it can quote the password.
        raise ValueError(msg) from None


def _redact_url(url: str) -> str:
    r"""Return the location of a Redis URL, without its credentials.

    Only the scheme, the host, the port, the path and the ``db`` option are
    kept. If the URL is not well formed, for example because a special
    character of the password is not percent-encoded, nothing after the
    scheme is kept.

    Args:
        url: A Redis connection URL.

    Returns:
        The URL without credentials.

    Example:
        ```pycon
        >>> from persista.store.redis import _redact_url
        >>> _redact_url("redis://user:secret@localhost:6379/0")
        'redis://localhost:6379/0'

        ```
    """
    hidden = "<hidden Redis URL>"
    try:
        parts = urlsplit(url)
        _ = parts.port
    except ValueError:
        return hidden
    # An "@" after the host means that the credentials contain an
    # unencoded "/", "?" or "#".
    if parts.scheme not in _URL_SCHEMES or "@" in parts.path + parts.query + parts.fragment:
        return hidden
    location = f"{parts.scheme}://{parts.netloc.rpartition('@')[2]}{parts.path}"
    query = urlencode([(name, value) for name, value in parse_qsl(parts.query) if name == "db"])
    return f"{location}?{query}" if query else location
