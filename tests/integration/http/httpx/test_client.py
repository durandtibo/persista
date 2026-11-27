from __future__ import annotations

import gzip
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import pytest

from persista.cache import Cache
from persista.http.httpx import AsyncHttpClient, HttpClient
from persista.testing.fixtures import httpx_available
from persista.utils.imports import is_httpx_available

if TYPE_CHECKING:
    from collections.abc import Iterator

if is_httpx_available():
    import httpx

REMOTE_URL = "https://jsonplaceholder.typicode.com/todos/1"
REMOTE_COLLECTION_URL = "https://jsonplaceholder.typicode.com/todos"


############################
#       HttpClient        #
############################


@httpx_available
def test_http_client_get_success_against_remote_url() -> None:
    with httpx.Client(timeout=10) as httpx_client:
        client = HttpClient(client=httpx_client)
        response = client.get(REMOTE_URL)

    assert response.status_code == 200
    assert response.json()["id"] == 1


@httpx_available
def test_http_client_post_success_against_remote_url() -> None:
    with httpx.Client(timeout=10) as httpx_client:
        client = HttpClient(client=httpx_client)
        response = client.post(REMOTE_COLLECTION_URL, json={"title": "example", "completed": False})

    assert response.status_code == 201
    assert response.json()["title"] == "example"


@httpx_available
def test_http_client_put_success_against_remote_url() -> None:
    with httpx.Client(timeout=10) as httpx_client:
        client = HttpClient(client=httpx_client)
        response = client.put(REMOTE_URL, json={"id": 1, "title": "updated"})

    assert response.status_code == 200
    assert response.json()["title"] == "updated"


@httpx_available
def test_http_client_patch_success_against_remote_url() -> None:
    with httpx.Client(timeout=10) as httpx_client:
        client = HttpClient(client=httpx_client)
        response = client.patch(REMOTE_URL, json={"title": "patched"})

    assert response.status_code == 200
    assert response.json()["title"] == "patched"


@httpx_available
def test_http_client_delete_success_against_remote_url() -> None:
    with httpx.Client(timeout=10) as httpx_client:
        client = HttpClient(client=httpx_client)
        response = client.delete(REMOTE_URL)

    assert response.status_code == 200


############################
#     AsyncHttpClient     #
############################


@httpx_available
async def test_async_http_client_get_success_against_remote_url() -> None:
    async with httpx.AsyncClient(timeout=10) as httpx_client:
        client = AsyncHttpClient(client=httpx_client)
        response = await client.get(REMOTE_URL)

    assert response.status_code == 200
    assert response.json()["id"] == 1


@httpx_available
async def test_async_http_client_post_success_against_remote_url() -> None:
    async with httpx.AsyncClient(timeout=10) as httpx_client:
        client = AsyncHttpClient(client=httpx_client)
        response = await client.post(
            REMOTE_COLLECTION_URL, json={"title": "example", "completed": False}
        )

    assert response.status_code == 201
    assert response.json()["title"] == "example"


@httpx_available
async def test_async_http_client_put_success_against_remote_url() -> None:
    async with httpx.AsyncClient(timeout=10) as httpx_client:
        client = AsyncHttpClient(client=httpx_client)
        response = await client.put(REMOTE_URL, json={"id": 1, "title": "updated"})

    assert response.status_code == 200
    assert response.json()["title"] == "updated"


@httpx_available
async def test_async_http_client_patch_success_against_remote_url() -> None:
    async with httpx.AsyncClient(timeout=10) as httpx_client:
        client = AsyncHttpClient(client=httpx_client)
        response = await client.patch(REMOTE_URL, json={"title": "patched"})

    assert response.status_code == 200
    assert response.json()["title"] == "patched"


@httpx_available
async def test_async_http_client_delete_success_against_remote_url() -> None:
    async with httpx.AsyncClient(timeout=10) as httpx_client:
        client = AsyncHttpClient(client=httpx_client)
        response = await client.delete(REMOTE_URL)

    assert response.status_code == 200


#######################################
#     Caching with a local server     #
#######################################


class EchoHandler(BaseHTTPRequestHandler):
    """Answer with a gzip JSON description of the request.

    The ``count`` field is the number of requests received by the
    server, so two equal responses show that the second one comes from
    the cache.
    """

    count = 0
    lock = threading.Lock()

    def do_GET(self) -> None:
        self._answer()

    def do_POST(self) -> None:
        self._answer()

    def log_message(self, *args: object) -> None:
        pass

    def _answer(self) -> None:
        """Send the description of the request."""
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        with EchoHandler.lock:
            EchoHandler.count += 1
            count = EchoHandler.count
        content = gzip.compress(
            json.dumps(
                {
                    "count": count,
                    "path": self.path,
                    "authorization": self.headers.get("authorization"),
                    "body": body.decode(),
                }
            ).encode()
        )
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-encoding", "gzip")
        self.send_header("content-length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


@pytest.fixture
def server_url() -> Iterator[str]:
    EchoHandler.count = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), EchoHandler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.fixture
