"""Characterize the public client and device lifecycle without hardware."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest

from duka_smartfan_sdk.device import Device
from duka_smartfan_sdk.dukaclient import DukaClient
from duka_smartfan_sdk.responsepacket import ResponsePacket

from conftest import FakeSocket


DEVICE_ID = "1234567890123456"
PASSWORD = "1111"
SEARCH_RESPONSE = bytes.fromhex(
    "fdfd0210554e4b4e4f574e44455649434530303000067c"
    "464f554e4444455649434530303030312109"
)


def wait_until(predicate: Any, timeout: float = 1.0) -> None:
    """Wait briefly for the listener thread without fixed sleeps."""
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            pytest.fail("condition was not reached before timeout")
        time.sleep(0.001)


def test_default_password_and_initial_device_state() -> None:
    """The public Device defaults are retained for compatibility."""
    device = Device(DEVICE_ID)

    assert device.device_id == DEVICE_ID
    assert device.password == PASSWORD
    assert device.ip_address == "<broadcast>"
    assert device.is_active is None
    assert device.fan_speed is None
    assert device.temperature is None
    assert device.humidity is None
    assert device.is_initialized() is False


def test_async_initialize_wait_returns_for_initialized_device() -> None:
    """The async wait API completes without blocking when state is ready."""
    device = Device(DEVICE_ID)
    device._firmware_version = "1.2"

    asyncio.run(device.wait_for_initialize_async())

    assert device.is_initialized()


def test_on_off_and_boost_commands_use_expected_packets(
    fake_socket: FakeSocket,
) -> None:
    """Public command methods preserve their existing UDP payloads."""
    client = DukaClient()
    try:
        wait_until(lambda: client._socket_listening)
        device = client.add_device(DEVICE_ID, PASSWORD, "192.0.2.20")
        client.turn_on(device)
        client.turn_off(device)
        client.turn_boost_on(device)
        client.turn_boost_off(device)
        client.toggle_boost(device)

        sent_hex = {payload.hex() for payload, _address in fake_socket.sent}
        assert {
            "fdfd02103132333435363738393031323334353604313131310301012104",
            "fdfd02103132333435363738393031323334353604313131310301002004",
            "fdfd02103132333435363738393031323334353604313131310305012504",
            "fdfd02103132333435363738393031323334353604313131310305002404",
            "fdfd02103132333435363738393031323334353604313131310305022604",
        }.issubset(sent_hex)
        assert all(address == ("192.0.2.20", 4000) for _, address in fake_socket.sent)
    finally:
        client.close()


def test_search_callback_receives_discovered_device(fake_socket: FakeSocket) -> None:
    """Discovery responses retain the callback-only observable behavior."""
    found: list[str] = []
    callback_called = threading.Event()

    def on_found(device_id: str) -> None:
        found.append(device_id)
        callback_called.set()

    client = DukaClient()
    try:
        wait_until(lambda: client._socket_listening)
        client.search_devices(on_found)
        fake_socket.queue_response(SEARCH_RESPONSE)

        assert callback_called.wait(1.0)
        assert found == ["FOUNDDEVICE00001"]
    finally:
        client.close()


def test_update_callback_excludes_rpm_only_changes(fake_socket: FakeSocket) -> None:
    """State callbacks fire for semantic state, but not for RPM-only updates."""
    changed: list[Device] = []
    client = DukaClient()
    try:
        wait_until(lambda: client._socket_listening)
        device = Device(DEVICE_ID, onchange=changed.append)
        first = ResponsePacket()
        first.fan_speed = 1000
        first.humidity = 55
        first.temperature = 23
        client.update_device(device, "192.0.2.20", first)

        rpm_only = ResponsePacket()
        rpm_only.fan_speed = 1001
        client.update_device(device, "192.0.2.20", rpm_only)

        assert changed == [device]
        assert device.is_active is True
        assert device.fan_speed == 1001
        assert device.humidity == 55
        assert device.temperature == 23
        assert device.ip_address == "192.0.2.20"
    finally:
        client.close()


def test_validation_success_and_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Validation returns a responding device and removes its temporary entry."""
    client = DukaClient.__new__(DukaClient)
    client._devices = {}
    client._devices_lock = threading.RLock()
    client._validation_timeout = 4.0
    client._monotonic = time.monotonic
    client._stop_event = threading.Event()
    client._last_error = None

    def add_device(
        device_id: str,
        password: str | None = None,
        ip_address: str = "<broadcast>",
        onchange: Any = None,
    ) -> Device:
        device = Device(device_id, password, ip_address, onchange)
        client._devices[device_id] = device
        return device

    monkeypatch.setattr(client, "add_device", add_device)
    monkeypatch.setattr(
        client,
        "_update_device_status",
        lambda device: setattr(device, "_unit_type", 1),
    )

    device = client.validate_device(DEVICE_ID, PASSWORD)

    assert device is not None
    assert device.unit_type == 1
    assert client.get_device_count() == 0


def test_validation_timeout_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """The legacy validation API returns None after its bounded wait."""
    client = DukaClient.__new__(DukaClient)
    client._devices = {}
    client._devices_lock = threading.RLock()
    client._validation_timeout = 4.0
    client._last_error = None
    clock = 0.0

    def now() -> float:
        return clock

    class AdvancingEvent:
        def wait(self, duration: float) -> bool:
            nonlocal clock
            clock += duration
            return False

    def add_device(
        device_id: str,
        password: str | None = None,
        ip_address: str = "<broadcast>",
        onchange: Any = None,
    ) -> Device:
        device = Device(device_id, password, ip_address, onchange)
        client._devices[device_id] = device
        return device

    monkeypatch.setattr(client, "add_device", add_device)
    monkeypatch.setattr(client, "_update_device_status", lambda _device: None)
    client._monotonic = now
    client._stop_event = AdvancingEvent()

    assert client.validate_device(DEVICE_ID, PASSWORD) is None
    assert clock >= 4.0
    assert client.get_device_count() == 0


def test_close_is_idempotent_and_joins_listener(fake_socket: FakeSocket) -> None:
    """Closing twice leaves no live listener thread or open socket."""
    client = DukaClient()
    wait_until(lambda: client._socket_listening)

    client.close()
    client.close()

    assert client._notifythread.is_alive() is False
    assert fake_socket.closed is True
