r"""Provide class-based HTTP clients with automatic retries and optional
response caching, built on ``httpx``."""

from __future__ import annotations

__all__ = ["AsyncHttpClient", "HttpClient"]

import base64
import logging
from typing import TYPE_CHECKING, Any

from persista.cache.utils import make_key
from persista.http.httpx.method import (
    DEFAULT_RETRY_STATUS_CODES,
    send_request,
    send_request_async,
)
from persista.utils.imports import check_httpx, is_httpx_available

if TYPE_CHECKING or is_httpx_available():  # pragma: no cover
    import httpx

if TYPE_CHECKING:
    from persista.cache.cache import Cache

logger: logging.Logger = logging.getLogger(__name__)

# Headers that describe the transfer of a content, not the decoded content.
_TRANSFER_HEADERS = frozenset({"content-encoding", "content-length", "transfer-encoding"})


def _prepare_cache_lookup(
    client: httpx.Client | httpx.AsyncClient,
    method: str,
    url: str,
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
    # latin-1 maps every byte to one character, so no information is lost.
    headers = [
        (name.lower().decode("latin-1"), value.decode("latin-1"))
        for name, value in request.headers.raw
    ]
    body = base64.b64encode(request.content).decode("ascii")
    return make_key(
        "persista.http.httpx",
        (request.method, str(request.url), headers, body, follow_redirects),
        {},
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


class HttpClient:
    """A wrapper around :class:`httpx.Client` with automatic retries and
    optional response caching.

    Retry behavior is delegated to :func:`~persista.http.httpx.send_request`.
    Caching is opt-in: it is only performed when ``cache`` is given, and
    only for methods listed in ``cacheable_methods``. Only successful
    (2xx) responses are cached.

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
        timeout: Default request timeout in seconds per attempt.
        max_retries: Default maximum number of retry attempts on
            transient failures.
        retry_status_codes: The HTTP status codes that trigger a
            retry by default.
        cache: An optional :class:`~persista.cache.cache.Cache` used
            to cache responses. ``None`` (the default) disables
            caching entirely.
        cacheable_methods: The HTTP methods (case-insensitive) whose
            responses are cached, when ``cache`` is given. Defaults
            to ``{"GET"}``.
        client: The :class:`httpx.Client` to wrap. The caller owns
            its lifecycle (creation and closing).

    Example:
        ```pycon
        >>> import httpx
        >>> from persista.http.httpx import HttpClient
        >>> with httpx.Client() as httpx_client:  # doctest: +SKIP
        ...     client = HttpClient(client=httpx_client)
        ...     response = client.get("https://jsonplaceholder.typicode.com/todos/1")
        ...

        ```
    """

    def __init__(
        self,
        client: httpx.Client,
        *,
        timeout: int = 30,
        max_retries: int = 3,
        retry_status_codes: set[int] | frozenset[int] = DEFAULT_RETRY_STATUS_CODES,
        cache: Cache | None = None,
        cacheable_methods: set[str] | frozenset[str] = frozenset({"GET"}),
    ) -> None:
        check_httpx()
        self._client = client
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_status_codes = retry_status_codes
        self._cache = cache
        self._cacheable_methods = frozenset(m.upper() for m in cacheable_methods)

    def request(
        self,
        method: str,
        url: str,
        *,
        timeout: int | None = None,
        max_retries: int | None = None,
        retry_status_codes: set[int] | frozenset[int] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send an HTTP request, serving/storing it via the cache when
        enabled for ``method``.

        Args:
            method: The HTTP method to use, e.g. ``"GET"``.
            url: The full URL to send the request to.
            timeout: Per-call timeout override. Defaults to the value
                given at construction.
            max_retries: Per-call max-retries override. Defaults to
                the value given at construction.
            retry_status_codes: Per-call retry-status-codes override.
                Defaults to the value given at construction.
            **kwargs: Additional keyword arguments forwarded to
                :meth:`httpx.Client.request`, e.g. ``headers``,
                ``json``, ``params``.

        Returns:
            The :class:`httpx.Response` object for the completed
            request, from the cache if it was a hit.
        """
        method = method.upper()
        cache = self._cache
        lookup = None
        if cache is not None and method in self._cacheable_methods:
            if "headers" in kwargs:
                # The headers are read twice (for the key and to send the
                # request), so a one-shot iterable must be materialized.
                kwargs["headers"] = httpx.Headers(kwargs["headers"])
            lookup = _prepare_cache_lookup(self._client, method, url, kwargs)
        if cache is not None and lookup is not None:
            request, key = lookup
            if (entry := cache.get(key)) is not None:
                logger.debug("Serving %s %s from cache", method, url)
                return _entry_to_response(entry, request)

        response = send_request(
            method=method,
            url=url,
            timeout=timeout if timeout is not None else self._timeout,
            max_retries=max_retries if max_retries is not None else self._max_retries,
            retry_status_codes=(
                retry_status_codes if retry_status_codes is not None else self._retry_status_codes
            ),
            client=self._client,
            **kwargs,
        )
        if cache is not None and lookup is not None and response.is_success:
            cache.set(lookup[1], _response_to_entry(response))
        return response

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send a ``GET`` request.

        See :meth:`request`.
        """
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send a ``POST`` request.

        See :meth:`request`.
        """
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send a ``PUT`` request.

        See :meth:`request`.
        """
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send a ``PATCH`` request.

        See :meth:`request`.
        """
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send a ``DELETE`` request.

        See :meth:`request`.
        """
        return self.request("DELETE", url, **kwargs)


class AsyncHttpClient:
    """A wrapper around :class:`httpx.AsyncClient` with automatic
    retries and optional response caching.

    This is the async counterpart of :class:`HttpClient`. See its
    docstring for the retry and caching behavior; the only difference
    is that the wrapped client is an :class:`httpx.AsyncClient` and
    caching is done through :class:`~persista.cache.cache.Cache`'s
    async methods (``aget``/``aset``).

    Args:
        timeout: Default request timeout in seconds per attempt.
        max_retries: Default maximum number of retry attempts on
            transient failures.
        retry_status_codes: The HTTP status codes that trigger a
            retry by default.
        cache: An optional :class:`~persista.cache.cache.Cache`
            used to cache responses. ``None`` (the default) disables
            caching entirely.
        cacheable_methods: The HTTP methods (case-insensitive) whose
            responses are cached, when ``cache`` is given. Defaults
            to ``{"GET"}``.
        client: The :class:`httpx.AsyncClient` to wrap. The caller
            owns its lifecycle (creation and closing).

    Example:
        ```pycon
        >>> import asyncio
        >>> import httpx
        >>> from persista.http.httpx import AsyncHttpClient
        >>> async def main():  # doctest: +SKIP
        ...     async with httpx.AsyncClient() as httpx_client:
        ...         client = AsyncHttpClient(client=httpx_client)
        ...         response = await client.get("https://jsonplaceholder.typicode.com/todos/1")
        ...
        >>> asyncio.run(main())  # doctest: +SKIP

        ```
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        timeout: int = 30,
        max_retries: int = 3,
        retry_status_codes: set[int] | frozenset[int] = DEFAULT_RETRY_STATUS_CODES,
        cache: Cache | None = None,
        cacheable_methods: set[str] | frozenset[str] = frozenset({"GET"}),
    ) -> None:
        check_httpx()
        self._client = client
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_status_codes = retry_status_codes
        self._cache = cache
        self._cacheable_methods = frozenset(m.upper() for m in cacheable_methods)

    async def request(
        self,
        method: str,
        url: str,
        *,
        timeout: int | None = None,
        max_retries: int | None = None,
        retry_status_codes: set[int] | frozenset[int] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send an HTTP request, serving/storing it via the cache when
        enabled for ``method``.

        See :meth:`HttpClient.request`.
        """
        method = method.upper()
        cache = self._cache
        lookup = None
        if cache is not None and method in self._cacheable_methods:
            if "headers" in kwargs:
                # The headers are read twice (for the key and to send the
                # request), so a one-shot iterable must be materialized.
                kwargs["headers"] = httpx.Headers(kwargs["headers"])
            lookup = _prepare_cache_lookup(self._client, method, url, kwargs)
        if cache is not None and lookup is not None:
            request, key = lookup
            if (entry := await cache.aget(key)) is not None:
                logger.debug("Serving %s %s from cache", method, url)
                return _entry_to_response(entry, request)

        response = await send_request_async(
            method=method,
            url=url,
            timeout=timeout if timeout is not None else self._timeout,
            max_retries=max_retries if max_retries is not None else self._max_retries,
            retry_status_codes=(
                retry_status_codes if retry_status_codes is not None else self._retry_status_codes
            ),
            client=self._client,
            **kwargs,
        )
        if cache is not None and lookup is not None and response.is_success:
            await cache.aset(lookup[1], _response_to_entry(response))
        return response

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send a ``GET`` request.

        See :meth:`request`.
        """
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send a ``POST`` request.

        See :meth:`request`.
        """
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send a ``PUT`` request.

        See :meth:`request`.
        """
        return await self.request("PUT", url, **kwargs)

    async def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send a ``PATCH`` request.

        See :meth:`request`.
        """
        return await self.request("PATCH", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send a ``DELETE`` request.

        See :meth:`request`.
        """
        return await self.request("DELETE", url, **kwargs)
