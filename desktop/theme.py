"""Flat corporate Qt theme - solid colours only, no gradients."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QProxyStyle, QStyle

BRAND = "#0B3D62"
BRAND_DARK = "#072B46"
INK = "#1F2933"
MUTED = "#5B6B7A"
LINE = "#D7DEE5"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#F4F6F8"
OK = "#1B7F4B"
WARN = "#B26A00"
ERR = "#B3261E"
INFO = "#1E5A8A"

#: Row tint used for PTFs that are in error (PE).
PE_ROW = "#FBE9E8"
WARN_ROW = "#FDF8EF"

DARK_INK = "#E7EDF3"
DARK_MUTED = "#A7B3BF"
DARK_LINE = "#344452"
DARK_SURFACE = "#18232D"
DARK_SURFACE_ALT = "#111A22"
DARK_HOVER = "#22313E"
DARK_SELECTED = "#29465D"
DARK_PE_ROW = "#3A2429"
DARK_WARN_ROW = "#3A3122"
DARK_OK = "#57C78B"
DARK_WARN = "#F0B35A"
DARK_ERR = "#F47B75"
DARK_INFO = "#65B7ED"

_DARK_ACTIVE = False

STATUS_COLOURS = {
    "COMPLETED": OK,
    "READY": OK,
    "COMPLETED WITH WARNINGS": WARN,
    "WARNING": WARN,
    "NO PTF FOUND": WARN,
    "HOLDDATA ONLY": INFO,
    "METADATA ONLY": INFO,
    "INCOMPLETE": ERR,
    "FAILED": ERR,
    "DUPLICATE": INFO,
    "ADDED": OK,
    "REMOVED": ERR,
    "CHANGED": WARN,
    "UNCHANGED": MUTED,
}

LEVEL_COLOURS = {
    "ERROR": ERR,
    "WARNING": WARN,
    "SUCCESS": OK,
    "INFO": INFO,
    "DEBUG": MUTED,
}

STYLESHEET = f"""
QWidget {{
    background: {SURFACE};
    color: {INK};
    font-family: "Segoe UI", "Noto Sans", sans-serif;
    font-size: 9.5pt;
}}

QMainWindow, QDialog {{ background: {SURFACE_ALT}; }}

/* ---- menu bar --------------------------------------------------------- */
QMenuBar {{
    background: {SURFACE};
    border-bottom: 1px solid {LINE};
    padding: 2px 4px;
}}
QMenuBar::item {{ padding: 6px 12px; border-radius: 3px; background: transparent; }}
QMenuBar::item:selected {{ background: {SURFACE_ALT}; color: {BRAND}; }}
QMenuBar::item:pressed {{ background: {SURFACE_ALT}; color: {BRAND}; }}

QMenu {{ background: {SURFACE}; border: 1px solid {LINE}; padding: 5px; }}
QMenu::item {{ padding: 6px 30px 6px 18px; border-radius: 3px; }}
QMenu::item:selected {{ background: {SURFACE_ALT}; color: {BRAND}; }}
QMenu::item:disabled {{ color: #A5B0BA; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 5px 10px; }}

/* ---- panels ----------------------------------------------------------- */
QFrame#Card {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: 4px;
}}
QLabel#CardTitle {{
    color: {MUTED};
    font-size: 8.5pt;
    font-weight: 600;
    letter-spacing: 1px;
    background: transparent;
}}
QLabel#SectionTitle {{ font-size: 11pt; font-weight: 600; color: {INK}; background: transparent; }}
QLabel#KeyLabel {{ color: {MUTED}; background: transparent; }}
QLabel#ValueLabel {{ color: {INK}; font-weight: 500; background: transparent; }}

QFrame#Metric {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-top: 3px solid {BRAND};
    border-radius: 4px;
}}
QLabel#MetricLabel {{ color: {MUTED}; font-size: 8pt; letter-spacing: 1px; background: transparent; }}
QLabel#MetricValue {{ color: {INK}; font-size: 18pt; font-weight: 600; background: transparent; }}
QLabel#MetricNote {{ color: {MUTED}; font-size: 8pt; background: transparent; }}

