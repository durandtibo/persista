r"""Provide class-based HTTP clients with automatic retries and optional
response caching, built on ``httpx``."""

from __future__ import annotations

__all__ = ["AsyncHttpClient", "HttpClient"]

import asyncio
import base64
import logging
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Self

from coola.utils.imports import lazy_import

from persista.http.retry import (
    DEFAULT_MAX_DELAY,
    DEFAULT_RETRY_STATUS_CODES,
    IDEMPOTENT_METHODS,
    RetryPolicy,
    normalize_methods,
)
from persista.utils.canonical import hash_canonical
from persista.utils.imports import check_httpx
from persista.utils.url import redact_url_credentials

if TYPE_CHECKING:
    from collections.abc import Iterable

    import httpx

    from persista.cache.cache import Cache
else:
    # Imported when the first request or client needs it.
    httpx = lazy_import("httpx")

logger: logging.Logger = logging.getLogger(__name__)

# Headers that describe the transfer of a content, not the decoded content.
_TRANSFER_HEADERS = frozenset({"content-encoding", "content-length", "transfer-encoding"})


def _prepare_cache_lookup(
    client: httpx.Client | httpx.AsyncClient,
    method: str,
    url: httpx.URL | str,
    kwargs: dict[str, Any],
) -> tuple[httpx.Request, str] | None:
    """Build the request and the cache key of a call, if its response
    can be cached.

    A response cannot be cached if the request is authenticated (an
    ``auth`` of the client or of the call, or credentials in the URL),
    if its body is streamed (including a multipart upload), if the
    client has request event hooks (they can change the request after
    the key is computed), or if the call passes ``extensions`` (they can
    change how the request is sent).

    Args:
        client: The client that sends the request.
        method: The HTTP method, e.g. ``"GET"``.
        url: The URL passed to the call, possibly relative to the
            ``base_url`` of the client.
        kwargs: The other arguments of the call, as accepted by
            :meth:`httpx.Client.request`. Not modified. Its values are
            read once more when the request is sent, so ``headers`` must
            not be a one-shot iterable.

    Returns:
        A ``(request, key)`` tuple, where ``request`` is the request
        built by the client and ``key`` its cache key, or ``None`` if
        the response must not be cached.
    """
    # A multipart upload is streamed. It is checked before the request
    # is built, so that a one-shot iterable of files is not consumed.
    if client.event_hooks["request"] or kwargs.get("extensions") or kwargs.get("files"):
        return None
    auth: Any = kwargs.get("auth", httpx.USE_CLIENT_DEFAULT)
    if auth is httpx.USE_CLIENT_DEFAULT:
        auth = client.auth
    if auth is not None:
        return None
    follow_redirects: Any = kwargs.get("follow_redirects", httpx.USE_CLIENT_DEFAULT)
    if follow_redirects is httpx.USE_CLIENT_DEFAULT:
        follow_redirects = client.follow_redirects
    build_kwargs = {k: v for k, v in kwargs.items() if k not in ("auth", "follow_redirects")}
    request = client.build_request(method, url, **build_kwargs)
    if request.url.userinfo:
        return None
    try:
        key = _cache_key(request, follow_redirects=follow_redirects)
    except httpx.RequestNotRead:
        return None
    return request, key


def _cache_key(request: httpx.Request, *, follow_redirects: bool) -> str:
    """Derive the cache key of a request.

    Args:
        request: The request, built by the client that sends it, so that
            it contains the final URL and all the headers.
        follow_redirects: Whether redirects are followed, since this
            changes the response of a redirected request.

    Returns:
        A hash of the method, URL, headers (names are case-insensitive),
        body, and ``follow_redirects``.

    Raises:
        httpx.RequestNotRead: If the body of the request is streamed.
    """
    headers = [(name.lower(), value) for name, value in request.headers.raw]
    return hash_canonical(
        (
            "persista.http.httpx",
            request.method,
            str(request.url),
            headers,
            request.content,
            follow_redirects,
        )
    )


