"""
Create a file called ".deviceid" in the current folder.
This file should contain  the duka smartfan wifi device id.
You can see the duka smartfan wifi device id in the duka app.
"""

import sys
import time

from duka_smartfan_sdk.device import Device
from duka_smartfan_sdk.dukaclient import DukaClient


def onchange(device: Device):
    """Callback function when device changes"""
    print(
        f"ip: {device.ip_address},"
        f" device id: {device.device_id},"
        f" is_active: {device.is_active},"
        f" fan_speed: {device.fan_speed},"
        f" humidity: {device.humidity},"
        f" temperature: {device.temperature},"
    )


def newdevice_callback(deviceid: str):
    print("New device id: " + deviceid)


def main():
    """Main example"""
    client: DukaClient = DukaClient()
    client.search_devices(newdevice_callback)
    time.sleep(5)

    # read the device id
    with open(".deviceid") as file:
        device_id = file.readline().replace("\n", "")
    # initialize the client and add the device
    device: Device = client.validate_device(device_id)
    if device is None:
        print("Device does not respond")
        exit(1)
    device = client.add_device(device_id, password="", onchange=onchange)
    print("Device added")

    print(f"Firmware version: {device.firmware_version}")
    print(f"Firmware date: {device.firmware_date}")
    print(f"Unit type: {device.unit_type}")
    while True:
        print(
            "Press one key and enter. "
            "1 for boost on, "
            "2 for boost off, "
            "3 for boost toggle, "
            "q for quit"
        )
        char = sys.stdin.read(2)[0]
        if char == "q":
            break
        if char == "1":
            client.turn_boost_on(device)
        if char == "2":
            client.turn_boost_off(device)
        if char == "3":
            client.toggle_boost(device)

    print("Closing")
    client.close()
    print("Done")

    exit(0)


if __name__ == "__main__":
    main()
