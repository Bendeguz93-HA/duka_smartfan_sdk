"""Thread-based client for communicating with Duka SmartFan devices."""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from .device import ChangeCallback, Device
from .dukapacket import DukaPacket
from .exceptions import (
    CommandError,
    DeviceUnreachableError,
    DukaSmartFanError,
    DukaTimeoutError,
    MalformedPacketError,
    TransportClosedError,
)
from .responsepacket import ResponsePacket
from .transport import (
    DatagramTransport,
    SocketDatagramTransport,
    TransportFactory,
)

_LOGGER = logging.getLogger(__name__)
FoundDeviceCallback = Callable[[str], None]


class ConnectionState(StrEnum):
    """Observable lifecycle and transport health state."""

    STOPPED = "stopped"
    STARTING = "starting"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class ReconnectPolicy:
    """Bounded exponential reconnect policy."""

    max_attempts: int = 5
    initial_delay: float = 0.25
    maximum_delay: float = 5.0
    jitter_ratio: float = 0.2

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if self.initial_delay < 0 or self.maximum_delay < 0:
            raise ValueError("reconnect delays cannot be negative")
        if self.maximum_delay < self.initial_delay:
            raise ValueError("maximum_delay cannot be less than initial_delay")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be between zero and one")

    def delay(self, attempt: int, random_value: float | None = None) -> float:
        """Return the capped delay before the next attempt."""
        if attempt < 1:
            raise ValueError("attempt must be at least one")
        base_delay: float = min(
            self.maximum_delay,
            self.initial_delay * (2.0 ** (attempt - 1)),
        )
        if self.jitter_ratio == 0 or base_delay == 0:
            return base_delay
        value = random.random() if random_value is None else random_value
        jitter = base_delay * self.jitter_ratio * ((2 * value) - 1)
        return float(max(0.0, min(self.maximum_delay, base_delay + jitter)))


