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

if is_httpx_available():  # pragma: no cover
    import httpx

if TYPE_CHECKING:
    from persista.cache.cache import Cache

logger: logging.Logger = logging.getLogger(__name__)


def _cache_key(method: str, url: str, kwargs: dict[str, Any]) -> str:
    """Derive a cache key for an HTTP request.

    Args:
        method: The HTTP method, e.g. ``"GET"``.
        url: The full URL being requested.
        kwargs: The request kwargs (e.g. ``params``, ``json``) used to
            derive the key. Values that are not JSON-serializable
            (e.g. an ``auth`` object) are dropped.

    Returns:
        A stable cache key for the request.
    """
    return make_key(f"{method.upper()} {url}", (), kwargs, ignore_non_serializable=True)


def _response_to_entry(response: httpx.Response) -> dict[str, Any]:
    """Convert a response to a JSON-serializable cache entry.

    Args:
        response: The response to convert.

    Returns:
        A dict with the response's status code, headers, and
        base64-encoded content.
    """
    return {
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "content": base64.b64encode(response.content).decode("ascii"),
    }


def _entry_to_response(entry: dict[str, Any]) -> httpx.Response:
    """Reconstruct a response from a cache entry.

    Args:
        entry: A cache entry produced by :func:`_response_to_entry`.

    Returns:
        An :class:`httpx.Response` equivalent to the one that was
        cached.
    """
    return httpx.Response(
        status_code=entry["status_code"],
        headers=entry["headers"],
        content=base64.b64decode(entry["content"]),
    )


class HttpClient:
    """A wrapper around :class:`httpx.Client` with automatic retries and
    optional response caching.

    Retry behavior is delegated to :func:`~persista.http.httpx.send_request`.
    Caching is opt-in: it is only performed when ``cache`` is given, and
    only for methods listed in ``cacheable_methods``. Cached entries store
    the response's status code, headers, and content, so a cache hit
    reconstructs an :class:`httpx.Response` equivalent to the one that
    was cached. Only successful (2xx) responses are cached.

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
        cacheable = cache is not None and method in self._cacheable_methods
        key = _cache_key(method, url, kwargs) if cacheable else None
        if cache is not None and key is not None and (entry := cache.get(key)) is not None:
            logger.debug("Serving %s %s from cache", method, url)
            return _entry_to_response(entry)

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
        if cache is not None and key is not None and response.is_success:
            cache.set(key, _response_to_entry(response))
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
        cacheable = cache is not None and method in self._cacheable_methods
        key = _cache_key(method, url, kwargs) if cacheable else None
        if cache is not None and key is not None and (entry := await cache.aget(key)) is not None:
            logger.debug("Serving %s %s from cache", method, url)
            return _entry_to_response(entry)

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
        if cache is not None and key is not None and response.is_success:
            await cache.aset(key, _response_to_entry(response))
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
