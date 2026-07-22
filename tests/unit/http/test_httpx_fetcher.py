from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from persista.cache import Cache
from persista.http.httpx_fetcher import BaseFetcher, CachedFetcher, Fetcher

if TYPE_CHECKING:
    from collections.abc import Callable

httpx = pytest.importorskip("httpx")


MODULE = "persista.http.httpx"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> Mock:
    mock = Mock()
    monkeypatch.setattr(f"{MODULE}.time.sleep", mock)
    return mock


def _counting_handler(
    statuses: list[int], json: dict[str, object] | None = None
) -> tuple[Callable, Mock]:
    calls = Mock(side_effect=iter(statuses))

    def handler(request: httpx.Request) -> httpx.Response:
        status = calls()
        return httpx.Response(status, json=json, request=request)

    return handler, calls


def _client(handler: Callable) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


############################
#     BaseFetcher          #
############################


def test_base_fetcher_is_abstract() -> None:
    with pytest.raises(TypeError):
        BaseFetcher()


############################
#     Fetcher              #
############################


def test_fetcher_is_base_fetcher() -> None:
    assert isinstance(Fetcher(httpx.Client()), BaseFetcher)


def test_fetcher_fetch_response_uses_own_client() -> None:
    handler, calls = _counting_handler([200], json={"ok": True})
    fetcher = Fetcher(_client(handler))

    response = fetcher.fetch_response("https://example.com")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls.call_count == 1


def test_fetcher_fetch_response_passes_headers() -> None:
    received: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received.update(request.headers)
        return httpx.Response(200)

    fetcher = Fetcher(_client(handler))
    fetcher.fetch_response("https://example.com", headers={"X-Custom": "value"})

    assert received["x-custom"] == "value"


def test_fetcher_fetch_response_retries_then_succeeds(no_sleep: Mock) -> None:
    handler, calls = _counting_handler([503, 502, 200], json={"ok": True})
    fetcher = Fetcher(_client(handler))

    response = fetcher.fetch_response("https://example.com", max_retries=3)

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls.call_count == 3
    assert no_sleep.call_count == 2


def test_fetcher_fetch_response_exhausts_retries_raises_http_status_error() -> None:
    handler, calls = _counting_handler([500, 500, 500])
    fetcher = Fetcher(_client(handler))

    with pytest.raises(httpx.HTTPStatusError):
        fetcher.fetch_response("https://example.com", max_retries=2)

    assert calls.call_count == 3


def test_fetcher_fetch_response_custom_retry_status_codes() -> None:
    handler, calls = _counting_handler([418, 200], json={"ok": True})
    fetcher = Fetcher(_client(handler))

    response = fetcher.fetch_response(
        "https://example.com", max_retries=1, retry_status_codes={418}
    )

    assert response.status_code == 200
    assert calls.call_count == 2


def test_fetcher_fetch_response_does_not_close_own_client() -> None:
    handler, _ = _counting_handler([200])
    client = _client(handler)
    fetcher = Fetcher(client)

    fetcher.fetch_response("https://example.com")

    assert not client.is_closed


############################
#     CachedFetcher        #
############################


def test_cached_fetcher_is_base_fetcher() -> None:
    assert isinstance(CachedFetcher(httpx.Client(), Cache()), BaseFetcher)


def test_cached_fetcher_fetch_response_caches_result() -> None:
    handler, calls = _counting_handler([200], json={"ok": True})
    fetcher = CachedFetcher(_client(handler), Cache())

    response1 = fetcher.fetch_response("https://example.com")
    response2 = fetcher.fetch_response("https://example.com")

    assert response1.status_code == response2.status_code == 200
    assert response1.json() == response2.json() == {"ok": True}
    assert calls.call_count == 1


def test_cached_fetcher_fetch_response_different_urls_are_not_shared() -> None:
    handler, calls = _counting_handler([200, 200])
    fetcher = CachedFetcher(_client(handler), Cache())

    fetcher.fetch_response("https://example.com/a")
    fetcher.fetch_response("https://example.com/b")

    assert calls.call_count == 2


def test_cached_fetcher_fetch_response_different_kwargs_are_not_shared() -> None:
    handler, calls = _counting_handler([200, 200])
    fetcher = CachedFetcher(_client(handler), Cache())

    fetcher.fetch_response("https://example.com", headers={"X-Custom": "1"})
    fetcher.fetch_response("https://example.com", headers={"X-Custom": "2"})

    assert calls.call_count == 2


def test_cached_fetcher_fetch_response_passes_headers() -> None:
    received: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received.update(request.headers)
        return httpx.Response(200)

    fetcher = CachedFetcher(_client(handler), Cache())
    fetcher.fetch_response("https://example.com", headers={"X-Custom": "value"})

    assert received["x-custom"] == "value"


def test_cached_fetcher_fetch_response_retries_then_succeeds(no_sleep: Mock) -> None:
    handler, calls = _counting_handler([503, 502, 200], json={"ok": True})
    fetcher = CachedFetcher(_client(handler), Cache())

    response = fetcher.fetch_response("https://example.com", max_retries=3)

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls.call_count == 3
    assert no_sleep.call_count == 2


def test_cached_fetcher_fetch_response_uses_pickle_strategy() -> None:
    handler, calls = _counting_handler([200])
    fetcher = CachedFetcher(_client(handler), Cache(), strategy="pickle")

    fetcher.fetch_response("https://example.com")
    fetcher.fetch_response("https://example.com")

    assert calls.call_count == 1


def test_cached_fetcher_fetch_response_does_not_close_own_client() -> None:
    handler, _ = _counting_handler([200])
    client = _client(handler)
    fetcher = CachedFetcher(client, Cache())

    fetcher.fetch_response("https://example.com")

    assert not client.is_closed
