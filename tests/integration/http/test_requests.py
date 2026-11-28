from __future__ import annotations

import socket
import time

import pytest

from persista.testing.fixtures import requests_available, requests_not_available
from persista.utils.imports import is_requests_available
from tests.integration.http.server_helpers import DROP, STALL, Answer, run_server

if is_requests_available():
    import requests

    from persista.http.requests import create_session, fetch_response

REMOTE_URL = "https://jsonplaceholder.typicode.com/todos/1"


############################
#     fetch_response       #
############################


@requests_available
def test_fetch_response_success_against_remote_url() -> None:
    response = fetch_response(REMOTE_URL, timeout=10)

    assert response.status_code == 200
    assert response.json()["id"] == 1


@requests_not_available
def test_fetch_response_raises_without_requests() -> None:
    with pytest.raises(RuntimeError, match=r"'requests' package is required but not installed."):
        fetch_response("http://127.0.0.1:1")


#######################################
#     Retries with a local server     #
#######################################


def _unused_port() -> int:
    """Return a port of the local host on which nothing listens."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(autouse=True)
def no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    # So that a proxy of the environment is not used for the local server.
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")


@requests_available
@pytest.mark.parametrize(
    "retry_after",
    [
        pytest.param("0", id="zero"),
        pytest.param("-1", id="negative"),
        pytest.param("100000", id="above-maximum"),
        pytest.param("9" * 5000, id="huge"),
        pytest.param("Fri, 31 Dec 9999 23:59:59 GMT", id="future-date"),
        pytest.param("Sun, 06 Nov 1994 08:49:37 GMT", id="past-date"),
        pytest.param("soon", id="garbage"),
    ],
)
def test_fetch_response_bounded_retry_after(retry_after: str) -> None:
    answers = (Answer(503, {"retry-after": retry_after}), Answer())
    with run_server(*answers) as server:
        start = time.monotonic()
        response = fetch_response(server.url, max_delay=0.01)

    assert (response.status_code, server.methods) == (200, ["GET", "GET"])
    assert time.monotonic() - start < 5


@requests_available
def test_fetch_response_bounded_backoff() -> None:
    with run_server(Answer(503), Answer(503), Answer(503), Answer()) as server:
        start = time.monotonic()
        fetch_response(server.url, backoff_factor=1000, max_delay=0.01)

    assert len(server.requests) == 4
    assert time.monotonic() - start < 5


@requests_available
def test_fetch_response_exhausts_retries() -> None:
    with (
        run_server(Answer(503)) as server,
        pytest.raises(requests.exceptions.HTTPError, match=r"503 Server Error"),
    ):
        fetch_response(server.url, max_retries=2, backoff_factor=0)

    assert len(server.requests) == 3


@requests_available
def test_fetch_response_does_not_retry_unlisted_status_with_retry_after() -> None:
    with (
        run_server(Answer(413, {"retry-after": "0"}), Answer()) as server,
        pytest.raises(requests.exceptions.HTTPError, match=r"413 Client Error"),
    ):
        fetch_response(server.url)

    assert len(server.requests) == 1


@requests_available
def test_fetch_response_retries_dropped_connection() -> None:
    with run_server(DROP, Answer()) as server:
        response = fetch_response(server.url, backoff_factor=0)

    assert (response.status_code, server.methods) == (200, ["GET", "GET"])


@requests_available
def test_fetch_response_refused_connection() -> None:
    with pytest.raises(requests.exceptions.ConnectionError, match=r"Max retries exceeded"):
        fetch_response(f"http://127.0.0.1:{_unused_port()}", backoff_factor=0)


@requests_available
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_create_session_retries_get_only(method: str) -> None:
    with (
        run_server(Answer(503, {"retry-after": "0"}), Answer()) as server,
        create_session() as session,
    ):
        response = getattr(session, method)(server.url, timeout=5)

    assert (response.status_code, len(server.requests)) == (503, 1)


@requests_available
def test_create_session_does_not_retry_post_after_dropped_connection() -> None:
    with (
        run_server(DROP, Answer()) as server,
        create_session(backoff_factor=0) as session,
        pytest.raises(requests.exceptions.ConnectionError, match=r"aborted"),
    ):
        session.post(server.url, timeout=5)

    assert server.methods == ["POST"]


@requests_available
@pytest.mark.parametrize(("method", "retries"), [("get", 2), ("post", 0)])
def test_create_session_retries_refused_connection_of_get_only(
    caplog: pytest.LogCaptureFixture, method: str, retries: int
) -> None:
    url = f"http://127.0.0.1:{_unused_port()}"
    with (
        create_session(max_retries=2, backoff_factor=0) as session,
        pytest.raises(requests.exceptions.ConnectionError, match=r"Max retries exceeded"),
    ):
        getattr(session, method)(url, timeout=5)

    # urllib3 logs one warning per retry.
    assert sum(message.startswith("Retrying") for message in caplog.messages) == retries


@requests_available
def test_create_session_read_timeout_of_post() -> None:
    with (
        run_server(STALL) as server,
        create_session() as session,
        pytest.raises(requests.exceptions.ReadTimeout, match=r"Read timed out"),
    ):
        session.post(server.url, timeout=0.05)

    assert server.methods == ["POST"]


@requests_available
def test_fetch_response_timeout_with_given_session() -> None:
    with (
        run_server(STALL) as server,
        create_session(max_retries=0) as session,
        pytest.raises(requests.exceptions.ConnectionError, match=r"Read timed out"),
    ):
        fetch_response(server.url, session=session, timeout=0.05)


@requests_available
def test_fetch_response_sends_session_settings() -> None:
    with run_server(Answer()) as server, create_session() as session:
        session.headers["x-user"] = "alice"
        session.auth = ("alice", "secret")
        fetch_response(server.url, session=session)

    headers = server.requests[0][1]
    assert (headers["x-user"], headers["authorization"][:5]) == ("alice", "Basic")
