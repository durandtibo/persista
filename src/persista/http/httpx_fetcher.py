r"""Provide context objects that wrap ``httpx`` clients, optionally
adding response caching."""

from __future__ import annotations

__all__ = ["BaseFetcher", "CachedFetcher", "Fetcher"]


import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from persista.cache import Cache, make_key
from persista.http.httpx import DEFAULT_RETRY_STATUS_CODES, fetch_response

if TYPE_CHECKING:
    import httpx


logger: logging.Logger = logging.getLogger(__name__)


class BaseFetcher(ABC):
    """Abstract base class for objects that manage an ``httpx`` client
    used to fetch remote content."""

    @abstractmethod
    def fetch_response(
        self,
        url: str,
        timeout: int = 30,
        max_retries: int = 3,
        headers: dict[str, str] | None = None,
        retry_status_codes: set[int] | frozenset[int] = DEFAULT_RETRY_STATUS_CODES,
    ) -> httpx.Response:
        """Fetch a URL with automatic retries and timeout.

        Args:
            url: The full URL to fetch.
            timeout: Request timeout in seconds per attempt.
            max_retries: Maximum number of retry attempts on transient
                failures. Set to 0 to disable retries.
            headers: HTTP headers to include in the request. Pass
                ``None`` to send no custom headers.
            retry_status_codes: The HTTP status codes that trigger a
                retry.

        Returns:
            The :class:`httpx.Response` object for the completed
            request.
        """


class Fetcher(BaseFetcher):
    """Fetch remote content using a shared ``httpx.Client``.

    Args:
        client: The :class:`httpx.Client` used by default for
            :meth:`fetch_response` calls that do not pass their own
            ``client``.
    """

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def fetch_response(
        self,
        url: str,
        timeout: int = 30,
        max_retries: int = 3,
        headers: dict[str, str] | None = None,
        retry_status_codes: set[int] | frozenset[int] = DEFAULT_RETRY_STATUS_CODES,
    ) -> httpx.Response:
        return fetch_response(
            url=url,
            timeout=timeout,
            max_retries=max_retries,
            headers=headers,
            retry_status_codes=retry_status_codes,
            client=self._client,
        )


class CachedFetcher(BaseFetcher):
    """Fetch remote content using a shared ``httpx.Client``, caching
    responses keyed by the request parameters.

    Args:
        client: The :class:`httpx.Client` used by default for
            :meth:`fetch_response` calls that do not pass their own
            ``client``.
        cache: The cache used to store and retrieve responses.
        strategy: The serialization strategy used to compute the
            cache key from the request parameters. See
            :func:`~persista.cache.make_key`.
        ignore_non_serializable: If ``True``, request parameters that
            are not serializable with ``strategy`` are dropped before
            computing the cache key, instead of raising an error. See
            :func:`~persista.cache.make_key`.
    """

    def __init__(
        self,
        client: httpx.Client,
        cache: Cache,
        strategy: str = "json",
        ignore_non_serializable: bool = False,
    ) -> None:
        self._client = client
        self._cache = cache
        self._strategy = strategy
        self._ignore_non_serializable = ignore_non_serializable

    def fetch_response(
        self,
        url: str,
        timeout: int = 30,
        max_retries: int = 3,
        headers: dict[str, str] | None = None,
        retry_status_codes: set[int] | frozenset[int] = DEFAULT_RETRY_STATUS_CODES,
    ) -> httpx.Response:
        kwargs = {
            "url": url,
            "timeout": timeout,
            "max_retries": max_retries,
            "headers": headers,
            "retry_status_codes": retry_status_codes,
        }
        key = make_key(
            "",
            args=(),
            kwargs=kwargs | {"retry_status_codes": sorted(retry_status_codes)},
            strategy=self._strategy,
            ignore_non_serializable=self._ignore_non_serializable,
        )
        return self._cache.get_or_compute(
            key,
            fn=fetch_response,
            args=(),
            kwargs=kwargs | {"client": self._client},
        )
