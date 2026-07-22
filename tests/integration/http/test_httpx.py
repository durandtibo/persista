from __future__ import annotations

import pytest

from persista.http.httpx import fetch_response, fetch_response_async
from persista.testing.fixtures import httpx_available, httpx_not_available

REMOTE_URL = "https://jsonplaceholder.typicode.com/todos/1"


############################
#     fetch_response       #
############################


@httpx_available
def test_fetch_response_success_against_remote_url() -> None:
    response = fetch_response(REMOTE_URL, timeout=10)

    assert response.status_code == 200
    assert response.json()["id"] == 1


@httpx_not_available
def test_fetch_response_raises_without_httpx() -> None:
    with pytest.raises(RuntimeError, match=r"'httpx' package is required but not installed."):
        fetch_response("http://127.0.0.1:1")


############################
#   fetch_response_async   #
############################


@httpx_available
async def test_fetch_response_async_success_against_remote_url() -> None:
    response = await fetch_response_async(REMOTE_URL, timeout=10)

    assert response.status_code == 200
    assert response.json()["id"] == 1


@httpx_not_available
async def test_fetch_response_async_raises_without_httpx() -> None:
    with pytest.raises(RuntimeError, match=r"'httpx' package is required but not installed."):
        await fetch_response_async("http://127.0.0.1:1")
