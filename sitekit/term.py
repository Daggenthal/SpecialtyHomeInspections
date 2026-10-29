"""Terminal colors and the debug switch.

red = errors and failures, bold red = failure headers, cyan = commands and paths,
yellow = warnings and expected problems, green = success. Colors only show on a terminal,
never in log files or the systemd journal. NO_COLOR=1 turns them off.
Debug mode (SHI_DEBUG=1 or --debug) prints every publish log in full.
"""
import os
import sys

_STYLES = {"error": "31", "fail": "1;31", "frame": "36", "warn": "33", "ok": "32", "dim": "2"}
_debug = os.environ.get("SHI_DEBUG", "") not in ("", "0", "false")


def _color(stream):
    return stream.isatty() and "NO_COLOR" not in os.environ


def paint(kind, text, stream=None):
    code = _STYLES.get(kind)
    return f"\033[{code}m{text}\033[0m" if code and _color(stream or sys.stdout) else text


def set_debug(on):
    global _debug
    _debug = bool(on)


def debug_on():
    return _debug
