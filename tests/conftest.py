"""Hardware-free test helpers for the SDK."""

from __future__ import annotations

import threading
from collections import deque
from typing import TYPE_CHECKING

import pytest

from duka_smartfan_sdk.exceptions import (
    DeviceUnreachableError,
    DukaTimeoutError,
    TransportClosedError,
)

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
        raise TimeoutError

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


class FakeTransport:
    """Injectable transport with deterministic responses and failures."""

    def __init__(self) -> None:
        self.is_open = False
        self.open_calls = 0
        self.close_calls = 0
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.receive_events: deque[tuple[bytes, tuple[str, int]] | Exception] = deque()
        self.open_error: Exception | None = None
        self.send_error: Exception | None = None
        self._closed = threading.Event()

    def open(self) -> None:
        """Open the fake or raise its configured failure."""
        self.open_calls += 1
        if self.open_error is not None:
            raise self.open_error
        self._closed.clear()
        self.is_open = True

    def send(self, data: bytes | bytearray, address: tuple[str, int]) -> None:
        """Record a datagram or raise its configured failure."""
        if not self.is_open:
            raise TransportClosedError("fake transport is closed")
        if self.send_error is not None:
            raise self.send_error
        self.sent.append((bytes(data), address))

    def receive(self, _max_bytes: int = 1024) -> tuple[bytes, tuple[str, int]]:
        """Return a queued event or a short deterministic timeout."""
        if not self.is_open:
            raise TransportClosedError("fake transport is closed")
        if self.receive_events:
            event = self.receive_events.popleft()
            if isinstance(event, Exception):
                raise event
            return event
        if self._closed.wait(0.001):
            raise TransportClosedError("fake transport is closed")
        raise DukaTimeoutError("fake receive timed out")

    def close(self) -> None:
        """Close idempotently and wake the receiver."""
        self.close_calls += 1
        self.is_open = False
        self._closed.set()

    def fail_unreachable(self) -> None:
        """Configure subsequent sends to fail as unreachable."""
        self.send_error = DeviceUnreachableError("fake device unreachable")


@pytest.fixture
def fake_socket(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeSocket]:
    """Replace UDP sockets before a client can start its listener thread."""
    instance = FakeSocket()
    monkeypatch.setattr(
        "duka_smartfan_sdk.transport.socket.socket",
        lambda *_args, **_kwargs: instance,
    )
    yield instance
    instance.close()
