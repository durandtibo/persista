from __future__ import annotations

import pytest

from persista.http.httpx import get_response, get_response_async
from persista.testing.fixtures import httpx_available, httpx_not_available

REMOTE_URL = "https://jsonplaceholder.typicode.com/todos/1"


############################
#     get_response       #
############################


@httpx_available
def test_get_response_success_against_remote_url() -> None:
    response = get_response(REMOTE_URL, timeout=10)

    assert response.status_code == 200
    assert response.json()["id"] == 1


@httpx_not_available
def test_get_response_raises_without_httpx() -> None:
    with pytest.raises(RuntimeError, match=r"'httpx' package is required but not installed."):
        get_response("http://127.0.0.1:1")


############################
#   get_response_async   #
############################


@httpx_available
async def test_get_response_async_success_against_remote_url() -> None:
    response = await get_response_async(REMOTE_URL, timeout=10)

    assert response.status_code == 200
    assert response.json()["id"] == 1


@httpx_not_available
async def test_get_response_async_raises_without_httpx() -> None:
    with pytest.raises(RuntimeError, match=r"'httpx' package is required but not installed."):
        await get_response_async("http://127.0.0.1:1")
