r"""Provide a local HTTP server that plays scripted answers, for the
integration tests of the HTTP helpers."""

from __future__ import annotations

__all__ = ["DROP", "STALL", "Answer", "ScriptedServer", "run_server"]

import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

# The maximum time the server waits before it answers a stalled request,
# in case the test does not stop it.
STALL_TIMEOUT = 10


@dataclass(frozen=True)
class Answer:
    r"""Define how the server answers one request.

    Args:
        status: The status code of the response.
        headers: The headers of the response.
        action: ``"drop"`` closes the connection without a response,
            ``"stall"`` answers only when the server stops, and
            ``"respond"`` answers immediately.
    """

    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    action: str = "respond"


DROP = Answer(action="drop")
STALL = Answer(action="stall")


class ScriptedServer(ThreadingHTTPServer):
    r"""A local server that answers the requests with a script.

    The last answer of the script is repeated.

    Args:
        answers: The answers, one per request.
    """

    def __init__(self, answers: tuple[Answer, ...]) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.answers = answers
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        # The method, headers and body of each request, in order.
        self.requests: list[tuple[str, dict[str, str], bytes]] = []

    @property
    def url(self) -> str:
        r"""The URL of the server."""
        return f"http://127.0.0.1:{self.server_port}"

    @property
    def methods(self) -> list[str]:
        r"""The methods of the requests received, in order."""
        return [method for method, _, _ in self.requests]

    @property
    def bodies(self) -> list[bytes]:
        r"""The bodies of the requests received, in order."""
        return [body for _, _, body in self.requests]

    def next_answer(self, method: str, headers: dict[str, str], body: bytes) -> Answer:
        r"""Record a request and return the answer to it.

        Args:
            method: The method of the request.
            headers: The headers of the request, with lower case names.
            body: The body of the request.

        Returns:
            The answer of the script for this request.
        """
        with self.lock:
            answer = self.answers[min(len(self.requests), len(self.answers) - 1)]
            self.requests.append((method, headers, body))
        return answer


class _Handler(BaseHTTPRequestHandler):
    r"""Answer a request with the script of the server."""

    server: ScriptedServer

    def do_GET(self) -> None:
        self._answer()

    def do_POST(self) -> None:
        self._answer()

    def do_PUT(self) -> None:
        self._answer()

    def do_PATCH(self) -> None:
        self._answer()

    def do_DELETE(self) -> None:
        self._answer()

    def log_message(self, *args: object) -> None:
        pass

    def _read_body(self) -> bytes:
        r"""Read the body of the request, which can be chunked."""
        if self.headers.get("transfer-encoding", "").lower() != "chunked":
            return self.rfile.read(int(self.headers.get("content-length", 0)))
        chunks = []
        while size := int(self.rfile.readline().strip(), 16):
            chunks.append(self.rfile.read(size))
            self.rfile.readline()
        self.rfile.readline()
        return b"".join(chunks)

    def _answer(self) -> None:
        r"""Send the next answer of the script."""
        headers = {name.lower(): value for name, value in self.headers.items()}
        answer = self.server.next_answer(self.command, headers, self._read_body())
        if answer.action == "drop":
            self.close_connection = True
            return
        if answer.action == "stall":
            self.server.stopping.wait(STALL_TIMEOUT)
            self.close_connection = True
            return
        self.send_response(answer.status)
        for name, value in answer.headers.items():
            self.send_header(name, value)
        self.send_header("content-length", "2")
        self.end_headers()
        self.wfile.write(b"ok")


@contextmanager
def run_server(*answers: Answer) -> Iterator[ScriptedServer]:
    r"""Run a scripted server in a thread.

    Args:
        *answers: The answers of the server, one per request.

    Yields:
        The running server.
    """
    server = ScriptedServer(answers)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield server
    finally:
        server.stopping.set()
        server.shutdown()
        thread.join()
        server.server_close()
