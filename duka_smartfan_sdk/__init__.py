"""
Duka Smartfan Wifi SDK
This is a Python module for making a connection to a Duka Smartfan Wifi
"""

from .device import Device
from .dukaclient import ConnectionState, DukaClient, ReconnectPolicy
from .exceptions import (
    AuthenticationError,
    CommandError,
    DeviceUnreachableError,
    DukaSmartFanError,
    DukaTimeoutError,
    MalformedPacketError,
    TransportClosedError,
)
from .transport import DatagramTransport, SocketDatagramTransport, TransportFactory

__all__ = [
    "AuthenticationError",
    "CommandError",
    "ConnectionState",
    "DatagramTransport",
    "Device",
    "DeviceUnreachableError",
    "DukaClient",
    "DukaSmartFanError",
    "DukaTimeoutError",
    "MalformedPacketError",
    "ReconnectPolicy",
    "SocketDatagramTransport",
    "TransportClosedError",
    "TransportFactory",
]