def _response_to_entry(response: httpx.Response) -> dict[str, Any]:
    """Convert a response to a JSON-serializable cache entry.

    The content is stored decoded, so the headers that describe how it
    was transferred (``content-encoding``, ``content-length`` and
    ``transfer-encoding``) are not stored.

    Args:
        response: The response to convert. Its content must have been
            read.

    Returns:
        A dict with the response's status code, headers, and
        base64-encoded content.
    """
    return {
        "status_code": response.status_code,
        "headers": {
            name: value
            for name, value in response.headers.items()
            if name.lower() not in _TRANSFER_HEADERS
        },
        "content": base64.b64encode(response.content).decode("ascii"),
    }


def _entry_to_response(entry: dict[str, Any], request: httpx.Request) -> httpx.Response:
    """Reconstruct a response from a cache entry.

    Args:
        entry: A cache entry produced by :func:`_response_to_entry`.
        request: The request that the response answers.

    Returns:
        An :class:`httpx.Response` with the status code, headers, and
        content of the one that was cached, and ``request`` attached.
    """
    return httpx.Response(
        status_code=entry["status_code"],
        headers=entry["headers"],
        content=base64.b64decode(entry["content"]),
        request=request,
    )


def _check_client_is_open(client: httpx.Client | httpx.AsyncClient) -> None:
    """Check that a client can send requests.

    A response must not be served from the cache by a closed client.

    Args:
        client: The client that sends the requests.

    Raises:
        RuntimeError: If the client is closed.
    """
    if client.is_closed:
        msg = "Cannot send a request, as the client has been closed."
        raise RuntimeError(msg)


def _is_replayable_body(kwargs: Mapping[str, Any]) -> bool:
    """Indicate if the body of a call can be sent several times.

    A body given as an iterator or a file can only be read once. A
    ``files`` upload is also streamed, and its files may not be
    rewindable.

    Args:
        kwargs: The arguments of the call, as accepted by
            :meth:`httpx.Client.request`. Not modified.

    Returns:
        ``False`` if the call has ``files``, or a ``content`` or
        ``data`` that is not a ``str``, ``bytes`` or (for ``data``) a
        mapping of form fields, otherwise ``True``.
    """
    if kwargs.get("files"):
        return False
    data = kwargs.get("data")
    if isinstance(data, Mapping):
        data = None
    return all(
        body is None or isinstance(body, (str, bytes)) for body in (kwargs.get("content"), data)
    )


def _is_transient_error(error: httpx.TransportError) -> bool:
    """Indicate if sending a request again can avoid a transport error.

    Args:
        error: The error raised by the request.

    Returns:
        ``False`` for an unsupported URL scheme
        (:class:`httpx.UnsupportedProtocol`) and for a request that breaks
        the protocol (:class:`httpx.LocalProtocolError`), otherwise
        ``True`` (timeouts, network errors, proxy errors and invalid
        responses of the server).
    """
    return not isinstance(error, (httpx.UnsupportedProtocol, httpx.LocalProtocolError))


def _plan_retry(
    outcome: httpx.Response | httpx.TransportError,
    *,
    policy: RetryPolicy,
    attempt: int,
    max_retries: int,
    method: str,
    url: str,
) -> float | None:
    """Decide if a request is sent again after an attempt.

    Args:
        outcome: The response of the attempt, or the transport error that
            it raised.
        policy: The retry policy of the call.
        attempt: The number of attempts made, starting at 1.
        max_retries: The maximum number of retries of this request.
        method: The method of the request, for the log.
        url: The URL of the request, without credentials, for the log.

    Returns:
        The delay to wait before the next attempt, in seconds, or
        ``None`` if the request is not sent again.
    """
    retry_after = None
    if isinstance(outcome, httpx.Response):
        if outcome.status_code not in policy.retry_status_codes:
            return None
        retry_after = outcome.headers.get("retry-after")
        reason = f"HTTP {outcome.status_code}"
    elif _is_transient_error(outcome):
        # The message of the error is not logged: it can contain the URL.
        reason = type(outcome).__name__
    else:
        return None
    if attempt > max_retries:
        return None
    delay = policy.get_delay(attempt, retry_after=retry_after)
    logger.debug(
        "Retrying %s %s in %.2fs (attempt %d/%d, %s)",
        method,
        url,
        delay,
        attempt,
        max_retries,
        reason,
    )
    return delay


