"""Implements a class for the UDP data packet"""

from .dukapacket import DukaPacket
from .exceptions import MalformedPacketError


class ResponsePacket(DukaPacket):
    """A udp data packet from the duka device."""

    parameter_size = {
        0x01: 1,  # On off 0-2 (off, on, invert)
        0x02: 1,  # Battery status 0-1 (discharged, normal rate)
        0x03: 1,  # 24 hour mode 0-1 (off, on, invert)
        0x04: 2,  # Fan speed (0-6000 RPM)
        0x05: 1,  # Boost mode
        0x06: 3,  # Boost mode countdown timer in seconds (1794sec)
        0x07: 1,  # Current status of the built-in timer 0-1 (off, on)
        0x08: 1,  # Current status of fan operation by humidity sensor 0-1 (off, on)
        0x0A: 1,  # Current status of fan operation by temperature sensor 0-1 (off, on)
        0x0B: 1,  # Current status of fan operation by motion sensor 0-1 (off, on)
        0x0C: 1,  # Current status of fan operation by signal from an external switch 0-1 (off, on)
        0x0D: 1,  # Current status of fan operation in interval ventilation mode 0-1 (off, on)
        0x0E: 1,  # Current status of fan operation in SILENT mode 0-1 (off, on)
        0x0F: 1,  # Permission of operation based on humidity sensor readings 0-2 (off, automatic, manual)
        0x11: 1,  # Permission of operation based on temperature sensor readings (off, on, invert)
        0x12: 1,  # Permission of operation based on motion sensor readings (off, on, invert)
        0x13: 1,  # Permission of operation based on signal from an external switch
        0x14: 1,  # Humidity manual mode percentage (0-100)
        0x16: 1,  # Temperature mode temperature (18-36)
        0x17: 1,  # ??? (10)
        0x18: 1,  # Max mode percentage (30-100)
        0x1A: 1,  # Silent mode percentage (30-100)
        0x1B: 1,  # Interval ventilation percentage (30-100)
        0x1D: 1,  # Interval ventilation mode (off, on, invert)
        0x1E: 1,  # Silent mode activation (off, on, invert)
        0x1F: 3,  # Silent mode start time in seconds (72000sec)
        0x20: 3,  # Silent mode end time in seconds (25200sec)
        0x21: 3,  # Current time of the fan internal clock in seconds
        0x23: 1,  # Turn off delay timer/Boost setpoint 0,2,3,4,6 (5, 15, 30, 60min)
        0x24: 1,  # Turn on delay timer 0,1,2 (0, 2, 5min)
        0x25: 1,  # Resetting parameters to factory settings
        0x2E: 1,  # Humidity (0-100)
        0x31: 1,  # Temperature
        0x7C: 16,  # Device search
        0x86: 6,  # Firmware version and date
        0x94: 1,  # Wifi mode
        0x95: 0,  # Wifi name in client mode
        0x96: 0,  # Wifi password
        0x99: 1,  # Wifi encryption
        0x9A: 1,  # Wifi channel 1-13
        0x9B: 1,  # Wifi DHCP
        0x9C: 4,  # IP Address
        0x9D: 4,  # Subnet mask
        0x9E: 4,  # Gateway
        0xA3: 4,  # Current wifi module IP address
        0xB9: 2,  # Unit type
    }

    def __init__(self) -> None:
        super().__init__()
        self.device_id: str | None = None
        self.device_password: str | None = None
        self.is_on: bool | None = None
        self.battery_status: int | None = None
        self.temperature: int | None = None
        self.fan_speed: int | None = None
        self.humidity: int | None = None
        self.search_device_id: str | None = None
        self.firmware_version: str | None = None
        self.firmware_date: str | None = None
        self.unit_type: int | None = None

    @classmethod
    def parse(cls, data: bytes | bytearray) -> "ResponsePacket":
        """Parse a response or raise :class:`MalformedPacketError`."""
        packet = cls()
        packet._initialize_or_raise(data)
        return packet

    def initialize_from_data(self, data: bytes | bytearray) -> bool:
        """Initialize a packet from data revieved from the device
        Returns False if the data is invalid
        """
        try:
            self._initialize_or_raise(data)
        except (IndexError, MalformedPacketError, TypeError, ValueError):
            return False
        return True

    def _initialize_or_raise(self, data: bytes | bytearray) -> None:
        """Initialize internal fields from one validated datagram."""
        self._data = bytearray(data)
        self._pos = 0
        size = len(data)
        if size < 8 or not self.is_header_ok():
            raise MalformedPacketError("invalid packet header or minimum length")
        checksum = self.calc_checksum(size - 2)
        data_checksum = self._data[size - 2] + (self._data[size - 1] << 8)
        if checksum != data_checksum:
            raise MalformedPacketError("packet checksum mismatch")
        self.device_id = self.read_string()
        self.device_password = self.read_string()
        if self.read_byte() != self.Func.RESPONSE.value:
            raise MalformedPacketError("packet is not a response")
        if not self.read_parameters():
            raise MalformedPacketError("packet contains an unknown parameter")

    def is_header_ok(self) -> bool:
        if self.read_byte() != 0xFD or self.read_byte() != 0xFD:
            return False
        return self.read_byte() == 0x02

    def read_byte(self) -> int:
        byte = self._data[self._pos]
        self._pos = self._pos + 1
        return byte

    def read_string(self) -> str:
        strlen = self.read_byte()
        txt = ""
        for i in range(self._pos, self._pos + strlen):
            txt += chr(self._data[i])
        self._pos += strlen
        return txt

    def debug_parameter(self, parameter: int, size: int) -> str:
        return ", ".join(
            [
                str(parameter),
                str(size),
                str(sum([self._data[self._pos + x] << 8 * x for x in range(size)])),
            ]
        )

    def read_parameters(self) -> bool:
        while self._pos < len(self._data) - 3:
            parameter = self.read_byte()
            size = 1
            if parameter == 0xFE:
                # change parameter size
                size = self.read_byte()
                parameter = self.read_byte()
            else:
                if parameter not in self.parameter_size:
                    return False
                size = self.parameter_size[parameter]

            if self._pos + size > len(self._data) - 2:
                raise MalformedPacketError("parameter payload exceeds packet boundary")

            if parameter == self.Parameters.ON_OFF.value:
                self.is_on = self._data[self._pos] != 0
            if parameter == self.Parameters.BATTERY_STATUS.value:
                self.battery_status = self._data[self._pos]
            elif parameter == self.Parameters.TEMPERATURE.value:
                self.temperature = self._data[self._pos]
            elif parameter == self.Parameters.FAN_SPEED.value:
                self.fan_speed = self._data[self._pos] + (
                    self._data[self._pos + 1] << 8
                )
            elif parameter == self.Parameters.HUMIDITY.value:
                self.humidity = self._data[self._pos]
            elif parameter == self.Parameters.READ_FIRMWARE_VERSION.value:
                major = self._data[self._pos]
                minor = self._data[self._pos + 1]
                self.firmware_version = f"{major}.{minor}"
                day = self._data[self._pos + 2]
                month = self._data[self._pos + 3]
                year = self._data[self._pos + 4] + (self._data[self._pos + 5] << 8)
                self.firmware_date = f"{day}-{month}-{year}"
            elif parameter == self.Parameters.UNIT_TYPE.value:
                self.unit_type = self._data[self._pos]
            elif parameter == self.Parameters.DEVICE_SEARCH.value:
                self.search_device_id = ""
                for i in range(self._pos, self._pos + 16):
                    self.search_device_id += chr(self._data[i])

            self._pos += size

        return True
