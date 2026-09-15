"""Background work so the window never freezes.

Two jobs run off the GUI thread:

* :class:`ScanTask` - hashes the selected files and groups them into packages
  (a 500 MB part takes a noticeable moment to SHA-256),
* :class:`AnalysisWorker` - the whole analysis pipeline.

The desktop app already has the files on disk, so parts are referenced in
place instead of being copied into a workspace; only the joined and
decompressed streams are written there.
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, Signal

from ptfanalyzer import __version__
from ptfanalyzer.database import AnalysisStore
from ptfanalyzer.logging_util import AnalysisLog
from ptfanalyzer.models import AnalysisReport, PartRef
from ptfanalyzer.parts import build_part_ref, group_parts
from ptfanalyzer.pipeline import AnalyzerOptions, Workspace, run_analysis
from ptfanalyzer.progress import Progress, ProgressEvent


class AnalysisCancelled(Exception):
    """Raised inside the worker thread when the user presses Cancel."""


# ---------------------------------------------------------------------------
# scanning (hash + group) - short, runs on the global thread pool
# ---------------------------------------------------------------------------


class ScanSignals(QObject):
    finished = Signal(int, list, list)  # token, parts, groups
    failed = Signal(int, str)


class ScanTask(QRunnable):
    """Hash the selected files and group them into packages."""

    def __init__(self, token: int, paths: Sequence[Path]):
        super().__init__()
        self.signals = ScanSignals()
        self._token = token
        self._paths = [Path(path) for path in paths]

    def run(self) -> None:  # pragma: no cover - exercised through the window
        try:
            parts: list[PartRef] = []
            for path in self._paths:
                if path.is_file():
                    parts.append(build_part_ref(path.name, path))
            groups = group_parts(parts, AnalysisLog())
            self.signals.finished.emit(self._token, parts, groups)
        except Exception as exc:  # noqa: BLE001 - reported in the UI
            self.signals.failed.emit(self._token, f"{type(exc).__name__}: {exc}")


def start_scan(token: int, paths: Sequence[Path]) -> ScanTask:
    task = ScanTask(token, paths)
    QThreadPool.globalInstance().start(task)
    return task


# ---------------------------------------------------------------------------
# analysis
# ---------------------------------------------------------------------------


class AnalysisWorker(QObject):
    """Runs one analysis; lives in its own thread."""

    progress = Signal(object)  # ProgressEvent
    log_entry = Signal(object)  # LogEntry
    finished = Signal(object)  # AnalysisReport
    saved = Signal(int)  # history id
    failed = Signal(str, str)  # message, traceback
    cancelled = Signal()

    def __init__(
        self,
        parts: Sequence[PartRef],
        paths: Sequence[Path],
        options: AnalyzerOptions,
        workspace: Workspace,
        store: Optional[AnalysisStore] = None,
    ):
        super().__init__()
        self._parts = list(parts)
        self._paths = [Path(path) for path in paths]
        self._options = options
        self._workspace = workspace
        self._store = store
        self._cancel = False

    def cancel(self) -> None:
        """Ask the run to stop at the next package boundary."""
        self._cancel = True

    def run(self) -> None:
        log = AnalysisLog(listener=self.log_entry.emit)
        progress = Progress(self._on_progress)
        try:
            parts = list(self._parts)
            if not parts:
                progress.begin_stage("read", "Reading the selected files", float(len(self._paths)))
                for position, path in enumerate(self._paths):
                    self._checkpoint()
                    if path.is_file():
                        progress.update(position, message=f"Hashing '{path.name}'")
                        parts.append(build_part_ref(path.name, path))
                        log.info(f"Read '{path.name}' ({path.stat().st_size / (1024 * 1024):.1f} MB)")
            else:
                for part in parts:
                    log.info(
                        f"Input '{part.display_name}' ({part.size / (1024 * 1024):.1f} MB, "
                        f"part {part.part_label}, SHA-256 {part.sha256[:16]}...)"
                    )
            self._checkpoint()

            report = run_analysis(parts, self._workspace, self._options, log, progress)

            # Saving happens before 'finished' so the GUI thread is never made
            # to wait for a multi megabyte write while tearing the thread down.
            if self._store is not None:
                try:
                    progress.note("Saving to the local database")
                    analysis_id = self._store.save_report(report, app_version=__version__)
                    log.success(f"Analysis stored in the local database (id {analysis_id}).")
                    self.saved.emit(analysis_id)
                except Exception as exc:  # noqa: BLE001 - never lose a good analysis
                    log.warning("The analysis could not be saved to the history.", exc=exc)

            report.log_entries = log.as_dicts()
            self.finished.emit(report)
        except AnalysisCancelled:
            log.warning("Analysis cancelled by the user.")
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 - surfaced in the UI, never a crash
            self.failed.emit(f"{type(exc).__name__}: {exc}", traceback.format_exc())

    def _on_progress(self, event: ProgressEvent) -> None:
        self._checkpoint()
        self.progress.emit(event)

    def _checkpoint(self) -> None:
        if self._cancel:
            raise AnalysisCancelled


class AnalysisRunner(QObject):
    """Owns the worker thread and re-emits its signals on the GUI thread."""

    progress = Signal(object)
    log_entry = Signal(object)
    finished = Signal(object)
    saved = Signal(int)
    failed = Signal(str, str)
    cancelled = Signal()
    started = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: Optional[QThread] = None
        self._worker: Optional[AnalysisWorker] = None

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(
        self,
        parts: Sequence[PartRef],
        paths: Sequence[Path],
        options: AnalyzerOptions,
        workspace: Workspace,
        store: Optional[AnalysisStore] = None,
    ) -> None:
        if self.busy:
            raise RuntimeError("An analysis is already running.")

        self._thread = QThread()
        self._worker = AnalysisWorker(parts, paths, options, workspace, store)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress)
        self._worker.saved.connect(self.saved)
        self._worker.log_entry.connect(self.log_entry)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(self._on_cancelled)

        self._thread.start()
        self.started.emit()

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    # -- teardown --------------------------------------------------------
    def _cleanup(self) -> None:
        thread, worker = self._thread, self._worker
        self._thread = None
        self._worker = None
        if thread is not None:
            thread.quit()
            thread.wait(5000)
            thread.deleteLater()
        if worker is not None:
            worker.deleteLater()

    def _on_finished(self, report: AnalysisReport) -> None:
        self._cleanup()
        self.finished.emit(report)

    def _on_failed(self, message: str, tb: str) -> None:
        self._cleanup()
        self.failed.emit(message, tb)

    def _on_cancelled(self) -> None:
        self._cleanup()
        self.cancelled.emit()

    def shutdown(self) -> None:
        """Stop a running analysis and wait for the thread (called on close)."""
        self.cancel()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(5000)
