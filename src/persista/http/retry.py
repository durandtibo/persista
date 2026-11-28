r"""Contain the retry policy of the HTTP helpers.

The module does not depend on an HTTP library: the ``httpx`` clients and
the ``requests`` helpers share its rules.
"""

from __future__ import annotations

__all__ = [
    "DEFAULT_MAX_DELAY",
    "DEFAULT_RETRY_STATUS_CODES",
    "IDEMPOTENT_METHODS",
    "RetryPolicy",
    "normalize_methods",
    "normalize_status_codes",
    "parse_retry_after",
    "validate_max_delay",
    "validate_max_retries",
]

import math
import re
import time
from collections.abc import Iterable
from datetime import UTC
from email.utils import parsedate_to_datetime
from numbers import Real

DEFAULT_RETRY_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
"""The HTTP status codes that are retried by default."""

IDEMPOTENT_METHODS: frozenset[str] = frozenset({"DELETE", "GET", "HEAD", "OPTIONS", "PUT", "TRACE"})
"""The idempotent HTTP methods (RFC 9110), retried by default."""

DEFAULT_MAX_DELAY: float = 60.0
"""The default maximum delay between two attempts, in seconds."""

# The largest exponent of 2 that is a finite float.
_MAX_EXPONENT = 1023


def parse_retry_after(value: str | None, *, now: float | None = None) -> float | None:
    r"""Return the delay requested by a ``Retry-After`` header.

    The header is a number of seconds or an HTTP date (RFC 9110). A date
    without a time zone is in UTC.

    Args:
        value: The value of the header, or ``None`` if the response has
            no such header.
        now: The current time, in seconds since the epoch, used to turn a
            date into a delay. ``None`` (the default) uses
            :func:`time.time`.

    Returns:
        The delay in seconds, ``0.0`` for a negative number or a date in
        the past, and possibly infinity for a huge number. ``None`` if
        there is no header or if it is not a number or a date (including
        ``NaN``). The delay has no maximum: see
        :meth:`RetryPolicy.get_delay`.

    Example:
        ```pycon
        >>> from persista.http.retry import parse_retry_after
        >>> parse_retry_after("120")
        120.0
        >>> parse_retry_after("-1")
        0.0
        >>> parse_retry_after("Sun, 06 Nov 1994 08:49:37 GMT", now=784111770.0)
        7.0
        >>> parse_retry_after("soon") is None
        True

        ```
    """
    if value is None:
        return None
    value = value.strip()
    # A number is checked first: a date is never a valid number.
    if re.fullmatch(r"[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+|inf(inity)?)", value, re.IGNORECASE):
        return max(0.0, float(value))
    try:
        date = parsedate_to_datetime(value)
    except (ValueError, OverflowError):
        return None
    if date.tzinfo is None:
        date = date.replace(tzinfo=UTC)
    return max(0.0, date.timestamp() - (time.time() if now is None else now))


class RetryPolicy:
    r"""Define when a failed HTTP request is sent again, and after which
    delay.

    A request is retried only if its method is in ``retry_methods``. By
    default these are the idempotent methods, so a ``POST`` or a
    ``PATCH`` request, which the server could apply twice, is not
    retried. The delay before the retry ``n`` (starting at 1) is the one
    of the ``Retry-After`` header of the response, or
    ``2 ** (n - 1)`` seconds, and is always between ``0`` and
    ``max_delay``.

    Args:
        max_retries: The maximum number of retries of a request, so a
            request is sent at most ``max_retries + 1`` times. ``0``
            disables the retries.
        retry_status_codes: The HTTP status codes of the responses that
            are retried.
        retry_methods: The HTTP methods (case-insensitive) that are
            retried. The collection replaces the default one: to retry
            ``POST`` too, pass ``IDEMPOTENT_METHODS | {"POST"}``.
        max_delay: The maximum delay between two attempts, in seconds.
            It also limits the delay requested by a ``Retry-After``
            header.

    Raises:
        TypeError: If ``max_retries`` is not an ``int``,
            ``retry_status_codes`` is not a collection of ``int``,
            ``retry_methods`` is not a collection of ``str``, or
            ``max_delay`` is not a real number.
        ValueError: If ``max_retries`` is negative, a status code is not
            between 100 and 599, or ``max_delay`` is negative, infinite
            or ``NaN``.

    Example:
        ```pycon
        >>> from persista.http.retry import RetryPolicy
        >>> policy = RetryPolicy(max_retries=5, max_delay=10)
        >>> policy.get_max_retries("GET")
        5
        >>> policy.get_max_retries("POST")
        0
        >>> [policy.get_delay(attempt) for attempt in range(1, 6)]
        [1.0, 2.0, 4.0, 8.0, 10.0]
        >>> policy.get_delay(1, retry_after="3600")
        10.0

        ```
    """

    def __init__(
        self,
        *,
        max_retries: int = 3,
        retry_status_codes: Iterable[int] = DEFAULT_RETRY_STATUS_CODES,
        retry_methods: Iterable[str] = IDEMPOTENT_METHODS,
        max_delay: float = DEFAULT_MAX_DELAY,
    ) -> None:
        validate_max_retries(max_retries)
        validate_max_delay(max_delay)
        self.max_retries = max_retries
        self.retry_status_codes = normalize_status_codes(retry_status_codes)
        self.retry_methods = normalize_methods(retry_methods, name="retry_methods")
        self.max_delay = float(max_delay)

    def __repr__(self) -> str:
        return (
            f"{type(self).__qualname__}(max_retries={self.max_retries}, "
            f"retry_status_codes={sorted(self.retry_status_codes)}, "
            f"retry_methods={sorted(self.retry_methods)}, max_delay={self.max_delay})"
        )

    def replace(
        self,
        *,
        max_retries: int | None = None,
        retry_status_codes: Iterable[int] | None = None,
    ) -> RetryPolicy:
        r"""Return a policy that differs from this one by the given
        values.

        Args:
            max_retries: The new maximum number of retries, or ``None``
                to keep the one of this policy.
            retry_status_codes: The new status codes that are retried, or
                ``None`` to keep those of this policy.

        Returns:
            A new policy, or this one if both arguments are ``None``.

        Raises:
            TypeError: If an argument has a wrong type.
            ValueError: If an argument has an invalid value.
        """
        if max_retries is None and retry_status_codes is None:
            return self
        return RetryPolicy(
            max_retries=self.max_retries if max_retries is None else max_retries,
            retry_status_codes=(
                self.retry_status_codes if retry_status_codes is None else retry_status_codes
            ),
            retry_methods=self.retry_methods,
            max_delay=self.max_delay,
        )

    def get_max_retries(self, method: str) -> int:
        r"""Return the maximum number of retries of a request.

        Args:
            method: The HTTP method of the request (case-insensitive).

        Returns:
            ``max_retries`` if the method is retried, otherwise ``0``.
        """
        return self.max_retries if method.upper() in self.retry_methods else 0

    def get_delay(self, attempt: int, *, retry_after: str | None = None) -> float:
        r"""Return the delay to wait before a retry.

        Args:
            attempt: The number of the retry, starting at 1.
            retry_after: The value of the ``Retry-After`` header of the
                response, or ``None`` if there is no response or no such
                header.

        Returns:
            The delay of the header (see :func:`parse_retry_after`), or
            ``2 ** (attempt - 1)`` if there is no valid header, limited to
            ``max_delay``. In seconds, never negative.

        Raises:
            ValueError: If ``attempt`` is lower than 1.
        """
        if attempt < 1:
            msg = f"attempt must be a positive integer, got {attempt}"
            raise ValueError(msg)
        delay = parse_retry_after(retry_after)
        if delay is None:
            delay = 2.0 ** min(attempt - 1, _MAX_EXPONENT)
        return min(delay, self.max_delay)


