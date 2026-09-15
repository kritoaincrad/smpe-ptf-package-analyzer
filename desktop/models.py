"""Qt table models over the analyzer's plain data structures.

The analyzer never depends on Qt; these adapters keep it that way.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor

from ptfanalyzer.models import PTFEntry

from . import theme

NUMERIC_COLUMNS = {"PRE", "REQ", "SUP", "Size (bytes)", "Size (MB)", "Parts", "Members", "PTFs", "HOLDs"}


class RowTableModel(QAbstractTableModel):
    """A table over ``list[dict]`` with a fixed column order."""

    def __init__(self, rows: Optional[Sequence[dict]] = None, columns: Optional[Sequence[str]] = None, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = list(rows or [])
        self._columns: list[str] = list(columns or (list(self._rows[0]) if self._rows else []))

    # -- data plumbing ---------------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt API
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt API
        return 0 if parent.isValid() else len(self._columns)

    def headerData(self, section: int, orientation, role=Qt.DisplayRole):  # noqa: N802 - Qt API
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self._columns[section]
        return section + 1

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        column = self._columns[index.column()]
        value = row.get(column, "")

        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            text = "" if value is None else str(value)
            if role == Qt.ToolTipRole and len(text) < 40:
                return None
            return text
        if role == Qt.UserRole:
            return value
        if role == Qt.TextAlignmentRole and column in NUMERIC_COLUMNS:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.BackgroundRole:
            tint = self.row_tint(row)
            if tint:
                return QColor(tint)
        if role == Qt.ForegroundRole and column in ("Status", "Hold Type", "level"):
            colour = theme.STATUS_COLOURS.get(str(value)) or theme.LEVEL_COLOURS.get(str(value))
            if colour:
                return QColor(colour)
        return None

    # -- helpers ---------------------------------------------------------
    def row_tint(self, row: dict) -> Optional[str]:
        return None

    def set_rows(self, rows: Sequence[dict], columns: Optional[Sequence[str]] = None) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        if columns is not None:
            self._columns = list(columns)
        elif self._rows and not self._columns:
            self._columns = list(self._rows[0])
        self.endResetModel()

    def row(self, position: int) -> dict:
        return self._rows[position]

    @property
    def rows(self) -> list[dict]:
        return self._rows

    @property
    def columns(self) -> list[str]:
        return self._columns


class PTFTableModel(RowTableModel):
    """PTF list with the source objects kept alongside the display rows."""

    #: Kept deliberately short - the detail pane shows everything else.
    COLUMNS = ["PTF", "Type", "FMID", "Description", "HOLD", "PE"]

    def __init__(self, ptfs: Optional[Iterable[PTFEntry]] = None, parent=None):
        self._ptfs: list[PTFEntry] = list(ptfs or [])
        self._haystacks: list[str] = [self._haystack(ptf) for ptf in self._ptfs]
        super().__init__([ptf.as_row() for ptf in self._ptfs], self.COLUMNS, parent)

    def set_ptfs(self, ptfs: Iterable[PTFEntry]) -> None:
        self._ptfs = list(ptfs)
        self._haystacks = [self._haystack(ptf) for ptf in self._ptfs]
        self.set_rows([ptf.as_row() for ptf in self._ptfs], self.COLUMNS)

    @staticmethod
    def _haystack(ptf: PTFEntry) -> str:
        """Everything searchable about a PTF, not only the visible columns."""
        parts = [
            ptf.sysmod_id,
            ptf.sysmod_type,
            ptf.description,
            ptf.source,
            *ptf.fmids,
            *ptf.vers,
            *ptf.pre,
            *ptf.req,
            *ptf.sup,
            *ptf.delete,
            *ptf.apars,
            *(element.name for element in ptf.elements),
            *(element.kind for element in ptf.elements),
            *(hold.reason for hold in ptf.holds),
            *(hold.comment for hold in ptf.holds),
        ]
        return " ".join(part for part in parts if part).upper()

    def search_text(self, position: int) -> str:
        if 0 <= position < len(self._haystacks):
            return self._haystacks[position]
        return ""

    def ptf_at(self, position: int) -> Optional[PTFEntry]:
        if 0 <= position < len(self._ptfs):
            return self._ptfs[position]
        return None

    @property
    def ptfs(self) -> list[PTFEntry]:
        return self._ptfs

    def row_tint(self, row: dict) -> Optional[str]:
        if row.get("PE") == "YES":
            return theme.PE_ROW
        if row.get("HOLD") not in ("-", "", None):
            return theme.WARN_ROW
        return None


class PTFFilterProxy(QSortFilterProxyModel):
    """Search box + FMID + 'only PE' + 'only HOLD' filtering."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._search = ""
        self._fmid = ""
        self._only_pe = False
        self._only_hold = False
        self.setSortCaseSensitivity(Qt.CaseInsensitive)

    def set_search(self, text: str) -> None:
        self._search = text.strip().upper()
        self.invalidate()

    def set_fmid(self, fmid: str) -> None:
        self._fmid = "" if fmid.startswith("All") else fmid.strip().upper()
        self.invalidate()

    def set_only_pe(self, enabled: bool) -> None:
        self._only_pe = enabled
        self.invalidate()

    def set_only_hold(self, enabled: bool) -> None:
        self._only_hold = enabled
        self.invalidate()

    def filterAcceptsRow(self, source_row: int, parent: QModelIndex) -> bool:  # noqa: N802 - Qt API
        model = self.sourceModel()
        if model is None:
            return True
        row = model.row(source_row)

        if self._only_pe and row.get("PE") != "YES":
            return False
        if self._only_hold and row.get("HOLD") in ("-", "", None):
            return False
        if self._fmid and self._fmid not in str(row.get("FMID", "")).upper():
            return False
        if self._search:
            if hasattr(model, "search_text"):
                haystack = model.search_text(source_row)
            else:
                haystack = " ".join(str(value) for value in row.values()).upper()
            if self._search not in haystack:
                return False
        return True

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802 - Qt API
        left_value = left.data(Qt.UserRole)
        right_value = right.data(Qt.UserRole)
        if isinstance(left_value, (int, float)) and isinstance(right_value, (int, float)):
            return left_value < right_value
        return str(left_value).upper() < str(right_value).upper()


def dict_rows(items: Iterable[Any]) -> list[dict]:
    """Normalize ``as_dict()``-style objects into plain rows."""
    return [item if isinstance(item, dict) else item.as_dict() for item in items]
