"""Flat corporate Qt theme - solid colours only, no gradients."""

from __future__ import annotations

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
