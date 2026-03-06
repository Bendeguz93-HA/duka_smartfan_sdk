"""Implements the duka smartfan wifi device class"""

import asyncio
import time
from typing import Callable


class Device:
    """A class representing a single Duka Smartfan Wifi Device"""

    def __init__(
        self,
        deviceid: str,
        password: str | None = None,
        ip_address: str = "<broadcast>",
        onchange: Callable[["Device"], None] | None = None,
    ):
        self._id = deviceid
        self._password = password
        self._ip_address = ip_address
        self._is_active: bool | None = None
        self._fan_speed: int | None = None
        self._humidity: int | None = None
        self._temperature: int | None = None
        self._changeevent = onchange
        self._firmware_version: str | None = None
        self._firmware_date: str | None = None
        self._unit_type: int | None = None

    @property
    def device_id(self) -> str:
        """Return  the device id"""
        return self._id

    @property
    def password(self) -> str:
        """Return the password for the device"""
        if self._password:
            return self._password
        return "1111"

    @property
    def ip_address(self) -> str:
        """Return the IP of the device"""
        return self._ip_address

    @property
    def is_active(self) -> bool | None:
        """Return whether the device is active"""
        return self._is_active

    @property
    def fan_speed(self) -> int | None:
        """Return the fan_speed of the device"""
        return self._fan_speed

    @property
    def temperature(self) -> int | None:
        """Return the temperature."""
        return self._temperature

    @property
    def humidity(self) -> int | None:
        """Return the humidity."""
        return self._humidity

    @property
    def firmware_version(self) -> str | None:
        """Return the firmware version of the duka one device"""
        return self._firmware_version

    @property
    def firmware_date(self) -> str | None:
        """return the firmware date"""
        return self._firmware_date

    @property
    def unit_type(self) -> int | None:
        return self._unit_type

    def is_initialized(self) -> bool:
        """Returns True if the device has initilized.

        The device is initialized once the get initial get firmware packet has been received.
        This packet is sent when the device is added to the client
        """
        return self.firmware_version is not None

    def wait_for_initialize(self) -> None:
        timeout = time.time() + 2
        while self.firmware_version is None and time.time() < timeout:
            time.sleep(0.1)

    async def wait_for_initialize_async(self) -> None:
        timeout = time.time() + 2
        while self.firmware_version is None and time.time() < timeout:
            await asyncio.sleep(0.1)
