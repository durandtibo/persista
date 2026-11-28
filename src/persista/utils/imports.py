r"""Contain utilities for optional dependencies.

Each optional library has two functions: ``is_<name>_available``, which
indicates if the library is installed, and ``check_<name>``, which
raises an error if it is not. Neither of them imports the library.
"""

from __future__ import annotations

__all__ = [
    "check_duckdb",
    "check_faker",
    "check_httpx",
    "check_lmdb",
    "check_psycopg",
    "check_redis",
    "check_requests",
    "check_rich",
    "check_urllib3",
    "is_duckdb_available",
    "is_faker_available",
    "is_httpx_available",
    "is_lmdb_available",
    "is_psycopg_available",
    "is_redis_available",
    "is_requests_available",
    "is_rich_available",
    "is_urllib3_available",
]

from functools import cache

from coola.utils.imports import package_available, raise_package_missing_error

##################
#     duckdb     #
##################


def check_duckdb() -> None:
    r"""Check if the ``duckdb`` package is installed.

    Raises:
        RuntimeError: if the ``duckdb`` package is not installed.

    Example:
        ```pycon
        >>> from persista.utils.imports import check_duckdb
        >>> check_duckdb()

        ```
    """
    if not is_duckdb_available():
        raise_package_missing_error("duckdb", "duckdb")


@cache
def is_duckdb_available() -> bool:
    r"""Indicate if the ``duckdb`` package is installed or not.

    Returns:
        ``True`` if ``duckdb`` is available otherwise ``False``.

    Example:
        ```pycon
        >>> from persista.utils.imports import is_duckdb_available
        >>> is_duckdb_available()

        ```
    """
    return package_available("duckdb")


#################
#     faker     #
#################


def check_faker() -> None:
    r"""Check if the ``faker`` package is installed.

    Raises:
        RuntimeError: if the ``faker`` package is not installed.

    Example:
        ```pycon
        >>> from persista.utils.imports import check_faker
        >>> check_faker()

        ```
    """
    if not is_faker_available():
        raise_package_missing_error("faker", "faker")


@cache
def is_faker_available() -> bool:
    r"""Indicate if the ``faker`` package is installed or not.

    Returns:
        ``True`` if ``faker`` is available otherwise ``False``.

    Example:
        ```pycon
        >>> from persista.utils.imports import is_faker_available
        >>> is_faker_available()

        ```
    """
    return package_available("faker")


#################
#     httpx     #
#################


def check_httpx() -> None:
    r"""Check if the ``httpx`` package is installed.

    Raises:
        RuntimeError: if the ``httpx`` package is not installed.

    Example:
        ```pycon
        >>> from persista.utils.imports import check_httpx
        >>> check_httpx()

        ```
    """
    if not is_httpx_available():
        raise_package_missing_error("httpx", "httpx")


@cache
def is_httpx_available() -> bool:
    r"""Indicate if the ``httpx`` package is installed or not.

    Returns:
        ``True`` if ``httpx`` is available otherwise ``False``.

    Example:
        ```pycon
        >>> from persista.utils.imports import is_httpx_available
        >>> is_httpx_available()

        ```
    """
    return package_available("httpx")


################
#     lmdb     #
################


def check_lmdb() -> None:
    r"""Check if the ``lmdb`` package is installed.

    Raises:
        RuntimeError: if the ``lmdb`` package is not installed.

    Example:
        ```pycon
        >>> from persista.utils.imports import check_lmdb
        >>> check_lmdb()

        ```
    """
    if not is_lmdb_available():
        raise_package_missing_error("lmdb", "lmdb")


@cache
def is_lmdb_available() -> bool:
    r"""Indicate if the ``lmdb`` package is installed or not.

    Returns:
        ``True`` if ``lmdb`` is available otherwise ``False``.

    Example:
        ```pycon
        >>> from persista.utils.imports import is_lmdb_available
        >>> is_lmdb_available()

        ```
    """
    return package_available("lmdb")


###################
#     psycopg     #
###################


def check_psycopg() -> None:
    r"""Check if the ``psycopg`` package is installed.

    Raises:
        RuntimeError: if the ``psycopg`` package is not installed.

    Example:
        ```pycon
        >>> from persista.utils.imports import check_psycopg
        >>> check_psycopg()

        ```
    """
    if not is_psycopg_available():
        raise_package_missing_error("psycopg", "psycopg[binary]")


@cache
def is_psycopg_available() -> bool:
    r"""Indicate if the ``psycopg`` package is installed or not.

    Returns:
        ``True`` if ``psycopg`` is available otherwise ``False``.

    Example:
        ```pycon
        >>> from persista.utils.imports import is_psycopg_available
        >>> is_psycopg_available()

        ```
    """
    return package_available("psycopg")


#################
#     redis     #
#################


def check_redis() -> None:
    r"""Check if the ``redis`` package is installed.

    Raises:
        RuntimeError: if the ``redis`` package is not installed.

    Example:
        ```pycon
        >>> from persista.utils.imports import check_redis
        >>> check_redis()

        ```
    """
    if not is_redis_available():
        raise_package_missing_error("redis", "redis")


@cache
def is_redis_available() -> bool:
    r"""Indicate if the ``redis`` package is installed or not.

    Returns:
        ``True`` if ``redis`` is available otherwise ``False``.

    Example:
        ```pycon
        >>> from persista.utils.imports import is_redis_available
        >>> is_redis_available()

        ```
    """
    return package_available("redis")


####################
#     requests     #
####################


def check_requests() -> None:
    r"""Check if the ``requests`` package is installed.

    Raises:
        RuntimeError: if the ``requests`` package is not installed.

    Example:
        ```pycon
        >>> from persista.utils.imports import check_requests
        >>> check_requests()

        ```
    """
    if not is_requests_available():
        raise_package_missing_error("requests", "requests")


@cache
def is_requests_available() -> bool:
    r"""Indicate if the ``requests`` package is installed or not.

    Returns:
        ``True`` if ``requests`` is available otherwise ``False``.

    Example:
        ```pycon
        >>> from persista.utils.imports import is_requests_available
        >>> is_requests_available()

        ```
    """
    return package_available("requests")


################
#     rich     #
################


def check_rich() -> None:
    r"""Check if the ``rich`` package is installed.

    Raises:
        RuntimeError: if the ``rich`` package is not installed.

    Example:
        ```pycon
        >>> from persista.utils.imports import check_rich
        >>> check_rich()

        ```
    """
    if not is_rich_available():
        raise_package_missing_error("rich", "rich")


@cache
def is_rich_available() -> bool:
    r"""Indicate if the ``rich`` package is installed or not.

    Returns:
        ``True`` if ``rich`` is available otherwise ``False``.

    Example:
        ```pycon
        >>> from persista.utils.imports import is_rich_available
        >>> is_rich_available()

        ```
    """
    return package_available("rich")


###################
#     urllib3     #
###################


def check_urllib3() -> None:
    r"""Check if the ``urllib3`` package is installed.

    Raises:
        RuntimeError: if the ``urllib3`` package is not installed.

    Example:
        ```pycon
        >>> from persista.utils.imports import check_urllib3
        >>> check_urllib3()

        ```
    """
    if not is_urllib3_available():
        raise_package_missing_error("urllib3", "urllib3")


@cache
def is_urllib3_available() -> bool:
    r"""Indicate if the ``urllib3`` package is installed or not.

    Returns:
        ``True`` if ``urllib3`` is available otherwise ``False``.

    Example:
        ```pycon
        >>> from persista.utils.imports import is_urllib3_available
        >>> is_urllib3_available()

        ```
    """
    return package_available("urllib3")
