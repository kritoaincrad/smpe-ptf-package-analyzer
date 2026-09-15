"""Preferences dialog: categories on the left, explained settings on the right."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
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
        note.setObjectName("KeyLabel")
        note.setWordWrap(True)
        note.setContentsMargins(20 if isinstance(control, QCheckBox) else 0, 0, 0, 0)
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
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color: {theme.LINE};")
        self._layout.addWidget(line)

    def add(self, control: QWidget, title: str, description: str) -> QWidget:
        self._layout.addWidget(Setting(control, title, description))
        return control

    def finish(self) -> None:
        self._layout.addStretch(1)


class PreferencesDialog(QDialog):
    """Modal settings editor - nothing is applied until OK is pressed."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
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
        self.categories.setFixedWidth(190)
        self.categories.setFrameShape(QFrame.NoFrame)
        self.categories.setStyleSheet(
            f"QListWidget {{ background: {theme.SURFACE_ALT};"
            f"border-right: 1px solid {theme.LINE}; outline: none; }}"
            "QListWidget::item { padding: 10px 14px; border-left: 3px solid transparent; }"
            f"QListWidget::item:hover {{ background: {theme.SURFACE}; }}"
            f"QListWidget::item:selected, QListWidget::item:selected:!active {{"
            f"background: {theme.SURFACE}; color: {theme.BRAND};"
            f"border-left: 3px solid {theme.BRAND}; font-weight: 600; }}"
        )
        self.pages = QStackedWidget()

        for title, builder in (
            ("Decompression", self._build_decompression_page),
            ("SMP/E metadata", self._build_metadata_page),
            ("History", self._build_history_page),
            ("Diagnostics", self._build_diagnostics_page),
        ):
            self.categories.addItem(QListWidgetItem(title))
            self.pages.addWidget(builder())
        self.categories.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.categories.setCurrentRow(0)

        body.addWidget(self.categories)
        body.addWidget(self.pages, 1)
        layout.addLayout(body, 1)

        footer = QFrame()
        footer.setStyleSheet(f"background: {theme.SURFACE_ALT}; border-top: 1px solid {theme.LINE};")
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
        ok_button.setStyleSheet(
            f"background: {theme.BRAND}; color: #FFFFFF; border: 1px solid {theme.BRAND};"
            "border-radius: 3px; padding: 6px 22px; font-weight: 600;"
        )
        footer_layout.addStretch(1)
        footer_layout.addWidget(buttons)
        layout.addWidget(footer)

        self._load(self._settings)

    # -- pages -----------------------------------------------------------
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
            debug=self.debug.isChecked(),
        )


def edit_settings(settings: Settings, parent=None) -> Optional[Settings]:
    """Show the dialog; returns the new settings or ``None`` if cancelled."""
    dialog = PreferencesDialog(settings, parent)
    if dialog.exec() == QDialog.Accepted:
        return dialog.result_settings()
    return None
