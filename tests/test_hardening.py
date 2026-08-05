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
SEARCH_DEVICE_ID = "FOUNDDEVICE00001"
SEARCH_RESPONSE = bytes.fromhex(
    "fdfd0210554e4b4e4f574e44455649434530303000067c464f554e4444455649434530303030312109"
)


def wait_until(predicate: object, timeout: float = 1.0) -> None:
    """Wait for a lifecycle state without relying on fixed long sleeps."""
    deadline = time.monotonic() + timeout
    while not predicate():  # type: ignore[operator]
        if time.monotonic() >= deadline:
            pytest.fail("condition was not reached before timeout")
        time.sleep(0.001)


class NonCooperativeTransport:
    """Transport that stays in receive until the test explicitly releases it."""

    def __init__(self) -> None:
        self.is_open = False
        self.receiving = threading.Event()
        self._release = threading.Event()

    def open(self) -> None:
        """Open the transport."""
        self.is_open = True

    def send(self, _data: bytes | bytearray, _address: tuple[str, int]) -> None:
        """Accept outgoing packets while open."""
        if not self.is_open:
            raise TransportClosedError("non-cooperative transport is closed")

    def receive(self, _max_bytes: int = 1024) -> tuple[bytes, tuple[str, int]]:
        """Block even after close until the test releases the transport."""
        self.receiving.set()
        self._release.wait()
        raise TransportClosedError("non-cooperative transport was released")

    def close(self) -> None:
        """Mark closed without unblocking receive."""
        self.is_open = False

    def release(self) -> None:
        """Allow the blocked receive call to finish."""
        self._release.set()


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


def test_discovery_without_device_id_calls_registered_callback() -> None:
    """Discovery does not depend on a normal response device ID."""
    found: list[str] = []
    client = DukaClient(autostart=False)
    client._found_device_callback = found.append
    packet = ResponsePacket()
    packet.device_id = None
    packet.search_device_id = SEARCH_DEVICE_ID

    client._handle_packet(packet, "192.0.2.10")

    assert found == [SEARCH_DEVICE_ID]
    assert client._found_device_callback is not None
    client.close()


def test_status_packet_still_updates_registered_device() -> None:
    """Normal status handling remains independent from discovery handling."""
    transport = FakeTransport()
    client = DukaClient(
        transport_factory=lambda: transport,
        socket_timeout=0.05,
        startup_timeout=0.2,
    )
    device = client.add_device(DEVICE_ID)
    packet = ResponsePacket()
    packet.device_id = DEVICE_ID
    packet.fan_speed = 1234
    packet.temperature = 23
    packet.humidity = 55

    client._handle_packet(packet, "192.0.2.20")

    assert device.fan_speed == 1234
    assert device.temperature == 23
    assert device.humidity == 55
    assert device.ip_address == "192.0.2.20"
    client.close()


def test_discovery_without_callback_is_harmless() -> None:
    """An unsolicited discovery response is ignored safely."""
    client = DukaClient(autostart=False)
    packet = ResponsePacket()
    packet.device_id = None
    packet.search_device_id = SEARCH_DEVICE_ID

    client._handle_packet(packet, "192.0.2.10")

    assert client.connection_state is ConnectionState.STOPPED
    client.close()


def test_discovery_callback_exception_does_not_stop_listener(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Application callback failures are logged while discovery continues."""
    transport = FakeTransport()
    callback_failed = threading.Event()
    callback_recovered = threading.Event()

    def failing_callback(_device_id: str) -> None:
        callback_failed.set()
        raise RuntimeError("callback failed")

    client = DukaClient(
        transport_factory=lambda: transport,
        socket_timeout=0.05,
        startup_timeout=0.2,
    )
    try:
        with caplog.at_level(logging.ERROR):
            client.search_devices(failing_callback)
            transport.receive_events.append((SEARCH_RESPONSE, ("192.0.2.10", 4000)))
            assert callback_failed.wait(1.0)

            client.search_devices(lambda _device_id: callback_recovered.set())
            transport.receive_events.append((SEARCH_RESPONSE, ("192.0.2.11", 4000)))
            assert callback_recovered.wait(1.0)

        assert client.is_healthy
        assert "device discovery callback failed" in caplog.text
    finally:
        client.close()


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


def test_shutdown_timeout_releases_callbacks_and_can_finish_later() -> None:
    """Timeout cleanup is final while a later close can reach CLOSED."""
    transport = NonCooperativeTransport()
    client = DukaClient(
        transport_factory=lambda: transport,
        socket_timeout=0.05,
        startup_timeout=0.2,
    )
    assert transport.receiving.wait(1.0)
    device = client.add_device(DEVICE_ID, onchange=lambda _device: None)
    client.search_devices(lambda _device_id: None)

    try:
        with pytest.raises(DukaTimeoutError) as raised:
            client.close(timeout=0.01)

        assert client.last_error is raised.value
        assert client.connection_state is ConnectionState.DEGRADED
        assert device._changeevent is None
        assert client._found_device_callback is None
    finally:
        transport.release()

    def listener_stopped() -> bool:
        thread = client._notifythread
        return thread is not None and not thread.is_alive()

    wait_until(listener_stopped)
    client.close()

    assert client.connection_state is ConnectionState.CLOSED


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


def test_close_cancels_reconnect_backoff() -> None:
    """Shutdown interrupts a pending reconnect delay without waiting for it."""
    connection_attempted = threading.Event()
    calls = 0

    def factory() -> FakeTransport:
        nonlocal calls
        calls += 1
        connection_attempted.set()
        raise DeviceUnreachableError("offline")

    client = DukaClient(
        transport_factory=factory,
        autostart=False,
        socket_timeout=0.05,
        reconnect_policy=ReconnectPolicy(
            max_attempts=5,
            initial_delay=30,
            maximum_delay=30,
            jitter_ratio=0,
        ),
    )
    client.start()
    assert connection_attempted.wait(1.0)

    started = time.monotonic()
    client.close(timeout=0.5)

    assert time.monotonic() - started < 0.5
    assert calls == 1
    assert client.connection_state is ConnectionState.CLOSED
    assert client._notifythread is not None
    assert client._notifythread.is_alive() is False


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
