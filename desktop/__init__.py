"""Native desktop front end (PySide6) for the SMP/E PTF Package Analyzer.

The analysis engine in :mod:`ptfanalyzer` knows nothing about Qt; this package
provides the native desktop interface.
"""

from __future__ import annotations

__all__ = ["main"]


def main(argv=None) -> int:
    from .app import main as _main

    return _main(argv)
