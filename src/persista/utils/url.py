r"""Contain URL utility functions."""

from __future__ import annotations

__all__ = ["redact_url_credentials"]

from urllib.parse import urlsplit, urlunsplit


def redact_url_credentials(url: object) -> str:
    r"""Return a URL without its credentials, to show it in a log
    message.

    Args:
        url: A URL, absolute or relative, as a ``str`` or an object whose
            ``str`` is the URL.

    Returns:
        The URL without the username and the password of its location, or
        ``"<hidden URL>"`` if it cannot be parsed. The path and the query
        are kept.

    Example:
        ```pycon
        >>> from persista.utils.url import redact_url_credentials
        >>> redact_url_credentials("https://user:secret@example.com/items?page=2")
        'https://example.com/items?page=2'

        ```
    """
    try:
        parts = urlsplit(str(url))
    except ValueError:
        # The URL is not shown: its location can contain a password.
        return "<hidden URL>"
    if "@" not in parts.netloc:
        return str(url)
    return urlunsplit(parts._replace(netloc=parts.netloc.rpartition("@")[2]))
