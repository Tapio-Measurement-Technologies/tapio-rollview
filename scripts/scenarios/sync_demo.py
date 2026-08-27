"""Drive a full sync against a fake RQFT device — good with --record.

    python scripts/guiharness.py scripts/scenarios/sync_demo.py \\
        --record sync.gif --real-serial

``--real-serial`` is needed so the harness leaves SerialWidget.scan_devices
alone; the fake device is what the scan actually finds, not real hardware.
"""

import math

from test.fakedevice import FakeRqftDevice, make_profile_bytes


def _profile(seed):
    return make_profile_bytes(
        [
            40.0 + 6.0 * math.sin(i / 40.0 + seed) + 2.0 * math.sin(i / 7.0)
            for i in range(600)
        ]
    )


def run(ctx):
    import store

    profiles = {
        f"250520-134139/{name}.prof": _profile(i)
        for i, name in enumerate(("a", "b", "c"))
    }

    with FakeRqftDevice(profiles=profiles, device_name="RQP Fake") as device, \
            device.patch_comports():
        serial_widget = ctx.window.serial_widget

        ctx.snap("01-before-scan")

        serial_widget.scan_devices()
        ctx.wait_until(lambda: not serial_widget.scanner.is_running(), timeout=15000)
        ctx.wait(400)
        ctx.snap("02-device-found")

        found = [p for p in serial_widget.view.model.ports if p.device_responded]
        if not found:
            print("[scenario] no device found; is --real-serial set?")
            return
        serial_widget.view.model.selected_port = found[0]

        serial_widget.sync_data()
        ctx.wait_until(
            lambda: not serial_widget.transferManager.is_transfer_in_progress(),
            timeout=30000,
        )
        ctx.wait(600)
        ctx.snap("03-after-sync", serial_widget.transferDialog)

        ctx.window.directory_view.change_root_directory(store.root_directory)
        ctx.wait(500)
        ctx.snap("04-profiles-listed")

        print(f"[scenario] files sent: {device.files_sent}")
        print(f"[scenario] device errors: {device.errors}")
