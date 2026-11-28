r"""Provide HTTP helper functions for fetching remote content."""

from __future__ import annotations

__all__ = ["create_session", "fetch_response"]


import logging
import math
import time
from typing import TYPE_CHECKING, Self

from persista.http.retry import (
    DEFAULT_MAX_DELAY,
    DEFAULT_RETRY_STATUS_CODES,
    RetryPolicy,
    parse_retry_after,
)
from persista.utils.imports import (
    check_requests,
    check_urllib3,
    is_requests_available,
    is_urllib3_available,
)
from persista.utils.url import redact_url_credentials

if TYPE_CHECKING or is_requests_available():  # pragma: no cover
    import requests
    from requests.adapters import HTTPAdapter
if TYPE_CHECKING or is_urllib3_available():  # pragma: no cover
    from urllib3.util.retry import Retry
else:
    # The module can be imported without urllib3.
    Retry = object

if TYPE_CHECKING:
    from collections.abc import Iterable
    from types import TracebackType

    from urllib3.connectionpool import ConnectionPool
    from urllib3.response import BaseHTTPResponse

logger: logging.Logger = logging.getLogger(__name__)


class _BoundedRetry(Retry):
    """A :class:`urllib3.util.retry.Retry` that follows the retry and
    delay rules of :mod:`persista.http.retry`.

    Compared with the parent class:

    - the delay of a ``Retry-After`` header is read by
      :func:`~persista.http.retry.parse_retry_after` and limited to
      ``backoff_max``, with every supported version of ``urllib3``;
    - an invalid ``Retry-After`` header is ignored instead of raising;
    - only the status codes of ``status_forcelist`` are retried;
    - a method that is not in ``allowed_methods`` is not retried after
      any error, including a failed connection.
    """

    # urllib3 also retries these statuses when they have a Retry-After
    # header, even if they are not in status_forcelist.
    RETRY_AFTER_STATUS_CODES = frozenset()

    def get_retry_after(self, response: BaseHTTPResponse) -> float | None:
        """Return the delay requested by the ``Retry-After`` header of a
        response.

        Args:
            response: The response.

        Returns:
            The delay in seconds, between ``0`` and ``backoff_max``, or
            ``None`` if there is no valid header.
        """
        delay = parse_retry_after(response.headers.get("Retry-After"))
        return None if delay is None else min(delay, float(self.backoff_max))

    def sleep_for_retry(self, response: BaseHTTPResponse) -> bool:
        """Wait the delay requested by the ``Retry-After`` header of a
        response.

        Unlike the parent method, a delay of ``0`` is respected: it is
        not replaced by the exponential backoff.

        Args:
            response: The response.

        Returns:
            ``True`` if the response has a valid header, otherwise
            ``False``.
        """
        delay = self.get_retry_after(response)
        if delay is None:
            return False
        time.sleep(delay)
        return True

    def get_backoff_time(self) -> float:
        """Return the exponential backoff delay before the next attempt.

        Returns:
            The delay in seconds, between ``0`` and ``backoff_max``, also
            when the number of attempts is too large for the computation.
        """
        try:
            return super().get_backoff_time()
        except OverflowError:
            return float(self.backoff_max) if self.backoff_factor else 0.0

    def increment(
        self,
        method: str | None = None,
        url: str | None = None,
        response: BaseHTTPResponse | None = None,
        error: Exception | None = None,
        _pool: ConnectionPool | None = None,
        _stacktrace: TracebackType | None = None,
    ) -> Self:
        """Count a failed attempt.

        See :meth:`urllib3.util.retry.Retry.increment`. An error of a
        request whose method is not retried exhausts the retries.

        Raises:
            urllib3.exceptions.MaxRetryError: If the request is not sent
                again.
        """
        retry = self
        if (
            error is not None
            and method is not None
            and self.allowed_methods is not None
            and method.upper() not in self.allowed_methods
        ):
            retry = self.new(total=0)
        return super(_BoundedRetry, retry).increment(
            method=method,
            url=url,
            response=response,
            error=error,
            _pool=_pool,
            _stacktrace=_stacktrace,
        )


