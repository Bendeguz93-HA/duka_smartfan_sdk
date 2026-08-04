"""Hardware-free test helpers for the SDK."""

from __future__ import annotations

from collections import deque
import socket
import threading
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator


class FakeSocket:
    """Small socket double that never accesses the network."""

    def __init__(self) -> None:
        self.bound_address: tuple[str, int] | None = None
        self.closed = False
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.timeout = 0.01
        self._responses: deque[tuple[bytes, tuple[str, int]]] = deque()
        self._response_ready = threading.Event()

    def setsockopt(self, *_args: object) -> None:
        """Accept socket options without side effects."""

    def bind(self, address: tuple[str, int]) -> None:
        """Record the requested bind address."""
        self.bound_address = address

    def settimeout(self, timeout: float) -> None:
        """Use a short deterministic timeout in tests."""
        self.timeout = min(timeout, 0.01)

    def sendto(self, data: bytes, address: tuple[str, int]) -> int:
        """Record a datagram without sending it."""
        if self.closed:
            raise OSError("socket is closed")
        payload = bytes(data)
        self.sent.append((payload, address))
        return len(payload)

    def recvfrom(self, _size: int) -> tuple[bytes, tuple[str, int]]:
        """Return queued data or emulate a socket timeout."""
        self._response_ready.wait(self.timeout)
        if self.closed:
            raise OSError("socket is closed")
        if self._responses:
            response = self._responses.popleft()
            if not self._responses:
                self._response_ready.clear()
            return response
        raise socket.timeout

    def queue_response(
        self, data: bytes, address: tuple[str, int] = ("192.0.2.10", 4000)
    ) -> None:
        """Queue a response for the listener thread."""
        self._responses.append((data, address))
        self._response_ready.set()

    def close(self) -> None:
        """Close the fake and wake a blocked receiver."""
        self.closed = True
        self._response_ready.set()


@pytest.fixture
def fake_socket(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeSocket]:
    """Replace UDP sockets before a client can start its listener thread."""
    instance = FakeSocket()
    monkeypatch.setattr(
        "duka_smartfan_sdk.dukaclient.socket.socket",
        lambda *_args, **_kwargs: instance,
    )
    yield instance
    instance.close()
