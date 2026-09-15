"""The desktop main window.

Layout::

    +--------------------------------------------------------------+
    | brand header                                                  |
    | toolbar: add files | folder | analyze | export | ...          |
    +----------------------+---------------------------------------+
    | input files          |  Summary | PTFs | HOLDDATA | ...       |
    | detected packages    |                                       |
    | [Analyze] progress   |  (PTF tab: table | live detail pane)   |
    +----------------------+---------------------------------------+
    | status bar: decoders, totals, duration                        |
    +--------------------------------------------------------------+
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QAction, QFont, QKeySequence, QTextDocument
from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrinter
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QSystemTrayIcon,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ptfanalyzer import __version__
from ptfanalyzer.compression import available_decoders
from ptfanalyzer.compare import compare_reports, comparison_summary
from ptfanalyzer.database import AnalysisStore, default_database_path
from ptfanalyzer.encoding import CANDIDATE_ENCODINGS
from ptfanalyzer.export import (
    frame_to_csv,
    hold_frame,
    member_frame,
    package_summary_frame,
    part_frame,
    ptf_frame,
    raw_statements_for,
    report_to_json,
)
from ptfanalyzer.models import AnalysisReport, PackageAnalysis, PackageGroup, PartRef, PTFEntry
from ptfanalyzer.pipeline import AnalyzerOptions, Workspace
from ptfanalyzer.progress import ProgressEvent
from ptfanalyzer.reporting import printable_html, write_excel_report
from ptfanalyzer.security import redact_sensitive

from . import theme
from .models import PTFFilterProxy, PTFTableModel, RowTableModel
from .preferences import edit_settings
from .settings import Settings
from .widgets import Card, Chip, DataTable, FileDropList, KeyValueGrid, MetricCard, PTFDetailPanel, StatusItem, list_item
from .worker import AnalysisRunner, start_scan
from .updater import check_for_update

LOG_LEVELS = ["ERROR", "WARNING", "SUCCESS", "INFO", "DEBUG"]


def human_size(size: float) -> str:
    """Bytes as KB/MB/GB - package parts range from a few KB to gigabytes."""
    for unit, limit in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if size >= limit:
            return f"{size / limit:.1f} {unit}"
    return f"{int(size)} B"


def human_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 60:
        return f"{seconds:.1f} s"
    return f"{int(seconds // 60)} m {seconds % 60:.0f} s"


class MainWindow(QMainWindow):
    """SMP/E PTF Package Analyzer - desktop front end."""

    report_ready = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SMP/E PTF Package Analyzer")
        self.resize(1480, 920)
        self.setMinimumSize(1100, 700)

        self._paths: list[Path] = []
        self._parts: list[PartRef] = []
        self._groups: list[PackageGroup] = []
        self._report: Optional[AnalysisReport] = None
        self._scan_token = 0
        self._workspace: Optional[Workspace] = None
        self._log_rows: list[dict] = []
        self._loaded_id: Optional[int] = None
        self._comparison_rows: list[dict] = []
        self.settings = Settings.load()
        self._store: Optional[AnalysisStore] = None
        self._store_error = ""
        try:
            encryption_key = os.environ.get("PTFANALYZER_DB_KEY", "") if self.settings.encrypt_database else ""
            if self.settings.encrypt_database and not encryption_key:
                raise RuntimeError("Database encryption is enabled but PTFANALYZER_DB_KEY is not set.")
            self._store = AnalysisStore(encryption_key=encryption_key)
        except Exception as exc:  # noqa: BLE001 - history is a convenience
            self._store_error = f"{type(exc).__name__}: {exc}"

        self._runner = AnalysisRunner(self)
        self._runner.progress.connect(self._on_progress)
        self._runner.log_entry.connect(self._on_log_entry)
        self._runner.finished.connect(self._on_finished)
        self._runner.failed.connect(self._on_failed)
        self._runner.cancelled.connect(self._on_cancelled)
        self._runner.saved.connect(self._on_saved)
        self._runner.started.connect(lambda: self._set_busy(True))

        self._build_ui()
        self._refresh_inputs()
        self.refresh_history()

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_input_panel())
        splitter.addWidget(self._build_tabs())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([340, 1140])
        layout.addWidget(splitter, 1)

        self.setCentralWidget(central)
        self._build_menu_bar()
        self._build_status_bar()



    def _build_menu_bar(self) -> None:
        """Dropdown menus - every action lives here, nothing is hidden."""
        bar = self.menuBar()
        bar.setNativeMenuBar(False)

        def action(text, slot, shortcut=None, tip="", checkable=False):
            item = QAction(text, self)
            item.triggered.connect(slot)
            if shortcut:
                item.setShortcut(QKeySequence(shortcut))
            if tip:
                item.setStatusTip(tip)
            item.setCheckable(checkable)
            return item

        # -- File ---------------------------------------------------------
        file_menu = bar.addMenu("&File")
        self.action_add_files = action(
            "&Add files...", self.add_files_dialog, "Ctrl+O", "Select package parts to analyze"
        )
        self.action_add_folder = action(
            "Add &folder...", self.add_folder_dialog, "Ctrl+Shift+O", "Add every file in a folder"
        )
        file_menu.addAction(self.action_add_files)
        file_menu.addAction(self.action_add_folder)
        file_menu.addSeparator()
        self.action_remove_file = action("&Remove selected file", self.remove_selected, "Del")
        self.action_clear_files = action("Clear &file list", self.clear_files)
        file_menu.addAction(self.action_remove_file)
        file_menu.addAction(self.action_clear_files)
        file_menu.addSeparator()
        self.action_export_csv = action(
            "&Export PTF list (CSV)...", self.export_csv, "Ctrl+E", "Save the PTF table as CSV"
        )
        self.action_export_json = action(
            "Export full report (&JSON)...", self.export_json, None, "Save the complete report"
        )
        self.action_export_log = action("Save &log (CSV)...", self.export_log)
        self.action_export_excel = action("Corporate report (&Excel)...", self.export_excel)
        self.action_export_pdf = action("Corporate report (&PDF)...", self.export_pdf)
        self.action_print_ptf = action("&Print selected PTF...", self.print_selected_ptf, "Ctrl+P")
        file_menu.addAction(self.action_export_csv)
        file_menu.addAction(self.action_export_json)
        file_menu.addAction(self.action_export_log)
        file_menu.addAction(self.action_export_excel)
        file_menu.addAction(self.action_export_pdf)
        file_menu.addAction(self.action_print_ptf)
        file_menu.addSeparator()
        file_menu.addAction(action("E&xit", self.close, "Ctrl+Q"))

        # -- Analysis -----------------------------------------------------
        analysis_menu = bar.addMenu("&Analysis")
        self.action_analyze = action(
            "&Analyze package", self.start_analysis, "F5", "Join, decompress and read the package"
        )
        self.action_cancel = action("&Cancel", self._runner.cancel, "Esc")
        self.action_cancel.setEnabled(False)
        self.action_clear = action("Clear &results", self.clear_all, "Ctrl+L")
        analysis_menu.addAction(self.action_analyze)
        analysis_menu.addAction(self.action_cancel)
        analysis_menu.addSeparator()
        analysis_menu.addAction(self.action_clear)

        # -- History ------------------------------------------------------
        history_menu = bar.addMenu("&History")
        history_menu.addAction(
            action(
                "Show &history",
                lambda: self.tabs.setCurrentIndex(5),
                "Ctrl+H",
                "Stored analyses you can reopen",
            )
        )
        self.recent_menu = history_menu.addMenu("&Recent analyses")
        self.recent_menu.aboutToShow.connect(self._fill_recent_menu)
        history_menu.addSeparator()
        self.action_save_now = action(
            "&Save current analysis", self.save_current_analysis, "Ctrl+S",
            "Store this analysis in the local database",
        )
        history_menu.addAction(self.action_save_now)
        history_menu.addAction(action("&Backup database...", self.backup_database))
        history_menu.addAction(action("&Restore database...", self.restore_database))
        history_menu.addAction(action("&Open database folder", self.open_database_folder))

        # -- View ---------------------------------------------------------
        view_menu = bar.addMenu("&View")
        for position, name in enumerate(
            ["Summary", "PTFs", "HOLDDATA", "Package contents", "Logs", "History", "Compare", "Inventory"]
        ):
            view_menu.addAction(
                action(f"&{position + 1}  {name}", lambda _=False, i=position: self.tabs.setCurrentIndex(i),
                       f"Ctrl+{position + 1}")
            )
        view_menu.addSeparator()
        self.action_debug = action("&Debug mode", self._toggle_debug, None, "", checkable=True)
        self.action_debug.setChecked(self.settings.debug)
        view_menu.addAction(self.action_debug)

        # -- Tools --------------------------------------------------------
        tools_menu = bar.addMenu("&Tools")
        tools_menu.addAction(
            action("&Preferences...", self.open_preferences, "Ctrl+,", "Decompression, encoding and history options")
        )
        tools_menu.addAction(
            action("Report &branding...", self.open_report_preferences, None, "Company name, report title and logo")
        )
        tools_menu.addAction(action("Available &decoders...", self.show_decoders))
        tools_menu.addAction(action("Check for signed &updates...", self.check_updates))

        # -- Help ---------------------------------------------------------
        help_menu = bar.addMenu("&Help")
        help_menu.addAction(action("&About", self.show_about))

        for item in (self.action_export_csv, self.action_export_json, self.action_export_log,
                     self.action_export_excel, self.action_export_pdf, self.action_print_ptf,
                     self.action_save_now):
            item.setEnabled(False)

    # -- menu actions ----------------------------------------------------
    def _fill_recent_menu(self) -> None:
        """Last analyses, straight from the database - one click reopens them."""
        self.recent_menu.clear()
        if self._store is None:
            self.recent_menu.addAction("History is not available").setEnabled(False)
            return
        summaries = self._store.list_analyses(limit=12)
        if not summaries:
            self.recent_menu.addAction("No analysis stored yet").setEnabled(False)
            return
        for summary in summaries:
            text = f"#{summary.id}  {summary.created_local}  -  {summary.label}  ({summary.ptf_count} PTF)"
            item = QAction(text, self)
            item.triggered.connect(lambda _=False, i=summary.id: self.open_history(i))
            self.recent_menu.addAction(item)

    def _toggle_debug(self, enabled: bool) -> None:
        self.settings.debug = enabled
        self.settings.save()
        self._refresh_logs()
        if self._report is not None:
            self._build_summary_cards(self._report)

    def open_preferences(self) -> None:
        self._open_preferences_page()

    def open_report_preferences(self) -> None:
        self._open_preferences_page("Reports")

    def _open_preferences_page(self, page: str = "") -> None:
        updated = edit_settings(self.settings, self, page)
        if updated is None:
            return
        self.settings = updated
        self.settings.save()
        theme.apply(QApplication.instance(), self.settings.dark_theme)
        self.action_debug.setChecked(self.settings.debug)
        self.hold_banner.setStyleSheet(theme.chip_style(theme.status_colour("ERROR")))
        self._refresh_logs()
        self.refresh_history()
        if self._report is not None:
            self._populate(self._report)
        if self._groups:
            self._on_scan_finished(self._scan_token, self._parts, self._groups)
        self.status_message.setText("Preferences saved.")

    def show_decoders(self) -> None:
        decoders = available_decoders()
        dialog = QDialog(self)
        dialog.setObjectName("DecoderDialog")
        dialog.setWindowTitle("Available decoders")
        dialog.setModal(True)
        dialog.setMinimumWidth(680)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(14)
        icon = QLabel("Z")
        icon.setObjectName("DecoderIcon")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(48, 48)
        header.addWidget(icon)

        heading = QVBoxLayout()
        heading.setSpacing(2)
        title = QLabel("Decompression decoders")
        title.setObjectName("DecoderTitle")
        subtitle = QLabel("Fallback chain for Unix .Z package streams")
        subtitle.setObjectName("DecoderSubtitle")
        heading.addWidget(title)
        heading.addWidget(subtitle)
        header.addLayout(heading, 1)

        available_count = sum(1 for decoder in decoders if decoder["available"])
        header.addWidget(Chip(f"{available_count} of {len(decoders)} available", theme.status_colour("SUCCESS")))
        layout.addLayout(header)

        explanation = QLabel(
            "Decoders are evaluated in the order shown below. If one cannot open the stream, "
            "the analyzer automatically continues with the next available option."
        )
        explanation.setObjectName("DecoderIntro")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        column_header = QFrame()
        column_header.setObjectName("DecoderHeader")
        column_layout = QHBoxLayout(column_header)
        column_layout.setContentsMargins(12, 6, 12, 6)
        column_layout.setSpacing(12)
        order_header = QLabel("ORDER")
        order_header.setFixedWidth(40)
        decoder_header = QLabel("DECODER")
        status_header = QLabel("STATUS")
        status_header.setFixedWidth(92)
        for label in (order_header, decoder_header, status_header):
            label.setObjectName("DecoderColumnLabel")
        column_layout.addWidget(order_header)
        column_layout.addWidget(decoder_header, 1)
        column_layout.addWidget(status_header)
        layout.addWidget(column_header)

        for index, decoder in enumerate(decoders, start=1):
            row = QFrame()
            row.setObjectName("DecoderRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(12, 10, 12, 10)
            row_layout.setSpacing(12)

            order = QLabel(f"{index:02d}")
            order.setObjectName("DecoderOrder")
            order.setAlignment(Qt.AlignCenter)
            order.setFixedSize(40, 30)
            row_layout.addWidget(order)

            details = QVBoxLayout()
            details.setSpacing(2)
            name = QLabel(decoder["name"])
            name.setObjectName("DecoderName")
            source_text = str(decoder["path"]) if decoder["available"] else "Not installed on this system"
            source = QLabel(source_text)
            source.setObjectName("DecoderPath")
            source.setTextInteractionFlags(Qt.TextSelectableByMouse)
            source.setWordWrap(True)
            details.addWidget(name)
            details.addWidget(source)
            row_layout.addLayout(details, 1)

            status_text = "Available" if decoder["available"] else "Not found"
            status_key = "SUCCESS" if decoder["available"] else "DEBUG"
            status = Chip(status_text, theme.status_colour(status_key))
            status.setFixedWidth(92)
            row_layout.addWidget(status)
            layout.addWidget(row)

        note = QLabel(
            "The built-in LZW decoder is always available. Configure decoder selection and "
            "large-file behavior in Tools > Preferences > Decompression."
        )
        note.setObjectName("DecoderNote")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setObjectName("Primary")
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def check_updates(self) -> None:
        if self.settings.offline_mode:
            QMessageBox.information(self, "Updates", "Offline mode is enabled. Disable it temporarily to contact the configured signed update channel.")
            return
        try:
            update = check_for_update(__version__)
        except Exception as exc:
            QMessageBox.warning(self, "Updates", f"The signed update channel could not be checked.\n\n{exc}")
            return
        if update is None:
            QMessageBox.information(self, "Updates", "This is the latest available version.")
            return
        answer = QMessageBox.question(self, "Signed update available", f"Version {update.version} is available.\n\n{update.notes}\n\nOpen the verified HTTPS download page?", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer == QMessageBox.Yes:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(update.url))

    def show_about(self) -> None:
        dialog = QDialog(self)
        dialog.setObjectName("AboutDialog")
        dialog.setWindowTitle("About")
        dialog.setModal(True)
        dialog.setFixedWidth(570)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(16)
        icon = QLabel("Z")
        icon.setObjectName("AboutIcon")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(64, 64)
        header.addWidget(icon)

        identity = QVBoxLayout()
        identity.setSpacing(3)
        title = QLabel("SMP/E PTF Package Analyzer")
        title.setObjectName("AboutTitle")
        version = QLabel(f"Desktop edition  ·  Version {__version__}")
        version.setObjectName("AboutVersion")
        identity.addStretch(1)
        identity.addWidget(title)
        identity.addWidget(version)
        identity.addStretch(1)
        header.addLayout(identity, 1)
        layout.addLayout(header)

        divider = QFrame()
        divider.setObjectName("Divider")
        divider.setFrameShape(QFrame.HLine)
        layout.addWidget(divider)

        body = QLabel(
            "A local desktop tool for joining split .XofY packages, decompressing Unix .Z streams, "
            "and analysing SMPPTFIN, HOLDDATA and GIMFAF metadata."
        )
        body.setObjectName("AboutBody")
        body.setWordWrap(True)
        layout.addWidget(body)

        meta = QLabel(
            "LOCAL PROCESSING  ·  OFFLINE BY DEFAULT\n"
            f"History: {redact_sensitive(default_database_path())}"
        )
        meta.setObjectName("AboutMeta")
        meta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(meta)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def open_database_folder(self) -> None:
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        folder = (self._store.path if self._store else default_database_path()).parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def backup_database(self) -> None:
        if self._store is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Backup history database", str(Path(self.settings.last_export_dir) / "ptf_history_backup.db"), "SQLite database (*.db)")
        if path:
            self._store.backup_to(Path(path))
            self.settings.last_export_dir = str(Path(path).parent)
            self.settings.save()
            self.status_message.setText("History database backup completed.")

    def restore_database(self) -> None:
        if self._store is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Restore history database", self.settings.last_export_dir, "SQLite database (*.db);;All files (*)")
        if not path:
            return
        answer = QMessageBox.question(self, "Restore database", "Replace the current history with this verified backup? A safety backup will be created first.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        safety = self._store.path.with_name(self._store.path.stem + ".before_restore.db")
        try:
            self._store.backup_to(safety)
            self._store.restore_from(Path(path))
            self.refresh_history()
            self.status_message.setText(f"Database restored. Safety backup: {safety}")
        except Exception as exc:
            QMessageBox.critical(self, "Restore database", f"Restore failed; the current database was kept.\n\n{exc}")

    def save_current_analysis(self) -> None:
        """Store the analysis on screen even when auto-save is switched off."""
        if self._report is None or self._store is None:
            return
        try:
            analysis_id = self._store.save_report(self._report, app_version=__version__)
        except Exception as exc:  # noqa: BLE001 - reported, never fatal
            QMessageBox.warning(self, "History", f"The analysis could not be saved.\n\n{exc}")
            return
        self._loaded_id = analysis_id
        self.refresh_history()
        self.status_message.setText(f"Analysis stored in the local database as #{analysis_id}.")

    def _build_input_panel(self) -> QWidget:
        panel = QWidget()
        # Keep the file list readable even when a wide table asks for room.
        panel.setMinimumWidth(320)
        panel.setMaximumWidth(460)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 6, 10)
        layout.setSpacing(10)

        files_card = Card("Input files")
        self.file_list = FileDropList()
        self.file_list.files_dropped.connect(self.add_paths)
        self.file_list.setMinimumHeight(140)
        files_card.add(self.file_list)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        add_button = QPushButton("Add...")
        add_button.clicked.connect(self.add_files_dialog)
        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(self.remove_selected)
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self.clear_files)
        for button in (add_button, remove_button, clear_button):
            buttons.addWidget(button)
        files_card.body().addLayout(buttons)
        layout.addWidget(files_card)

        packages_card = Card("Detected packages")
        self.package_tree = QTreeWidget()
        self.package_tree.setHeaderLabels(["Package", "Status"])
        self.package_tree.setColumnWidth(0, 190)
        self.package_tree.setAlternatingRowColors(True)
        self.package_tree.setMinimumHeight(190)
        packages_card.add(self.package_tree)
        layout.addWidget(packages_card, 1)

        self.analyze_button = QPushButton("Analyze package")
        self.analyze_button.setObjectName("Primary")
        self.analyze_button.setMinimumHeight(34)
        self.analyze_button.clicked.connect(self.start_analysis)
        layout.addWidget(self.analyze_button)

        self.progress_card = Card("Progress")
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress_stage = QLabel("Idle")
        self.progress_stage.setObjectName("ValueLabel")
        self.progress_stage.setWordWrap(True)
        self.progress_detail = QLabel("")
        self.progress_detail.setObjectName("KeyLabel")
        self.progress_detail.setWordWrap(True)
        self.progress_elapsed = QLabel("")
        self.progress_elapsed.setObjectName("KeyLabel")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self._runner.cancel)
        self.cancel_button.setEnabled(False)

        self.progress_card.add(self.progress)
        self.progress_card.add(self.progress_stage)
        self.progress_card.add(self.progress_detail)
        self.progress_card.add(self.progress_elapsed)
        self.progress_card.add(self.cancel_button)
        self.progress_card.setVisible(False)
        layout.addWidget(self.progress_card)
        return panel

    def _build_tabs(self) -> QWidget:
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_summary_tab(), "Summary")
        self.tabs.addTab(self._build_ptf_tab(), "PTFs")
        self.tabs.addTab(self._build_hold_tab(), "HOLDDATA")
        self.tabs.addTab(self._build_contents_tab(), "Package contents")
        self.tabs.addTab(self._build_log_tab(), "Logs")
        self.tabs.addTab(self._build_history_tab(), "History")
        self.tabs.addTab(self._build_comparison_tab(), "Compare")
        self.tabs.addTab(self._build_inventory_tab(), "Inventory")
        return self.tabs

    # -- tabs ------------------------------------------------------------
    def _build_summary_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        metrics = QHBoxLayout()
        metrics.setSpacing(10)
        self.metric_packages = MetricCard("Packages", "0")
        self.metric_ptfs = MetricCard("PTFs", "0")
        self.metric_holds = MetricCard("HOLD entries", "0")
        self.metric_errors = MetricCard("Errors", "0")
        self.metric_duration = MetricCard("Duration", "-")
        for card in (
            self.metric_packages,
            self.metric_ptfs,
            self.metric_holds,
            self.metric_errors,
            self.metric_duration,
        ):
            metrics.addWidget(card)
        layout.addLayout(metrics)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._summary_body = QWidget()
        self._summary_layout = QVBoxLayout(self._summary_body)
        self._summary_layout.setContentsMargins(0, 0, 0, 0)
        self._summary_layout.setSpacing(10)
        self._summary_layout.addStretch(1)
        scroll.setWidget(self._summary_body)
        layout.addWidget(scroll, 1)
        return page

    def _build_ptf_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search PTF id, FMID, APAR or description text...")
        self.search_box.setClearButtonEnabled(True)
        self.fmid_combo = QComboBox()
        self.fmid_combo.addItem("All FMIDs")
        self.fmid_combo.setMinimumWidth(150)
        self.only_pe = QCheckBox("Only PE")
        self.only_hold = QCheckBox("Only with HOLD")
        self.filter_profile = QComboBox()
        self.filter_profile.setMinimumWidth(130)
        self.filter_profile.addItem("Filter profiles...")
        self._load_filter_profiles()
        save_profile = QPushButton("Save profile")
        save_profile.clicked.connect(self.save_filter_profile)
        delete_profile = QPushButton("Delete profile")
        delete_profile.clicked.connect(self.delete_filter_profile)
        filters.addWidget(self.search_box, 1)
        filters.addWidget(QLabel("FMID:"))
        filters.addWidget(self.fmid_combo)
        filters.addWidget(self.only_pe)
        filters.addWidget(self.only_hold)
        filters.addWidget(self.filter_profile)
        filters.addWidget(save_profile)
        filters.addWidget(delete_profile)
        self.ptf_count_label = QLabel("0 PTF")
        self.ptf_count_label.setObjectName("KeyLabel")
        filters.addWidget(self.ptf_count_label)
        layout.addLayout(filters)

        splitter = QSplitter(Qt.Horizontal)
        self.ptf_table = DataTable("Description")
        self.ptf_table.setObjectName("ptf_table")
        self.ptf_model = PTFTableModel()
        self.ptf_proxy = PTFFilterProxy(self)
        self.ptf_proxy.setSourceModel(self.ptf_model)
        self.ptf_table.setModel(self.ptf_proxy)
        self.ptf_table.selectionModel().selectionChanged.connect(self._on_ptf_selected)

        self.detail_panel = PTFDetailPanel()
        self.ptf_table.setMinimumWidth(430)
        self.detail_panel.setMinimumWidth(430)
        splitter.addWidget(self.ptf_table)
        splitter.addWidget(self.detail_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([700, 640])
        layout.addWidget(splitter, 1)

        self.search_box.textChanged.connect(self._apply_ptf_filters)
        self.fmid_combo.currentTextChanged.connect(self._apply_ptf_filters)
        self.only_pe.toggled.connect(self._apply_ptf_filters)
        self.only_hold.toggled.connect(self._apply_ptf_filters)
        self.filter_profile.currentIndexChanged.connect(self.apply_filter_profile)
        return page

    def _build_hold_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.hold_banner = QLabel("")
        self.hold_banner.setStyleSheet(theme.chip_style(theme.status_colour("ERROR")))
        self.hold_banner.hide()
        layout.addWidget(self.hold_banner)
        self.hold_table = DataTable("Comment")
        self.hold_table.setObjectName("hold_table")
        self.hold_table.setModel(RowTableModel([], ["PTF", "Hold Type", "Reason", "FMID", "Date", "Class", "Resolver", "Comment", "Source"]))
        layout.addWidget(self.hold_table, 1)
        return page

    def _build_contents_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        selector = QHBoxLayout()
        selector.addWidget(QLabel("Package:"))
        self.package_combo = QComboBox()
        self.package_combo.setMinimumWidth(320)
        self.package_combo.currentIndexChanged.connect(self._refresh_contents)
        selector.addWidget(self.package_combo)
        selector.addStretch(1)
        layout.addLayout(selector)

        splitter = QSplitter(Qt.Vertical)
        self.member_table = DataTable("Member")
        self.member_table.setObjectName("member_table")
        self.member_table.setModel(RowTableModel([], ["Member", "Role", "Size (bytes)", "Type", "Container"]))
        gimfaf_card = QWidget()
        gimfaf_layout = QVBoxLayout(gimfaf_card)
        gimfaf_layout.setContentsMargins(0, 6, 0, 0)
        gimfaf_layout.setSpacing(5)
        self.gimfaf_label = QLabel("GIMFAF / GIMPAF metadata")
        self.gimfaf_label.setObjectName("CardTitle")
        self.gimfaf_table = DataTable("Path")
        self.gimfaf_table.setModel(RowTableModel([], ["Element", "Name", "Path", "Value"]))
        gimfaf_layout.addWidget(self.gimfaf_label)
        gimfaf_layout.addWidget(self.gimfaf_table)
        splitter.addWidget(self.member_table)
        splitter.addWidget(gimfaf_card)
        splitter.setSizes([460, 220])
        layout.addWidget(splitter, 1)
        return page

    def _build_log_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Minimum level:"))
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_level_combo.setCurrentText("INFO")
        self.log_level_combo.currentTextChanged.connect(self._refresh_logs)
        controls.addWidget(self.log_level_combo)
        controls.addStretch(1)
        save_button = QPushButton("Save log...")
        save_button.clicked.connect(self.export_log)
        controls.addWidget(save_button)
        layout.addLayout(controls)

        self.log_table = DataTable("message")
        self.log_table.setObjectName("log_table")
        self.log_table.setModel(RowTableModel([], ["time", "level", "scope", "message"]))
        self.log_table.setSortingEnabled(False)
        self.log_table.clicked.connect(self._show_log_detail)
        layout.addWidget(self.log_table, 1)

        self.log_detail = QTextEdit()
        self.log_detail.setReadOnly(True)
        self.log_detail.setFont(QFont("Consolas", 9))
        self.log_detail.setMaximumHeight(150)
        self.log_detail.setPlaceholderText("Select a log line to see its technical detail.")
        layout.addWidget(self.log_detail)
        return page

    def _build_history_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("Filter stored analyses by package name or label...")
        self.history_search.setClearButtonEnabled(True)
        self.history_search.textChanged.connect(self.refresh_history)
        controls.addWidget(self.history_search, 1)

        self.history_open_button = QPushButton("Open")
        self.history_open_button.setObjectName("Primary")
        self.history_open_button.clicked.connect(self.open_selected_history)
        self.history_rename_button = QPushButton("Rename")
        self.history_rename_button.clicked.connect(self.rename_selected_history)
        self.history_note_button = QPushButton("Notes")
        self.history_note_button.clicked.connect(self.note_selected_history)
        self.history_archive_button = QPushButton("Archive")
        self.history_archive_button.clicked.connect(self.archive_selected_history)
        self.history_delete_button = QPushButton("Delete")
        self.history_delete_button.clicked.connect(self.delete_selected_history)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh_history)
        for button in (
            self.history_open_button,
            self.history_rename_button,
            self.history_note_button,
            self.history_archive_button,
            self.history_delete_button,
            refresh_button,
        ):
            controls.addWidget(button)
        layout.addLayout(controls)

        splitter = QSplitter(Qt.Vertical)

        history_panel = QWidget()
        history_layout = QVBoxLayout(history_panel)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.setSpacing(4)
        history_title = QLabel("STORED ANALYSES")
        history_title.setObjectName("CardTitle")
        self.history_table = DataTable("Label")
        self.history_table.setObjectName("history_table")
        self.history_table.setModel(
            RowTableModel(
                [],
                ["ID", "Date", "Label", "Archived", "Notes", "Packages", "PTFs", "HOLDs", "Errors", "Duration (s)", "Sources"],
            )
        )
        self.history_table.doubleClicked.connect(lambda _: self.open_selected_history())
        history_layout.addWidget(history_title)
        history_layout.addWidget(self.history_table)
        splitter.addWidget(history_panel)

        search_panel = QWidget()
        search_layout = QVBoxLayout(search_panel)
        search_layout.setContentsMargins(0, 6, 0, 0)
        search_layout.setSpacing(4)
        search_title = QLabel("FIND A PTF ACROSS EVERY STORED ANALYSIS")
        search_title.setObjectName("CardTitle")
        self.ptf_history_search = QLineEdit()
        self.ptf_history_search.setPlaceholderText("PTF id, APAR, FMID or description text...")
        self.ptf_history_search.setClearButtonEnabled(True)
        self.ptf_history_search.textChanged.connect(self.search_history_ptfs)
        self.history_ptf_table = DataTable("Description")
        self.history_ptf_table.setObjectName("history_ptf_table")
        self.history_ptf_table.setModel(
            RowTableModel(
                [],
                ["Analysis", "Date", "PTF", "Type", "FMID", "Description", "APARs", "HOLD", "PE", "Package"],
            )
        )
        self.history_ptf_table.doubleClicked.connect(self._open_history_from_ptf)
        search_layout.addWidget(search_title)
        search_layout.addWidget(self.ptf_history_search)
        search_layout.addWidget(self.history_ptf_table)
        splitter.addWidget(search_panel)
        splitter.setSizes([420, 320])
        layout.addWidget(splitter, 1)

        self.history_status = QLabel("")
        self.history_status.setObjectName("KeyLabel")
        layout.addWidget(self.history_status)
        return page

    def _build_comparison_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Before:"))
        self.compare_before = QComboBox()
        controls.addWidget(self.compare_before, 1)
        controls.addWidget(QLabel("After:"))
        self.compare_after = QComboBox()
        controls.addWidget(self.compare_after, 1)
        run = QPushButton("Compare")
        run.setObjectName("Primary")
        run.clicked.connect(self.run_comparison)
        controls.addWidget(run)
        layout.addLayout(controls)
        self.compare_summary = QLabel("Select two stored analyses.")
        self.compare_summary.setObjectName("KeyLabel")
        layout.addWidget(self.compare_summary)
        self.compare_table = DataTable("Description")
        self.compare_table.setObjectName("comparison")
        self.compare_table.setModel(RowTableModel([], ["Status", "PTF", "FMID", "PE", "Changed fields", "Description"]))
        layout.addWidget(self.compare_table, 1)
        return page

    def _build_inventory_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        controls = QHBoxLayout()
        self.inventory_search = QLineEdit()
        self.inventory_search.setPlaceholderText("Filter by PTF, FMID or description...")
        self.inventory_search.setClearButtonEnabled(True)
        self.inventory_search.textChanged.connect(self.refresh_inventory)
        controls.addWidget(self.inventory_search, 1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_inventory)
        controls.addWidget(refresh)
        layout.addLayout(controls)
        self.inventory_table = DataTable()
        self.inventory_table.setObjectName("inventory")
        self.inventory_table.setModel(RowTableModel([], ["PTF", "Type", "FMID", "Seen", "First seen", "Last seen", "Ever PE"]))
        layout.addWidget(self.inventory_table, 1)
        self.duplicate_label = QLabel("")
        self.duplicate_label.setObjectName("KeyLabel")
        layout.addWidget(self.duplicate_label)
        return page

    # -- options dock ----------------------------------------------------

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        self.status_message = QLabel("Ready.")
        bar.addWidget(self.status_message, 1)
        available = sum(1 for decoder in available_decoders() if decoder["available"])
        self.status_decoders = StatusItem("Decoders:", f"{available} available")
        self.status_totals = StatusItem("Result:", "-")
        self.status_database = StatusItem("History:", "-")
        self.status_database.setToolTip(str(default_database_path()))
        bar.addPermanentWidget(self.status_decoders)
        bar.addPermanentWidget(self.status_totals)
        bar.addPermanentWidget(self.status_database)
        bar.addPermanentWidget(QLabel(f"v{__version__}"))

    # ------------------------------------------------------------------
    # input handling
    # ------------------------------------------------------------------
    def add_files_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select package files (.pax.Z, .Z or .XofY parts)",
            self.settings.last_input_dir,
            "All files (*)",
        )
        if paths:
            self.settings.last_input_dir = str(Path(paths[0]).parent)
            self.settings.save()
            self.add_paths(paths)

    def add_folder_dialog(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Select the folder holding the package parts", self.settings.last_input_dir)
        if not directory:
            return
        self.settings.last_input_dir = directory
        self.settings.save()
        iterator = Path(directory).rglob("*") if self.settings.recursive_folders else Path(directory).iterdir()
        files = sorted(path for path in iterator if path.is_file())
        if not files:
            QMessageBox.information(self, "Empty folder", "No files were found in that folder.")
            return
        self.add_paths(files)

    def add_paths(self, paths: Sequence) -> None:
        added = 0
        for raw in paths:
            path = Path(raw)
            if path.is_dir():
                iterator = path.rglob("*") if self.settings.recursive_folders else path.iterdir()
                for child in sorted(iterator):
                    if child.is_file() and child not in self._paths:
                        self._paths.append(child)
                        added += 1
                continue
            if path.is_file() and path not in self._paths:
                self._paths.append(path)
                added += 1
        if added:
            self._refresh_inputs()
            self.status_message.setText(f"{added} file(s) added.")

    def remove_selected(self) -> None:
        for item in self.file_list.selectedItems():
            path = Path(item.data(Qt.UserRole))
            if path in self._paths:
                self._paths.remove(path)
        self._refresh_inputs()

    def clear_files(self) -> None:
        self._paths.clear()
        self._refresh_inputs()

    def clear_all(self) -> None:
        self.clear_files()
        self._report = None
        self._log_rows = []
        self.ptf_model.set_ptfs([])
        self.detail_panel.clear()
        self.hold_table.setModel(RowTableModel([], ["PTF", "Hold Type", "Reason", "FMID", "Date", "Class", "Resolver", "Comment", "Source"]))
        self.package_combo.clear()
        self._clear_summary()
        self._refresh_logs()
        for metric in (self.metric_packages, self.metric_ptfs, self.metric_holds, self.metric_errors):
            metric.set_value(0, "")
        self.metric_duration.set_value("-", "")
        self.status_totals.set_value("-")
        for item in (
            self.action_export_csv,
            self.action_export_json,
            self.action_export_log,
            self.action_export_excel,
            self.action_export_pdf,
            self.action_print_ptf,
            self.action_save_now,
        ):
            item.setEnabled(False)
        self.status_message.setText("Cleared.")

    def _refresh_inputs(self) -> None:
        self.file_list.clear()
        for path in self._paths:
            size = path.stat().st_size if path.is_file() else 0
            item = list_item(f"{path.name}   ({human_size(size)})", str(path), str(path))
            self.file_list.addItem(item)

        self.analyze_button.setEnabled(bool(self._paths) and not self._runner.busy)
        self.action_analyze.setEnabled(self.analyze_button.isEnabled())

        self.package_tree.clear()
        if not self._paths:
            self._groups = []
            self._parts = []
            return

        placeholder = QTreeWidgetItem(["Scanning...", ""])
        self.package_tree.addTopLevelItem(placeholder)

        self._scan_token += 1
        task = start_scan(self._scan_token, list(self._paths))
        task.signals.finished.connect(self._on_scan_finished)
        task.signals.failed.connect(self._on_scan_failed)

    def _on_scan_finished(self, token: int, parts: list, groups: list) -> None:
        if token != self._scan_token:
            return  # a newer scan is already running
        self._parts = parts
        self._groups = groups
        self.package_tree.clear()
        for group in groups:
            item = QTreeWidgetItem([group.display_name, group.status])
            colour = theme.status_colour(group.status)
            if colour:
                from PySide6.QtGui import QBrush, QColor

                item.setForeground(1, QBrush(QColor(colour)))
            item.addChild(
                QTreeWidgetItem(
                    [f"{len(group.parts)} part(s), {human_size(group.total_size)}", ""]
                )
            )
            for error in group.errors:
                child = QTreeWidgetItem([error, "ERROR"])
                child.setToolTip(0, error)
                item.addChild(child)
            for warning in group.warnings:
                child = QTreeWidgetItem([warning, "WARNING"])
                child.setToolTip(0, warning)
                item.addChild(child)
            self.package_tree.addTopLevelItem(item)
            item.setExpanded(bool(group.errors or group.warnings))

    def _on_scan_failed(self, token: int, message: str) -> None:
        if token != self._scan_token:
            return
        self.package_tree.clear()
        self.package_tree.addTopLevelItem(QTreeWidgetItem([message, "ERROR"]))

    # ------------------------------------------------------------------
    # analysis
    # ------------------------------------------------------------------
    def current_options(self) -> AnalyzerOptions:
        return self.settings.to_analyzer_options()

    def start_analysis(self) -> None:
        if self._runner.busy:
            return
        if not self._paths:
            QMessageBox.warning(self, "No files", "Add at least one package file first.")
            return

        if self._workspace is not None:
            self._workspace.cleanup()
        self._workspace = Workspace()

        self._log_rows = []
        self._refresh_logs()
        self._loaded_id = None
        self.progress_card.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self.progress_stage.setText("Starting...")
        self.progress_detail.setText("")
        self.progress_elapsed.setText("")
        self.status_message.setText("Analyzing...")
        parts = self._parts if len(self._parts) == len(self._paths) else []
        store = self._store if self.settings.auto_save else None
        self._runner.start(parts, list(self._paths), self.current_options(), self._workspace, store)

    def _set_busy(self, busy: bool) -> None:
        self.analyze_button.setEnabled(not busy and bool(self._paths))
        self.action_analyze.setEnabled(self.analyze_button.isEnabled())
        self.action_cancel.setEnabled(busy)
        self.cancel_button.setEnabled(busy)
        for action in (self.action_add_files, self.action_add_folder, self.action_clear):
            action.setEnabled(not busy)
        if not busy:
            self.progress_card.setVisible(False)

    def _on_progress(self, event: ProgressEvent) -> None:
        self.progress.setValue(event.percent)
        self.progress_stage.setText(event.headline)
        if event.total > 0 and event.stage in ("join", "decompress", "read"):
            self.progress_detail.setText(
                f"{event.stage_label}: {event.current / max(event.total, 1) * 100:.0f}% of this step"
            )
        else:
            self.progress_detail.setText(event.stage_label)
        self.progress_elapsed.setText(f"Elapsed {human_duration(event.elapsed)}")

    def _on_log_entry(self, entry) -> None:
        self._log_rows.append(entry.as_dict())
        if self._row_visible(self._log_rows[-1]):
            self._append_log_row(self._log_rows[-1])
        if entry.level in ("ERROR", "WARNING", "SUCCESS"):
            self.status_message.setText(entry.message)

    def _on_finished(self, report: AnalysisReport) -> None:
        self._set_busy(False)
        self._report = report
        self._populate(report)
        self.report_ready.emit(report)
        errors = sum(len(package.errors) for package in report.packages)
        self.status_message.setText(
            f"Analysis finished in {human_duration(report.duration_s)} - "
            f"{len(report.analyzed_packages)} package(s), {len(report.ptfs)} PTF(s)"
            + (f", {errors} error(s)" if errors else "")
        )
        if self.settings.notifications and QSystemTrayIcon.isSystemTrayAvailable():
            if not hasattr(self, "_tray"):
                self._tray = QSystemTrayIcon(self.windowIcon(), self)
                self._tray.show()
            self._tray.showMessage("PTF analysis complete", f"{len(report.analyzed_packages)} package(s), {len(report.ptfs)} PTF(s), {errors} error(s)", QSystemTrayIcon.Information, 8000)

    def _on_saved(self, analysis_id: int) -> None:
        self._loaded_id = analysis_id
        self.refresh_history()
        self.status_database.set_value(f"saved as #{analysis_id}")

    def _on_failed(self, message: str, tb: str) -> None:
        self._set_busy(False)
        self.status_message.setText("Analysis failed.")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle("Analysis failed")
        box.setText("The analysis could not be completed.")
        box.setInformativeText(message)
        if self.settings.debug:
            box.setDetailedText(tb)
        box.exec()

    def _on_cancelled(self) -> None:
        self._set_busy(False)
        self.status_message.setText("Analysis cancelled.")

    # ------------------------------------------------------------------
    # result rendering
    # ------------------------------------------------------------------
    def _populate(self, report: AnalysisReport) -> None:
        ptfs = report.ptfs
        holds = [hold for package in report.packages for hold in package.all_holds]
        errors = sum(len(package.errors) for package in report.packages)
        pe_count = sum(1 for ptf in ptfs if ptf.is_pe)

        self.metric_packages.set_value(len(report.analyzed_packages), f"{len(report.groups)} group(s) detected")
        self.metric_ptfs.set_value(len(ptfs), f"{len(report.unique_ptf_ids)} unique SYSMOD id(s)")
        self.metric_holds.set_value(len(holds), f"{pe_count} PTF(s) in error (PE)")
        self.metric_errors.set_value(errors, "see the Logs tab" if errors else "no failures")
        self.metric_duration.set_value(human_duration(report.duration_s), "total analysis time")
        self.status_totals.set_value(f"{len(ptfs)} PTF / {len(holds)} HOLD / {errors} error")

        self._build_summary_cards(report)

        self.ptf_model.set_ptfs(ptfs)
        fmids = sorted({fmid for ptf in ptfs for fmid in ptf.fmids})
        self.fmid_combo.blockSignals(True)
        self.fmid_combo.clear()
        self.fmid_combo.addItem("All FMIDs")
        self.fmid_combo.addItems(fmids)
        self.fmid_combo.blockSignals(False)
        self._apply_ptf_filters()
        if ptfs:
            self.ptf_table.selectRow(0)

        self.hold_table.setModel(
            RowTableModel(
                [hold.as_dict() for hold in holds],
                ["PTF", "Hold Type", "Reason", "FMID", "Date", "Class", "Resolver", "Comment", "Source"],
            )
        )
        error_holds = [hold for hold in holds if hold.is_error_hold]
        self.hold_banner.setText(
            f"{len(error_holds)} ERROR hold (PE) entry/entries - these PTFs are known to be in error."
            if error_holds
            else ""
        )
        self.hold_banner.setVisible(bool(error_holds))

        self.package_combo.blockSignals(True)
        self.package_combo.clear()
        for package in report.packages:
            self.package_combo.addItem(f"{package.group.display_name}  [{package.status}]")
        self.package_combo.blockSignals(False)
        self._refresh_contents()

        self._log_rows = list(report.log_entries)
        self._refresh_logs()

        self.action_export_csv.setEnabled(bool(ptfs))
        self.action_export_json.setEnabled(True)
        self.action_export_log.setEnabled(bool(self._log_rows))
        self.action_export_excel.setEnabled(True)
        self.action_export_pdf.setEnabled(True)
        self.action_print_ptf.setEnabled(bool(ptfs))
        self.action_save_now.setEnabled(self._store is not None)

    def _clear_summary(self) -> None:
        while self._summary_layout.count() > 1:
            item = self._summary_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _build_summary_cards(self, report: AnalysisReport) -> None:
        self._clear_summary()
        for package in report.packages:
            self._summary_layout.insertWidget(self._summary_layout.count() - 1, self._package_card(package))

        parts_card = Card("Input files")
        frame = part_frame(report)
        table = DataTable("File")
        table.setModel(RowTableModel(frame.to_dict("records"), list(frame.columns)))
        table.setMinimumHeight(150)
        parts_card.add(table)
        self._summary_layout.insertWidget(self._summary_layout.count() - 1, parts_card)

        summary_card = Card("Packages")
        summary_frame = package_summary_frame(report)
        summary_table = DataTable("Package")
        summary_table.setModel(RowTableModel(summary_frame.to_dict("records"), list(summary_frame.columns)))
        summary_table.setMaximumHeight(160)
        summary_card.add(summary_table)
        self._summary_layout.insertWidget(0, summary_card)

    def _package_card(self, package: PackageAnalysis) -> QWidget:
        group = package.group
        card = Card()
        header = QHBoxLayout()
        title = QLabel(group.display_name)
        title.setObjectName("SectionTitle")
        chip = Chip()
        chip.set_status(package.status)
        header.addWidget(title)
        header.addSpacing(8)
        header.addWidget(chip)
        header.addStretch(1)
        card.body().addLayout(header)

        grids = QHBoxLayout()
        grids.setSpacing(24)
        left = KeyValueGrid()
        left.set_items(
            [
                ("Parts joined", f"{len(group.parts)} ({', '.join(p.part_label for p in group.parts)})"),
                ("Total size", human_size(group.total_size)),
                ("Fingerprint", group.fingerprint[:32] + "..." if group.fingerprint else "-"),
                ("Duplicate of", group.duplicate_of or "-"),
            ]
        )
        right_items = [
            ("Stream format", package.stream_format.label if package.stream_format else "-"),
            ("Decoder used", package.decompression.method if package.decompression else "-"),
        ]
        if package.decompression:
            right_items.append(
                (
                    "Decompressed",
                    f"{package.decompression.input_size:,} -> {package.decompression.output_size:,} bytes",
                )
            )
        for analysis in package.smpptfin:
            right_items.append(
                (
                    f"Encoding ({Path(analysis.member).name})",
                    f"{analysis.encoding.encoding}, {analysis.record_count:,} records, layout {analysis.layout}",
                )
            )
        right = KeyValueGrid()
        right.set_items(right_items)
        grids.addWidget(left, 1)
        grids.addWidget(right, 1)
        card.body().addLayout(grids)

        for analysis in package.smpptfin:
            if analysis.prologue:
                header_text = QTextEdit()
                header_text.setObjectName("Description")
                header_text.setReadOnly(True)
                header_text.setPlainText("\n".join(analysis.prologue))
                header_text.setMaximumHeight(80)
                card.add(header_text)

        for error in package.errors:
            label = QLabel(f"{error['message']}" + (f"\nHint: {error['hint']}" if error.get("hint") else ""))
            label.setWordWrap(True)
            label.setStyleSheet(theme.banner_style(theme.status_colour("ERROR"), theme.row_colour("pe")))
            card.add(label)
            if self.settings.debug and error.get("detail"):
                detail = QTextEdit()
                detail.setReadOnly(True)
                detail.setFont(QFont("Consolas", 9))
                detail.setPlainText(str(error.get("traceback") or error["detail"]))
                detail.setMaximumHeight(160)
                card.add(detail)

        for warning in dict.fromkeys(package.warnings):
            label = QLabel(warning)
            label.setWordWrap(True)
            label.setStyleSheet(theme.banner_style(theme.status_colour("WARNING"), theme.row_colour("warn")))
            card.add(label)
        return card

    def _load_filter_profiles(self) -> None:
        raw = QSettings().value("filters/ptf_profiles", "{}")
        try:
            profiles = json.loads(str(raw))
        except (TypeError, ValueError):
            profiles = {}
        self._filter_profiles = profiles if isinstance(profiles, dict) else {}
        if hasattr(self, "filter_profile"):
            for name in sorted(self._filter_profiles):
                self.filter_profile.addItem(name)

    def save_filter_profile(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        name, accepted = QInputDialog.getText(self, "Save filter profile", "Profile name:")
        if not accepted or not name.strip():
            return
        self._filter_profiles[name.strip()] = {
            "search": self.search_box.text(), "fmid": self.fmid_combo.currentText(),
            "only_pe": self.only_pe.isChecked(), "only_hold": self.only_hold.isChecked(),
        }
        QSettings().setValue("filters/ptf_profiles", json.dumps(self._filter_profiles))
        if self.filter_profile.findText(name.strip()) < 0:
            self.filter_profile.addItem(name.strip())
        self.filter_profile.setCurrentText(name.strip())

    def apply_filter_profile(self, index: int) -> None:
        if index <= 0:
            return
        profile = self._filter_profiles.get(self.filter_profile.currentText())
        if not profile:
            return
        self.search_box.setText(profile.get("search", ""))
        position = self.fmid_combo.findText(profile.get("fmid", "All FMIDs"))
        self.fmid_combo.setCurrentIndex(max(position, 0))
        self.only_pe.setChecked(bool(profile.get("only_pe")))
        self.only_hold.setChecked(bool(profile.get("only_hold")))

    def delete_filter_profile(self) -> None:
        name = self.filter_profile.currentText()
        if self.filter_profile.currentIndex() <= 0 or name not in self._filter_profiles:
            return
        self._filter_profiles.pop(name)
        QSettings().setValue("filters/ptf_profiles", json.dumps(self._filter_profiles))
        self.filter_profile.removeItem(self.filter_profile.currentIndex())

    def _apply_ptf_filters(self) -> None:
        self.ptf_proxy.set_search(self.search_box.text())
        self.ptf_proxy.set_fmid(self.fmid_combo.currentText())
        self.ptf_proxy.set_only_pe(self.only_pe.isChecked())
        self.ptf_proxy.set_only_hold(self.only_hold.isChecked())
        self.ptf_count_label.setText(
            f"{self.ptf_proxy.rowCount()} of {self.ptf_model.rowCount()} PTF"
        )

    def _on_ptf_selected(self) -> None:
        indexes = self.ptf_table.selectionModel().selectedRows()
        if not indexes:
            self.detail_panel.clear()
            return
        source_row = self.ptf_proxy.mapToSource(indexes[0]).row()
        ptf = self.ptf_model.ptf_at(source_row)
        if ptf is None:
            self.detail_panel.clear()
            return
        raw = raw_statements_for(self._report, ptf) if self._report is not None else []
        self.detail_panel.show_ptf(ptf, raw)

    def _selected_ptf(self) -> Optional[PTFEntry]:
        indexes = self.ptf_table.selectionModel().selectedRows()
        if not indexes:
            return None
        return self.ptf_model.ptf_at(self.ptf_proxy.mapToSource(indexes[0]).row())

    def _refresh_contents(self) -> None:
        if self._report is None or not self._report.packages:
            return
        index = max(self.package_combo.currentIndex(), 0)
        if index >= len(self._report.packages):
            return
        package = self._report.packages[index]
        frame = member_frame(package)
        self.member_table.setModel(RowTableModel(frame.to_dict("records"), list(frame.columns)))
        rows = package.gimfaf
        columns = ["Element", "Name", "Path", "Value"] if rows else ["Element", "Name", "Path", "Value"]
        self.gimfaf_table.setModel(RowTableModel(rows, columns))
        self.gimfaf_label.setText(
            f"GIMFAF / GIMPAF metadata ({', '.join(package.gimfaf_members)})"
            if package.gimfaf_members
            else "GIMFAF / GIMPAF metadata - not present in this package"
        )

    # -- logs ------------------------------------------------------------
    def _row_visible(self, row: dict) -> bool:
        from ptfanalyzer.logging_util import _ORDER

        minimum = self.log_level_combo.currentText() if hasattr(self, "log_level_combo") else "INFO"
        return _ORDER.get(row.get("level", "INFO"), 20) >= _ORDER.get(minimum, 20)

    def _log_columns(self) -> list[str]:
        return ["time", "level", "scope", "message", "detail"] if self.settings.debug else [
            "time",
            "level",
            "scope",
            "message",
        ]

    def _refresh_logs(self) -> None:
        if not hasattr(self, "log_table"):
            return
        rows = [row for row in self._log_rows if self._row_visible(row)]
        self.log_table.setModel(RowTableModel(rows, self._log_columns()))
        self.log_table.scrollToBottom()

    def _append_log_row(self, row: dict) -> None:
        model = self.log_table.model()
        if isinstance(model, RowTableModel):
            model.set_rows([*model.rows, row], self._log_columns())
            self.log_table.scrollToBottom()

    def _show_log_detail(self, index) -> None:
        model = self.log_table.model()
        if not isinstance(model, RowTableModel):
            return
        row = model.row(index.row())
        detail = row.get("detail") or "(no technical detail for this entry)"
        self.log_detail.setPlainText(f"{row.get('level')} - {row.get('message')}\n\n{detail}")

    # ------------------------------------------------------------------
    # history (local database)
    # ------------------------------------------------------------------
    def refresh_history(self) -> None:
        if self._store is None:
            self.history_status.setText(
                f"The local database is not available: {self._store_error}"
            )
            self.status_database.set_value("unavailable")
            return

        summaries = self._store.list_analyses(search=self.history_search.text().strip(), limit=self.settings.history_limit)
        self.history_table.setModel(
            RowTableModel(
                [summary.as_row() for summary in summaries],
                ["ID", "Date", "Label", "Archived", "Notes", "Packages", "PTFs", "HOLDs", "Errors", "Duration (s)", "Sources"],
            )
        )
        stats = self._store.stats()
        self.history_status.setText(
            f"{stats['analyses']} stored analysis/analyses - {stats['ptf_rows']} PTF row(s), "
            f"{stats['unique_ptfs']} unique id(s) - {human_size(stats['size_bytes'])} - {stats['path']}"
        )
        self.status_database.set_value(f"{stats['analyses']} stored")
        selected_before = self.compare_before.currentData() if hasattr(self, "compare_before") else None
        selected_after = self.compare_after.currentData() if hasattr(self, "compare_after") else None
        if hasattr(self, "compare_before"):
            self.compare_before.clear()
            self.compare_after.clear()
            for summary in reversed(summaries):
                label = f"#{summary.id}  {summary.created_local}  {summary.label}"
                self.compare_before.addItem(label, summary.id)
                self.compare_after.addItem(label, summary.id)
            for combo, selected in ((self.compare_before, selected_before), (self.compare_after, selected_after)):
                position = combo.findData(selected)
                combo.setCurrentIndex(position if position >= 0 else max(combo.count() - 1, 0))
        self.refresh_inventory()

    def _selected_history_id(self) -> Optional[int]:
        indexes = self.history_table.selectionModel().selectedRows()
        if not indexes:
            return None
        model = self.history_table.model()
        if not isinstance(model, RowTableModel):
            return None
        return int(model.row(indexes[0].row())["ID"])

    def open_selected_history(self) -> None:
        analysis_id = self._selected_history_id()
        if analysis_id is None:
            QMessageBox.information(self, "History", "Select a stored analysis first.")
            return
        self.open_history(analysis_id)

    def open_history(self, analysis_id: int) -> None:
        if self._store is None:
            return
        try:
            report = self._store.load_report(analysis_id)
        except Exception as exc:  # noqa: BLE001 - shown, never fatal
            QMessageBox.critical(self, "History", f"The analysis could not be opened.\n\n{exc}")
            return

        self._report = report
        self._loaded_id = analysis_id
        self._populate(report)
        self._log_rows = list(report.log_entries)
        self._refresh_logs()
        self.tabs.setCurrentIndex(0)
        self.status_message.setText(
            f"Opened stored analysis #{analysis_id} "
            f"({len(report.ptfs)} PTF, {len(report.analyzed_packages)} package). "
            "Raw MCS statements are not part of the stored data."
        )

    def rename_selected_history(self) -> None:
        analysis_id = self._selected_history_id()
        if analysis_id is None or self._store is None:
            return
        from PySide6.QtWidgets import QInputDialog

        label, accepted = QInputDialog.getText(self, "Rename analysis", "New label:")
        if accepted and label.strip():
            self._store.rename(analysis_id, label.strip())
            self.refresh_history()

    def note_selected_history(self) -> None:
        analysis_id = self._selected_history_id()
        if analysis_id is None or self._store is None:
            return
        from PySide6.QtWidgets import QInputDialog
        current = next((s.notes for s in self._store.list_analyses(limit=self.settings.history_limit) if s.id == analysis_id), "")
        notes, accepted = QInputDialog.getMultiLineText(self, "Analysis notes", "Notes:", current)
        if accepted:
            self._store.annotate(analysis_id, notes.strip())
            self.refresh_history()

    def archive_selected_history(self) -> None:
        analysis_id = self._selected_history_id()
        if analysis_id is None or self._store is None:
            return
        summary = next((s for s in self._store.list_analyses(limit=self.settings.history_limit) if s.id == analysis_id), None)
        self._store.set_archived(analysis_id, not bool(summary and summary.archived))
        self.refresh_history()

    def run_comparison(self) -> None:
        if self._store is None or self.compare_before.currentData() is None or self.compare_after.currentData() is None:
            return
        before_id, after_id = int(self.compare_before.currentData()), int(self.compare_after.currentData())
        if before_id == after_id:
            QMessageBox.information(self, "Compare", "Select two different analyses.")
            return
        try:
            self._comparison_rows = compare_reports(self._store.load_report(before_id), self._store.load_report(after_id))
        except Exception as exc:
            QMessageBox.critical(self, "Compare", f"Analyses could not be compared.\n\n{exc}")
            return
        self.compare_table.setModel(RowTableModel(self._comparison_rows, ["Status", "PTF", "FMID", "PE", "Changed fields", "Description"]))
        counts = comparison_summary(self._comparison_rows)
        self.compare_summary.setText(" · ".join(f"{name}: {count}" for name, count in counts.items()))

    def refresh_inventory(self) -> None:
        if self._store is None or not hasattr(self, "inventory_table"):
            return
        rows = self._store.inventory(self.inventory_search.text().strip())
        self.inventory_table.setModel(RowTableModel(rows, ["PTF", "Type", "FMID", "Seen", "First seen", "Last seen", "Ever PE"]))
        duplicates = self._store.duplicate_packages()
        self.duplicate_label.setText(f"{len(rows)} inventory row(s) · {len(duplicates)} repeated package fingerprint(s)")

    def delete_selected_history(self) -> None:
        analysis_id = self._selected_history_id()
        if analysis_id is None or self._store is None:
            return
        confirm = QMessageBox.question(
            self,
            "Delete analysis",
            f"Delete stored analysis #{analysis_id}? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            self._store.delete(analysis_id)
            self.refresh_history()
            self.status_message.setText(f"Stored analysis #{analysis_id} deleted.")

    def search_history_ptfs(self) -> None:
        if self._store is None:
            return
        text = self.ptf_history_search.text().strip()
        rows = self._store.search_ptfs(text) if text else []
        self.history_ptf_table.setModel(
            RowTableModel(
                rows,
                ["Analysis", "Date", "PTF", "Type", "FMID", "Description", "APARs", "HOLD", "PE", "Package"],
            )
        )

    def _open_history_from_ptf(self, index) -> None:
        model = self.history_ptf_table.model()
        if isinstance(model, RowTableModel):
            self.open_history(int(model.row(index.row())["Analysis"]))

    # ------------------------------------------------------------------
    # exports
    # ------------------------------------------------------------------
    def _export_target(self, filename: str) -> str:
        return str(Path(self.settings.last_export_dir) / filename) if self.settings.last_export_dir else filename

    def _remember_export(self, path: str) -> None:
        self.settings.last_export_dir = str(Path(path).parent)
        self.settings.save()

    def export_csv(self) -> None:
        if self._report is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save PTF list", self._export_target("ptf_list.csv"), "CSV files (*.csv)")
        if path:
            data = frame_to_csv(ptf_frame(self._report.ptfs))
            if self.settings.mask_private_paths:
                data = redact_sensitive(data.decode("utf-8-sig")).encode("utf-8-sig")
            Path(path).write_bytes(data)
            self._remember_export(path)
            self.status_message.setText("PTF list written.")

    def export_json(self) -> None:
        if self._report is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save report", self._export_target("ptf_report.json"), "JSON files (*.json)")
        if path:
            Path(path).write_text(redact_sensitive(report_to_json(self._report), self.settings.mask_private_paths), encoding="utf-8")
            self._remember_export(path)
            self.status_message.setText("Report written.")

    def export_log(self) -> None:
        if not self._log_rows:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save log", self._export_target("analysis_log.csv"), "CSV files (*.csv)")
        if path:
            import pandas as pd

            data = frame_to_csv(pd.DataFrame(self._log_rows))
            if self.settings.mask_private_paths:
                data = redact_sensitive(data.decode("utf-8-sig")).encode("utf-8-sig")
            Path(path).write_bytes(data)
            self._remember_export(path)
            self.status_message.setText("Log written.")

    def export_excel(self) -> None:
        if self._report is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Corporate Excel report", self._export_target("ptf_analysis.xlsx"), "Excel workbook (*.xlsx)")
        if not path:
            return
        try:
            write_excel_report(self._report, Path(path), self._comparison_rows or None, self.settings.mask_private_paths)
            self._remember_export(path)
            self.status_message.setText("Corporate Excel report written.")
        except Exception as exc:
            QMessageBox.critical(self, "Excel report", f"The report could not be written.\n\n{exc}")

    def _report_html(self) -> str:
        return printable_html(self._report, self.settings.company_name, self.settings.report_title,
                              self.settings.logo_path, self._comparison_rows or None,
                              self.settings.mask_private_paths)

    def export_pdf(self) -> None:
        if self._report is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Corporate PDF report", self._export_target("ptf_analysis.pdf"), "PDF document (*.pdf)")
        if not path:
            return
        document = QTextDocument(self)
        document.setHtml(self._report_html())
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)
        document.print_(printer)
        self._remember_export(path)
        self.status_message.setText("Corporate PDF report written.")

    def print_selected_ptf(self) -> None:
        ptf = self._selected_ptf()
        if ptf is None:
            QMessageBox.information(self, "Print PTF", "Select a PTF first.")
            return
        body = f"<h1>{html.escape(ptf.sysmod_id)}</h1><p><b>FMID:</b> {html.escape(', '.join(ptf.fmids))}</p><p>{html.escape(ptf.description)}</p>"
        body += "<h2>Dependencies</h2><p><b>PRE:</b> " + html.escape(', '.join(ptf.pre)) + "<br><b>REQ:</b> " + html.escape(', '.join(ptf.req)) + "<br><b>SUP:</b> " + html.escape(', '.join(ptf.sup)) + "</p>"
        body += "<h2>HOLD / actions</h2>" + "".join(f"<p><b>{html.escape(h.hold_type)}</b> {html.escape(h.reason)} — {html.escape(h.comment)}</p>" for h in ptf.holds)
        document = QTextDocument(self)
        document.setHtml(f"<html><body>{body}</body></html>")
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        preview = QPrintPreviewDialog(printer, self)
        preview.paintRequested.connect(document.print_)
        preview.exec()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def closeEvent(self, event):  # noqa: N802 - Qt API
        self._runner.shutdown()
        if self._workspace is not None:
            self._workspace.cleanup()
        super().closeEvent(event)
