"""Structured, in-memory logging used by the desktop application.

The analyzer never writes to stdout directly: it appends :class:`LogEntry`
records to an :class:`AnalysisLog`. The UI renders them in the *Logs* tab.
Tracebacks are always captured but only *displayed* when debug mode is on.
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from typing import Callable, Iterable, Literal

from .security import redact_sensitive

Level = Literal["DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR"]

_ORDER: dict[str, int] = {"DEBUG": 10, "INFO": 20, "SUCCESS": 20, "WARNING": 30, "ERROR": 40}


@dataclass
class LogEntry:
    level: Level
    message: str
    scope: str = ""
    detail: str | None = None
    traceback_text: str | None = None
    timestamp: float = field(default_factory=time.time)

    @property
    def elapsed_label(self) -> str:
        return time.strftime("%H:%M:%S", time.localtime(self.timestamp))

    def as_dict(self) -> dict:
        return {
            "time": self.elapsed_label,
            "level": self.level,
            "scope": self.scope,
            "message": self.message,
            "detail": self.detail,
        }


class AnalysisLog:
    """Collects log entries for one analysis run.

    An optional *listener* is called for every entry as it is written, which is
    what lets a GUI stream the log live instead of waiting for the run to end.
    """

    def __init__(
        self,
        scope: str = "",
        entries: list[LogEntry] | None = None,
        listener: Callable[[LogEntry], None] | None = None,
        redact: bool = True,
    ):
        self._scope = scope
        self._entries: list[LogEntry] = entries if entries is not None else []
        self._listener = listener
        self._redact = redact

    # -- construction ----------------------------------------------------
    def child(self, scope: str) -> "AnalysisLog":
        """Return a log that shares storage but prefixes a different scope."""
        new_scope = f"{self._scope}/{scope}" if self._scope else scope
        return AnalysisLog(new_scope, self._entries, self._listener, self._redact)

    def set_listener(self, listener: Callable[[LogEntry], None] | None) -> None:
        """Install (or remove) the live listener for this log and its children."""
        self._listener = listener

    # -- emitting --------------------------------------------------------
    def _add(self, level: Level, message: str, detail: str | None = None, exc: BaseException | None = None) -> LogEntry:
        tb = None
        if exc is not None:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            if detail is None:
                detail = f"{type(exc).__name__}: {exc}"
        if self._redact:
            message = redact_sensitive(message)
            detail = redact_sensitive(detail) if detail is not None else None
            tb = redact_sensitive(tb) if tb is not None else None
        entry = LogEntry(level=level, message=message, scope=self._scope, detail=detail, traceback_text=tb)
        self._entries.append(entry)
        if self._listener is not None:
            try:
                self._listener(entry)
            except Exception:  # noqa: BLE001 - a broken listener must not break the run
                pass
        return entry

    def debug(self, message: str, detail: str | None = None) -> LogEntry:
        return self._add("DEBUG", message, detail)

    def info(self, message: str, detail: str | None = None) -> LogEntry:
        return self._add("INFO", message, detail)

    def success(self, message: str, detail: str | None = None) -> LogEntry:
        return self._add("SUCCESS", message, detail)

    def warning(self, message: str, detail: str | None = None, exc: BaseException | None = None) -> LogEntry:
        return self._add("WARNING", message, detail, exc)

    def error(self, message: str, detail: str | None = None, exc: BaseException | None = None) -> LogEntry:
        return self._add("ERROR", message, detail, exc)

    # -- reading ---------------------------------------------------------
    @property
    def entries(self) -> list[LogEntry]:
        return list(self._entries)

    def filtered(self, min_level: Level = "INFO") -> list[LogEntry]:
        threshold = _ORDER[min_level]
        return [e for e in self._entries if _ORDER[e.level] >= threshold]

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for entry in self._entries:
            out[entry.level] = out.get(entry.level, 0) + 1
        return out

    @property
    def has_errors(self) -> bool:
        return any(e.level == "ERROR" for e in self._entries)

    def extend(self, entries: Iterable[LogEntry]) -> None:
        self._entries.extend(entries)

    def as_dicts(self) -> list[dict]:
        return [e.as_dict() for e in self._entries]

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._entries)
