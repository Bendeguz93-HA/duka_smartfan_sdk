"""Injectable UDP transport boundary used by the SDK client."""

from __future__ import annotations

import socket
from collections.abc import Callable
from socket import SO_BROADCAST, SO_REUSEADDR, SOL_SOCKET
from typing import Protocol, runtime_checkable

from .exceptions import (
    DeviceUnreachableError,
    DukaTimeoutError,
    TransportClosedError,
)

Address = tuple[str, int]


@runtime_checkable
class DatagramTransport(Protocol):
    """Minimal transport contract required by :class:`DukaClient`."""

    @property
    def is_open(self) -> bool:
        """Return whether the transport currently accepts I/O."""

    def open(self) -> None:
        """Allocate and bind transport resources."""

    def send(self, data: bytes | bytearray, address: Address) -> None:
        """Send one datagram."""

    def receive(self, max_bytes: int = 1024) -> tuple[bytes, Address]:
        """Receive one datagram or raise a typed transport error."""

    def close(self) -> None:
        """Release resources. Implementations must make this idempotent."""


TransportFactory = Callable[[], DatagramTransport]


class SocketDatagramTransport:
    """UDP socket implementation of the transport contract."""

    def __init__(
        self,
        *,
        bind_address: Address = ("0.0.0.0", 4000),
        timeout: float = 1.0,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        self._bind_address = bind_address
        self._timeout = timeout
        self._socket: socket.socket | None = None

    @property
    def is_open(self) -> bool:
        """Return whether the socket is allocated."""
        return self._socket is not None

    def open(self) -> None:
        """Open and bind a broadcast-capable UDP socket."""
        if self._socket is not None:
            return
        udp_socket: socket.socket | None = None
        try:
            udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
            udp_socket.setsockopt(SOL_SOCKET, SO_BROADCAST, 1)
            udp_socket.bind(self._bind_address)
            udp_socket.settimeout(self._timeout)
        except OSError as err:
            if udp_socket is not None:
                udp_socket.close()
            raise DeviceUnreachableError("unable to open UDP transport") from err
        self._socket = udp_socket

    def send(self, data: bytes | bytearray, address: Address) -> None:
        """Send a datagram through the bound socket."""
        udp_socket = self._socket
        if udp_socket is None:
            raise TransportClosedError("UDP transport is closed")
        try:
            udp_socket.sendto(data, address)
        except OSError as err:
            if self._socket is None:
                raise TransportClosedError("UDP transport is closed") from err
            raise DeviceUnreachableError(
                f"unable to send UDP datagram to {address[0]}"
            ) from err

    def receive(self, max_bytes: int = 1024) -> tuple[bytes, Address]:
        """Receive one datagram with a bounded socket timeout."""
        udp_socket = self._socket
        if udp_socket is None:
            raise TransportClosedError("UDP transport is closed")
        try:
            data, address = udp_socket.recvfrom(max_bytes)
        except TimeoutError as err:
            raise DukaTimeoutError("UDP receive timed out") from err
        except OSError as err:
            if self._socket is None:
                raise TransportClosedError("UDP transport is closed") from err
            raise DeviceUnreachableError("UDP receive failed") from err
        return bytes(data), address

    def close(self) -> None:
        """Close the socket and make repeated calls harmless."""
        udp_socket, self._socket = self._socket, None
        if udp_socket is not None:
            udp_socket.close()
