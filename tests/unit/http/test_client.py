from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import Mock

import pytest

from persista.cache import AsyncCache, Cache
from persista.http.client import AsyncHttpClient, HttpClient

if TYPE_CHECKING:
    from collections.abc import Callable

httpx = pytest.importorskip("httpx")


MODULE = "persista.http.httpx"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f"{MODULE}.time.sleep", Mock())

    async def fake_async_sleep(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        return None

    monkeypatch.setattr(f"{MODULE}.asyncio.sleep", fake_async_sleep)


def _counting_handler(json_factory: Callable[[int], dict[str, object]]) -> tuple[Callable, Mock]:
    calls = Mock(side_effect=range(1_000_000))

    def handler(request: httpx.Request) -> httpx.Response:
        n = calls()
        return httpx.Response(200, json=json_factory(n), request=request)

    return handler, calls


def _client(handler: Callable) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _async_client(handler: Callable) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


############################
#       HttpClient        #
############################


def test_http_client_no_cache_by_default() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = HttpClient(client=_client(handler))

    assert client.get("https://example.com").json() == {"n": 0}
    assert client.get("https://example.com").json() == {"n": 1}
    assert calls.call_count == 2


def test_http_client_caches_get_on_hit() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = HttpClient(cache=Cache(), client=_client(handler))

    r1 = client.get("https://example.com/foo")
    r2 = client.get("https://example.com/foo")

    assert r1.json() == r2.json() == {"n": 0}
    assert calls.call_count == 1


def test_http_client_cache_keys_differ_by_url() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = HttpClient(cache=Cache(), client=_client(handler))

    client.get("https://example.com/foo")
    client.get("https://example.com/bar")

    assert calls.call_count == 2


def test_http_client_cache_keys_differ_by_params() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = HttpClient(cache=Cache(), client=_client(handler))

    client.get("https://example.com", params={"x": 1})
    client.get("https://example.com", params={"x": 2})

    assert calls.call_count == 2


def test_http_client_put() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = HttpClient(client=_client(handler))

    response = client.put("https://example.com", json={"a": 1})

    assert response.json() == {"n": 0}
    assert calls.call_count == 1


def test_http_client_patch() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = HttpClient(client=_client(handler))

    response = client.patch("https://example.com", json={"a": 1})

    assert response.json() == {"n": 0}
    assert calls.call_count == 1


def test_http_client_delete() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = HttpClient(client=_client(handler))

    response = client.delete("https://example.com")

    assert response.json() == {"n": 0}
    assert calls.call_count == 1


def test_http_client_does_not_cache_non_cacheable_method() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = HttpClient(cache=Cache(), client=_client(handler))

    client.post("https://example.com", json={"a": 1})
    client.post("https://example.com", json={"a": 1})

    assert calls.call_count == 2


def test_http_client_does_not_cache_error_response() -> None:
    calls = Mock(return_value=None)

    def handler(request: httpx.Request) -> httpx.Response:
        calls()
        return httpx.Response(500, request=request)

    client = HttpClient(cache=Cache(), max_retries=0, client=_client(handler))

    with pytest.raises(httpx.HTTPStatusError):
        client.get("https://example.com")
    with pytest.raises(httpx.HTTPStatusError):
        client.get("https://example.com")

    assert calls.call_count == 2


def test_http_client_context_manager_closes_client() -> None:
    handler, _ = _counting_handler(lambda n: {"n": n})
    raw_client = _client(handler)

    with HttpClient(client=raw_client) as client:
        client.get("https://example.com")

    assert raw_client.is_closed


############################
#     AsyncHttpClient     #
############################


async def test_async_http_client_caches_get_on_hit() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = AsyncHttpClient(cache=AsyncCache(), client=_async_client(handler))

    r1 = await client.get("https://example.com/foo")
    r2 = await client.get("https://example.com/foo")

    assert r1.json() == r2.json() == {"n": 0}
    assert calls.call_count == 1


async def test_async_http_client_no_cache_by_default() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = AsyncHttpClient(client=_async_client(handler))

    await client.get("https://example.com")
    await client.get("https://example.com")

    assert calls.call_count == 2


async def test_async_http_client_post() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = AsyncHttpClient(client=_async_client(handler))

    response = await client.post("https://example.com", json={"a": 1})

    assert response.json() == {"n": 0}
    assert calls.call_count == 1


async def test_async_http_client_put() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = AsyncHttpClient(client=_async_client(handler))

    response = await client.put("https://example.com", json={"a": 1})

    assert response.json() == {"n": 0}
    assert calls.call_count == 1


async def test_async_http_client_patch() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = AsyncHttpClient(client=_async_client(handler))

    response = await client.patch("https://example.com", json={"a": 1})

    assert response.json() == {"n": 0}
    assert calls.call_count == 1


async def test_async_http_client_delete() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = AsyncHttpClient(client=_async_client(handler))

    response = await client.delete("https://example.com")

    assert response.json() == {"n": 0}
    assert calls.call_count == 1


async def test_async_http_client_context_manager_closes_client() -> None:
    handler, _ = _counting_handler(lambda n: {"n": n})
    raw_client = _async_client(handler)

    async with AsyncHttpClient(client=raw_client) as client:
        await client.get("https://example.com")

    assert raw_client.is_closed
