from __future__ import annotations

import pytest

from persista.http.httpx import (
    delete_response,
    delete_response_async,
    get_response,
    get_response_async,
    patch_response,
    patch_response_async,
    post_response,
    post_response_async,
    put_response,
    put_response_async,
)
from persista.testing.fixtures import httpx_available, httpx_not_available

REMOTE_URL = "https://jsonplaceholder.typicode.com/todos/1"
REMOTE_COLLECTION_URL = "https://jsonplaceholder.typicode.com/todos"


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


############################
#      post_response       #
############################


@httpx_available
def test_post_response_success_against_remote_url() -> None:
    response = post_response(
        REMOTE_COLLECTION_URL, timeout=10, json={"title": "example", "completed": False}
    )

    assert response.status_code == 201
    assert response.json()["title"] == "example"


@httpx_not_available
def test_post_response_raises_without_httpx() -> None:
    with pytest.raises(RuntimeError, match=r"'httpx' package is required but not installed."):
        post_response("http://127.0.0.1:1")


############################
#    post_response_async   #
############################


@httpx_available
async def test_post_response_async_success_against_remote_url() -> None:
    response = await post_response_async(
        REMOTE_COLLECTION_URL, timeout=10, json={"title": "example", "completed": False}
    )

    assert response.status_code == 201
    assert response.json()["title"] == "example"


@httpx_not_available
async def test_post_response_async_raises_without_httpx() -> None:
    with pytest.raises(RuntimeError, match=r"'httpx' package is required but not installed."):
        await post_response_async("http://127.0.0.1:1")


############################
#       put_response        #
############################


@httpx_available
def test_put_response_success_against_remote_url() -> None:
    response = put_response(REMOTE_URL, timeout=10, json={"id": 1, "title": "updated"})

    assert response.status_code == 200
    assert response.json()["title"] == "updated"


@httpx_not_available
def test_put_response_raises_without_httpx() -> None:
    with pytest.raises(RuntimeError, match=r"'httpx' package is required but not installed."):
        put_response("http://127.0.0.1:1")


############################
#    put_response_async    #
############################


@httpx_available
async def test_put_response_async_success_against_remote_url() -> None:
    response = await put_response_async(REMOTE_URL, timeout=10, json={"id": 1, "title": "updated"})

    assert response.status_code == 200
    assert response.json()["title"] == "updated"


@httpx_not_available
async def test_put_response_async_raises_without_httpx() -> None:
    with pytest.raises(RuntimeError, match=r"'httpx' package is required but not installed."):
        await put_response_async("http://127.0.0.1:1")


############################
#      patch_response       #
############################


@httpx_available
def test_patch_response_success_against_remote_url() -> None:
    response = patch_response(REMOTE_URL, timeout=10, json={"title": "patched"})

    assert response.status_code == 200
    assert response.json()["title"] == "patched"


@httpx_not_available
def test_patch_response_raises_without_httpx() -> None:
    with pytest.raises(RuntimeError, match=r"'httpx' package is required but not installed."):
        patch_response("http://127.0.0.1:1")


############################
#   patch_response_async    #
############################


@httpx_available
async def test_patch_response_async_success_against_remote_url() -> None:
    response = await patch_response_async(REMOTE_URL, timeout=10, json={"title": "patched"})

    assert response.status_code == 200
    assert response.json()["title"] == "patched"


@httpx_not_available
async def test_patch_response_async_raises_without_httpx() -> None:
    with pytest.raises(RuntimeError, match=r"'httpx' package is required but not installed."):
        await patch_response_async("http://127.0.0.1:1")


############################
#      delete_response      #
############################


@httpx_available
def test_delete_response_success_against_remote_url() -> None:
    response = delete_response(REMOTE_URL, timeout=10)

    assert response.status_code == 200


@httpx_not_available
def test_delete_response_raises_without_httpx() -> None:
    with pytest.raises(RuntimeError, match=r"'httpx' package is required but not installed."):
        delete_response("http://127.0.0.1:1")


############################
#   delete_response_async   #
############################


@httpx_available
async def test_delete_response_async_success_against_remote_url() -> None:
    response = await delete_response_async(REMOTE_URL, timeout=10)

    assert response.status_code == 200


@httpx_not_available
async def test_delete_response_async_raises_without_httpx() -> None:
    with pytest.raises(RuntimeError, match=r"'httpx' package is required but not installed."):
        await delete_response_async("http://127.0.0.1:1")