def create_session(
    max_retries: int = 3,
    retry_status_codes: Iterable[int] | None = None,
    backoff_factor: float = 1,
    *,
    max_delay: float = DEFAULT_MAX_DELAY,
) -> requests.Session:
    """Create a :class:`requests.Session` with a retry adapter mounted.

    Configures retries for transient failures on both ``https://`` and
    ``http://`` connections. Useful for sharing a single session across
    multiple requests for connection pooling. The session has no cache.

    Only ``GET`` requests are retried: after a response whose status is in
    ``retry_status_codes``, or after a connection or read error. The delay
    is the one of the ``Retry-After`` header of the response (a number of
    seconds or an HTTP date). Without a valid header, there is no delay
    before the first retry, then
    ``backoff_factor * (2 ** (retry_number - 1))`` seconds. The delay is
    always between ``0`` and ``max_delay``. After the last attempt, the
    session returns the response, or raises the error of
    ``requests``.

    A streamed body that can only be read once (e.g. a generator) is not
    detected: do not send one with a ``GET`` request.

    Args:
        max_retries: Maximum number of retry attempts on transient failures.
            Defaults to 3. Set to 0 to disable retries.
        retry_status_codes: HTTP status codes that should trigger a retry.
            Pass ``None`` to use the default set (429, 500, 502, 503, 504).
        backoff_factor: Multiplier used to compute the delay between retry
            attempts. Defaults to 1.
        max_delay: The maximum delay between two attempts, in seconds.
            Defaults to 60.

    Returns:
        A configured :class:`requests.Session` with retry adapters mounted
        on both ``https://`` and ``http://``.

    Raises:
        RuntimeError: if the ``requests`` or ``urllib3`` package is not
            installed.
        TypeError: If an argument has a wrong type.
        ValueError: If ``max_retries`` is negative, a status code is not
            between 100 and 599, or ``backoff_factor`` or ``max_delay`` is
            negative, infinite or ``NaN``.

    Example:
        ```pycon
        >>> from persista.http.requests import create_session
        >>> session = create_session(max_retries=5, max_delay=30)

        ```
    """
    check_requests()
    check_urllib3()
    policy = RetryPolicy(
        max_retries=max_retries,
        retry_status_codes=(
            DEFAULT_RETRY_STATUS_CODES if retry_status_codes is None else retry_status_codes
        ),
        retry_methods={"GET"},
        max_delay=max_delay,
    )
    if not math.isfinite(backoff_factor) or backoff_factor < 0:
        msg = f"backoff_factor must be a finite non-negative number, got {backoff_factor}"
        raise ValueError(msg)
    retry_strategy = _BoundedRetry(
        total=policy.max_retries,
        backoff_factor=backoff_factor,
        backoff_max=policy.max_delay,
        status_forcelist=policy.retry_status_codes,
        allowed_methods=policy.retry_methods,
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
    *,
    timeout: float = 30,
    max_retries: int = 3,
    retry_status_codes: Iterable[int] | None = None,
    backoff_factor: float = 1,
    max_delay: float = DEFAULT_MAX_DELAY,
    headers: dict[str, str] | None = None,
    session: requests.Session | None = None,
) -> requests.Response:
    """Fetch a URL with a ``GET`` request, with automatic retries and
    timeout.

    The retries are those of :func:`create_session`: after a connection or
    read error, or a response whose status is in ``retry_status_codes``,
    with a delay between ``0`` and ``max_delay`` that follows the
    ``Retry-After`` header of the response.

    If a ``session`` is provided it is used directly, allowing callers to
    share a single session across multiple calls for connection pooling.
    Otherwise a new session is created and closed automatically.

    The messages of the errors of ``requests`` are not rewritten: they can
    contain the URL, including the credentials that it has.

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
        max_delay: The maximum delay between two attempts, in seconds.
            Defaults to 60. Ignored when ``session`` is provided.
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
        TypeError: If a retry argument has a wrong type.
        ValueError: If a retry argument has an invalid value.
        requests.exceptions.ConnectTimeout: If the connection of all the
            attempts exceeds ``timeout`` seconds.
        requests.exceptions.HTTPError: On 4xx/5xx responses that are not
            retried (e.g. 404, 403).
        requests.exceptions.ConnectionError: If the host is unreachable
            after all retries are exhausted.
        requests.exceptions.RequestException: For any other unrecoverable
            network failure.

    Example:
        ```pycon
        >>> from persista.http.requests import fetch_response
        >>> html = fetch_response(  # doctest: +SKIP
        ...     "https://jsonplaceholder.typicode.com/todos/1",
        ...     timeout=10,
        ...     max_retries=5,
        ... )

        ```
    """
    check_requests()
    logger.debug("Fetching %s...", redact_url_credentials(url))

    own_session = session is None
    if own_session:
        session = create_session(
            max_retries=max_retries,
            retry_status_codes=retry_status_codes,
            backoff_factor=backoff_factor,
            max_delay=max_delay,
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
