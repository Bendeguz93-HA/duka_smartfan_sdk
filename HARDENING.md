# Phase 2B hardening record

## Provenance baseline

- GitHub fork: `Bendeguz93-HA/duka_smartfan_sdk`
- Direct fork parent: `syre/duka_smartfan_sdk`
- Historical source shown by GitHub: `dingusdk/dukaonesdk`
- Audited base commit: `9442ba25dbbc599dbad4b3e7005d074a6ff455c5`
- Base Git tree: `ec4b7049349b7735de3d92ef7ee98d0c064f20e6`
- Root commit: `ee7e69e964d28fb21794c61e5284e63e1d26596c`
- GPL license SHA-256:
  `8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903`
- Development branch: `hardening/phase-2b`

The branch was created directly from the audited base. `HEAD`, the working
tree, and the Git tree matched that base before the first test change. The GPL
license file and inherited Git history remain unchanged.

No code, comments, structure, or tests were copied from `ha-dukasmartfan` or
`ha-dukaone`. This work is derived only from the SDK repository and its public
wire behavior.

## Implemented hardening

- characterization tests for command packets, checksums, known responses,
  malformed packets, unknown parameters, validation, callbacks, commands,
  sensor state, and shutdown;
- injectable `DatagramTransport` boundary and hardware-free fake transports;
- public exception hierarchy for authentication, unreachable devices,
  timeout, malformed packets, closed transports, and command failures;
- explicit, idempotent lifecycle with a managed daemon listener and context
  manager support;
- configurable startup, validation, and socket timeouts using monotonic
  deadlines;
- bounded exponential reconnect with a maximum delay, bounded jitter, health
  state, and finite logging;
- public API typing and a packaged `py.typed` marker;
- Ruff format/lint, strict package typecheck, tests, coverage, package build
  check, and public GitHub Actions CI without publishing credentials or steps.

`is_healthy` reports only whether the client's local UDP transport is open.
It does not prove that a remote fan is reachable or responding; remote
responsiveness requires a successful response or higher-level validation.

## CI reproducibility

- uv is pinned to `0.12.1`, dependency resolution is committed in `uv.lock`,
  and CI sync/run commands use frozen mode;
- `actions/checkout` is pinned to immutable commit
  `3d3c42e5aac5ba805825da76410c181273ba90b1` (`v7.0.1`);
- `astral-sh/setup-uv` is pinned to immutable commit
  `c771a70e6277c0a99b617c7a806ffedaca235ff9` (`v9.0.0`).

Both pinned action releases declare a Node 24 runtime, replacing the reviewed
Node 20 actions that GitHub had warned it was forcing to Node 24.

## Backward compatibility

The following behavior is intentionally preserved:

- `DukaClient()` autostarts by default;
- existing device, on/off, boost, discovery, validation, sensor, and callback
  methods remain available;
- `validate_device()` returns `None` on timeout unless the new
  `raise_on_error=True` option is selected;
- `ResponsePacket.initialize_from_data()` continues to return `False` for an
  invalid packet;
- characterized on/off, boost, status, firmware, and discovery payloads are
  byte-identical to the audited base;
- RPM-only updates still do not invoke the device change callback.

Potential breaking-change risks:

- command transport failures now surface as `CommandError` with a typed cause
  instead of leaking an arbitrary socket exception;
- callback exceptions are logged and contained instead of terminating the
  listener thread;
- `close()` releases callback references and a custom transport that refuses
  to stop can produce `DukaTimeoutError`;
- malformed packet parsing now resets parser position and offers a strict
  `ResponsePacket.parse()` API in addition to the legacy boolean API.

These changes do not alter the packet protocol. **Unverified:** behavior with
physical fan firmware and network-loss timing still requires a separately
approved hardware test. The protocol does not currently expose a verified
negative-authentication response, so `AuthenticationError` is public for API
stability but is not raised speculatively.

## License gate

The existing discrepancy is intentionally preserved:

- README: GPL-3.0-or-later wording;
- `pyproject.toml`: `GPL-3.0-only`.

Phase 2B does not determine the authoritative SPDX expression. Stop before a
release build, tag, PyPI publication, or Home Assistant Core dependency use
until the relevant rights holders document the intended expression. The CI
package build is only a non-publishing integrity check.

## Rollback

The hardening branch can be rolled back without affecting upstream, Home
Assistant, or HACS by closing its pull request or resetting the fork branch to
the audited base commit. No tag, package publication, Core code, migration, or
runtime change is part of this phase.
