from __future__ import annotations

import gzip
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import pytest

from persista.cache import Cache
from persista.http.httpx import AsyncHttpClient, HttpClient
from persista.testing.fixtures import httpx_available, httpx_not_available
from persista.utils.imports import is_httpx_available
from tests.integration.http.server_helpers import DROP, STALL, Answer, run_server

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

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


#######################################
#     Retries with a local server     #
#######################################


def _unused_port() -> int:
    """Return a port of the local host on which nothing listens."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


UNAVAILABLE = Answer(503, {"retry-after": "0"})


@httpx_not_available
@pytest.mark.parametrize("cls", [HttpClient, AsyncHttpClient])
def test_http_client_raises_without_httpx(cls: type) -> None:
    with pytest.raises(RuntimeError, match=r"'httpx' package is required but not installed."):
        cls()


@httpx_available
def test_http_client_own_client() -> None:
    with run_server(Answer()) as server, HttpClient() as client:
        response = client.get(server.url)

    assert response.text == "ok"


@httpx_available
def test_http_client_retries_unavailable_server() -> None:
    with run_server(UNAVAILABLE, Answer()) as server, _client() as httpx_client:
        HttpClient(httpx_client).get(server.url)

    assert server.methods == ["GET", "GET"]


@httpx_available
@pytest.mark.parametrize(
    "retry_after",
    [
        pytest.param("-1", id="negative"),
        pytest.param("9" * 1000, id="huge"),
        pytest.param("Fri, 31 Dec 9999 23:59:59 GMT", id="future-date"),
        pytest.param("Sun, 06 Nov 1994 08:49:37 GMT", id="past-date"),
        pytest.param("soon", id="garbage"),
    ],
)
def test_http_client_bounded_retry_after(retry_after: str) -> None:
    answers = (Answer(503, {"retry-after": retry_after}), Answer())
    with run_server(*answers) as server, _client() as httpx_client:
        start = time.monotonic()
        response = HttpClient(httpx_client, max_delay=0.01).get(server.url)

    assert (response.status_code, server.methods) == (200, ["GET", "GET"])
    assert time.monotonic() - start < 5


@httpx_available
@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_http_client_does_not_retry_not_idempotent_method(method: str) -> None:
    with run_server(UNAVAILABLE) as server, _client() as httpx_client:
        client = HttpClient(httpx_client)
        with pytest.raises(httpx.HTTPStatusError, match=r"503 Service Unavailable"):
            client.request(method, server.url, content=b"a")

    assert server.methods == [method]


@httpx_available
def test_http_client_retries_added_method_with_same_body() -> None:
    with run_server(UNAVAILABLE, Answer()) as server, _client() as httpx_client:
        HttpClient(httpx_client, retry_methods={"POST"}).post(server.url, json={"a": 1})

    assert server.bodies == [b'{"a":1}', b'{"a":1}']


@httpx_available
def test_http_client_does_not_resend_streaming_body() -> None:
    with run_server(UNAVAILABLE, Answer()) as server, _client() as httpx_client:
        client = HttpClient(httpx_client)
        with pytest.raises(httpx.HTTPStatusError, match=r"503"):
            client.put(server.url, content=iter([b"a", b"b"]))

    assert server.bodies == [b"ab"]


@httpx_available
def test_http_client_timeout_with_given_client() -> None:
    with run_server(STALL) as server, _client() as httpx_client:
        client = HttpClient(httpx_client, max_retries=0)
        start = time.monotonic()
        with pytest.raises(httpx.ReadTimeout, match=r"timed out"):
            client.get(server.url, timeout=0.05)

        # The timeout of the client is 10 seconds.
        assert time.monotonic() - start < 5


@httpx_available
def test_http_client_retries_after_timeout() -> None:
    with run_server(STALL, Answer()) as server, _client() as httpx_client:
        response = HttpClient(httpx_client, max_delay=0).get(server.url, timeout=0.2)

    assert (response.status_code, server.methods) == (200, ["GET", "GET"])


@httpx_available
def test_http_client_retries_dropped_connection() -> None:
    with run_server(DROP, Answer()) as server, _client() as httpx_client:
        response = HttpClient(httpx_client, max_delay=0).get(server.url)

    assert (response.status_code, server.methods) == (200, ["GET", "GET"])


@httpx_available
def test_http_client_does_not_retry_post_after_dropped_connection() -> None:
    with run_server(DROP, Answer()) as server, _client() as httpx_client:
        client = HttpClient(httpx_client, max_delay=0)
        with pytest.raises(httpx.RemoteProtocolError, match=r"disconnected"):
            client.post(server.url)

    assert server.methods == ["POST"]


@httpx_available
def test_http_client_retries_refused_connection() -> None:
    attempts: list[httpx.Request] = []
    with _client(event_hooks={"request": [attempts.append]}) as httpx_client:
        client = HttpClient(httpx_client, max_retries=2, max_delay=0)
        with pytest.raises(httpx.ConnectError, match=r"refused"):
            client.get(f"http://127.0.0.1:{_unused_port()}")

    assert len(attempts) == 3


@httpx_available
def test_http_client_digest_auth_with_retry() -> None:
    challenge = Answer(401, {"www-authenticate": 'Digest realm="r", nonce="n", qop="auth"'})
    answers = (challenge, UNAVAILABLE, challenge, Answer())
    with run_server(*answers) as server, _client(auth=httpx.DigestAuth("a", "b")) as httpx_client:
        response = HttpClient(httpx_client).get(server.url)

    assert response.status_code == 200
    assert server.requests[-1][1]["authorization"].startswith("Digest ")


@httpx_available
async def test_async_http_client_own_client() -> None:
    with run_server(Answer()) as server:
        async with AsyncHttpClient() as client:
            response = await client.get(server.url)

    assert response.text == "ok"


@httpx_available
async def test_async_http_client_bounded_retry_after() -> None:
    with run_server(Answer(503, {"retry-after": "-1"}), Answer()) as server:
        async with _async_client() as httpx_client:
            await AsyncHttpClient(httpx_client).get(server.url)

    assert server.methods == ["GET", "GET"]


@httpx_available
async def test_async_http_client_does_not_retry_post() -> None:
    with run_server(UNAVAILABLE) as server:
        async with _async_client() as httpx_client:
            client = AsyncHttpClient(httpx_client)
            with pytest.raises(httpx.HTTPStatusError, match=r"503"):
                await client.post(server.url, content=b"a")

    assert server.methods == ["POST"]


@httpx_available
async def test_async_http_client_does_not_resend_streaming_body() -> None:
    async def body() -> AsyncIterator[bytes]:
        yield b"a"
        yield b"b"

    with run_server(UNAVAILABLE, Answer()) as server:
        async with _async_client() as httpx_client:
            client = AsyncHttpClient(httpx_client)
            with pytest.raises(httpx.HTTPStatusError, match=r"503"):
                await client.put(server.url, content=body())

    assert server.bodies == [b"ab"]


@httpx_available
async def test_async_http_client_timeout_with_given_client() -> None:
    with run_server(STALL) as server:
        async with _async_client() as httpx_client:
            client = AsyncHttpClient(httpx_client, max_retries=0)
            with pytest.raises(httpx.ReadTimeout, match=r"^$"):
                await client.get(server.url, timeout=0.05)


@httpx_available
async def test_async_http_client_retries_dropped_connection() -> None:
    with run_server(DROP, Answer()) as server:
        async with _async_client() as httpx_client:
            await AsyncHttpClient(httpx_client, max_delay=0).get(server.url)

    assert server.methods == ["GET", "GET"]
