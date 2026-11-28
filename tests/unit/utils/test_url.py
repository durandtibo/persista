from __future__ import annotations

import pytest

from persista.utils.url import redact_url_credentials

############################################
#     Tests for redact_url_credentials     #
############################################


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://user:s3cret@example.com/a?b=1#c", "https://example.com/a?b=1#c"),
        ("https://s3cret@example.com", "https://example.com"),
        ("https://user:s3@cret@example.com:8080/a", "https://example.com:8080/a"),
        ("http://user:s3cret@[::1]:80/", "http://[::1]:80/"),
        ("//user:s3cret@example.com/a", "//example.com/a"),
    ],
)
def test_redact_url_credentials(url: str, expected: str) -> None:
    assert redact_url_credentials(url) == expected


@pytest.mark.parametrize(
    "url",
    ["", "https://example.com/a?b=1", "/users/@me", "items", "https://example.com/@user"],
)
def test_redact_url_credentials_without_credentials(url: str) -> None:
    assert redact_url_credentials(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "https://user:s3cret@[bad/",
        # A character that NFKC normalization turns into "a/c".
        f"https://user:s3cret@ho{chr(0x2100)}st/",
    ],
)
def test_redact_url_credentials_invalid_url(url: str) -> None:
    assert redact_url_credentials(url) == "<hidden URL>"


class URL:
    r"""An object whose ``str`` is a URL."""

    def __str__(self) -> str:
        return "https://user:s3cret@example.com"


def test_redact_url_credentials_object() -> None:
    assert redact_url_credentials(URL()) == "https://example.com"
