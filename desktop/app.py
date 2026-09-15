"""Application entry point for the Qt desktop front end."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import QApplication

from . import theme
from .main_window import MainWindow
from .settings import Settings


def build_application(argv=None) -> QApplication:
    """Create (or reuse) the QApplication with the corporate look applied."""
    existing = QApplication.instance()
    application = existing or QApplication(list(argv or sys.argv))
    application.setApplicationName("SMP/E PTF Package Analyzer")
    application.setOrganizationName("SMP/E Tools")
    application.setStyle(theme.ProfessionalStyle("Fusion"))
    theme.apply(application, Settings.load().dark_theme)
    application.setFont(QFont("Segoe UI", 9))
    application.setWindowIcon(_icon())
    return application


def _icon() -> QIcon:
    """A simple solid-colour app icon drawn at runtime (no binary assets)."""
    from PySide6.QtGui import QColor, QPainter

    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(theme.BRAND))
    painter = QPainter(pixmap)
    painter.setPen(QColor("#FFFFFF"))
    font = painter.font()
    font.setPointSize(26)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "Z")
    painter.end()
    return QIcon(pixmap)


def main(argv=None) -> int:
    application = build_application(argv)
    window = MainWindow()

    # Files passed on the command line are added straight away.
    arguments = list(argv if argv is not None else sys.argv)[1:]
    paths = [Path(argument) for argument in arguments if Path(argument).exists()]
    if paths:
        window.add_paths(paths)

    window.show()
    return application.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