def validate_max_retries(max_retries: int) -> None:
    r"""Validate a maximum number of retries.

    Args:
        max_retries: The value to validate.

    Raises:
        TypeError: If ``max_retries`` is not an ``int``.
        ValueError: If ``max_retries`` is negative.

    Example:
        ```pycon
        >>> from persista.http.retry import validate_max_retries
        >>> validate_max_retries(3)

        ```
    """
    if isinstance(max_retries, bool) or not isinstance(max_retries, int):
        msg = f"max_retries must be an int, got {type(max_retries).__name__}"
        raise TypeError(msg)
    if max_retries < 0:
        msg = f"max_retries must be a non-negative integer, got {max_retries}"
        raise ValueError(msg)


def validate_max_delay(max_delay: float) -> None:
    r"""Validate a maximum delay between two attempts.

    Args:
        max_delay: The value to validate, in seconds.

    Raises:
        TypeError: If ``max_delay`` is not a real number.
        ValueError: If ``max_delay`` is negative, infinite or ``NaN``.

    Example:
        ```pycon
        >>> from persista.http.retry import validate_max_delay
        >>> validate_max_delay(60.0)

        ```
    """
    if isinstance(max_delay, bool) or not isinstance(max_delay, Real):
        msg = f"max_delay must be a number, got {type(max_delay).__name__}"
        raise TypeError(msg)
    if not math.isfinite(max_delay) or max_delay < 0:
        msg = f"max_delay must be a finite non-negative number, got {max_delay}"
        raise ValueError(msg)


def normalize_status_codes(status_codes: Iterable[int]) -> frozenset[int]:
    r"""Validate a collection of HTTP status codes.

    Args:
        status_codes: The status codes. An iterable is consumed once.

    Returns:
        The status codes as a ``frozenset``.

    Raises:
        TypeError: If ``status_codes`` is not an iterable of ``int``.
        ValueError: If a status code is not between 100 and 599.

    Example:
        ```pycon
        >>> from persista.http.retry import normalize_status_codes
        >>> sorted(normalize_status_codes([503, 429, 503]))
        [429, 503]

        ```
    """
    if not isinstance(status_codes, Iterable):
        msg = f"retry_status_codes must be a collection of int, got {status_codes!r}"
        raise TypeError(msg)
    codes = list(status_codes)
    for code in codes:
        if isinstance(code, bool) or not isinstance(code, int):
            msg = f"retry_status_codes must be a collection of int, got the item {code!r}"
            raise TypeError(msg)
        if not 100 <= code <= 599:
            msg = f"An HTTP status code must be between 100 and 599, got {code}"
            raise ValueError(msg)
    return frozenset(codes)


def normalize_methods(methods: Iterable[str], *, name: str) -> frozenset[str]:
    r"""Validate a collection of HTTP methods and convert them to upper
    case.

    Args:
        methods: The HTTP methods. An iterable is consumed once.
        name: The name of the argument, shown in the error messages.

    Returns:
        The methods in upper case, as a ``frozenset``.

    Raises:
        TypeError: If ``methods`` is a ``str`` (a collection with one
            method is expected) or is not an iterable of ``str``.

    Example:
        ```pycon
        >>> from persista.http.retry import normalize_methods
        >>> sorted(normalize_methods(["get", "Post"], name="retry_methods"))
        ['GET', 'POST']

        ```
    """
    if isinstance(methods, str) or not isinstance(methods, Iterable):
        msg = f"{name} must be a collection of str, got {methods!r}"
        raise TypeError(msg)
    items = list(methods)
    for method in items:
        if not isinstance(method, str):
            msg = f"{name} must be a collection of str, got the item {method!r}"
            raise TypeError(msg)
    return frozenset(method.upper() for method in items)
