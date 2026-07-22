from __future__ import annotations

from persista.http.client import AsyncHttpClient, HttpClient
from persista.testing.fixtures import httpx_available

REMOTE_URL = "https://jsonplaceholder.typicode.com/todos/1"
REMOTE_COLLECTION_URL = "https://jsonplaceholder.typicode.com/todos"


############################
#       HttpClient        #
############################


@httpx_available
def test_http_client_get_success_against_remote_url() -> None:
    with HttpClient(timeout=10) as client:
        response = client.get(REMOTE_URL)

    assert response.status_code == 200
    assert response.json()["id"] == 1


@httpx_available
def test_http_client_post_success_against_remote_url() -> None:
    with HttpClient(timeout=10) as client:
        response = client.post(REMOTE_COLLECTION_URL, json={"title": "example", "completed": False})

    assert response.status_code == 201
    assert response.json()["title"] == "example"


@httpx_available
def test_http_client_put_success_against_remote_url() -> None:
    with HttpClient(timeout=10) as client:
        response = client.put(REMOTE_URL, json={"id": 1, "title": "updated"})

    assert response.status_code == 200
    assert response.json()["title"] == "updated"


@httpx_available
def test_http_client_patch_success_against_remote_url() -> None:
    with HttpClient(timeout=10) as client:
        response = client.patch(REMOTE_URL, json={"title": "patched"})

    assert response.status_code == 200
    assert response.json()["title"] == "patched"


@httpx_available
def test_http_client_delete_success_against_remote_url() -> None:
    with HttpClient(timeout=10) as client:
        response = client.delete(REMOTE_URL)

    assert response.status_code == 200


############################
#     AsyncHttpClient     #
############################


@httpx_available
async def test_async_http_client_get_success_against_remote_url() -> None:
    async with AsyncHttpClient(timeout=10) as client:
        response = await client.get(REMOTE_URL)

    assert response.status_code == 200
    assert response.json()["id"] == 1


@httpx_available
async def test_async_http_client_post_success_against_remote_url() -> None:
    async with AsyncHttpClient(timeout=10) as client:
        response = await client.post(
            REMOTE_COLLECTION_URL, json={"title": "example", "completed": False}
        )

    assert response.status_code == 201
    assert response.json()["title"] == "example"


@httpx_available
async def test_async_http_client_put_success_against_remote_url() -> None:
    async with AsyncHttpClient(timeout=10) as client:
        response = await client.put(REMOTE_URL, json={"id": 1, "title": "updated"})

    assert response.status_code == 200
    assert response.json()["title"] == "updated"


@httpx_available
async def test_async_http_client_patch_success_against_remote_url() -> None:
    async with AsyncHttpClient(timeout=10) as client:
        response = await client.patch(REMOTE_URL, json={"title": "patched"})

    assert response.status_code == 200
    assert response.json()["title"] == "patched"


@httpx_available
async def test_async_http_client_delete_success_against_remote_url() -> None:
    async with AsyncHttpClient(timeout=10) as client:
        response = await client.delete(REMOTE_URL)

    assert response.status_code == 200