class HttpClient:
    """A wrapper around :class:`httpx.Client` with automatic retries and
    optional response caching.

    A request behaves as with the wrapped client: the arguments of a call
    (``timeout``, ``headers``, ``auth``, ``follow_redirects``, ...)
    are passed to :meth:`httpx.Client.request`, and the settings of the
    client apply to the others. The differences are the retries, the
    optional cache, and that a 4xx or 5xx response raises
    :class:`httpx.HTTPStatusError`.

    **Retries.** A request is sent again, up to ``max_retries`` times,
    after a response whose status is in ``retry_status_codes`` or after a
    transport error (:class:`httpx.TransportError`, except
    ``UnsupportedProtocol`` and ``LocalProtocolError``). Only the
    methods in ``retry_methods`` are retried: by default the idempotent
    ones, so not ``POST`` or ``PATCH``. A request whose body can only be
    read once (an iterator or a file passed as ``content`` or ``data``,
    or a ``files`` upload) is never retried. The delay before the retry
    ``n`` is the one of the ``Retry-After`` header (a number of seconds
    or an HTTP date), or ``2 ** (n - 1)`` seconds, between ``0`` and
    ``max_delay`` (see :class:`~persista.http.retry.RetryPolicy`). After
    the last attempt, the transport error of that attempt is raised, or
    its response is handled like any response. The ``timeout`` applies to
    each attempt, not to the whole call.

    **Errors.** The messages of the errors of ``httpx`` are not rewritten:
    they can contain the URL of the request, including the credentials that
    it has. The log messages of ``persista`` do not contain them (the
    query string is kept), but those of ``httpx`` can.

    **Cache.** Caching is opt-in: it is only performed when ``cache`` is
    given, and only for methods listed in ``cacheable_methods``. Only
    successful (2xx) responses are cached.

    A cached response is served only for a request with the same method,
    final URL (including the ``base_url`` and parameters of the client),
    headers (including those of the client and the cookies), body, and
    redirect setting, as built by
    :meth:`httpx.Client.build_request`. The cache is not used at all for
    a request that has an ``auth`` (of the client or of the call) or
    credentials in its URL, a streaming body (including ``files``
    uploads), or ``extensions``, nor for a client with request event
    hooks. The ``Cache-Control``, ``ETag`` and ``Vary`` headers are not
    interpreted.

    A response from the cache has the status code, headers and content of
    the one that was cached, except the ``content-encoding``,
    ``content-length`` and ``transfer-encoding`` headers (the content is
    stored decoded, and ``content-length`` is that of the decoded
    content). Its ``request`` is the request of the current call.

    Args:
        client: The :class:`httpx.Client` to wrap. The caller owns its
            lifecycle: the wrapper does not close it. ``None`` (the
            default) creates a client with the default settings of
            ``httpx``, which the wrapper closes (see :meth:`close`).
        max_retries: Default maximum number of retries of a request.
        retry_status_codes: The HTTP status codes that trigger a retry
            by default.
        retry_methods: The HTTP methods (case-insensitive) that are
            retried. The collection replaces the default one.
        max_delay: The maximum delay between two attempts, in seconds.
        cache: An optional :class:`~persista.cache.cache.Cache` used
            to cache responses. ``None`` (the default) disables
            caching entirely.
        cacheable_methods: The HTTP methods (case-insensitive) whose
            responses are cached, when ``cache`` is given. Defaults
            to ``{"GET"}``.

    Raises:
        RuntimeError: If the ``httpx`` package is not installed.
        TypeError: If a retry argument or ``cacheable_methods`` has a
            wrong type.
        ValueError: If a retry argument has an invalid value.

    Example:
        ```pycon
        >>> import httpx
        >>> from persista.http.httpx import HttpClient
        >>> transport = httpx.MockTransport(lambda request: httpx.Response(200, text="ok"))
        >>> with httpx.Client(transport=transport) as httpx_client:
        ...     client = HttpClient(httpx_client, max_retries=5)
        ...     client.get("https://example.com", timeout=10).text
        ...
        'ok'

        ```
    """

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        max_retries: int = 3,
        retry_status_codes: Iterable[int] = DEFAULT_RETRY_STATUS_CODES,
        retry_methods: Iterable[str] = IDEMPOTENT_METHODS,
        max_delay: float = DEFAULT_MAX_DELAY,
        cache: Cache | None = None,
        cacheable_methods: Iterable[str] = frozenset({"GET"}),
    ) -> None:
        check_httpx()
        self._policy = RetryPolicy(
            max_retries=max_retries,
            retry_status_codes=retry_status_codes,
            retry_methods=retry_methods,
            max_delay=max_delay,
        )
        self._cache = cache
        self._cacheable_methods = normalize_methods(cacheable_methods, name="cacheable_methods")
        # Created last, so an invalid argument leaves no client open.
        self._owns_client = client is None
        self._client = httpx.Client() if client is None else client

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the client if the wrapper created it.

        A client given to the constructor is left open. Closing twice
        does nothing.
        """
        if self._owns_client:
            self._client.close()

    def request(
        self,
        method: str,
        url: httpx.URL | str,
        *,
        max_retries: int | None = None,
        retry_status_codes: Iterable[int] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send an HTTP request, with retries, serving/storing it via
        the cache when enabled for ``method``.

        Args:
            method: The HTTP method to use, e.g. ``"GET"``.
            url: The URL of the request, possibly relative to the
                ``base_url`` of the client.
            max_retries: Per-call max-retries override. Defaults to
                the value given at construction. It does not make a method
                retried if it is not in ``retry_methods``.
            retry_status_codes: Per-call retry-status-codes override.
                Defaults to the value given at construction.
            **kwargs: Additional keyword arguments forwarded to
                :meth:`httpx.Client.request`, e.g. ``timeout``,
                ``headers``, ``json``, ``params``, ``auth``.

        Returns:
            The :class:`httpx.Response` object for the completed
            request, from the cache if it was a hit.

        Raises:
            RuntimeError: If the client is closed.
            TypeError: If a retry argument has a wrong type.
            ValueError: If a retry argument has an invalid value.
            httpx.HTTPStatusError: If the response of the last attempt has
                a 4xx or 5xx status.
            httpx.TransportError: If the last attempt did not get a
                response (e.g. unreachable host or timeout).
        """
        _check_client_is_open(self._client)
        method = method.upper()
        policy = self._policy.replace(
            max_retries=max_retries, retry_status_codes=retry_status_codes
        )
        if kwargs.get("headers") is not None:
            # The headers are read several times (for the cache key and by
            # each attempt), so a one-shot iterable must be materialized.
            kwargs["headers"] = httpx.Headers(kwargs["headers"])
        cache = self._cache
        lookup = None
        if cache is not None and method in self._cacheable_methods:
            lookup = _prepare_cache_lookup(self._client, method, url, kwargs)
        if cache is not None and lookup is not None:
            request, key = lookup
            if (entry := cache.get(key)) is not None:
                logger.debug("Serving %s %s from cache", method, redact_url_credentials(url))
                return _entry_to_response(entry, request)

        response = self._send(method, url, policy, kwargs)
        if cache is not None and lookup is not None and response.is_success:
            cache.set(lookup[1], _response_to_entry(response))
        return response

    def _send(
        self,
        method: str,
        url: httpx.URL | str,
        policy: RetryPolicy,
        kwargs: dict[str, Any],
    ) -> httpx.Response:
        """Send a request until it succeeds or cannot be retried.

        ``httpx`` reads and closes the response of each attempt.

        Args:
            method: The HTTP method, in upper case.
            url: The URL of the request.
            policy: The retry policy of the call.
            kwargs: The other arguments of
                :meth:`httpx.Client.request`.

        Returns:
            The response of the last attempt.

        Raises:
            httpx.HTTPStatusError: If the response of the last attempt has
                a 4xx or 5xx status.
            httpx.TransportError: If the last attempt did not get a
                response.
        """
        max_retries = policy.get_max_retries(method) if _is_replayable_body(kwargs) else 0
        shown_url = redact_url_credentials(url)
        logger.debug("Sending %s %s...", method, shown_url)
        attempt = 0
        while True:
            attempt += 1
            start = time.perf_counter()
            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.TransportError as error:
                delay = _plan_retry(
                    error,
                    policy=policy,
                    attempt=attempt,
                    max_retries=max_retries,
                    method=method,
                    url=shown_url,
                )
                if delay is None:
                    raise
            else:
                logger.debug(
                    "Response received: HTTP %d (%d bytes) in %.2fs",
                    response.status_code,
                    len(response.content),
                    time.perf_counter() - start,
                )
                delay = _plan_retry(
                    response,
                    policy=policy,
                    attempt=attempt,
                    max_retries=max_retries,
                    method=method,
                    url=shown_url,
                )
                if delay is None:
                    break
            time.sleep(delay)
        if response.is_error:
            response.raise_for_status()
        return response

    def get(self, url: httpx.URL | str, **kwargs: Any) -> httpx.Response:
        """Send a ``GET`` request.

        See :meth:`request`.
        """
        return self.request("GET", url, **kwargs)

    def post(self, url: httpx.URL | str, **kwargs: Any) -> httpx.Response:
        """Send a ``POST`` request.

        See :meth:`request`.
        """
        return self.request("POST", url, **kwargs)

    def put(self, url: httpx.URL | str, **kwargs: Any) -> httpx.Response:
        """Send a ``PUT`` request.

        See :meth:`request`.
        """
        return self.request("PUT", url, **kwargs)

    def patch(self, url: httpx.URL | str, **kwargs: Any) -> httpx.Response:
        """Send a ``PATCH`` request.

        See :meth:`request`.
        """
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: httpx.URL | str, **kwargs: Any) -> httpx.Response:
        """Send a ``DELETE`` request.

        See :meth:`request`.
        """
        return self.request("DELETE", url, **kwargs)