QTextEdit#Description {{
    background: {SURFACE_ALT};
    border: 1px solid {LINE};
    border-left: 3px solid {BRAND};
    padding: 8px;
    font-size: 10pt;
}}

/* ---- inputs ----------------------------------------------------------- */
QPushButton {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: 3px;
    padding: 6px 14px;
    color: {INK};
}}
QPushButton:hover {{ background: {SURFACE_ALT}; border-color: {BRAND}; }}
QPushButton:disabled {{ color: #A5B0BA; background: {SURFACE_ALT}; border-color: {LINE}; }}
QPushButton#Primary {{
    background: {BRAND};
    border: 1px solid {BRAND};
    color: #FFFFFF;
    font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {BRAND_DARK}; border-color: {BRAND_DARK}; }}
QPushButton#Primary:disabled {{ background: #7E97AC; border-color: #7E97AC; color: #E8EEF3; }}

QLineEdit, QComboBox, QSpinBox {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: 3px;
    padding: 5px 7px;
    selection-background-color: {BRAND};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {BRAND}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 17px; border: none; background: {SURFACE_ALT}; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: #E4EAF0; }}
QCheckBox {{ spacing: 7px; background: transparent; }}
QRadioButton {{ spacing: 7px; background: transparent; }}
QCheckBox#PreferenceCheckBox {{
    spacing: 10px;
    padding: 3px 0;
    font-size: 9.5pt;
    font-weight: 500;
}}
QCheckBox::indicator {{ width: 18px; height: 18px; }}
QRadioButton::indicator {{ width: 16px; height: 16px; }}

/* ---- preferences and about ------------------------------------------ */
QDialog#PreferencesDialog, QDialog#AboutDialog, QDialog#DecoderDialog {{ background: {SURFACE}; }}
QListWidget#PreferenceCategories {{
    background: {SURFACE_ALT};
    border: none;
    border-right: 1px solid {LINE};
    outline: none;
}}
QListWidget#PreferenceCategories::item {{
    color: {MUTED};
    padding: 10px 14px;
    border-left: 3px solid transparent;
}}
QListWidget#PreferenceCategories::item:hover {{ background: {SURFACE}; color: {INK}; }}
QListWidget#PreferenceCategories::item:selected,
QListWidget#PreferenceCategories::item:selected:!active {{
    background: {SURFACE};
    color: {INK};
    border-left: 3px solid {INFO};
    font-weight: 600;
}}
QStackedWidget#PreferencePages {{ background: {SURFACE}; border: none; }}
QFrame#DialogFooter {{ background: {SURFACE_ALT}; border-top: 1px solid {LINE}; }}
QFrame#Divider {{ color: {LINE}; background: {LINE}; max-height: 1px; border: none; }}
QLabel#SettingNote {{ color: {MUTED}; background: transparent; font-size: 8.75pt; }}
QLabel#SecurityNote {{
    color: {MUTED}; background: {SURFACE_ALT}; border: 1px solid {LINE};
    border-radius: 3px; padding: 9px 11px;
}}
QLabel#ReportHint, QLabel#DecoderIntro, QLabel#DecoderNote {{
    color: {MUTED}; background: {SURFACE_ALT}; border: 1px solid {LINE};
    border-left: 3px solid {INFO}; border-radius: 3px; padding: 9px 11px;
}}
QFrame#DecoderHeader {{ background: {SURFACE_ALT}; border-bottom: 1px solid {LINE}; }}
QLabel#DecoderColumnLabel {{ color: {MUTED}; background: transparent; font-size: 8pt; font-weight: 600; letter-spacing: 1px; }}
QFrame#DecoderRow {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 4px; }}
QFrame#DecoderRow:hover {{ background: {SURFACE_ALT}; border-color: {BRAND}; }}
QLabel#DecoderIcon {{ color: #FFFFFF; background: {BRAND}; border-radius: 4px; font-size: 20pt; font-weight: 700; }}
QLabel#DecoderTitle {{ color: {INK}; font-size: 13pt; font-weight: 600; background: transparent; }}
QLabel#DecoderSubtitle, QLabel#DecoderPath {{ color: {MUTED}; background: transparent; }}
QLabel#DecoderName {{ color: {INK}; font-weight: 600; background: transparent; }}
QLabel#DecoderOrder {{ color: {BRAND}; background: {SURFACE_ALT}; border-radius: 3px; font-weight: 700; }}
QLabel#AboutIcon {{
    color: #FFFFFF; background: {BRAND}; border-radius: 4px;
    font-size: 27pt; font-weight: 700;
}}
QLabel#AboutTitle {{ color: {INK}; font-size: 14pt; font-weight: 600; background: transparent; }}
QLabel#AboutVersion {{ color: {MUTED}; font-size: 9pt; background: transparent; }}
QLabel#AboutBody {{ color: {INK}; font-size: 9.5pt; background: transparent; }}
QLabel#AboutMeta {{
    color: {MUTED}; background: {SURFACE_ALT}; border: 1px solid {LINE};
    border-radius: 3px; padding: 9px 11px; font-family: Consolas, monospace;
}}

