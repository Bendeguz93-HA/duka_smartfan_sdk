"""Tests for typed errors, transport injection, lifecycle, and reconnect."""

from __future__ import annotations

import logging
import threading
import time

import pytest
from conftest import FakeTransport

from duka_smartfan_sdk import (
    AuthenticationError,
    CommandError,
    ConnectionState,
    DeviceUnreachableError,
    DukaClient,
    DukaSmartFanError,
    DukaTimeoutError,
    MalformedPacketError,
    ReconnectPolicy,
    TransportClosedError,
)
from duka_smartfan_sdk.responsepacket import ResponsePacket

DEVICE_ID = "1234567890123456"


def wait_until(predicate: object, timeout: float = 1.0) -> None:
    """Wait for a lifecycle state without relying on fixed long sleeps."""
    deadline = time.monotonic() + timeout
    while not predicate():  # type: ignore[operator]
        if time.monotonic() >= deadline:
            pytest.fail("condition was not reached before timeout")
        time.sleep(0.001)


@pytest.mark.parametrize(
    "error_type",
    [
        AuthenticationError,
        CommandError,
        DeviceUnreachableError,
        DukaTimeoutError,
        MalformedPacketError,
        TransportClosedError,
    ],
)
def test_public_exceptions_share_sdk_base(error_type: type[Exception]) -> None:
    """Callers can catch every typed failure through one stable base class."""
    assert issubclass(error_type, DukaSmartFanError)


def test_response_parse_raises_typed_malformed_packet() -> None:
    """The strict parser adds typed errors without changing the bool API."""
    with pytest.raises(MalformedPacketError):
        ResponsePacket.parse(b"not a protocol packet")

    assert ResponsePacket().initialize_from_data(b"not a protocol packet") is False


def test_explicit_lifecycle_and_health_state() -> None:
    """A caller can opt out of autostart and deterministically own the thread."""
    transport = FakeTransport()
    client = DukaClient(
        transport_factory=lambda: transport,
        autostart=False,
        socket_timeout=0.05,
        startup_timeout=0.2,
    )

    assert client.connection_state is ConnectionState.STOPPED
    assert client.is_healthy is False

    client.start()
    wait_until(lambda: client.connection_state is ConnectionState.CONNECTED)

    assert client.is_healthy is True
    assert client._notifythread is not None
    assert client._notifythread.daemon is True

    client.close()
    client.close()

    assert client.connection_state is ConnectionState.CLOSED
    assert client._notifythread.is_alive() is False
    assert transport.is_open is False


def test_context_manager_closes_after_exception() -> None:
    """Context-manager shutdown also releases the listener on cancellation paths."""
    transport = FakeTransport()
    client = DukaClient(
        transport_factory=lambda: transport,
        autostart=False,
        socket_timeout=0.05,
    )

    with pytest.raises(RuntimeError, match="cancel work"), client:
        wait_until(lambda current=client: current.is_healthy)
        raise RuntimeError("cancel work")

    assert client.connection_state is ConnectionState.CLOSED
    assert client._notifythread is not None
    assert client._notifythread.is_alive() is False


def test_close_releases_registered_callbacks() -> None:
    """Shutdown drops application callback references."""
    transport = FakeTransport()
    changed: list[object] = []
    client = DukaClient(
        transport_factory=lambda: transport,
        socket_timeout=0.05,
        startup_timeout=0.2,
    )
    wait_until(lambda: client.is_healthy)
    device = client.add_device(DEVICE_ID, onchange=changed.append)
    client.search_devices(lambda _device_id: None)

    client.close()

    assert device._changeevent is None
    assert client._found_device_callback is None


def test_command_failure_uses_typed_error() -> None:
    """Transport send failures are translated to a public command error."""
    transport = FakeTransport()
    client = DukaClient(
        transport_factory=lambda: transport,
        socket_timeout=0.05,
        startup_timeout=0.2,
    )
    wait_until(lambda: client.is_healthy)
    transport.fail_unreachable()

    with pytest.raises(CommandError) as raised:
        client.add_device(DEVICE_ID)

    assert isinstance(raised.value.__cause__, DeviceUnreachableError)
    client.close()


def test_reconnect_policy_is_exponential_capped_and_deterministic() -> None:
    """Backoff follows a predictable exponential sequence with bounded jitter."""
    policy = ReconnectPolicy(
        max_attempts=5,
        initial_delay=1.0,
        maximum_delay=4.0,
        jitter_ratio=0.2,
    )

    assert policy.delay(1, random_value=0.5) == 1.0
    assert policy.delay(2, random_value=0.5) == 2.0
    assert policy.delay(3, random_value=0.5) == 4.0
    assert policy.delay(4, random_value=0.5) == 4.0
    assert policy.delay(1, random_value=0.0) == pytest.approx(0.8)
    assert policy.delay(1, random_value=1.0) == pytest.approx(1.2)


def test_reconnect_succeeds_within_bounded_attempts() -> None:
    """Two failed opens back off before a successful injected transport."""
    transport = FakeTransport()
    calls = 0

    def factory() -> FakeTransport:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise DeviceUnreachableError("not ready")
        return transport

    client = DukaClient(
        transport_factory=factory,
        autostart=False,
        socket_timeout=0.05,
        reconnect_policy=ReconnectPolicy(
            max_attempts=3,
            initial_delay=0,
            maximum_delay=0,
            jitter_ratio=0,
        ),
    )
    client.start()
    wait_until(lambda: client.is_healthy)

    assert calls == 3
    assert client.reconnect_attempts == 2
    assert client.last_error is None
    client.close()


def test_reconnect_stops_at_maximum_without_log_spam(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unreachable endpoint exhausts a finite attempt budget and exits."""
    calls = 0

    def factory() -> FakeTransport:
        nonlocal calls
        calls += 1
        raise DeviceUnreachableError("still unreachable")

    client = DukaClient(
        transport_factory=factory,
        autostart=False,
        socket_timeout=0.05,
        reconnect_policy=ReconnectPolicy(
            max_attempts=3,
            initial_delay=0,
            maximum_delay=0,
            jitter_ratio=0,
        ),
    )
    with caplog.at_level(logging.WARNING):
        client.start()
        wait_until(
            lambda: (
                client.connection_state is ConnectionState.DEGRADED
                and client._notifythread is not None
                and not client._notifythread.is_alive()
            )
        )

    assert calls == 3
    assert client.reconnect_attempts == 3
    assert isinstance(client.last_error, DeviceUnreachableError)
    assert len(caplog.records) == 3
    client.close()


def test_repeated_clients_leave_no_listener_threads() -> None:
    """Start/close cycles do not leak the owned non-main listener resource."""
    for _ in range(20):
        transport = FakeTransport()
        client = DukaClient(
            transport_factory=lambda transport=transport: transport,
            socket_timeout=0.05,
        )
        wait_until(lambda current=client: current.is_healthy)
        client.close()

    leaked = [
        thread
        for thread in threading.enumerate()
        if thread.name == "duka-smartfan-listener" and thread.is_alive()
    ]
    assert leaked == []
