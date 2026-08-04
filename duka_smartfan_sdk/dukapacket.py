"""Implements a class for the UDP data packet."""

from enum import Enum
from typing import Final

from .device import Device


class DukaPacket:
    """A udp data packet to/from the duka device."""

    class Func(Enum):
        READ = 1
        WRITE = 2
        WRITEREAD = 3
        INCREAD = 4
        DECREAD = 5
        RESPONSE = 6

    class Parameters(Enum):
        ON_OFF = 0x01
        BATTERY_STATUS = 0x02
        TWENTY_FOUR_HOUR_MODE = 0x03
        FAN_SPEED = 0x04
        BOOST_MODE = 0x05
        BOOST_MODE_COUNTDOWN_TIMER = 0x06
        BUILTIN_TIMER_STATUS = 0x07
        HUMIDITY_SENSOR_STATUS = 0x08
        TEMPERATURE_SENSOR_STATUS = 0x0A
        MOTION_SENSOR_STATUS = 0x0B
        EXTERNAL_SWITCH_STATUS = 0x0C
        INTERNAL_VENTILATION_MODE_STATUS = 0x0D
        SILENT_MODE_STATUS = 0x0E
        HUMIDITY_MODE = 0x0F
        TEMPERATURE_MODE = 0x11
        MOTION_MODE = 0x12
        EXTERNAL_SWITCH_MODE = 0x13
        HUMIDITY_MANUAL_MODE_PERCENTAGE = 0x14
        TEMPERATURE_MODE_TEMPERATURE = 0x16
        ONE_SEVEN = 0x17
        MAX_MODE_PERCENTAGE = 0x18
        SILENT_MODE_PERCENTAGE = 0x1A
        INTERVAL_VENTILATION_PERCENTAGE = 0x1B
        INTERVAL_VENTILATION_ACTIVATION = 0x1D
        SILENT_MODE_ACTIVATION = 0x1E
        SILENT_MODE_START = 0x1F
        SILENT_MODE_END = 0x20
        FAN_INTERNAL_CLOCK_TIME = 0x21
        TURN_OFF_DELAY_TIMER = 0x23
        TURN_ON_DELAY_TIMER = 0x24
        RESET_TO_FACTORY_SETTINGS = 0x25
        HUMIDITY = 0x2E
        TEMPERATURE = 0x31
        DEVICE_SEARCH = 0x7C
        READ_FIRMWARE_VERSION = 0x86
        WIFI_MODE = 0x94
        WIFI_NAME = 0x95
        WIFI_PASSWORD = 0x96
        WIFI_ENCRYPTION = 0x99
        WIFI_FREQUENCY = 0x9A
        WIFI_DHCP = 0x9B
        WIFI_IP_ADDRESS = 0x9C
        WIFI_SUBNET_MASK = 0x9D
        WIFI_GATEWAY = 0x9E
        WIFI_APPLY_PARAMETERS = 0xA0
        WIFI_MODULE_IP_ADDRESS = 0xA3
        UNIT_TYPE = 0xB9

    def __init__(self) -> None:
        self._data = bytearray()
        self._pos = 0
        self.maxsize: Final = 200

    def initialize_search_cmd(self) -> None:
        """Initialize a search command packet"""
        self.__build_data("DEFAULT_DEVICEID", "")
        self.__add_byte(DukaPacket.Func.READ.value)
        self.__add_byte(DukaPacket.Parameters.DEVICE_SEARCH.value)
        self.__add_checksum()

    def initialize_on_cmd(self, device: Device) -> None:
        """Initialize a ON command packet to be sent to a device"""
        self.__build_data(device.device_id, device.password)
        self.__add_byte(DukaPacket.Func.WRITEREAD.value)
        self.__add_byte(DukaPacket.Parameters.ON_OFF.value)
        self.__add_byte(0x01)
        self.__add_checksum()

    def initialize_off_cmd(self, device: Device) -> None:
        """Initialize a Off command packet to be sent to a device"""
        self.__build_data(device.device_id, device.password)
        self.__add_byte(DukaPacket.Func.WRITEREAD.value)
        self.__add_byte(DukaPacket.Parameters.ON_OFF.value)
        self.__add_byte(0x00)
        self.__add_checksum()

    def initialize_boost_toggle_cmd(self, device: Device) -> None:
        """Initialize a Boost toggle command packet to be sent to a device"""
        self.__build_data(device.device_id, device.password)
        self.__add_byte(DukaPacket.Func.WRITEREAD.value)
        self.__add_byte(DukaPacket.Parameters.BOOST_MODE.value)
        self.__add_byte(0x02)
        self.__add_checksum()

    def initialize_boost_on_cmd(self, device: Device) -> None:
        """Initialize a Boost on command packet to be sent to a device"""
        self.__build_data(device.device_id, device.password)
        self.__add_byte(DukaPacket.Func.WRITEREAD.value)
        self.__add_byte(DukaPacket.Parameters.BOOST_MODE.value)
        self.__add_byte(0x01)
        self.__add_checksum()

    def initialize_boost_off_cmd(self, device: Device) -> None:
        """Initialize a Boost off command packet to be sent to a device"""
        self.__build_data(device.device_id, device.password)
        self.__add_byte(DukaPacket.Func.WRITEREAD.value)
        self.__add_byte(DukaPacket.Parameters.BOOST_MODE.value)
        self.__add_byte(0x00)
        self.__add_checksum()

    def initialize_status_cmd(self, device: Device) -> None:
        """Initialize a status command packet to be sent to a device"""
        self.__build_data(device.device_id, device.password)
        self.__add_byte(self.Func.READ.value)
        self.__add_byte(self.Parameters.ON_OFF.value)
        self.__add_byte(self.Parameters.BATTERY_STATUS.value)
        self.__add_byte(self.Parameters.TWENTY_FOUR_HOUR_MODE.value)
        self.__add_byte(self.Parameters.FAN_SPEED.value)
        self.__add_byte(self.Parameters.HUMIDITY.value)
        self.__add_byte(self.Parameters.TEMPERATURE.value)
        self.__add_byte(self.Parameters.UNIT_TYPE.value)
        self.__add_checksum()

    def initialize_get_firmware_cmd(self, device: Device) -> None:
        """Initialize a get firmware command packet to be sent to a
        device"""
        self.__build_data(device.device_id, device.password)
        self.__add_byte(self.Func.READ.value)
        self.__add_byte(self.Parameters.READ_FIRMWARE_VERSION.value)
        self.__add_byte(self.Parameters.UNIT_TYPE.value)
        self.__add_checksum()

    @property
    def data(self) -> bytearray:
        """Return the data for the packet"""
        return self._data[0 : self._pos]

    def __add_byte(self, byte: int) -> None:
        """Add a byte to the packet"""
        self._data[self._pos] = byte
        self._pos += 1

    def __build_data(self, device_id: str, password: str) -> None:
        """Build a packet of the specified size"""
        self._data = bytearray(self.maxsize)
        self._pos = 0
        self.__add_byte(0xFD)
        self.__add_byte(0xFD)
        self.__add_byte(0x02)
        self.__add_byte(len(device_id))
        for char in device_id:
            self.__add_byte(ord(char))
        self.__add_byte(len(password))
        for char in password:
            self.__add_byte(ord(char))

    def __add_parameter(self, parameter: int, value: int) -> None:
        self.__add_byte(parameter)
        self.__add_byte(value)

    def __add_checksum(self) -> None:
        """Add a checksum to the packet"""
        checksum = self.calc_checksum(self._pos)
        self.__add_byte(checksum & 0xFF)
        self.__add_byte(checksum >> 8)

    def calc_checksum(self, size: int) -> int:
        """Calculate the check sum for the packet"""
        checksum: int = 0
        for i in range(2, size):
            checksum += self._data[i]
        return checksum & 0xFFFF