def cache() -> Iterator[Cache]:
    with Cache() as cache:
        yield cache


def _client(**kwargs: object) -> httpx.Client:
    # trust_env=False so that a proxy of the environment is not used.
    return httpx.Client(trust_env=False, timeout=10, **kwargs)


def _async_client(**kwargs: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(trust_env=False, timeout=10, **kwargs)


@httpx_available
def test_http_client_cache_does_not_share_response_between_users(
    server_url: str, cache: Cache
) -> None:
    with (
        _client(headers={"Authorization": "Bearer alice"}) as alice,
        _client(headers={"Authorization": "Bearer bob"}) as bob,
    ):
        HttpClient(alice, cache=cache).get(server_url)
        response = HttpClient(bob, cache=cache).get(server_url)

    assert response.json()["authorization"] == "Bearer bob"


@httpx_available
def test_http_client_cache_uses_base_url(server_url: str, cache: Cache) -> None:
    with (
        _client(base_url=f"{server_url}/a") as first,
        _client(base_url=f"{server_url}/b") as second,
    ):
        HttpClient(first, cache=cache).get("/items")
        response = HttpClient(second, cache=cache).get("/items")

    assert response.json()["path"] == "/b/items"


@httpx_available
def test_http_client_cache_uses_query_params_object(server_url: str, cache: Cache) -> None:
    with _client() as httpx_client:
        client = HttpClient(httpx_client, cache=cache)
        client.get(server_url, params=httpx.QueryParams({"p": 1}))
        response = client.get(server_url, params=httpx.QueryParams({"p": 2}))

    assert response.json()["path"] == "/?p=2"


@httpx_available
def test_http_client_cache_uses_bytes_body(server_url: str, cache: Cache) -> None:
    with _client() as httpx_client:
        client = HttpClient(httpx_client, cache=cache, cacheable_methods={"POST"})
        client.post(server_url, content=b"a")
        response = client.post(server_url, content=b"b")

    assert response.json()["body"] == "b"


@httpx_available
@pytest.mark.parametrize("password", ["secret", ""])
def test_http_client_cache_skips_authenticated_request(
    server_url: str, cache: Cache, password: str
) -> None:
    with _client(auth=("alice", password)) as httpx_client:
        client = HttpClient(httpx_client, cache=cache)
        client.get(server_url)
        response = client.get(server_url)

    assert response.json()["count"] == 2


@httpx_available
def test_http_client_cache_hit_of_gzip_response(server_url: str, cache: Cache) -> None:
    with _client() as httpx_client:
        client = HttpClient(httpx_client, cache=cache)
        client.get(server_url)
        response = client.get(server_url)

    assert response.json()["count"] == 1


@httpx_available
def test_http_client_cache_hit_raise_for_status(server_url: str, cache: Cache) -> None:
    with _client() as httpx_client:
        client = HttpClient(httpx_client, cache=cache)
        client.get(server_url)
        response = client.get(server_url)

    assert response.raise_for_status() is response


@httpx_available
async def test_async_http_client_cache_does_not_share_response_between_users(
    server_url: str, cache: Cache
) -> None:
    async with (
        _async_client(headers={"Authorization": "Bearer alice"}) as alice,
        _async_client(headers={"Authorization": "Bearer bob"}) as bob,
    ):
        await AsyncHttpClient(alice, cache=cache).get(server_url)
        response = await AsyncHttpClient(bob, cache=cache).get(server_url)

    assert response.json()["authorization"] == "Bearer bob"


@httpx_available
async def test_async_http_client_cache_uses_query_params_object(
    server_url: str, cache: Cache
) -> None:
    async with _async_client() as httpx_client:
        client = AsyncHttpClient(httpx_client, cache=cache)
        await client.get(server_url, params=httpx.QueryParams({"p": 1}))
        response = await client.get(server_url, params=httpx.QueryParams({"p": 2}))

    assert response.json()["path"] == "/?p=2"


@httpx_available
async def test_async_http_client_cache_skips_authenticated_request(
    server_url: str, cache: Cache
) -> None:
    async with _async_client() as httpx_client:
        client = AsyncHttpClient(httpx_client, cache=cache)
        await client.get(server_url, auth=("alice", "secret"))
        response = await client.get(server_url, auth=("alice", "secret"))

    assert response.json()["count"] == 2


@httpx_available
async def test_async_http_client_cache_hit_of_gzip_response(server_url: str, cache: Cache) -> None:
    async with _async_client() as httpx_client:
        client = AsyncHttpClient(httpx_client, cache=cache)
        await client.get(server_url)
        response = await client.get(server_url)

    assert response.raise_for_status().json()["count"] == 1
