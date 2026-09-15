"""Preferences dialog: categories on the left, explained settings on the right."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ptfanalyzer.compression import available_decoders
from ptfanalyzer.database import default_database_path
from ptfanalyzer.encoding import CANDIDATE_ENCODINGS

from . import theme
from .settings import AUTOMATIC, Settings

AUTOMATIC_DECODER = "Automatic (fallback chain)"
AUTOMATIC_ENCODING = "Automatic detection"


class Setting(QWidget):
    """One row: the control, its title and a one line explanation."""

    def __init__(self, control: QWidget, title: str, description: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        if isinstance(control, QCheckBox):
            control.setText(title)
            control.setObjectName("PreferenceCheckBox")
            layout.addWidget(control)
        else:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            label = QLabel(title)
            label.setMinimumWidth(190)
            row.addWidget(label)
            row.addWidget(control, 1)
            layout.addLayout(row)

        note = QLabel(description)
        note.setObjectName("SettingNote")
        note.setWordWrap(True)
        note.setContentsMargins(30 if isinstance(control, QCheckBox) else 0, 0, 0, 0)
        layout.addWidget(note)


class Page(QWidget):
    """One preferences category."""

    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(20, 18, 20, 18)
        self._layout.setSpacing(14)

        heading = QLabel(title)
        heading.setObjectName("SectionTitle")
        self._layout.addWidget(heading)
        if subtitle:
            note = QLabel(subtitle)
            note.setObjectName("KeyLabel")
            note.setWordWrap(True)
            self._layout.addWidget(note)

        line = QFrame()
        line.setObjectName("Divider")
        line.setFrameShape(QFrame.HLine)
        self._layout.addWidget(line)

    def add(self, control: QWidget, title: str, description: str) -> QWidget:
        self._layout.addWidget(Setting(control, title, description))
        return control

    def finish(self) -> None:
        self._layout.addStretch(1)


class PreferencesDialog(QDialog):
    """Modal settings editor - nothing is applied until OK is pressed."""

    def __init__(self, settings: Settings, parent=None, initial_page: str = ""):
        super().__init__(parent)
        self.setObjectName("PreferencesDialog")
        self.setWindowTitle("Preferences")
        self.setMinimumSize(760, 520)
        self._settings = settings.copy()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.categories = QListWidget()
        self.categories.setObjectName("PreferenceCategories")
        self.categories.setFixedWidth(184)
        self.categories.setFrameShape(QFrame.NoFrame)
        self.pages = QStackedWidget()
        self.pages.setObjectName("PreferencePages")

        category_titles = []
        for title, builder in (
            ("Appearance", self._build_appearance_page),
            ("Decompression", self._build_decompression_page),
            ("SMP/E metadata", self._build_metadata_page),
            ("History", self._build_history_page),
            ("Reports", self._build_reports_page),
            ("Security", self._build_security_page),
            ("Diagnostics", self._build_diagnostics_page),
        ):
            category_titles.append(title)
            self.categories.addItem(QListWidgetItem(title))
            self.pages.addWidget(builder())
        self.categories.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.categories.setCurrentRow(
            category_titles.index(initial_page) if initial_page in category_titles else 0
        )

        body.addWidget(self.categories)
        body.addWidget(self.pages, 1)
        layout.addLayout(body, 1)

        footer = QFrame()
        footer.setObjectName("DialogFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 10, 16, 10)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self._restore_defaults)
        ok_button = buttons.button(QDialogButtonBox.Ok)
        ok_button.setDefault(True)
        ok_button.setObjectName("Primary")
        footer_layout.addStretch(1)
        footer_layout.addWidget(buttons)
        layout.addWidget(footer)

        self._load(self._settings)

    # -- pages -----------------------------------------------------------
    def _build_appearance_page(self) -> QWidget:
        page = Page("Appearance and workflow", "Desktop display and file-selection behaviour.")
        self.dark_theme = page.add(QCheckBox(), "Dark theme", "Applied immediately after saving preferences.")
        self.notifications = page.add(QCheckBox(), "Notify when analysis finishes", "Shows a native desktop notification when the application is in the background.")
        self.recursive_folders = page.add(QCheckBox(), "Include subfolders when a folder is dropped", "Find package parts recursively and skip duplicate paths.")
        page.finish()
        return page

    def _build_decompression_page(self) -> QWidget:
        page = Page(
            "Decompression",
            "How the joined .Z stream is expanded. The built-in decoder is always "
            "available; external tools are faster on very large packages.",
        )
        self.allow_partial = page.add(
            QCheckBox(),
            "Accept partially decodable streams",
            "If the stream ends in the middle of a code, keep what could be decoded "
            "instead of failing the whole package.",
        )
        self.prefer_external = page.add(
            QCheckBox(),
            "Prefer external tools for large packages",
            "7-Zip or uncompress are several times faster than a pure python decoder.",
        )
        self.threshold = page.add(
            self._spin(8, 4096, 16, " MB"),
            "External tool threshold",
            "Packages larger than this use an external decoder first, when one is installed.",
        )
        self.decoder = QComboBox()
        self.decoder.addItem(AUTOMATIC_DECODER)
        for decoder in available_decoders():
            suffix = "" if decoder["available"] else "  (not installed)"
            self.decoder.addItem(f"{decoder['name']}{suffix}")
        page.add(
            self.decoder,
            "Force one decoder",
            "Normally every decoder is tried in order until one succeeds. Pin one only "
            "to reproduce a problem.",
        )
        page.finish()
        return page

    def _build_metadata_page(self) -> QWidget:
        page = Page(
            "SMP/E metadata",
            "How SMPPTFIN, SMPMCS and HOLDDATA are decoded and parsed.",
        )
        self.encoding = QComboBox()
        self.encoding.addItem(AUTOMATIC_ENCODING)
        self.encoding.addItems(list(CANDIDATE_ENCODINGS))
        page.add(
            self.encoding,
            "Character encoding",
            "Detection looks for real SMP/E keywords in every candidate code page and "
            "picks the best match. Force one only if detection gets it wrong.",
        )
        self.honor_columns = page.add(
            QCheckBox(),
            "Ignore columns 73-80 (sequence numbers)",
            "SMP/E itself ignores these columns on 80 byte card images.",
        )
        self.nested_depth = page.add(
            self._spin(0, 3, 1, " level(s)"),
            "Nested archive depth",
            "GIMZIP style packages contain archives inside archives; this is how deep to look.",
        )
        self.analyze_duplicates = page.add(
            QCheckBox(),
            "Analyze duplicate packages too",
            "By default a package that is byte identical to another one is listed but not "
            "processed twice.",
        )
        page.finish()
        return page

    def _build_history_page(self) -> QWidget:
        page = Page(
            "History",
            f"Analyses are stored in a local SQLite database:\n{default_database_path()}",
        )
        self.auto_save = page.add(
            QCheckBox(),
            "Save every analysis automatically",
            "Stored analyses can be reopened from the History tab without processing the "
            "package again.",
        )
        self.history_limit = page.add(
            self._spin(10, 2000, 10, " entries"),
            "Entries shown in the history list",
            "Older analyses stay in the database; this only limits what the list displays.",
        )
        page.finish()
        return page

    def _build_diagnostics_page(self) -> QWidget:
        page = Page(
            "Diagnostics",
            "Extra detail for tracking down a problem with a specific package.",
        )
        self.debug = page.add(
            QCheckBox(),
            "Debug mode",
            "Shows technical detail, decoder attempts, encoding candidates, raw MCS "
            "statements and python tracebacks next to the plain messages.",
        )
        page.finish()
        return page

    def _build_reports_page(self) -> QWidget:
        page = Page("Corporate reports", "Branding used by PDF exports and printable reports.")
        hint = QLabel(
            "Set your identity here, save with OK, then create the report from "
            "File > Corporate report (PDF) or Corporate report (Excel)."
        )
        hint.setObjectName("ReportHint")
        hint.setWordWrap(True)
        page._layout.addWidget(hint)

        self.company_name = QLineEdit()
        self.company_name.setPlaceholderText("Example: Company or business unit")
        page.add(self.company_name, "Company name", "Optional name displayed below the report title.")

        self.report_title = QLineEdit()
        self.report_title.setPlaceholderText("SMP/E PTF Analysis Report")
        page.add(self.report_title, "Report title", "Heading used in printable and PDF reports.")

        logo_control = QWidget()
        logo_layout = QHBoxLayout(logo_control)
        logo_layout.setContentsMargins(0, 0, 0, 0)
        logo_layout.setSpacing(6)
        self.logo_path = QLineEdit()
        self.logo_path.setPlaceholderText("No logo selected")
        self.logo_path.setReadOnly(True)
        browse_logo = QPushButton("Browse...")
        browse_logo.clicked.connect(self._choose_logo)
        clear_logo = QPushButton("Clear")
        clear_logo.clicked.connect(self.logo_path.clear)
        logo_layout.addWidget(self.logo_path, 1)
        logo_layout.addWidget(browse_logo)
        logo_layout.addWidget(clear_logo)
        page.add(logo_control, "Company logo", "Optional PNG, JPG or SVG image used in PDF and print output.")
        self.mask_private_paths = page.add(QCheckBox(), "Mask private paths in exports", "Replaces user, network and home paths plus e-mail/IP values in corporate reports and logs.")
        page.finish()
        return page

    def _choose_logo(self) -> None:
        start = self.logo_path.text() or self._settings.logo_path
        path, _ = QFileDialog.getOpenFileName(
            self, "Select company logo", start,
            "Image files (*.png *.jpg *.jpeg *.svg);;All files (*)",
        )
        if path:
            self.logo_path.setText(path)

    def _build_security_page(self) -> QWidget:
        page = Page("Security", "Controls that reduce accidental data disclosure.")
        self.offline_mode = page.add(QCheckBox(), "Enforce offline analysis", "Blocks outbound socket connections for the duration of every analysis.")
        self.encrypt_database = page.add(QCheckBox(), "Encrypt history database with SQLCipher", "Requires a SQLCipher Python driver and the PTFANALYZER_DB_KEY environment variable. Restart after changing.")
        note = QLabel("The database key is never stored in application settings. Windows signing needs an organization-managed certificate.")
        note.setObjectName("SecurityNote")
        note.setWordWrap(True)
        page._layout.addWidget(note)
        page.finish()
        return page

    @staticmethod
    def _spin(minimum: int, maximum: int, step: int, suffix: str) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setSuffix(suffix)
        spin.setMinimumWidth(170)
        spin.setMaximumWidth(210)
        return spin

    # -- values ----------------------------------------------------------
    def _load(self, settings: Settings) -> None:
        self.allow_partial.setChecked(settings.allow_partial)
        self.prefer_external.setChecked(settings.prefer_external)
        self.threshold.setValue(settings.threshold_mb)
        self.decoder.setCurrentIndex(0)
        if settings.forced_decoder:
            for index in range(self.decoder.count()):
                if self.decoder.itemText(index).startswith(settings.forced_decoder):
                    self.decoder.setCurrentIndex(index)
                    break
        self.encoding.setCurrentText(settings.encoding or AUTOMATIC_ENCODING)
        self.honor_columns.setChecked(settings.honor_columns)
        self.nested_depth.setValue(settings.nested_depth)
        self.analyze_duplicates.setChecked(settings.analyze_duplicates)
        self.auto_save.setChecked(settings.auto_save)
        self.history_limit.setValue(settings.history_limit)
        self.dark_theme.setChecked(settings.dark_theme)
        self.notifications.setChecked(settings.notifications)
        self.recursive_folders.setChecked(settings.recursive_folders)
        self.company_name.setText(settings.company_name)
        self.report_title.setText(settings.report_title)
        self.logo_path.setText(settings.logo_path)
        self.mask_private_paths.setChecked(settings.mask_private_paths)
        self.offline_mode.setChecked(settings.offline_mode)
        self.encrypt_database.setChecked(settings.encrypt_database)
        self.debug.setChecked(settings.debug)

    def _restore_defaults(self) -> None:
        self._load(Settings())

    def result_settings(self) -> Settings:
        decoder = self.decoder.currentText()
        encoding = self.encoding.currentText()
        return Settings(
            allow_partial=self.allow_partial.isChecked(),
            prefer_external=self.prefer_external.isChecked(),
            threshold_mb=self.threshold.value(),
            forced_decoder=AUTOMATIC if decoder == AUTOMATIC_DECODER else decoder.split("  (")[0],
            encoding=AUTOMATIC if encoding == AUTOMATIC_ENCODING else encoding,
            honor_columns=self.honor_columns.isChecked(),
            nested_depth=self.nested_depth.value(),
            analyze_duplicates=self.analyze_duplicates.isChecked(),
            auto_save=self.auto_save.isChecked(),
            history_limit=self.history_limit.value(),
            dark_theme=self.dark_theme.isChecked(),
            notifications=self.notifications.isChecked(),
            recursive_folders=self.recursive_folders.isChecked(),
            last_input_dir=self._settings.last_input_dir,
            last_export_dir=self._settings.last_export_dir,
            company_name=self.company_name.text().strip(),
            report_title=self.report_title.text().strip() or "SMP/E PTF Analysis Report",
            logo_path=self.logo_path.text().strip(),
            mask_private_paths=self.mask_private_paths.isChecked(),
            offline_mode=self.offline_mode.isChecked(),
            encrypt_database=self.encrypt_database.isChecked(),
            debug=self.debug.isChecked(),
        )


def edit_settings(settings: Settings, parent=None, initial_page: str = "") -> Optional[Settings]:
    """Show the dialog; returns the new settings or ``None`` if cancelled."""
    dialog = PreferencesDialog(settings, parent, initial_page)
    if dialog.exec() == QDialog.Accepted:
        return dialog.result_settings()
    return None
