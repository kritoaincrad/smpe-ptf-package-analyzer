#!/usr/bin/env python
"""Launcher for the native desktop application.

    python desktop_app.py                      # empty window
    python desktop_app.py example-package.*  # pre-load a part set
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from desktop.app import main

if __name__ == "__main__":
    raise SystemExit(main())