/* ---- tables ----------------------------------------------------------- */
QTableView, QTreeWidget, QListWidget {{
    background: {SURFACE};
    border: 1px solid {LINE};
    gridline-color: #EDF1F4;
    selection-background-color: #DCE7F0;
    selection-color: {INK};
    alternate-background-color: #FAFBFC;
}}
QHeaderView::section {{
    background: {SURFACE_ALT};
    color: {MUTED};
    border: none;
    border-right: 1px solid {LINE};
    border-bottom: 1px solid {LINE};
    padding: 6px 8px;
    font-weight: 600;
}}
QTableView::item {{ padding: 3px 4px; }}

/* ---- tabs ------------------------------------------------------------- */
QTabWidget::pane {{ border: 1px solid {LINE}; background: {SURFACE}; top: -1px; }}
QTabBar::tab {{
    background: {SURFACE_ALT};
    border: 1px solid {LINE};
    border-bottom: none;
    padding: 7px 16px;
    margin-right: 2px;
    color: {MUTED};
}}
QTabBar::tab:selected {{
    background: {SURFACE};
    color: {INK};
    border-bottom: 2px solid {BRAND};
    font-weight: 600;
}}

/* ---- misc ------------------------------------------------------------- */
QSplitter::handle {{ background: {LINE}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QProgressBar {{
    background: {SURFACE_ALT};
    border: 1px solid {LINE};
    border-radius: 3px;
    height: 16px;
    text-align: center;
    color: {INK};
}}
QProgressBar::chunk {{ background: {BRAND}; }}
QStatusBar {{ background: {SURFACE_ALT}; border-top: 1px solid {LINE}; color: {MUTED}; }}
QStatusBar::item {{ border: none; }}
QToolBar {{ background: {SURFACE}; border-bottom: 1px solid {LINE}; spacing: 4px; padding: 5px; }}
QGroupBox {{
    border: 1px solid {LINE};
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: 600;
    color: {MUTED};
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 9px; padding: 0 4px; }}
QScrollBar:vertical {{ background: {SURFACE_ALT}; width: 11px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #C3CDD6; min-height: 24px; border-radius: 5px; }}
QScrollBar::handle:vertical:hover {{ background: {MUTED}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: {SURFACE_ALT}; height: 11px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #C3CDD6; min-width: 24px; border-radius: 5px; }}
"""

# The dark palette deliberately keeps status colours stable so warnings and
# PE rows retain the same meaning in both modes.
DARK_STYLESHEET = STYLESHEET
for _light, _dark in (
    ("#FFFFFF", "#18212B"),
    ("#F4F6F8", "#111820"),
    ("#1F2933", "#E6EDF3"),
    ("#5B6B7A", "#AAB7C4"),
    ("#D7DEE5", "#334250"),
    ("#FAFBFC", "#1D2833"),
    ("#EDF1F4", "#2B3946"),
    ("#DCE7F0", "#29435A"),
    ("#E4EAF0", "#2D3A46"),
    ("#A5B0BA", "#708090"),
):
    DARK_STYLESHEET = DARK_STYLESHEET.replace(_light, _dark)

DARK_STYLESHEET += f"""
/* ---- explicit dark interaction states ------------------------------- */
QWidget {{ background-color: {DARK_SURFACE}; color: {DARK_INK}; }}
QMainWindow, QDialog {{ background-color: {DARK_SURFACE_ALT}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background-color: {DARK_SURFACE}; }}
QMenuBar {{ background-color: {DARK_SURFACE_ALT}; color: {DARK_INK}; border-bottom-color: {DARK_LINE}; }}
QMenuBar::item {{ color: {DARK_INK}; background: transparent; }}
QMenuBar::item:selected {{ color: #FFFFFF; background: {DARK_HOVER}; }}
QMenuBar::item:pressed {{ color: #FFFFFF; background: {DARK_SELECTED}; }}
QMenu {{ background-color: {DARK_SURFACE}; color: {DARK_INK}; border-color: {DARK_LINE}; }}
QMenu::item {{ color: {DARK_INK}; background: transparent; }}
QMenu::item:selected {{ color: #FFFFFF; background: {DARK_SELECTED}; }}
QMenu::item:disabled {{ color: #6F7E8B; }}
QMenu::separator {{ background: {DARK_LINE}; }}

QToolButton {{ color: {DARK_INK}; background: transparent; border: 1px solid transparent; border-radius: 3px; padding: 5px; }}
QToolButton:hover {{ color: #FFFFFF; background: {DARK_HOVER}; border-color: {DARK_LINE}; }}
QToolButton:pressed, QToolButton:checked {{ color: #FFFFFF; background: {DARK_SELECTED}; border-color: {DARK_INFO}; }}
QToolButton:disabled {{ color: #71808D; background: transparent; }}

QPushButton {{ color: {DARK_INK}; background: {DARK_SURFACE}; border-color: {DARK_LINE}; }}
QPushButton:hover {{ color: #FFFFFF; background: {DARK_HOVER}; border-color: {DARK_INFO}; }}
QPushButton:pressed {{ color: #FFFFFF; background: {DARK_SELECTED}; border-color: {DARK_INFO}; }}
QPushButton:focus {{ border-color: {DARK_INFO}; }}
QPushButton:disabled {{ color: #71808D; background: {DARK_SURFACE_ALT}; border-color: #2A3742; }}
QPushButton#Primary {{ color: #FFFFFF; background: #176A9C; border-color: #2D8DC5; }}
QPushButton#Primary:hover {{ color: #FFFFFF; background: #2080B9; border-color: {DARK_INFO}; }}
QPushButton#Primary:pressed {{ background: #12577F; }}
QPushButton#Primary:disabled {{ color: #CBD5DC; background: #405767; border-color: #4A6273; }}

QLineEdit, QComboBox, QSpinBox, QTextEdit, QPlainTextEdit {{
    color: {DARK_INK}; background: {DARK_SURFACE_ALT}; border-color: {DARK_LINE};
    selection-color: #FFFFFF; selection-background-color: #236C99;
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QTextEdit:hover, QPlainTextEdit:hover {{ border-color: #4B6070; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {DARK_INFO}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {{ color: #71808D; background: #121A21; }}
QLineEdit::placeholder {{ color: #82909C; }}
QComboBox QAbstractItemView {{
    color: {DARK_INK}; background: {DARK_SURFACE}; border: 1px solid {DARK_LINE};
    selection-color: #FFFFFF; selection-background-color: {DARK_SELECTED}; outline: none;
}}
QComboBox QAbstractItemView::item:hover {{ color: #FFFFFF; background: {DARK_HOVER}; }}

QCheckBox, QRadioButton {{ color: {DARK_INK}; background: transparent; }}
QCheckBox:hover, QRadioButton:hover {{ color: #FFFFFF; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: #71808D; }}

QTableView, QTreeWidget, QListWidget {{
    color: {DARK_INK}; background: {DARK_SURFACE}; alternate-background-color: #15202A;
    gridline-color: #2A3945; border-color: {DARK_LINE};
    selection-color: #FFFFFF; selection-background-color: {DARK_SELECTED};
}}
QTableView::item, QTreeWidget::item, QListWidget::item {{ color: {DARK_INK}; }}
QAbstractItemView::item:hover {{ color: #FFFFFF; background: {DARK_HOVER}; }}
QAbstractItemView::item:selected, QAbstractItemView::item:selected:!active {{ color: #FFFFFF; background: {DARK_SELECTED}; }}
QTableCornerButton::section, QHeaderView::section {{
    color: #C8D3DC; background: {DARK_SURFACE_ALT}; border-color: {DARK_LINE};
}}
QHeaderView::section:hover {{ color: #FFFFFF; background: {DARK_HOVER}; }}

QTabWidget::pane {{ background: {DARK_SURFACE}; border-color: {DARK_LINE}; }}
QTabBar::tab {{ color: {DARK_MUTED}; background: {DARK_SURFACE_ALT}; border-color: {DARK_LINE}; }}
QTabBar::tab:hover {{ color: #FFFFFF; background: {DARK_HOVER}; }}
QTabBar::tab:selected {{ color: #FFFFFF; background: {DARK_SURFACE}; border-bottom: 2px solid {DARK_INFO}; }}
QTabBar::tab:disabled {{ color: #657480; background: #111820; }}

QToolTip {{ color: {DARK_INK}; background: #243340; border: 1px solid #516575; padding: 4px; }}
QStatusBar {{ color: {DARK_MUTED}; background: {DARK_SURFACE_ALT}; border-top-color: {DARK_LINE}; }}
QStatusBar QLabel {{ color: {DARK_MUTED}; background: transparent; }}
QProgressBar {{ color: {DARK_INK}; background: {DARK_SURFACE_ALT}; border-color: {DARK_LINE}; }}
QProgressBar::chunk {{ background: #247DAD; }}
QSplitter::handle {{ background: {DARK_LINE}; }}
QScrollBar:vertical, QScrollBar:horizontal {{ background: {DARK_SURFACE_ALT}; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{ background: #536574; }}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{ background: #718493; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QGroupBox {{ color: {DARK_MUTED}; border-color: {DARK_LINE}; }}
QToolBar {{ color: {DARK_INK}; background: {DARK_SURFACE_ALT}; border-color: {DARK_LINE}; }}

QFrame#Card, QFrame#Metric {{ background: {DARK_SURFACE}; border-color: {DARK_LINE}; }}
QLabel#SectionTitle, QLabel#ValueLabel, QLabel#MetricValue, QLabel#AboutTitle, QLabel#AboutBody {{ color: {DARK_INK}; }}
QLabel#CardTitle, QLabel#KeyLabel, QLabel#MetricLabel, QLabel#MetricNote,
QLabel#SettingNote, QLabel#AboutVersion {{ color: {DARK_MUTED}; }}
QTextEdit#Description {{ color: {DARK_INK}; background: {DARK_SURFACE_ALT}; border-color: {DARK_LINE}; border-left-color: {DARK_INFO}; }}
QDialog#PreferencesDialog, QDialog#AboutDialog, QDialog#DecoderDialog {{ background: {DARK_SURFACE}; }}
QListWidget#PreferenceCategories, QFrame#DialogFooter {{ background: {DARK_SURFACE_ALT}; border-color: {DARK_LINE}; }}
QListWidget#PreferenceCategories::item {{ color: {DARK_MUTED}; }}
QListWidget#PreferenceCategories::item:hover {{ color: #FFFFFF; background: {DARK_HOVER}; }}
QListWidget#PreferenceCategories::item:selected {{ color: #FFFFFF; background: {DARK_SURFACE}; border-left-color: {DARK_INFO}; }}
QStackedWidget#PreferencePages {{ background: {DARK_SURFACE}; }}
QLabel#SecurityNote, QLabel#AboutMeta, QLabel#ReportHint, QLabel#DecoderIntro, QLabel#DecoderNote {{ color: {DARK_MUTED}; background: {DARK_SURFACE_ALT}; border-color: {DARK_LINE}; border-left-color: {DARK_INFO}; }}
QFrame#DecoderHeader {{ background: {DARK_SURFACE_ALT}; border-bottom-color: {DARK_LINE}; }}
QLabel#DecoderColumnLabel, QLabel#DecoderSubtitle, QLabel#DecoderPath {{ color: {DARK_MUTED}; }}
QFrame#DecoderRow {{ background: {DARK_SURFACE}; border-color: {DARK_LINE}; }}
QFrame#DecoderRow:hover {{ background: {DARK_HOVER}; border-color: {DARK_INFO}; }}
QLabel#DecoderTitle, QLabel#DecoderName {{ color: {DARK_INK}; }}
QLabel#DecoderOrder {{ color: {DARK_INFO}; background: {DARK_SURFACE_ALT}; }}
QDialogButtonBox {{ background: transparent; }}
QMessageBox QLabel {{ color: {DARK_INK}; background: transparent; }}
"""


def stylesheet(dark: bool = False) -> str:
    global _DARK_ACTIVE
    _DARK_ACTIVE = dark
    return DARK_STYLESHEET if dark else STYLESHEET


def is_dark() -> bool:
    return _DARK_ACTIVE


def text_colour() -> str:
    return DARK_INK if _DARK_ACTIVE else INK


def row_colour(kind: str) -> str:
    if kind == "pe":
        return DARK_PE_ROW if _DARK_ACTIVE else PE_ROW
    return DARK_WARN_ROW if _DARK_ACTIVE else WARN_ROW


def status_colour(value: str) -> str:
    if _DARK_ACTIVE:
        colours = {
            "COMPLETED": DARK_OK, "READY": DARK_OK, "SUCCESS": DARK_OK,
            "COMPLETED WITH WARNINGS": DARK_WARN, "WARNING": DARK_WARN,
            "NO PTF FOUND": DARK_WARN, "INCOMPLETE": DARK_ERR, "FAILED": DARK_ERR,
            "ERROR": DARK_ERR, "HOLDDATA ONLY": DARK_INFO, "METADATA ONLY": DARK_INFO,
            "DUPLICATE": DARK_INFO, "INFO": DARK_INFO, "DEBUG": DARK_MUTED,
            "ADDED": DARK_OK, "REMOVED": DARK_ERR, "CHANGED": DARK_WARN,
            "UNCHANGED": DARK_MUTED,
        }
        return colours.get(value, DARK_MUTED)
    return STATUS_COLOURS.get(value) or LEVEL_COLOURS.get(value) or MUTED


def qt_palette(dark: bool = False) -> QPalette:
    palette = QPalette()
    if not dark:
        return palette
    values = {
        QPalette.ColorRole.Window: DARK_SURFACE_ALT,
        QPalette.ColorRole.WindowText: DARK_INK,
        QPalette.ColorRole.Base: DARK_SURFACE,
        QPalette.ColorRole.AlternateBase: "#15202A",
        QPalette.ColorRole.ToolTipBase: "#243340",
        QPalette.ColorRole.ToolTipText: DARK_INK,
        QPalette.ColorRole.Text: DARK_INK,
        QPalette.ColorRole.Button: DARK_SURFACE,
        QPalette.ColorRole.ButtonText: DARK_INK,
        QPalette.ColorRole.BrightText: "#FFFFFF",
        QPalette.ColorRole.Highlight: DARK_SELECTED,
        QPalette.ColorRole.HighlightedText: "#FFFFFF",
        QPalette.ColorRole.PlaceholderText: "#82909C",
        QPalette.ColorRole.Mid: "#536574",
        QPalette.ColorRole.Light: "#687C8C",
        QPalette.ColorRole.Dark: "#0D141A",
        QPalette.ColorRole.Link: DARK_INFO,
        QPalette.ColorRole.LinkVisited: "#B19AE8",
    }
    for role, colour in values.items():
        palette.setColor(role, QColor(colour))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#71808D"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#71808D"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#71808D"))
    return palette


def apply(application, dark: bool = False) -> None:
    application.setPalette(qt_palette(True) if dark else application.style().standardPalette())
    application.setStyleSheet(stylesheet(dark))


class ProfessionalStyle(QProxyStyle):
    """Fusion style with a crisp, high-contrast checkbox indicator."""

    def drawPrimitive(self, element, option, painter, widget=None):  # noqa: N802 - Qt API
        if element != QStyle.PrimitiveElement.PE_IndicatorCheckBox:
            return super().drawPrimitive(element, option, painter, widget)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(option.rect).adjusted(1.0, 1.0, -1.0, -1.0)
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        checked = bool(option.state & QStyle.StateFlag.State_On)
        partial = bool(option.state & QStyle.StateFlag.State_NoChange)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        palette = option.palette
        if checked or partial:
            fill = QColor("#2D83BD" if enabled else "#60788A")
            border = fill.lighter(112) if hovered else fill
        else:
            fill = palette.base().color()
            border = palette.highlight().color() if hovered else palette.mid().color()
        painter.setPen(QPen(border, 1.2))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 3.0, 3.0)
        painter.setPen(QPen(QColor("#FFFFFF"), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        if checked:
            path = QPainterPath(QPointF(rect.left() + rect.width() * 0.23, rect.top() + rect.height() * 0.52))
            path.lineTo(QPointF(rect.left() + rect.width() * 0.43, rect.top() + rect.height() * 0.72))
            path.lineTo(QPointF(rect.left() + rect.width() * 0.79, rect.top() + rect.height() * 0.30))
            painter.drawPath(path)
        elif partial:
            painter.drawLine(QPointF(rect.left() + 4, rect.center().y()), QPointF(rect.right() - 4, rect.center().y()))
        painter.restore()


def rgba(colour: str, alpha: float) -> str:
    """``#RRGGBB`` + opacity as a Qt friendly ``rgba()`` string.

    Qt stylesheets read an 8 digit hex as ``#AARRGGBB``, not ``#RRGGBBAA``, so
    appending an alpha suffix silently produces the wrong colour.
    """
    value = colour.lstrip("#")
    red, green, blue = (int(value[index : index + 2], 16) for index in (0, 2, 4))
    return f"rgba({red}, {green}, {blue}, {alpha:.2f})"


def chip_style(colour: str) -> str:
    """Inline style for a small status chip label."""
    return (
        f"background: {rgba(colour, 0.10)}; color: {colour};"
        f"border: 1px solid {rgba(colour, 0.35)};"
        "border-radius: 3px; padding: 2px 8px; font-size: 8pt; font-weight: 600;"
    )


def banner_style(colour: str, background: str) -> str:
    """Inline style for an inline error/warning panel."""
    return (
        f"background: {background}; color: {colour};"
        f"border: 1px solid {rgba(colour, 0.35)};"
        "border-radius: 3px; padding: 7px;"
    )