class AsyncHttpClient:
    """A wrapper around :class:`httpx.AsyncClient` with automatic
    retries and optional response caching.

    This is the async counterpart of :class:`HttpClient`. See its
    docstring for the behavior of the requests, the retries, the errors
    and the cache; the differences are that the wrapped client is an
    :class:`httpx.AsyncClient`, that the wrapper is closed with
    :meth:`aclose` or ``async with``, and that caching is done through
    :class:`~persista.cache.cache.Cache`'s async methods
    (``aget``/``aset``).

    Args:
        client: The :class:`httpx.AsyncClient` to wrap. The caller owns
            its lifecycle: the wrapper does not close it. ``None`` (the
            default) creates a client with the default settings of
            ``httpx``, which the wrapper closes (see :meth:`aclose`).
        max_retries: Default maximum number of retries of a request.
        retry_status_codes: The HTTP status codes that trigger a retry
            by default.
        retry_methods: The HTTP methods (case-insensitive) that are
            retried. The collection replaces the default one.
        max_delay: The maximum delay between two attempts, in seconds.
        cache: An optional :class:`~persista.cache.cache.Cache`
            used to cache responses. ``None`` (the default) disables
            caching entirely.
        cacheable_methods: The HTTP methods (case-insensitive) whose
            responses are cached, when ``cache`` is given. Defaults
            to ``{"GET"}``.

    Raises:
        RuntimeError: If the ``httpx`` package is not installed.
        TypeError: If a retry argument or ``cacheable_methods`` has a
            wrong type.
        ValueError: If a retry argument has an invalid value.

    Example:
        ```pycon
        >>> import asyncio
        >>> import httpx
        >>> from persista.http.httpx import AsyncHttpClient
        >>> async def main():
        ...     transport = httpx.MockTransport(lambda request: httpx.Response(200, text="ok"))
        ...     async with httpx.AsyncClient(transport=transport) as httpx_client:
        ...         client = AsyncHttpClient(httpx_client, max_retries=5)
        ...         response = await client.get("https://example.com", timeout=10)
        ...         return response.text
        ...
        >>> asyncio.run(main())
        'ok'

        ```
    """

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        max_retries: int = 3,
        retry_status_codes: Iterable[int] = DEFAULT_RETRY_STATUS_CODES,
        retry_methods: Iterable[str] = IDEMPOTENT_METHODS,
        max_delay: float = DEFAULT_MAX_DELAY,
        cache: Cache | None = None,
        cacheable_methods: Iterable[str] = frozenset({"GET"}),
    ) -> None:
        check_httpx()
        self._policy = RetryPolicy(
            max_retries=max_retries,
            retry_status_codes=retry_status_codes,
            retry_methods=retry_methods,
            max_delay=max_delay,
        )
        self._cache = cache
        self._cacheable_methods = normalize_methods(cacheable_methods, name="cacheable_methods")
        # Created last, so an invalid argument leaves no client open.
        self._owns_client = client is None
        self._client = httpx.AsyncClient() if client is None else client

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the client if the wrapper created it.

        A client given to the constructor is left open. Closing twice
        does nothing.
        """
        if self._owns_client:
            await self._client.aclose()

    async def request(
        self,
        method: str,
        url: httpx.URL | str,
        *,
        max_retries: int | None = None,
        retry_status_codes: Iterable[int] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send an HTTP request, with retries, serving/storing it via
        the cache when enabled for ``method``.

        See :meth:`HttpClient.request`.
        """
        _check_client_is_open(self._client)
        method = method.upper()
        policy = self._policy.replace(
            max_retries=max_retries, retry_status_codes=retry_status_codes
        )
        if kwargs.get("headers") is not None:
            # The headers are read several times (for the cache key and by
            # each attempt), so a one-shot iterable must be materialized.
            kwargs["headers"] = httpx.Headers(kwargs["headers"])
        cache = self._cache
        lookup = None
        if cache is not None and method in self._cacheable_methods:
            lookup = _prepare_cache_lookup(self._client, method, url, kwargs)
        if cache is not None and lookup is not None:
            request, key = lookup
            if (entry := await cache.aget(key)) is not None:
                logger.debug("Serving %s %s from cache", method, redact_url_credentials(url))
                return _entry_to_response(entry, request)

        response = await self._send(method, url, policy, kwargs)
        if cache is not None and lookup is not None and response.is_success:
            await cache.aset(lookup[1], _response_to_entry(response))
        return response

    async def _send(
        self,
        method: str,
        url: httpx.URL | str,
        policy: RetryPolicy,
        kwargs: dict[str, Any],
    ) -> httpx.Response:
        """Send a request until it succeeds or cannot be retried.

        See :meth:`HttpClient._send`.
        """
        max_retries = policy.get_max_retries(method) if _is_replayable_body(kwargs) else 0
        shown_url = redact_url_credentials(url)
        logger.debug("Sending %s %s...", method, shown_url)
        attempt = 0
        while True:
            attempt += 1
            start = time.perf_counter()
            try:
                response = await self._client.request(method, url, **kwargs)
            except httpx.TransportError as error:
                delay = _plan_retry(
                    error,
                    policy=policy,
                    attempt=attempt,
                    max_retries=max_retries,
                    method=method,
                    url=shown_url,
                )
                if delay is None:
                    raise
            else:
                logger.debug(
                    "Response received: HTTP %d (%d bytes) in %.2fs",
                    response.status_code,
                    len(response.content),
                    time.perf_counter() - start,
                )
                delay = _plan_retry(
                    response,
                    policy=policy,
                    attempt=attempt,
                    max_retries=max_retries,
                    method=method,
                    url=shown_url,
                )
                if delay is None:
                    break
            await asyncio.sleep(delay)
        if response.is_error:
            response.raise_for_status()
        return response

    async def get(self, url: httpx.URL | str, **kwargs: Any) -> httpx.Response:
        """Send a ``GET`` request.

        See :meth:`request`.
        """
        return await self.request("GET", url, **kwargs)

    async def post(self, url: httpx.URL | str, **kwargs: Any) -> httpx.Response:
        """Send a ``POST`` request.

        See :meth:`request`.
        """
        return await self.request("POST", url, **kwargs)

    async def put(self, url: httpx.URL | str, **kwargs: Any) -> httpx.Response:
        """Send a ``PUT`` request.

        See :meth:`request`.
        """
        return await self.request("PUT", url, **kwargs)

    async def patch(self, url: httpx.URL | str, **kwargs: Any) -> httpx.Response:
        """Send a ``PATCH`` request.

        See :meth:`request`.
        """
        return await self.request("PATCH", url, **kwargs)

    async def delete(self, url: httpx.URL | str, **kwargs: Any) -> httpx.Response:
        """Send a ``DELETE`` request.

        See :meth:`request`.
        """
        return await self.request("DELETE", url, **kwargs)
