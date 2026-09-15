"""Privacy and offline-mode helpers shared by UI, logs and reports."""

from __future__ import annotations

import contextlib
import re
import socket
from pathlib import Path
from typing import Iterator

_WINDOWS_PATH = re.compile(r"(?i)\b[A-Z]:\\(?:[^\\\s<>:\"|?*]+\\)*[^\s<>:\"|?*]*")
_UNC_PATH = re.compile(r"\\\\[^\\\s]+\\[^\s]+")
_HOME_PATH = re.compile(r"(?<!\w)/(?:home|Users)/[^/\s]+(?:/[^\s]*)?")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_IPV4 = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")


def redact_sensitive(value: object, enabled: bool = True) -> str:
    """Mask local paths and common personal identifiers in exported text."""
    text = "" if value is None else str(value)
    if not enabled:
        return text
    text = _WINDOWS_PATH.sub("<LOCAL_PATH>", text)
    text = _UNC_PATH.sub("<NETWORK_PATH>", text)
    text = _HOME_PATH.sub("<HOME_PATH>", text)
    text = _EMAIL.sub("<EMAIL>", text)
    return _IPV4.sub("<IP_ADDRESS>", text)


def safe_filename(value: str, fallback: str = "report") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(value).name).strip("._")
    return cleaned or fallback


@contextlib.contextmanager
def offline_guard(enabled: bool = True) -> Iterator[None]:
    """Block outbound sockets while an analysis is running."""
    if not enabled:
        yield
        return
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create = socket.create_connection

    def blocked(*_args, **_kwargs):
        raise OSError("Network access is disabled by Offline mode")

    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.create_connection = blocked
    try:
        yield
    finally:
        socket.socket.connect = original_connect
        socket.socket.connect_ex = original_connect_ex
        socket.create_connection = original_create
