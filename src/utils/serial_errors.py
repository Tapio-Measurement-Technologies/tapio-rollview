"""One vocabulary for what went wrong with a serial port.

A failed open, a dropped link and a silent device reach the operator
through different paths -- the device list, the sync's message box, the
RQFT session, the status bar -- and each used to word the failure its own
way, two of them with the operating system's text pasted in. "Access is
denied" is Windows saying that another program has the port; the page
timeout is a paired unit that is off; "cannot find the file" is a port
that is no longer there. This module sorts every serial failure into a
handful of causes and words each cause once: what happened, naming the
unit and the port, and what to do about it.

Causes are decided from error codes wherever there is one, so a Windows
in another language classifies the same; the words are the fallback.
pyserial does not chain the OSError it formats into its message, so the
codes are read out of the text when they are not on the exception.
"""

import errno
import re
from dataclasses import dataclass

from utils.translation import _

CAUSE_HELD = "held"                # another program has the port
CAUSE_UNREACHABLE = "unreachable"  # a paired unit that is off or out of range
CAUSE_GONE = "gone"                # the port is no longer there
CAUSE_LINK_LOST = "link_lost"      # reading or writing failed mid-session
CAUSE_SILENT = "silent"            # the port opened and nothing came back
CAUSE_UNKNOWN = "unknown"

CAUSES = (
    CAUSE_HELD, CAUSE_UNREACHABLE, CAUSE_GONE,
    CAUSE_LINK_LOST, CAUSE_SILENT, CAUSE_UNKNOWN,
)

# pyserial on Windows: "could not open port 'COM6': PermissionError(13,
# 'Access is denied.', None, 5)" -- errno first, the Windows code last.
_WINERROR_RE = re.compile(r"\((\d+), (?:'[^']*'|\"[^\"]*\"), None, (\d+)\)")
# pyserial on POSIX: "[Errno 2] could not open port /dev/ttyUSB0: ..."
_ERRNO_RE = re.compile(r"\[Errno (\d+)\]")

# Windows error codes.
_WIN_HELD = {5, 32}                 # ACCESS_DENIED, SHARING_VIOLATION
_WIN_UNREACHABLE = {121, 1460}      # SEM_TIMEOUT (the page timeout), TIMEOUT
_WIN_GONE = {2, 3, 433, 1167}       # FILE_NOT_FOUND, PATH_NOT_FOUND, NO_SUCH_DEVICE, DEVICE_NOT_CONNECTED
_WIN_LINK_LOST = {6, 21, 22, 31, 995, 1117, 1167}  # INVALID_HANDLE, NOT_READY, BAD_COMMAND, GEN_FAILURE, OPERATION_ABORTED, IO_DEVICE, DEVICE_NOT_CONNECTED


def _errnos(literals, *names):
    """The platform's numbers for these errno names, plus Linux's as
    literals: the errno module on Windows maps the network ones to WinSock
    values, and a message from a Linux host carries Linux's numbers."""
    return set(literals) | {
        value for value in (getattr(errno, name, None) for name in names)
        if value is not None
    }


_POSIX_HELD = _errnos({1, 13, 16}, "EPERM", "EACCES", "EBUSY")
_POSIX_UNREACHABLE = _errnos(
    {110, 111, 112, 113}, "ETIMEDOUT", "ECONNREFUSED", "EHOSTDOWN", "EHOSTUNREACH"
)
_POSIX_GONE = _errnos({2, 6, 19}, "ENOENT", "ENXIO", "ENODEV")
_POSIX_LINK_LOST = _errnos(
    {5, 6, 9, 19, 32, 104}, "EIO", "ENXIO", "EBADF", "ENODEV", "EPIPE", "ECONNRESET"
)


def _codes(error):
    """The Windows error code and the errno of an error, either None."""
    winerror = None
    posix = None
    seen = []
    current = error
    while isinstance(current, BaseException) and current not in seen:
        seen.append(current)
        if isinstance(current, OSError):
            if winerror is None:
                winerror = getattr(current, "winerror", None)
            if posix is None:
                posix = current.errno
        current = current.__cause__ or current.__context__
    text = str(error)
    match = _WINERROR_RE.search(text)
    if match:
        if posix is None:
            posix = int(match.group(1))
        if winerror is None:
            winerror = int(match.group(2))
    else:
        match = _ERRNO_RE.search(text)
        if match and posix is None:
            posix = int(match.group(1))
    return winerror, posix


def classify_port_error(error, opened=False):
    """The cause behind an exception, or its text.

    ``opened`` says the port had been opened successfully before the
    failure: a code that means "the device went away" is then a lost
    link rather than a port that was never there.
    """
    if error is None:
        return CAUSE_SILENT
    if isinstance(error, str) and error in CAUSES:
        return error
    winerror, posix = _codes(error)
    if winerror is not None:
        if opened and winerror in _WIN_LINK_LOST:
            return CAUSE_LINK_LOST
        if winerror in _WIN_HELD:
            return CAUSE_LINK_LOST if opened else CAUSE_HELD
        if winerror in _WIN_UNREACHABLE:
            return CAUSE_UNREACHABLE
        if winerror in _WIN_GONE:
            return CAUSE_GONE
        if winerror in _WIN_LINK_LOST:
            return CAUSE_LINK_LOST
    if posix is not None:
        if opened and posix in _POSIX_LINK_LOST:
            return CAUSE_LINK_LOST
        if posix in _POSIX_HELD:
            return CAUSE_LINK_LOST if opened else CAUSE_HELD
        if posix in _POSIX_UNREACHABLE:
            return CAUSE_UNREACHABLE
        if posix in _POSIX_GONE:
            return CAUSE_GONE
        if posix in _POSIX_LINK_LOST:
            return CAUSE_LINK_LOST
    text = str(error).casefold()
    if "access is denied" in text or "permission denied" in text or "resource busy" in text:
        return CAUSE_LINK_LOST if opened else CAUSE_HELD
    if "semaphore timeout" in text or "timed out" in text:
        return CAUSE_UNREACHABLE
    if "cannot find the file" in text or "no such file" in text:
        return CAUSE_GONE
    if opened:
        return CAUSE_LINK_LOST
    return CAUSE_UNKNOWN


@dataclass(frozen=True)
class PortErrorText:
    """What to tell the operator: a short title, what happened, what to do."""
    cause: str
    title: str
    sentence: str
    hint: str

    @property
    def body(self):
        return f"{self.sentence} {self.hint}".strip()


def describe_port_error(error, port, unit_name="", opened=False):
    """Words for a failure on ``port``. ``error`` may be an exception, the
    text of one, or a cause from this module."""
    cause = classify_port_error(error, opened=opened)
    unit = unit_name or _("PORT_ERROR_DEVICE")
    key = cause.upper()
    return PortErrorText(
        cause=cause,
        title=_(f"PORT_ERROR_{key}_TITLE"),
        sentence=_(f"PORT_ERROR_{key}").format(port=port, unit=unit),
        hint=_(f"PORT_ERROR_{key}_HINT"),
    )
