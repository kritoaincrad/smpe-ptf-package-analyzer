"""Small reusable widgets for the desktop front end."""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtGui import QAction, QFont, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSizePolicy,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ptfanalyzer.models import PTFEntry

from . import theme
from .models import RowTableModel


class Chip(QLabel):
    """Small coloured status badge."""

    def __init__(self, text: str = "", colour: str = theme.MUTED, parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.set_colour(colour)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)

    def set_colour(self, colour: str) -> None:
        self.setStyleSheet(theme.chip_style(colour))

    def set_status(self, status: str) -> None:
        self.setText(status)
        self.set_colour(theme.STATUS_COLOURS.get(status, theme.MUTED))
        self.setVisible(bool(status))


class MetricCard(QFrame):
    """Headline number with a caption."""

    def __init__(self, label: str, value: str = "-", note: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Metric")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(1)

        self._label = QLabel(label.upper())
        self._label.setObjectName("MetricLabel")
        self._value = QLabel(value)
        self._value.setObjectName("MetricValue")
        self._note = QLabel(note)
        self._note.setObjectName("MetricNote")

        layout.addWidget(self._label)
        layout.addWidget(self._value)
        layout.addWidget(self._note)

    def set_value(self, value, note: str = "") -> None:
        self._value.setText(str(value))
        self._note.setText(note)


class KeyValueGrid(QWidget):
    """Two column label/value list."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setHorizontalSpacing(14)
        self._layout.setVerticalSpacing(5)
        self._layout.setColumnStretch(1, 1)

    def set_items(self, items: Sequence[tuple[str, str]]) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for row, (key, value) in enumerate(items):
            key_label = QLabel(key)
            key_label.setObjectName("KeyLabel")
            key_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            value_label = QLabel(str(value) if value not in (None, "") else "-")
            value_label.setObjectName("ValueLabel")
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._layout.addWidget(key_label, row, 0)
            self._layout.addWidget(value_label, row, 1)


class Card(QFrame):
    """Bordered panel with an optional uppercase title."""

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 10, 12, 12)
        self._layout.setSpacing(8)
        if title:
            label = QLabel(title.upper())
            label.setObjectName("CardTitle")
            self._layout.addWidget(label)

    def body(self) -> QVBoxLayout:
        return self._layout

    def add(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)


class FileDropList(QListWidget):
    """File list that accepts drag and drop from Explorer."""

    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.setToolTip("Drop the package files here, or use 'Add files...'")

    def dragEnterEvent(self, event):  # noqa: N802 - Qt API
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):  # noqa: N802 - Qt API
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):  # noqa: N802 - Qt API
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()


class DataTable(QTableView):
    """Read-only, sortable table with copy support."""

    def __init__(self, stretch_column: Optional[str] = None, parent=None):
        super().__init__(parent)
        self._stretch_column = stretch_column
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.setWordWrap(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(24)
        self.horizontalHeader().setHighlightSections(False)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)

        copy_action = QAction("Copy", self)
        copy_action.setShortcut(QKeySequence.Copy)
        copy_action.triggered.connect(self.copy_selection)
        self.addAction(copy_action)

    def setModel(self, model):  # noqa: N802 - Qt API
        super().setModel(model)
        self._apply_column_sizing()

    def _apply_column_sizing(self, max_width: int = 190) -> None:
        """Size columns to their content, capped, with one column stretching.

        Without the cap a single long value (a SHA-256, a 200 character
        comment) pushes every other column off screen.
        """
        model = self.model()
        if model is None:
            return
        header = self.horizontalHeader()
        header.setMinimumSectionSize(58)
        header.setSectionResizeMode(QHeaderView.Interactive)
        self.resizeColumnsToContents()

        stretch_column = None
        for column in range(model.columnCount()):
            name = model.headerData(column, Qt.Horizontal, Qt.DisplayRole)
            if name == self._stretch_column:
                stretch_column = column
                continue
            self.setColumnWidth(column, min(self.columnWidth(column) + 10, max_width))
        if stretch_column is not None:
            header.setSectionResizeMode(stretch_column, QHeaderView.Stretch)

    def _context_menu(self, position) -> None:
        menu = QMenu(self)
        menu.addAction("Copy", self.copy_selection)
        menu.addAction("Select all", self.selectAll)
        menu.exec(self.viewport().mapToGlobal(position))

    def copy_selection(self) -> None:
        indexes: list[QModelIndex] = self.selectedIndexes()
        if not indexes:
            return
        rows: dict[int, dict[int, str]] = {}
        for index in indexes:
            rows.setdefault(index.row(), {})[index.column()] = index.data(Qt.DisplayRole) or ""
        lines = []
        for row in sorted(rows):
            columns = rows[row]
            lines.append("\t".join(columns[column] for column in sorted(columns)))
        QGuiApplication.clipboard().setText("\n".join(lines))


def make_table(rows: Iterable[dict], columns: Optional[Sequence[str]] = None, stretch: Optional[str] = None) -> DataTable:
    table = DataTable(stretch)
    table.setModel(RowTableModel(list(rows), columns))
    return table


class PTFDetailPanel(QWidget):
    """Everything known about the selected PTF."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QTabWidget  # local import keeps the header short

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        self._title = QLabel("-")
        self._title.setObjectName("SectionTitle")
        self._type_chip = Chip("", theme.INFO)
        self._pe_chip = Chip("", theme.ERR)
        self._hold_chip = Chip("", theme.WARN)
        self._jclin_chip = Chip("", theme.MUTED)
        header.addWidget(self._title)
        header.addSpacing(6)
        for chip in (self._type_chip, self._pe_chip, self._hold_chip, self._jclin_chip):
            chip.hide()
            header.addWidget(chip)
        header.addStretch(1)
        layout.addLayout(header)

        self._description = QTextEdit()
        self._description.setObjectName("Description")
        self._description.setReadOnly(True)
        self._description.setMinimumHeight(88)
        self._description.setMaximumHeight(170)
        layout.addWidget(self._description)

        grids = QHBoxLayout()
        grids.setSpacing(24)
        self._left_grid = KeyValueGrid()
        self._right_grid = KeyValueGrid()
        grids.addWidget(self._left_grid, 1)
        grids.addWidget(self._right_grid, 1)
        layout.addLayout(grids)

        self._tabs = QTabWidget()
        self._elements = DataTable("Element")
        self._holds = DataTable("Comment")
        self._raw = QTextEdit()
        self._raw.setReadOnly(True)
        self._raw.setFont(QFont("Consolas", 9))
        self._tabs.addTab(self._elements, "Elements")
        self._tabs.addTab(self._holds, "HOLD / RELEASE")
        self._tabs.addTab(self._raw, "Raw MCS")
        layout.addWidget(self._tabs, 1)

        self.clear()

    def clear(self) -> None:
        self._title.setText("Select a PTF")
        for chip in (self._type_chip, self._pe_chip, self._hold_chip, self._jclin_chip):
            chip.hide()
        self._description.setPlainText("")
        self._left_grid.set_items([])
        self._right_grid.set_items([])
        self._elements.setModel(RowTableModel([], ["Type", "Element", "DISTLIB", "RELFILE", "SYSLIB/other"]))
        self._holds.setModel(RowTableModel([], ["PTF", "Hold Type", "Reason", "FMID", "Date", "Class", "Comment"]))
        self._raw.setPlainText("")

    def show_ptf(self, ptf: PTFEntry, raw_statements: Sequence[str] = ()) -> None:
        self._title.setText(ptf.sysmod_id)

        self._type_chip.setText(ptf.sysmod_type)
        self._type_chip.show()
        self._pe_chip.setText("PE - IN ERROR")
        self._pe_chip.setVisible(ptf.is_pe)
        self._hold_chip.setText(f"{len(ptf.holds)} HOLD")
        self._hold_chip.setVisible(bool(ptf.holds))
        self._jclin_chip.setText("JCLIN")
        self._jclin_chip.setVisible(ptf.has_jclin)

        self._description.setPlainText(ptf.description or "No description text in this package.")

        self._left_grid.set_items(
            [
                ("FMID", ", ".join(ptf.fmids)),
                ("VER / RMID", ", ".join(ptf.vers)),
                ("Rework", ptf.reworked),
                ("JCLIN", "yes" if ptf.has_jclin else "no"),
                ("Source member", ptf.source),
                ("First record", ptf.record_start),
            ]
        )
        self._right_grid.set_items(
            [
                ("PRE (prerequisites)", ", ".join(ptf.pre)),
                ("REQ (co-requisites)", ", ".join(ptf.req)),
                ("SUP (supersedes)", ", ".join(ptf.sup)),
                ("APARs fixed", ", ".join(ptf.apars)),
                ("DELETE", ", ".join(ptf.delete)),
                (
                    "Conditional (++IF)",
                    "; ".join(
                        f"FMID {', '.join(c['FMID'])} -> REQ {', '.join(c['REQ'])}"
                        for c in ptf.if_conditions
                    ),
                ),
            ]
        )

        self._elements.setModel(
            RowTableModel(
                [element.as_dict() for element in ptf.elements],
                ["Type", "Element", "DISTLIB", "RELFILE", "SYSLIB/other"],
            )
        )
        self._tabs.setTabText(0, f"Elements ({len(ptf.elements)})")
        self._holds.setModel(
            RowTableModel(
                [hold.as_dict() for hold in ptf.holds],
                ["PTF", "Hold Type", "Reason", "FMID", "Date", "Class", "Comment"],
            )
        )
        self._tabs.setTabText(1, f"HOLD / RELEASE ({len(ptf.holds)})")
        self._raw.setPlainText("\n\n".join(raw_statements) or "-")


class StatusItem(QWidget):
    """Label pair used in the status bar."""

    def __init__(self, caption: str, value: str = "-", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(5)
        caption_label = QLabel(caption)
        caption_label.setObjectName("KeyLabel")
        self._value = QLabel(value)
        self._value.setObjectName("ValueLabel")
        layout.addWidget(caption_label)
        layout.addWidget(self._value)

    def set_value(self, value: str) -> None:
        self._value.setText(str(value))


def list_item(text: str, tooltip: str = "", data=None) -> QListWidgetItem:
    item = QListWidgetItem(text)
    if tooltip:
        item.setToolTip(tooltip)
    if data is not None:
        item.setData(Qt.UserRole, data)
    return item
