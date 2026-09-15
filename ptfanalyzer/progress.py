"""Fine grained progress reporting for the desktop application.

The analysis is not one long opaque step: a package is joined, decompressed,
listed, decoded and parsed.  Each stage reports into a :class:`Progress`
object, which turns stage-local counters into one overall percentage plus a
human sentence such as::

    Package 1/2 - Decompressing: 45.2 MB of 118.0 MB

The desktop layer only sees :class:`ProgressEvent` objects; the engine never
imports Qt.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

#: Relative cost of each stage inside one package.  These are rough but they
#: keep the bar moving smoothly instead of jumping from 0% to 100%.
STAGE_WEIGHTS: dict[str, float] = {
    "read": 4.0,
    "join": 8.0,
    "identify": 1.0,
    "decompress": 45.0,
    "archive": 14.0,
    "parse": 25.0,
    "holddata": 2.0,
    "finish": 1.0,
}

STAGE_LABELS: dict[str, str] = {
    "read": "Reading files",
    "join": "Joining parts",
    "identify": "Identifying format",
    "decompress": "Decompressing",
    "archive": "Reading archive",
    "parse": "Parsing SMP/E metadata",
    "holddata": "Reading HOLDDATA",
    "finish": "Finishing",
}

TOTAL_WEIGHT = sum(STAGE_WEIGHTS.values())

#: Minimum seconds between two events of the same stage (keeps the UI cheap).
THROTTLE_SECONDS = 0.08


@dataclass
class ProgressEvent:
    """One snapshot of what the analyzer is doing right now."""

    stage: str
    stage_label: str
    message: str
    current: float
    total: float  # 0 means "unknown / indeterminate"
    fraction: float  # overall completion, 0.0 - 1.0
    package: str
    package_index: int
    package_count: int
    elapsed: float

    @property
    def percent(self) -> int:
        return int(round(max(0.0, min(self.fraction, 1.0)) * 100))

    @property
    def headline(self) -> str:
        prefix = ""
        if self.package_count > 1 and self.package:
            prefix = f"Package {self.package_index + 1}/{self.package_count} - "
        elif self.package:
            prefix = f"{self.package} - "
        return f"{prefix}{self.message or self.stage_label}"


ProgressCallback = Optional[Callable[[ProgressEvent], None]]


def format_bytes(value: float) -> str:
    for unit, limit in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if value >= limit:
            return f"{value / limit:.1f} {unit}"
    return f"{int(value)} B"


class Progress:
    """Collects stage progress and emits :class:`ProgressEvent` objects.

    A ``Progress`` without a callback is a no-op, so engine code can always
    call it unconditionally.
    """

    def __init__(self, callback: ProgressCallback = None):
        self._callback = callback
        self._started = time.time()
        self._last_emit = 0.0
        self._package = ""
        self._package_index = 0
        self._package_count = 1
        self._stage = ""
        self._stage_label = ""
        self._completed_weight = 0.0
        self._current = 0.0
        self._total = 0.0
        self._message = ""

    # -- structure -------------------------------------------------------
    def begin_package(self, name: str, index: int, count: int) -> None:
        self._package = name
        self._package_index = index
        self._package_count = max(count, 1)
        self._completed_weight = 0.0
        self._stage = ""
        self._stage_label = ""
        self._current = 0.0
        self._total = 0.0
        self.emit(f"Starting '{name}'", force=True)

    def begin_stage(self, stage: str, message: str = "", total: float = 0.0) -> None:
        if self._stage:
            self._completed_weight += STAGE_WEIGHTS.get(self._stage, 0.0)
        self._stage = stage
        self._stage_label = STAGE_LABELS.get(stage, stage.title())
        self._current = 0.0
        self._total = max(total, 0.0)
        self._message = message or self._stage_label
        self.emit(self._message, force=True)

    def end_stage(self) -> None:
        if self._stage:
            self._completed_weight += STAGE_WEIGHTS.get(self._stage, 0.0)
            self._stage = ""
            self._stage_label = ""
            self._current = 0.0
            self._total = 0.0

    # -- updates ---------------------------------------------------------
    def update(self, current: float, total: Optional[float] = None, message: str = "") -> None:
        self._current = max(current, 0.0)
        if total is not None:
            self._total = max(total, 0.0)
        if message:
            self._message = message
        self.emit(self._message)

    def advance(self, amount: float = 1.0, message: str = "") -> None:
        self.update(self._current + amount, message=message)

    def note(self, message: str) -> None:
        """Change the description without touching the counters."""
        self._message = message
        self.emit(message, force=True)

    def bytes_update(self, done: float, total: float, what: str = "") -> None:
        label = what or self._stage_label
        if total > 0:
            text = f"{label}: {format_bytes(done)} of {format_bytes(total)}"
        else:
            text = f"{label}: {format_bytes(done)}"
        self.update(done, total, text)

    def finish(self, message: str = "Finished") -> None:
        self._completed_weight = TOTAL_WEIGHT
        self._stage = "finish"
        self._stage_label = STAGE_LABELS["finish"]
        self._current = self._total = 1.0
        self._package_index = self._package_count - 1
        self.emit(message, force=True)

    # -- emitting --------------------------------------------------------
    @property
    def fraction(self) -> float:
        stage_weight = STAGE_WEIGHTS.get(self._stage, 0.0)
        stage_fraction = 0.0
        if self._total > 0:
            stage_fraction = min(self._current / self._total, 1.0)
        within = (self._completed_weight + stage_weight * stage_fraction) / TOTAL_WEIGHT
        overall = (self._package_index + min(within, 1.0)) / self._package_count
        return max(0.0, min(overall, 1.0))

    def event(self, message: str = "") -> ProgressEvent:
        return ProgressEvent(
            stage=self._stage,
            stage_label=self._stage_label,
            message=message or self._message,
            current=self._current,
            total=self._total,
            fraction=self.fraction,
            package=self._package,
            package_index=self._package_index,
            package_count=self._package_count,
            elapsed=time.time() - self._started,
        )

    def emit(self, message: str = "", force: bool = False) -> None:
        if self._callback is None:
            return
        now = time.time()
        if not force and (now - self._last_emit) < THROTTLE_SECONDS:
            return
        self._last_emit = now
        try:
            self._callback(self.event(message))
        except Exception:  # noqa: BLE001 - a broken listener must not break the run
            pass

    # -- helpers ---------------------------------------------------------
    def byte_sink(self, total: float, what: str = ""):
        """Adapter for low level code that reports ``(done, total)``."""

        def sink(done: int, reported_total: int) -> None:
            self.bytes_update(done, reported_total or total, what)

        return sink


#: A shared do-nothing instance for callers that do not care about progress.
NULL_PROGRESS = Progress()