class DukaClient:
    """Manage devices and a lifecycle-controlled UDP listener.

    ``autostart=True`` preserves the historical constructor behavior. New
    callers can pass ``autostart=False`` and call :meth:`start` explicitly.
    In both modes the listener is owned by the client and stopped by
    :meth:`close`.
    """

    def __init__(
        self,
        *,
        transport_factory: TransportFactory | None = None,
        autostart: bool = True,
        socket_timeout: float = 1.0,
        startup_timeout: float = 3.0,
        validation_timeout: float = 4.0,
        reconnect_policy: ReconnectPolicy | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if socket_timeout <= 0 or startup_timeout <= 0 or validation_timeout <= 0:
            raise ValueError("timeouts must be greater than zero")
        self._devices: dict[str, Device] = {}
        self._devices_lock = threading.RLock()
        self._transport_lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self._transport: DatagramTransport | None = None
        self._socket_timeout = socket_timeout
        self._startup_timeout = startup_timeout
        self._validation_timeout = validation_timeout
        self._reconnect_policy = reconnect_policy or ReconnectPolicy()
        self._monotonic = monotonic
        self._transport_factory = transport_factory or self._default_transport_factory

        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._notifyrunning = False
        self._notifythread: threading.Thread | None = None
        self._socket_listening = False
        self._closed = False
        self._state = ConnectionState.STOPPED
        self._last_error: DukaSmartFanError | None = None
        self._reconnect_attempts = 0
        self._found_device_callback: FoundDeviceCallback | None = None

        if autostart:
            self.start()

    def _default_transport_factory(self) -> DatagramTransport:
        return SocketDatagramTransport(timeout=self._socket_timeout)

    @property
    def connection_state(self) -> ConnectionState:
        """Return the current lifecycle/connection state."""
        return self._state

    @property
    def is_healthy(self) -> bool:
        """Return whether the transport is currently connected."""
        return self._state is ConnectionState.CONNECTED

    @property
    def last_error(self) -> DukaSmartFanError | None:
        """Return the latest typed transport or packet error."""
        return self._last_error

    @property
    def reconnect_attempts(self) -> int:
        """Return the number of failed connection attempts."""
        return self._reconnect_attempts

    def start(self) -> None:
        """Start the owned listener thread once."""
        with self._lifecycle_lock:
            if self._closed:
                raise TransportClosedError("client is closed")
            if self._notifythread is not None and self._notifythread.is_alive():
                return
            self._stop_event.clear()
            self._ready_event.clear()
            self._notifyrunning = True
            self._state = ConnectionState.STARTING
            self._notifythread = threading.Thread(
                target=self.__notify_fn,
                name="duka-smartfan-listener",
                daemon=True,
            )
            self._notifythread.start()

    def close(self, timeout: float | None = None) -> None:
        """Stop the listener and release transport/callback resources.

        The method is idempotent. A custom transport that ignores ``close``
        and prevents the listener from terminating produces a typed timeout.
        """
        with self._lifecycle_lock:
            thread = self._notifythread
            if self._closed and (thread is None or not thread.is_alive()):
                return
            self._closed = True
            self._notifyrunning = False
            self._stop_event.set()
            self._close_transport()

        try:
            if thread is not None and thread is not threading.current_thread():
                join_timeout = (
                    timeout if timeout is not None else self._socket_timeout + 1.0
                )
                thread.join(join_timeout)
                if thread.is_alive():
                    error = DukaTimeoutError(
                        "listener thread did not stop before timeout"
                    )
                    self._last_error = error
                    self._state = ConnectionState.DEGRADED
                    raise error

            self._state = ConnectionState.CLOSED
        finally:
            self._release_callbacks()

    def __enter__(self) -> DukaClient:
        """Start and return the client for context-manager use."""
        self.start()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        """Close the client when leaving a context manager."""
        self.close()

    def add_device(
        self,
        device_id: str,
        password: str | None = None,
        ip_address: str = "<broadcast>",
        onchange: ChangeCallback | None = None,
    ) -> Device:
        """Add a device or return the existing device with the same ID."""
        with self._devices_lock:
            device = self._devices.get(device_id)
            if device is None:
                device = Device(device_id, password, ip_address, onchange)
                self._devices[device_id] = device
        packet = DukaPacket()
        packet.initialize_get_firmware_cmd(device)
        self._send_data(device, packet.data)
        return device

    def remove_device(self, device_id: str | Device) -> Device | None:
        """Remove a device by ID or object and return it when present."""
        resolved_id = (
            device_id.device_id if isinstance(device_id, Device) else device_id
        )
        with self._devices_lock:
            return self._devices.pop(resolved_id, None)

    def get_device(self, device_id: str) -> Device | None:
        """Return a device by ID."""
        with self._devices_lock:
            return self._devices.get(device_id)

    def get_device_count(self) -> int:
        """Return the number of registered devices."""
        with self._devices_lock:
            return len(self._devices)

    def search_devices(self, callback: FoundDeviceCallback) -> None:
        """Broadcast discovery and notify ``callback`` for each response."""
        self._found_device_callback = callback
        packet = DukaPacket()
        packet.initialize_search_cmd()
        self._wait_for_transport()
        self._send_raw(packet.data, ("<broadcast>", 4000))

    def turn_off(self, device: Device) -> None:
        """Turn off a device."""
        self._send_command(device, DukaPacket.initialize_off_cmd)

    def turn_on(self, device: Device) -> None:
        """Turn on a device."""
        self._send_command(device, DukaPacket.initialize_on_cmd)

    def turn_boost_off(self, device: Device) -> None:
        """Turn off boost."""
        self._send_command(device, DukaPacket.initialize_boost_off_cmd)

    def turn_boost_on(self, device: Device) -> None:
        """Turn on boost."""
        self._send_command(device, DukaPacket.initialize_boost_on_cmd)

    def toggle_boost(self, device: Device) -> None:
        """Toggle boost."""
        self._send_command(device, DukaPacket.initialize_boost_toggle_cmd)

    def validate_device(
        self,
        device_id: str,
        password: str | None = None,
        ip_address: str = "<broadcast>",
        *,
        timeout: float | None = None,
        raise_on_error: bool = False,
    ) -> Device | None:
        """Validate a device within a bounded wait.

        The legacy default returns ``None`` on timeout. Set ``raise_on_error``
        to receive :class:`DukaTimeoutError` instead.
        """
        existing = self.get_device(device_id)
        if existing is not None:
            return existing
        device: Device | None = None
        try:
            device = self.add_device(device_id, password, ip_address)
            self._update_device_status(device)
            deadline = self._monotonic() + (
                self._validation_timeout if timeout is None else timeout
            )
            while device.unit_type is None:
                remaining = deadline - self._monotonic()
                if remaining <= 0:
                    error = DukaTimeoutError("device validation timed out")
                    self._last_error = error
                    if raise_on_error:
                        raise error
                    return None
                self._stop_event.wait(min(0.1, remaining))
            return device
        except DukaSmartFanError:
            if raise_on_error:
                raise
            return None
        finally:
            if device is not None:
                self.remove_device(device)

    def _send_command(
        self,
        device: Device,
        initializer: Callable[[DukaPacket, Device], None],
    ) -> None:
        packet = DukaPacket()
        initializer(packet, device)
        self._send_data(device, packet.data)

    def _update_device_status(self, device: Device) -> None:
        packet = DukaPacket()
        packet.initialize_status_cmd(device)
        self._send_data(device, packet.data)

    def _update_all_device_status(self) -> None:
        with self._devices_lock:
            devices = tuple(self._devices.values())
        for device in devices:
            self._update_device_status(device)

    def _send_data(self, device: Device, data: bytes | bytearray) -> None:
        self._wait_for_transport()
        self._send_raw(data, (device.ip_address, 4000))

    def _send_raw(self, data: bytes | bytearray, address: tuple[str, int]) -> None:
        try:
            with self._transport_lock:
                transport = self._transport
                if transport is None:
                    raise TransportClosedError("UDP transport is not connected")
                transport.send(data, address)
        except (DeviceUnreachableError, TransportClosedError) as err:
            self._mark_disconnected(err)
            raise CommandError(f"unable to send command to {address[0]}") from err

    def _wait_for_transport(self) -> None:
        if self._closed:
            raise TransportClosedError("client is closed")
        thread = self._notifythread
        if thread is None or not thread.is_alive():
            self.start()
        if not self._ready_event.wait(self._startup_timeout):
            error = DukaTimeoutError("timed out waiting for UDP transport")
            self._last_error = error
            raise error
        with self._transport_lock:
            if self._transport is None or not self._transport.is_open:
                raise TransportClosedError("UDP transport is not connected")

    def _connect_transport(self) -> bool:
        for attempt in range(1, self._reconnect_policy.max_attempts + 1):
            if self._stop_event.is_set():
                return False
            self._state = ConnectionState.CONNECTING
            transport: DatagramTransport | None = None
            try:
                transport = self._transport_factory()
                transport.open()
            except DukaSmartFanError as err:
                error = err
            except OSError as err:
                error = DeviceUnreachableError("unable to open UDP transport")
                error.__cause__ = err
            else:
                with self._transport_lock:
                    self._transport = transport
                    self._socket_listening = True
                    self._ready_event.set()
                self._last_error = None
                self._state = ConnectionState.CONNECTED
                return True

            if transport is not None:
                transport.close()
            self._reconnect_attempts += 1
            self._last_error = error
            if attempt >= self._reconnect_policy.max_attempts:
                _LOGGER.error(
                    "UDP transport unavailable after %s attempts: %s",
                    attempt,
                    error,
                )
                break
            delay = self._reconnect_policy.delay(attempt)
            _LOGGER.warning(
                "UDP transport connection attempt %s failed; retrying in %.3fs",
                attempt,
                delay,
            )
            if self._stop_event.wait(delay):
                return False

        self._state = ConnectionState.DEGRADED
        return False

    def _close_transport(self) -> None:
        with self._transport_lock:
            transport, self._transport = self._transport, None
            self._socket_listening = False
            self._ready_event.clear()
        if transport is not None:
            transport.close()

    def _mark_disconnected(self, error: DukaSmartFanError) -> None:
        self._last_error = error
        self._state = ConnectionState.DEGRADED
        self._close_transport()

    def _receive_data(self) -> tuple[bytes, tuple[str, int]] | None:
        with self._transport_lock:
            transport = self._transport
        if transport is None:
            raise TransportClosedError("UDP transport is not connected")
        try:
            return transport.receive(1024)
        except DukaTimeoutError:
            self._update_all_device_status()
            return None

    def __notify_fn(self) -> None:
        try:
            while not self._stop_event.is_set():
                if self._transport is None and not self._connect_transport():
                    break
                try:
                    received = self._receive_data()
                except DukaSmartFanError as err:
                    if self._stop_event.is_set():
                        break
                    self._mark_disconnected(err)
                    continue
                if received is None:
                    continue
                data, address = received
                try:
                    packet = ResponsePacket.parse(data)
                except MalformedPacketError as err:
                    self._last_error = err
                    continue
                self._handle_packet(packet, address[0])
        finally:
            self._close_transport()
            self._notifyrunning = False
            if self._closed:
                self._state = ConnectionState.CLOSED
            elif self._state is not ConnectionState.DEGRADED:
                self._state = ConnectionState.STOPPED

    def _handle_packet(self, packet: ResponsePacket, ip_address: str) -> None:
        search_device_id = packet.search_device_id
        callback = self._found_device_callback
        if search_device_id is not None and callback is not None:
            try:
                callback(search_device_id)
            except Exception:  # callbacks are application-owned
                _LOGGER.exception("device discovery callback failed")

        device_id = packet.device_id
        if device_id is None:
            return
        with self._devices_lock:
            device = self._devices.get(device_id)
        if device is None:
            return
        self.update_device(device, ip_address, packet)

    def update_device(
        self, device: Device, ip_address: str, packet: ResponsePacket
    ) -> None:
        """Update a device from a decoded response packet."""
        has_change = False
        if device._ip_address is not None and ip_address != device._ip_address:
            device._ip_address = ip_address
            has_change = True
        if packet.fan_speed is not None and bool(packet.fan_speed) != device._is_active:
            device._is_active = bool(packet.fan_speed)
            has_change = True
        if packet.humidity is not None and packet.humidity != device._humidity:
            device._humidity = packet.humidity
            has_change = True
        if packet.temperature is not None and packet.temperature != device._temperature:
            device._temperature = packet.temperature
            has_change = True
        if packet.firmware_version is not None:
            device._firmware_version = packet.firmware_version
        if packet.firmware_date is not None:
            device._firmware_date = packet.firmware_date
        if packet.unit_type is not None:
            device._unit_type = packet.unit_type

        callback = device._changeevent
        if has_change and callback is not None:
            try:
                callback(device)
            except Exception:  # callbacks are application-owned
                _LOGGER.exception("device change callback failed")
        if packet.fan_speed is not None and packet.fan_speed != device._fan_speed:
            device._fan_speed = packet.fan_speed

    def _release_callbacks(self) -> None:
        self._found_device_callback = None
        with self._devices_lock:
            devices = tuple(self._devices.values())
        for device in devices:
            device._changeevent = None
