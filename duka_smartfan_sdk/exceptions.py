"""Public exception hierarchy for Duka SmartFan SDK failures."""


class DukaSmartFanError(Exception):
    """Base class for all public SDK errors."""


class AuthenticationError(DukaSmartFanError):
    """The device rejected authentication credentials."""


class DeviceUnreachableError(DukaSmartFanError):
    """The device or local UDP endpoint cannot be reached."""


class DukaTimeoutError(DukaSmartFanError, TimeoutError):
    """An SDK operation exceeded its configured timeout."""


class MalformedPacketError(DukaSmartFanError, ValueError):
    """A received packet is incomplete or violates the protocol framing."""


class TransportClosedError(DukaSmartFanError):
    """An operation was attempted on a closed transport or client."""


class CommandError(DukaSmartFanError):
    """A device command could not be sent."""
