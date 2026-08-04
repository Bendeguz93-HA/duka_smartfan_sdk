"""Characterize packet encoding and decoding at the audited baseline."""

from __future__ import annotations

import pytest

from duka_smartfan_sdk.device import Device
from duka_smartfan_sdk.dukapacket import DukaPacket
from duka_smartfan_sdk.responsepacket import ResponsePacket


DEVICE_ID = "1234567890123456"
PASSWORD = "1111"
KNOWN_RESPONSE = bytes.fromhex(
    "fdfd021031323334353637383930313233343536043131313106"
    "010104d2042e3731178601020408ea07b934123008"
)


@pytest.mark.parametrize(
    ("initializer", "expected_hex"),
    [
        (
            "initialize_on_cmd",
            "fdfd02103132333435363738393031323334353604313131310301012104",
        ),
        (
            "initialize_off_cmd",
            "fdfd02103132333435363738393031323334353604313131310301002004",
        ),
        (
            "initialize_boost_on_cmd",
            "fdfd02103132333435363738393031323334353604313131310305012504",
        ),
        (
            "initialize_boost_off_cmd",
            "fdfd02103132333435363738393031323334353604313131310305002404",
        ),
        (
            "initialize_boost_toggle_cmd",
            "fdfd02103132333435363738393031323334353604313131310305022604",
        ),
        (
            "initialize_status_cmd",
            "fdfd021031323334353637383930313233343536043131313101010203042e31b93f05",
        ),
        (
            "initialize_get_firmware_cmd",
            "fdfd02103132333435363738393031323334353604313131310186b95c05",
        ),
    ],
)
def test_device_command_encoding(initializer: str, expected_hex: str) -> None:
    """Existing commands have stable, byte-for-byte wire representations."""
    packet = DukaPacket()
    getattr(packet, initializer)(Device(DEVICE_ID, PASSWORD))

    assert packet.data.hex() == expected_hex


def test_search_packet_encoding() -> None:
    """Device discovery keeps its existing broadcast packet."""
    packet = DukaPacket()
    packet.initialize_search_cmd()

    assert packet.data.hex() == (
        "fdfd021044454641554c545f444556494345494400017c3005"
    )


def test_checksum_is_little_endian_sum_from_protocol_version() -> None:
    """The checksum excludes the two marker bytes and is little endian."""
    packet = DukaPacket()
    packet.initialize_on_cmd(Device(DEVICE_ID, PASSWORD))
    data = packet.data

    expected = sum(data[2:-2]) & 0xFFFF
    actual = data[-2] | (data[-1] << 8)

    assert actual == expected


def test_known_response_decodes_sensor_and_device_values() -> None:
    """A captured-format response exposes current public sensor values."""
    packet = ResponsePacket()

    assert packet.initialize_from_data(KNOWN_RESPONSE)
    assert packet.device_id == DEVICE_ID
    assert packet.device_password == PASSWORD
    assert packet.is_on is True
    assert packet.fan_speed == 1234
    assert packet.humidity == 55
    assert packet.temperature == 23
    assert packet.firmware_version == "1.2"
    assert packet.firmware_date == "4-8-2026"
    assert packet.unit_type == 0x34


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"\xfd\xfd\x02",
        b"\x00\xfd\x02\x00",
        KNOWN_RESPONSE[:-1],
        KNOWN_RESPONSE[:-2] + b"\x00\x00",
    ],
)
def test_malformed_or_bad_checksum_packets_are_rejected(payload: bytes) -> None:
    """Malformed packets fail closed without leaking parser exceptions."""
    assert ResponsePacket().initialize_from_data(payload) is False


def test_unknown_parameter_is_rejected() -> None:
    """A response containing a normal unknown parameter is rejected."""
    prefix = bytearray.fromhex(
        "fdfd021031323334353637383930313233343536043131313106aa00"
    )
    checksum = sum(prefix[2:]) & 0xFFFF
    payload = bytes(prefix + bytes((checksum & 0xFF, checksum >> 8)))

    assert ResponsePacket().initialize_from_data(payload) is False
