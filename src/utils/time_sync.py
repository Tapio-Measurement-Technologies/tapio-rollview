import datetime
import serial

def get_timestamp():
    timestamp = datetime.datetime.now().timestamp()
    tz_offset = datetime.datetime.now().astimezone().utcoffset().seconds
    timestamp += tz_offset
    return int(timestamp)

def send_timestamp(port: serial.Serial):
    timestamp = get_timestamp()
    port.write(f'RQP+SETTIME={timestamp}'.encode("ISO-8859-1"))