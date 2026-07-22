r"""Provide HTTP helper functions for fetching remote content using
``httpx``."""

from __future__ import annotations

__all__ = ["get_response", "get_response_async", "send_request", "send_request_async"]


import asyncio
import logging
import time
from typing import Any

from persista.utils.imports import check_httpx, is_httpx_available

if is_httpx_available():  # pragma: no cover
    import httpx

logger: logging.Logger = logging.getLogger(__name__)

DEFAULT_RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def get_response(
    url: str,
    timeout: int = 30,
    max_retries: int = 3,
    retry_status_codes: set[int] | frozenset[int] = DEFAULT_RETRY_STATUS_CODES,
    client: httpx.Client | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """Fetch a URL with automatic retries and timeout.

    This is a convenience wrapper around :func:`send_request` for the
    common case of issuing a ``GET`` request. See :func:`send_request`
    for full documentation of the retry and backoff behavior.

    Args:
        url: The full URL to fetch.
        timeout: Request timeout in seconds per attempt. Defaults to 30.
            Ignored when ``client`` is provided.
        max_retries: Maximum number of retry attempts on transient failures.
            Defaults to 3. Set to 0 to disable retries.
        retry_status_codes: The HTTP status codes that trigger a retry.
            Defaults to ``{429, 500, 502, 503, 504}``.
        client: An optional :class:`httpx.Client` to reuse. When ``None``,
            a new client is created and closed after the request completes.
        **kwargs: Additional keyword arguments forwarded to
            :meth:`httpx.Client.request`, e.g. ``headers``, ``params``.

    Returns:
        The :class:`httpx.Response` object for the completed request.

    Raises:
        RuntimeError: if the ``httpx`` package is not installed.
        httpx.HTTPStatusError: On 4xx/5xx responses that are not retried
            (e.g. 404, 403).
        httpx.TransportError: If the host is unreachable or the request
            times out after all retries are exhausted.

    Example:
        ```pycon
        >>> from persista.http.httpx import get_response
        >>> response = get_response(  # doctest: +SKIP
        ...     "https://jsonplaceholder.typicode.com/todos/1",
        ...     timeout=10,
        ...     max_retries=5,
        ... )

        ```
    """
    return send_request(
        method="GET",
        url=url,
        timeout=timeout,
        max_retries=max_retries,
        retry_status_codes=retry_status_codes,
        client=client,
        **kwargs,
    )


def send_request(
    method: str,
    url: str,
    timeout: int = 30,
    max_retries: int = 3,
    retry_status_codes: set[int] | frozenset[int] = DEFAULT_RETRY_STATUS_CODES,
    client: httpx.Client | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """Send an HTTP request with automatic retries and timeout.

    Uses exponential backoff to handle transient network failures, connection
    timeouts, and 5xx server errors. Successive retry delays are 1s, 2s, 4s,
    and so on up to ``max_retries`` attempts.

    If a ``client`` is provided it is used directly, allowing callers to
    share a single client across multiple calls for connection pooling.
    Otherwise a new client is created and closed automatically.

    Args:
        method: The HTTP method to use, e.g. ``"GET"``, ``"POST"``,
            ``"PUT"``, ``"PATCH"``, ``"DELETE"``.
        url: The full URL to send the request to.
        timeout: Request timeout in seconds per attempt. Defaults to 30.
            Ignored when ``client`` is provided.
        max_retries: Maximum number of retry attempts on transient failures.
            Defaults to 3. Set to 0 to disable retries.
        retry_status_codes: The HTTP status codes that trigger a retry.
            Defaults to ``{429, 500, 502, 503, 504}``.
        client: An optional :class:`httpx.Client` to reuse. When ``None``,
            a new client is created and closed after the request completes.
        **kwargs: Additional keyword arguments forwarded to
            :meth:`httpx.Client.request`, e.g. ``headers``, ``json``,
            ``data``, ``params``, ``content``, ``files``.

    Returns:
        The :class:`httpx.Response` object for the completed request.

    Raises:
        RuntimeError: if the ``httpx`` package is not installed.
        httpx.HTTPStatusError: On 4xx/5xx responses that are not retried
            (e.g. 404, 403).
        httpx.TransportError: If the host is unreachable or the request
            times out after all retries are exhausted.

    Example:
        ```pycon
        >>> from persista.http.httpx import send_request
        >>> response = send_request(  # doctest: +SKIP
        ...     "POST",
        ...     "https://jsonplaceholder.typicode.com/todos",
        ...     json={"title": "example"},
        ...     timeout=10,
        ...     max_retries=5,
        ... )

        ```
    """
    check_httpx()
    logger.debug("Sending %s %s...", method, url)

    own_client = client is None
    active_client = client if client is not None else httpx.Client(timeout=timeout)

    try:
        attempt = 0
        while True:
            try:
                start = time.perf_counter()
                response = active_client.request(method, url, timeout=timeout, **kwargs)
                elapsed = time.perf_counter() - start
                logger.debug(
                    "Response received: HTTP %d (%d bytes) in %.2fs",
                    response.status_code,
                    len(response.content),
                    elapsed,
                )
                if response.status_code in retry_status_codes and attempt < max_retries:
                    attempt += 1
                    delay = _get_retry_delay(response, attempt)
                    logger.debug(
                        "Retrying %s %s in %.2fs (attempt %d/%d, HTTP %d)",
                        method,
                        url,
                        delay,
                        attempt,
                        max_retries,
                        response.status_code,
                    )
                    time.sleep(delay)
                    continue
            except httpx.TransportError:
                if attempt >= max_retries:
                    raise
                delay = 2**attempt
                attempt += 1
                logger.debug(
                    "Retrying %s %s in %.2fs (attempt %d/%d) after transport error",
                    method,
                    url,
                    delay,
                    attempt,
                    max_retries,
                )
                time.sleep(delay)
            else:
                response.raise_for_status()
                return response
    finally:
        if own_client:
            active_client.close()


async def get_response_async(
    url: str,
    timeout: int = 30,
    max_retries: int = 3,
    retry_status_codes: set[int] | frozenset[int] = DEFAULT_RETRY_STATUS_CODES,
    client: httpx.AsyncClient | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """Fetch a URL asynchronously with automatic retries and timeout.

    This is a convenience wrapper around :func:`send_request_async` for the
    common case of issuing a ``GET`` request. See :func:`send_request_async`
    for full documentation of the retry and backoff behavior.

    Args:
        url: The full URL to fetch.
        timeout: Request timeout in seconds per attempt. Defaults to 30.
            Ignored when ``client`` is provided.
        max_retries: Maximum number of retry attempts on transient failures.
            Defaults to 3. Set to 0 to disable retries.
        retry_status_codes: The HTTP status codes that trigger a retry.
            Defaults to ``{429, 500, 502, 503, 504}``.
        client: An optional :class:`httpx.AsyncClient` to reuse. When
            ``None``, a new client is created and closed after the request
            completes.
        **kwargs: Additional keyword arguments forwarded to
            :meth:`httpx.AsyncClient.request`, e.g. ``headers``, ``params``.

    Returns:
        The :class:`httpx.Response` object for the completed request.

    Raises:
        RuntimeError: if the ``httpx`` package is not installed.
        httpx.HTTPStatusError: On 4xx/5xx responses that are not retried
            (e.g. 404, 403).
        httpx.TransportError: If the host is unreachable or the request
            times out after all retries are exhausted.

    Example:
        ```pycon
        >>> import asyncio
        >>> from persista.http.httpx import get_response_async
        >>> response = asyncio.run(  # doctest: +SKIP
        ...     get_response_async(
        ...         "https://jsonplaceholder.typicode.com/todos/1",
        ...         timeout=10,
        ...         max_retries=5,
        ...     )
        ... )

        ```
    """
    return await send_request_async(
        method="GET",
        url=url,
        timeout=timeout,
        max_retries=max_retries,
        retry_status_codes=retry_status_codes,
        client=client,
        **kwargs,
    )


async def send_request_async(
    method: str,
    url: str,
    timeout: int = 30,
    max_retries: int = 3,
    retry_status_codes: set[int] | frozenset[int] = DEFAULT_RETRY_STATUS_CODES,
    client: httpx.AsyncClient | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """Send an HTTP request asynchronously with automatic retries and
    timeout.

    Uses exponential backoff to handle transient network failures, connection
    timeouts, and 5xx server errors. Successive retry delays are 1s, 2s, 4s,
    and so on up to ``max_retries`` attempts.

    If a ``client`` is provided it is used directly, allowing callers to
    share a single client across multiple calls for connection pooling.
    Otherwise a new client is created and closed automatically.

    Args:
        method: The HTTP method to use, e.g. ``"GET"``, ``"POST"``,
            ``"PUT"``, ``"PATCH"``, ``"DELETE"``.
        url: The full URL to send the request to.
        timeout: Request timeout in seconds per attempt. Defaults to 30.
            Ignored when ``client`` is provided.
        max_retries: Maximum number of retry attempts on transient failures.
            Defaults to 3. Set to 0 to disable retries.
        retry_status_codes: The HTTP status codes that trigger a retry.
            Defaults to ``{429, 500, 502, 503, 504}``.
        client: An optional :class:`httpx.AsyncClient` to reuse. When
            ``None``, a new client is created and closed after the request
            completes.
        **kwargs: Additional keyword arguments forwarded to
            :meth:`httpx.AsyncClient.request`, e.g. ``headers``, ``json``,
            ``data``, ``params``, ``content``, ``files``.

    Returns:
        The :class:`httpx.Response` object for the completed request.

    Raises:
        RuntimeError: if the ``httpx`` package is not installed.
        httpx.HTTPStatusError: On 4xx/5xx responses that are not retried
            (e.g. 404, 403).
        httpx.TransportError: If the host is unreachable or the request
            times out after all retries are exhausted.

    Example:
        ```pycon
        >>> import asyncio
        >>> from persista.http.httpx import send_request_async
        >>> response = asyncio.run(  # doctest: +SKIP
        ...     send_request_async(
        ...         "POST",
        ...         "https://jsonplaceholder.typicode.com/todos",
        ...         json={"title": "example"},
        ...         timeout=10,
        ...         max_retries=5,
        ...     )
        ... )

        ```
    """
    check_httpx()
    logger.debug("Sending %s %s...", method, url)

    own_client = client is None
    active_client = client if client is not None else httpx.AsyncClient(timeout=timeout)

    try:
        attempt = 0
        while True:
            try:
                start = time.perf_counter()
                response = await active_client.request(method, url, timeout=timeout, **kwargs)
                elapsed = time.perf_counter() - start
                logger.debug(
                    "Response received: HTTP %d (%d bytes) in %.2fs",
                    response.status_code,
                    len(response.content),
                    elapsed,
                )
                if response.status_code in retry_status_codes and attempt < max_retries:
                    attempt += 1
                    delay = _get_retry_delay(response, attempt)
                    logger.debug(
                        "Retrying %s %s in %.2fs (attempt %d/%d, HTTP %d)",
                        method,
                        url,
                        delay,
                        attempt,
                        max_retries,
                        response.status_code,
                    )
                    await asyncio.sleep(delay)
                    continue
            except httpx.TransportError:
                if attempt >= max_retries:
                    raise
                delay = 2**attempt
                attempt += 1
                logger.debug(
                    "Retrying %s %s in %.2fs (attempt %d/%d) after transport error",
                    method,
                    url,
                    delay,
                    attempt,
                    max_retries,
                )
                await asyncio.sleep(delay)
            else:
                response.raise_for_status()
                return response
    finally:
        if own_client:
            await active_client.aclose()


def _get_retry_delay(response: httpx.Response, attempt: int) -> float:
    """Compute the delay in seconds before the next retry attempt.

    Honors the ``Retry-After`` response header when present, otherwise
    falls back to exponential backoff.

    Args:
        response: The response that triggered the retry.
        attempt: The retry attempt number (1-indexed).

    Returns:
        The delay in seconds before the next attempt.
    """
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return float(retry_after)
        except ValueError:
            pass
    return float(2 ** (attempt - 1))
