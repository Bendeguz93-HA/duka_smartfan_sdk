# Introduction

This is a Python module for making a connection to a [Duka Smartfan Wifi](https://dukaventilation.dk/produkter/ventilatorer-styringer-og-tilbehoer/smartfan-wi-fi).

Forked from and heavily inspired by the great [dingusdk dukaonesdk package](https://github.com/dingusdk/dukaonesdk) for connecting with a Duka One.

The primary goal for this module is to make an interface from Home Assistant to Duka Smartfan Wifi.

The module implements:

* On/Off
* Boost mode
* Notification when a state changes.
* Hardware-independent transport injection for deterministic tests.
* Typed transport, timeout, packet, authentication and command errors.

## Lifecycle and transport

`DukaClient()` keeps the historical autostart behavior. New callers can own
the lifecycle explicitly, which is recommended for applications that need
deterministic startup and shutdown:

```python
from duka_smartfan_sdk import DukaClient

client = DukaClient(autostart=False)
client.start()
try:
    device = client.add_device("DEVICE_IDENTIFIER")
finally:
    client.close()
```

`close()` is idempotent. The client also supports a context manager. A custom
`DatagramTransport` factory can be injected for tests; the default transport
uses broadcast-capable UDP on port 4000.

Connection health is exposed through `connection_state`, `is_healthy`,
`last_error`, and `reconnect_attempts`. Reconnect uses a finite exponential
backoff policy with a maximum delay and bounded jitter. `is_healthy` means
only that the client's local UDP transport is open; it does not prove that a
remote fan is reachable or responding. Remote responsiveness requires a
successful response or higher-level validation.

## Development status

The phase 2B hardening work is based on upstream commit
`9442ba25dbbc599dbad4b3e7005d074a6ff455c5`. Tests do not require a fan,
Home Assistant, HACS, or network access. See [HARDENING.md](HARDENING.md) for
the provenance baseline, compatibility notes, checks, and remaining hardware
verification.
 
## Example

See the example.py file

Have a look at http://www.dingus.dk/ for the original implementation.

## Other compatible devices

There are other devices for which this package should also work:
* Blauberg Smart Wi-fi

[You can see the documentation from Blauberg here](https://blaubergventilatoren.de/uploads/download/b168_1en_01preview.pdf)

# License

duka_smartfan_sdk is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

duka_smartfan_sdk is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this library.  If not, see <http://www.gnu.org/licenses/>.

The README text above says GPL version 3 or later, while `pyproject.toml`
currently declares `GPL-3.0-only`. Phase 2B does not choose between those
expressions. The discrepancy must be resolved by the relevant rights holders
before a release build, tag, PyPI publication, or Home Assistant Core
dependency proposal.
