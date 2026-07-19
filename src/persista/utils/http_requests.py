r"""Provide HTTP helper functions for fetching remote content."""

from __future__ import annotations

__all__ = ["create_session", "fetch_response"]


import logging
import time

from persista.utils.imports import (
    check_requests,
    check_urllib3,
    is_requests_available,
    is_urllib3_available,
)

if is_requests_available():  # pragma: no cover
    import requests
    from requests.adapters import HTTPAdapter
if is_urllib3_available():  # pragma: no cover
    from urllib3.util.retry import Retry

logger: logging.Logger = logging.getLogger(__name__)


def create_session(
    max_retries: int = 3,
    retry_status_codes: list[int] | None = None,
    backoff_factor: float = 1,
) -> requests.Session:
    """Create a :class:`requests.Session` with a retry adapter mounted.

    Configures exponential backoff retries for transient failures on both
    ``https://`` and ``http://`` connections. Useful for sharing a single
    session across multiple requests for connection pooling.

    Args:
        max_retries: Maximum number of retry attempts on transient failures
            with exponential backoff. Defaults to 3.
        retry_status_codes: HTTP status codes that should trigger a retry.
            Pass ``None`` to use the default set (429, 500, 502, 503, 504).
        backoff_factor: Multiplier used to compute the delay between retry
            attempts. Successive delays are
            ``backoff_factor * (2 ** (retry_number - 1))`` seconds.
            Defaults to 1.

    Returns:
        A configured :class:`requests.Session` with retry adapters mounted
        on both ``https://`` and ``http://``.

    Example:
        ```pycon
        >>> from persista.utils.http_requests import create_session
        >>> session = create_session(max_retries=5)

        ```
    """
    check_requests()
    check_urllib3()
    if retry_status_codes is None:
        retry_status_codes = [429, 500, 502, 503, 504]
    retry_strategy = Retry(
        total=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=retry_status_codes,
        allowed_methods=["GET"],
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def fetch_response(
    url: str,
    timeout: int = 30,
    max_retries: int = 3,
    retry_status_codes: list[int] | None = None,
    backoff_factor: float = 1,
    headers: dict[str, str] | None = None,
    session: requests.Session | None = None,
) -> requests.Response:
    """Fetch a URL with automatic retries and timeout.

    Uses exponential backoff to handle transient network failures, connection
    timeouts, and 5xx server errors. Successive retry delays are
    ``backoff_factor`` * 1s, 2s, 4s, and so on up to ``max_retries`` attempts.

    If a ``session`` is provided it is used directly, allowing callers to
    share a single session across multiple calls for connection pooling.
    Otherwise a new session is created and closed automatically.

    Args:
        url: The full URL to fetch.
        timeout: Request timeout in seconds per attempt. Defaults to 30.
        max_retries: Maximum number of retry attempts on transient failures.
            Defaults to 3. Set to 0 to disable retries. Ignored when
            ``session`` is provided.
        retry_status_codes: HTTP status codes that should trigger a retry.
            Pass ``None`` to use the default set (429, 500, 502, 503, 504).
            Ignored when ``session`` is provided.
        backoff_factor: Multiplier used to compute the delay between retry
            attempts. Defaults to 1. Ignored when ``session`` is provided.
        headers: HTTP headers to include in the request. Pass ``None`` to
            send no custom headers (the default). Pass an empty dict to
            send no headers explicitly.
        session: An optional :class:`requests.Session` to reuse. When
            ``None``, a new session is created via :func:`create_session`
            and closed after the request completes.

    Returns:
        The :class:`requests.Response` object for the completed request.

    Raises:
        RuntimeError: if the ``requests`` package is not installed.
        requests.exceptions.ConnectTimeout: If all retry attempts exceed
            ``timeout`` seconds.
        requests.exceptions.HTTPError: On 4xx/5xx responses that are not
            retried (e.g. 404, 403).
        requests.exceptions.ConnectionError: If the host is unreachable
            after all retries are exhausted.
        requests.exceptions.RequestException: For any other unrecoverable
            network failure.

    Example:
        ```pycon
        >>> from persista.utils.http_requests import fetch_response
        >>> html = fetch_response(  # doctest: +SKIP
        ...     "https://jsonplaceholder.typicode.com/todos/1",
        ...     timeout=10,
        ...     max_retries=5,
        ... )

        ```
    """
    check_requests()
    logger.debug("Fetching %s...", url)

    own_session = session is None
    if own_session:
        session = create_session(
            max_retries=max_retries,
            retry_status_codes=retry_status_codes,
            backoff_factor=backoff_factor,
        )

    try:
        start = time.perf_counter()
        response = session.get(url, headers=headers, timeout=timeout)
        elapsed = time.perf_counter() - start
        logger.debug(
            "Response received: HTTP %d (%d bytes) in %.2fs",
            response.status_code,
            len(response.content),
            elapsed,
        )
        response.raise_for_status()
        return response
    finally:
        if own_session:
            session.close()
