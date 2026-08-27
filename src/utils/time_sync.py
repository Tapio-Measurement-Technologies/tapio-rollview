import datetime
import serial

def get_timestamp():
    timestamp = datetime.datetime.now().timestamp()
    tz_offset = datetime.datetime.now().astimezone().utcoffset().total_seconds()
    timestamp += tz_offset
    return int(timestamp)

def device_wall_clock_to_epoch(device_timestamp):
    """Invert get_timestamp() for a timestamp reported back by the device.

    The device stores what it is handed and renders it as UTC, so the offset
    added above is what puts its screen and its FAT timestamps on local time.
    Timestamps coming back are therefore local wall-clock fields packed as an
    epoch, and reading them directly leaves everything an offset ahead."""
    wall_clock = datetime.datetime.fromtimestamp(
        device_timestamp, datetime.timezone.utc
    ).replace(tzinfo=None)
    # Resolved against the local zone rather than by subtracting today's
    # offset, so a file written under the other DST offset keeps its clock.
    return wall_clock.astimezone().timestamp()

def send_timestamp(port: serial.Serial):
    timestamp = get_timestamp()
    port.write(f'RQP+SETTIME={timestamp}\n'.encode("ISO-8859-1"))