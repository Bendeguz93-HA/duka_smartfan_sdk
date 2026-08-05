# DUKA SmartFan SDK phase 2C hardware validation

This procedure validates the merged phase 2B SDK against a physical fan while
keeping the active Home Assistant installation recoverable.

The validation branch starts from SDK merge commit
`be693a62e1c939c19013d96317af060591a68e4c`. The branch adds only this
procedure and `tools/hardware_validation.py`; it must not change protocol or
production SDK behavior.

## Safety rules

- Be physically present and able to see/hear the fan.
- Run the test when nobody needs the bathroom ventilation.
- Confirm that the DUKA app can still control the fan before starting.
- Do not store the raw device ID, password, or IP address in GitHub.
- Do not run the SDK test client at the same time as the Home Assistant DUKA
  integration. Both use UDP port 4000 and simultaneous clients make evidence
  ambiguous.
- The tool refuses to run unless `--ha-integration-disabled` is supplied after
  the operator has disabled the integration for the test window.
- Read-only validation must pass before any state-changing command is allowed.
  The tool will skip all requested writes automatically if Stage A fails.
- Boost validation is optional and is allowed only when boost is known to be
  off before the test and the fan is initially on.
- Network-loss validation is a separate manual step. The script never changes
  router settings or removes power from the fan.

## Preconditions

Record these facts in the coordination handoff before the physical run:

- date and local start time;
- Home Assistant backup status;
- active DUKA entity names;
- initial fan on/off state;
- initial RPM, temperature and humidity;
- initial boost state confirmed in the DUKA app;
- `input_boolean.bad_fan_controller_aktiv` initial state;
- person responsible for observing the fan.

Stop if the active integration is already unavailable, the DUKA app cannot
control the fan, or the initial state cannot be determined.

## Prepare the isolated checkout

Use a directory outside `/config` so the active integration cannot import the
validation checkout accidentally. A suitable location is:

```text
/share/duka_hardware_validation/sdk
```

Clone or update the validation branch, then verify that the merged SDK commit is
an ancestor:

```shell
git clone --branch validation/phase-2c \
  https://github.com/Bendeguz93-HA/duka_smartfan_sdk.git \
  /share/duka_hardware_validation/sdk
cd /share/duka_hardware_validation/sdk
git merge-base --is-ancestor \
  be693a62e1c939c19013d96317af060591a68e4c HEAD
```

The final command must exit with status 0.

Use Python 3.12 or 3.13. Install dependencies in an isolated virtual
environment. Do not install this branch into Home Assistant Core or the HACS
runtime.

Example with uv:

```shell
cd /share/duka_hardware_validation/sdk
uv sync --frozen --extra dev
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

All checks must pass before physical validation.

## Put Home Assistant into a reversible test state

Immediately before running the script:

1. Note the fan's current on/off, boost and RPM state.
2. Turn off `input_boolean.bad_fan_controller_aktiv`.
3. Disable only the DUKA SmartFan integration under
   **Settings → Devices & services**.
4. Wait a few seconds, then confirm that its entities become unavailable and
   that no DUKA automation is still issuing commands.
5. Keep the DUKA app available as the independent recovery path.

Do not delete the integration, remove entities, edit YAML, restart Home
Assistant or uninstall HACS components.

## Stage A — read-only validation

The tool prompts for the device identifier and password. The password is read
with `getpass` and is never written to the report. Leaving it blank uses the
SDK's inherited default.

```shell
cd /share/duka_hardware_validation/sdk
uv run python tools/hardware_validation.py --ha-integration-disabled
```

Expected evidence:

- the expected hashed device identifier is found by broadcast discovery;
- device validation completes within the configured timeout;
- firmware version/date and unit type are received;
- RPM, temperature and humidity are received;
- client shutdown completes;
- the generated JSON file contains no raw device ID, password or IP address.

The report is written with file mode `0600`, normally below:

```text
/share/duka_hardware_validation/results/
```

Stop after Stage A if the tool prints `NOT PASSED`, discovery finds an
unexpected set of devices, telemetry is incomplete, or the fan behaves
unexpectedly.

## Stage B — reversible on/off validation

Run this only after Stage A passes and while observing the physical fan:

```shell
uv run python tools/hardware_validation.py \
  --ha-integration-disabled \
  --write-test
```

The program refuses to change state until the exact phrase
`CHANGE FAN STATE` is entered. It changes the fan to the opposite on/off state,
observes the result, and then restores the initial on/off state. It performs a
second restoration attempt in a `finally` block.

Even when `--write-test` is supplied, the tool records the write stage as
`executed: false` and sends no state-changing command if the read-only stage
fails.

Stop and use the DUKA app if the physical state and reported state disagree.

## Stage C — optional boost validation

Only run this when the fan is initially on and the DUKA app confirms boost is
off:

```shell
uv run python tools/hardware_validation.py \
  --ha-integration-disabled \
  --write-test \
  --include-boost \
  --initial-boost-off
```

The tool requires a measurable RPM rise and then issues boost-off to restore
the known initial boost state. Do not run this mode when initial boost state is
unknown.

## Stage D — manual network-loss and reconnect validation

Run this only after Stages A–C are complete and documented.

Preferred method:

1. Start a read-only client and verify normal telemetry.
2. Temporarily block only the fan's Wi-Fi client in the router.
3. Observe bounded reconnect behavior and `DEGRADED` state.
4. Remove the block.
5. Verify discovery, telemetry and a harmless status cycle again.

Do not power-cycle a fixed electrical installation solely for this test. If the
router cannot safely block one client, record network-loss validation as
`NOT RUN` rather than improvising.

## Restore Home Assistant

Whether the test passes or fails:

1. Ensure the validation process has exited.
2. Confirm no `duka-smartfan-listener` process/thread remains in the test
   process.
3. Re-enable the DUKA SmartFan integration.
4. Confirm the fan, RPM, temperature and humidity entities recover.
5. Confirm manual on/off and boost through Home Assistant.
6. Restore `input_boolean.bad_fan_controller_aktiv` to its initial state.
7. Observe one normal bathroom automation cycle before declaring completion.

If recovery fails, leave the controller disabled, control the fan through the
DUKA app and record the exact failure without deleting or recreating entities.

## Result classification

- **PASS:** discovery, validation, telemetry, requested command stages,
  restoration and Home Assistant recovery all succeed.
- **PARTIAL:** safe stages pass but boost or network-loss was deliberately not
  run.
- **FAIL:** any requested stage fails, restoration is uncertain, or Home
  Assistant does not recover.

Hardware evidence does not resolve the GPL SPDX issue and does not authorize a
tag, release, PyPI publication, Home Assistant Core code or migration.
