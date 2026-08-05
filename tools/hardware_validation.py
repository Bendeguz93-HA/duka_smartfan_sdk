#!/usr/bin/env python3
"""Guarded hardware validation for the DUKA SmartFan SDK.

Read-only discovery and telemetry are the default. State-changing commands
require an explicit flag and an interactive confirmation phrase. Reports are
sanitized before being written and never contain the device password, raw
device ID, or IP address.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from duka_smartfan_sdk import Device, DukaClient, DukaSmartFanError

EXPECTED_SDK_MERGE = "be693a62e1c939c19013d96317af060591a68e4c"
WRITE_CONFIRMATION = "CHANGE FAN STATE"
IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _hash_identifier(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _sanitize_text(value: str, device_id: str) -> str:
    sanitized = value.replace(device_id, "<device-id-redacted>")
    return IPV4_PATTERN.sub("<ip-redacted>", sanitized)


def _device_snapshot(device: Device) -> dict[str, Any]:
    return {
        "is_active": device.is_active,
        "fan_speed_raw": device.fan_speed,
        "temperature_raw": device.temperature,
        "humidity_raw": device.humidity,
        "firmware_version": device.firmware_version,
        "firmware_date": device.firmware_date,
        "unit_type": device.unit_type,
    }


def _wait_until(
    predicate: Callable[[], bool],
    timeout: float,
    *,
    interval: float = 0.25,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _default_output_path() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    share_root = Path("/share/duka_hardware_validation/results")
    local_root = Path("hardware_validation_results")
    root = share_root if Path("/share").is_dir() else local_root
    return root / f"phase_2c_{stamp}.json"


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    path.chmod(0o600)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Safely validate a physical DUKA SmartFan against the SDK.",
    )
    parser.add_argument(
        "--device-id",
        help="Device identifier. Omit to enter it interactively.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_default_output_path(),
        help="Sanitized JSON report path.",
    )
    parser.add_argument("--discovery-seconds", type=float, default=5.0)
    parser.add_argument("--status-timeout", type=float, default=12.0)
    parser.add_argument(
        "--write-test",
        action="store_true",
        help="Run a reversible on/off command test after read-only validation.",
    )
    parser.add_argument(
        "--include-boost",
        action="store_true",
        help="Also test boost. Requires --write-test and --initial-boost-off.",
    )
    parser.add_argument(
        "--initial-boost-off",
        action="store_true",
        help="Confirm that boost is known to be off before the test.",
    )
    return parser.parse_args()


def _record_error(
    report: dict[str, Any], stage: str, error: BaseException, device_id: str
) -> None:
    report["errors"].append(
        {
            "stage": stage,
            "type": type(error).__name__,
            "message": _sanitize_text(str(error), device_id),
        }
    )


def _run_write_test(
    client: DukaClient,
    device: Device,
    report: dict[str, Any],
    *,
    timeout: float,
    include_boost: bool,
    initial_boost_off: bool,
) -> bool:
    initial = _device_snapshot(device)
    initial_active = device.is_active
    if initial_active is None:
        raise RuntimeError("cannot run write test without a known active state")

    confirmation = input(
        f'Type "{WRITE_CONFIRMATION}" to permit temporary fan state changes: '
    )
    if confirmation != WRITE_CONFIRMATION:
        raise RuntimeError("write test confirmation was not provided")

    steps: list[dict[str, Any]] = []
    write_report: dict[str, Any] = {
        "requested": True,
        "initial_state": initial,
        "steps": steps,
        "restoration_attempted": False,
        "restoration_error_types": [],
    }
    report["write_test"] = write_report

    opposite = not initial_active
    write_passed = True
    boost_started = False

    try:
        if opposite:
            client.turn_on(device)
            command = "turn_on"
        else:
            client.turn_off(device)
            command = "turn_off"
        changed = _wait_until(lambda: device.is_active is opposite, timeout)
        steps.append(
            {
                "command": command,
                "target_active": opposite,
                "observed": _device_snapshot(device),
                "passed": changed,
            }
        )
        write_passed &= changed

        if initial_active:
            client.turn_on(device)
            restore_command = "turn_on"
        else:
            client.turn_off(device)
            restore_command = "turn_off"
        restored = _wait_until(lambda: device.is_active is initial_active, timeout)
        steps.append(
            {
                "command": restore_command,
                "target_active": initial_active,
                "observed": _device_snapshot(device),
                "passed": restored,
                "purpose": "restore_initial_on_off_state",
            }
        )
        write_passed &= restored

        if include_boost:
            if not initial_boost_off:
                raise RuntimeError(
                    "boost test requires --initial-boost-off after checking the app"
                )
            if not initial_active:
                raise RuntimeError("boost test requires the fan to be initially on")
            baseline = device.fan_speed
            if baseline is None:
                raise RuntimeError("boost test requires a known baseline fan speed")

            client.turn_boost_on(device)
            boost_started = True
            threshold = max(100, int(baseline * 0.20))
            boosted = _wait_until(
                lambda: (
                    device.fan_speed is not None
                    and device.fan_speed >= baseline + threshold
                ),
                timeout,
            )
            peak = device.fan_speed
            steps.append(
                {
                    "command": "turn_boost_on",
                    "baseline_fan_speed_raw": baseline,
                    "observed": _device_snapshot(device),
                    "passed": boosted,
                }
            )
            write_passed &= boosted

            client.turn_boost_off(device)
            boost_started = False
            boost_cleared = _wait_until(
                lambda: (
                    peak is not None
                    and device.fan_speed is not None
                    and device.fan_speed <= peak - threshold
                ),
                timeout,
            )
            steps.append(
                {
                    "command": "turn_boost_off",
                    "observed": _device_snapshot(device),
                    "passed": boost_cleared,
                    "purpose": "restore_known_initial_boost_off_state",
                }
            )
            write_passed &= boost_cleared
    finally:
        write_report["restoration_attempted"] = True
        restoration_errors: list[str] = write_report["restoration_error_types"]

        if boost_started:
            try:
                client.turn_boost_off(device)
            except DukaSmartFanError as error:
                restoration_errors.append(type(error).__name__)
                write_passed = False

        try:
            if initial_active:
                client.turn_on(device)
            else:
                client.turn_off(device)
        except DukaSmartFanError as error:
            restoration_errors.append(type(error).__name__)
            write_passed = False

        restored_finally = _wait_until(
            lambda: device.is_active is initial_active,
            timeout,
        )
        write_passed &= restored_finally
        write_report["final_state"] = _device_snapshot(device)
        write_report["final_on_off_restored"] = restored_finally

    return write_passed


def main() -> int:
    args = _parse_args()
    if args.include_boost and not args.write_test:
        print("--include-boost requires --write-test", file=sys.stderr)
        return 2

    device_id = (args.device_id or input("DUKA device identifier: ")).strip()
    if not device_id:
        print("A device identifier is required", file=sys.stderr)
        return 2

    password_value = os.environ.get("DUKA_PASSWORD")
    if password_value is None:
        password_value = getpass.getpass(
            "DUKA password (leave blank to use the SDK default): "
        )
    password = password_value or None

    report: dict[str, Any] = {
        "schema": "duka-sdk-hardware-validation-v1",
        "started_at": datetime.now(UTC).isoformat(),
        "expected_sdk_merge": EXPECTED_SDK_MERGE,
        "device_id_sha256_prefix": _hash_identifier(device_id),
        "mode": "write" if args.write_test else "read-only",
        "secrets_recorded": False,
        "raw_device_id_recorded": False,
        "ip_address_recorded": False,
        "errors": [],
    }

    client = DukaClient(
        autostart=False,
        socket_timeout=1.0,
        startup_timeout=4.0,
        validation_timeout=args.status_timeout,
    )
    exit_code = 0

    try:
        client.start()
        discovered: set[str] = set()

        def on_discovered(found_id: str) -> None:
            discovered.add(_hash_identifier(found_id))

        client.search_devices(on_discovered)
        time.sleep(args.discovery_seconds)
        expected_hash = _hash_identifier(device_id)
        report["discovery"] = {
            "window_seconds": args.discovery_seconds,
            "discovered_device_hashes": sorted(discovered),
            "expected_device_found": expected_hash in discovered,
        }

        validated = client.validate_device(
            device_id,
            password,
            timeout=args.status_timeout,
            raise_on_error=True,
        )
        if validated is None:
            raise RuntimeError("device validation returned no device")
        report["validation"] = {
            "passed": True,
            "observed": _device_snapshot(validated),
        }

        callback_count = 0

        def on_change(_device: Device) -> None:
            nonlocal callback_count
            callback_count += 1

        device = client.add_device(device_id, password, onchange=on_change)
        telemetry_ready = _wait_until(
            lambda: (
                device.firmware_version is not None
                and device.unit_type is not None
                and device.fan_speed is not None
                and device.temperature is not None
                and device.humidity is not None
            ),
            args.status_timeout,
        )
        report["telemetry"] = {
            "complete_snapshot_received": telemetry_ready,
            "callback_count": callback_count,
            "observed": _device_snapshot(device),
        }

        discovery_passed = report["discovery"]["expected_device_found"]
        if not discovery_passed or not telemetry_ready:
            exit_code = 2

        if args.write_test:
            write_passed = _run_write_test(
                client,
                device,
                report,
                timeout=args.status_timeout,
                include_boost=args.include_boost,
                initial_boost_off=args.initial_boost_off,
            )
            if not write_passed:
                exit_code = 2
    except (DukaSmartFanError, OSError, RuntimeError, ValueError) as error:
        _record_error(report, "validation", error, device_id)
        exit_code = 2
    finally:
        try:
            client.close(timeout=3.0)
        except Exception as error:  # shutdown evidence must still be recorded
            _record_error(report, "client_close", error, device_id)
            exit_code = 2
        report["client_final_state"] = str(client.connection_state)
        report["client_last_error_type"] = (
            type(client.last_error).__name__ if client.last_error is not None else None
        )
        report["finished_at"] = datetime.now(UTC).isoformat()
        report["passed"] = exit_code == 0
        _write_report(args.output, report)

    print(f"Sanitized report written to: {args.output}")
    print("PASS" if exit_code == 0 else "NOT PASSED")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
