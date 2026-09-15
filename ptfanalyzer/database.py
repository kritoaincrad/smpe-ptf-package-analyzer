"""Local analysis history in SQLite.

Every analysis can be stored and reopened later, so a package only has to be
processed once.  SQLite is part of the standard library, the database is a
single file, and it is fully inspectable with any SQL tool.

Layout::

    analyses   one row per run, with the whole report as JSON
    ptf_index  one row per PTF, so PTFs can be searched across every analysis
    packages   one row per package, for the history list

Default location:

* Windows  ``%LOCALAPPDATA%\\PTFAnalyzer\\analyses.db``
* Linux    ``~/.local/share/ptfanalyzer/analyses.db``
* macOS    ``~/Library/Application Support/PTFAnalyzer/analyses.db``

Override with the ``PTFANALYZER_DB`` environment variable.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from .models import AnalysisReport
from .serialize import describe_sources, report_from_record, report_to_record

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analyses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT    NOT NULL,
    label         TEXT    NOT NULL DEFAULT '',
    sources       TEXT    NOT NULL DEFAULT '',
    app_version   TEXT    NOT NULL DEFAULT '',
    duration_s    REAL    NOT NULL DEFAULT 0,
    package_count INTEGER NOT NULL DEFAULT 0,
    ptf_count     INTEGER NOT NULL DEFAULT 0,
    hold_count    INTEGER NOT NULL DEFAULT 0,
    error_count   INTEGER NOT NULL DEFAULT 0,
    report_json   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS packages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id INTEGER NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT '',
    parts       INTEGER NOT NULL DEFAULT 0,
    total_size  INTEGER NOT NULL DEFAULT 0,
    decoder     TEXT    NOT NULL DEFAULT '',
    fingerprint TEXT    NOT NULL DEFAULT '',
    ptf_count   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ptf_index (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id  INTEGER NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    package      TEXT    NOT NULL DEFAULT '',
    sysmod_id    TEXT    NOT NULL DEFAULT '',
    sysmod_type  TEXT    NOT NULL DEFAULT '',
    fmid         TEXT    NOT NULL DEFAULT '',
    description  TEXT    NOT NULL DEFAULT '',
    apars        TEXT    NOT NULL DEFAULT '',
    hold_reasons TEXT    NOT NULL DEFAULT '',
    is_pe        INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ptf_sysmod   ON ptf_index(sysmod_id);
CREATE INDEX IF NOT EXISTS idx_ptf_analysis ON ptf_index(analysis_id);
CREATE INDEX IF NOT EXISTS idx_pkg_analysis ON packages(analysis_id);
CREATE INDEX IF NOT EXISTS idx_analyses_at  ON analyses(created_at DESC);
"""


# ---------------------------------------------------------------------------
# location
# ---------------------------------------------------------------------------


def default_database_path() -> Path:
    """Where the history lives unless the caller says otherwise."""
    override = os.environ.get("PTFANALYZER_DB")
    if override:
        return Path(override).expanduser()

    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "PTFAnalyzer" / "analyses.db"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "PTFAnalyzer" / "analyses.db"
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "ptfanalyzer" / "analyses.db"


@dataclass
class AnalysisSummary:
    """One row of the history list."""

    id: int
    created_at: str
    label: str
    sources: str
    duration_s: float
    package_count: int
    ptf_count: int
    hold_count: int
    error_count: int
    app_version: str = ""
    size_bytes: int = 0

    @property
    def created_local(self) -> str:
        try:
            moment = datetime.fromisoformat(self.created_at)
        except ValueError:
            return self.created_at
        if moment.tzinfo is not None:
            moment = moment.astimezone()
        return moment.strftime("%Y-%m-%d %H:%M")

    def as_row(self) -> dict:
        return {
            "ID": self.id,
            "Date": self.created_local,
            "Label": self.label,
            "Packages": self.package_count,
            "PTFs": self.ptf_count,
            "HOLDs": self.hold_count,
            "Errors": self.error_count,
            "Duration (s)": round(self.duration_s, 2),
            "Sources": self.sources,
        }


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------


class AnalysisStore:
    """The local history database.

    A connection is opened per operation, which keeps the store usable from a
    worker thread and a GUI thread without any locking ceremony.
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else default_database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    # -- connection ------------------------------------------------------
    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path), timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    # -- writing ---------------------------------------------------------
    def save_report(
        self,
        report: AnalysisReport,
        label: str = "",
        app_version: str = "",
        sources: str = "",
    ) -> int:
        """Store *report* and return its history id."""
        record = report_to_record(report, app_version=app_version)
        totals = record["totals"]
        created = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO analyses
                    (created_at, label, sources, app_version, duration_s,
                     package_count, ptf_count, hold_count, error_count, report_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created,
                    label or describe_sources(report),
                    sources or ", ".join(group.display_name for group in report.groups),
                    app_version,
                    float(report.duration_s),
                    int(totals["packages"]),
                    int(totals["ptfs"]),
                    int(totals["holds"]),
                    int(totals["errors"]),
                    json.dumps(record, ensure_ascii=False, default=str),
                ),
            )
            analysis_id = int(cursor.lastrowid)

            for package in report.packages:
                connection.execute(
                    """
                    INSERT INTO packages
                        (analysis_id, name, status, parts, total_size, decoder, fingerprint, ptf_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        analysis_id,
                        package.group.display_name,
                        package.status,
                        len(package.group.parts),
                        package.group.total_size,
                        package.decompression.method if package.decompression else "",
                        package.group.fingerprint,
                        len(package.ptfs),
                    ),
                )
                for ptf in package.ptfs:
                    connection.execute(
                        """
                        INSERT INTO ptf_index
                            (analysis_id, package, sysmod_id, sysmod_type, fmid,
                             description, apars, hold_reasons, is_pe)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            analysis_id,
                            package.group.display_name,
                            ptf.sysmod_id,
                            ptf.sysmod_type,
                            ", ".join(ptf.fmids),
                            ptf.short_description,
                            ", ".join(ptf.apars),
                            ", ".join(ptf.hold_reasons),
                            1 if ptf.is_pe else 0,
                        ),
                    )
        return analysis_id

    def rename(self, analysis_id: int, label: str) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE analyses SET label = ? WHERE id = ?", (label, analysis_id))

    def delete(self, analysis_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM ptf_index WHERE analysis_id = ?", (analysis_id,))
            connection.execute("DELETE FROM packages WHERE analysis_id = ?", (analysis_id,))
            connection.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,))

    def clear(self) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM ptf_index")
            connection.execute("DELETE FROM packages")
            connection.execute("DELETE FROM analyses")

    # -- reading ---------------------------------------------------------
    def list_analyses(self, limit: int = 200, search: str = "") -> list[AnalysisSummary]:
        query = (
            "SELECT id, created_at, label, sources, app_version, duration_s, "
            "package_count, ptf_count, hold_count, error_count, LENGTH(report_json) AS size "
            "FROM analyses "
        )
        parameters: list[Any] = []
        if search:
            query += "WHERE label LIKE ? OR sources LIKE ? "
            needle = f"%{search}%"
            parameters += [needle, needle]
        query += "ORDER BY id DESC LIMIT ?"
        parameters.append(int(limit))

        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [
            AnalysisSummary(
                id=row["id"],
                created_at=row["created_at"],
                label=row["label"],
                sources=row["sources"],
                duration_s=row["duration_s"],
                package_count=row["package_count"],
                ptf_count=row["ptf_count"],
                hold_count=row["hold_count"],
                error_count=row["error_count"],
                app_version=row["app_version"],
                size_bytes=row["size"] or 0,
            )
            for row in rows
        ]

    def load_report(self, analysis_id: int) -> AnalysisReport:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT report_json FROM analyses WHERE id = ?", (analysis_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"No stored analysis with id {analysis_id}.")
        return report_from_record(json.loads(row["report_json"]))

    def search_ptfs(self, text: str, limit: int = 500) -> list[dict]:
        """Find a PTF across every stored analysis."""
        needle = f"%{text.strip()}%"
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT p.analysis_id, a.created_at, a.label, p.package, p.sysmod_id,
                       p.sysmod_type, p.fmid, p.description, p.apars, p.hold_reasons, p.is_pe
                FROM ptf_index p
                JOIN analyses a ON a.id = p.analysis_id
                WHERE p.sysmod_id LIKE ? OR p.description LIKE ? OR p.apars LIKE ?
                   OR p.fmid LIKE ? OR p.package LIKE ? OR p.hold_reasons LIKE ?
                ORDER BY p.analysis_id DESC, p.sysmod_id
                LIMIT ?
                """,
                (needle, needle, needle, needle, needle, needle, int(limit)),
            ).fetchall()

        results = []
        for row in rows:
            created = row["created_at"]
            try:
                created = datetime.fromisoformat(created).astimezone().strftime("%Y-%m-%d %H:%M")
            except ValueError:
                pass
            results.append(
                {
                    "Analysis": row["analysis_id"],
                    "Date": created,
                    "PTF": row["sysmod_id"],
                    "Type": row["sysmod_type"],
                    "FMID": row["fmid"],
                    "Description": row["description"],
                    "APARs": row["apars"],
                    "HOLD": row["hold_reasons"],
                    "PE": "YES" if row["is_pe"] else "",
                    "Package": row["package"],
                }
            )
        return results

    def stats(self) -> dict:
        with self.connect() as connection:
            analyses = connection.execute("SELECT COUNT(*) AS n FROM analyses").fetchone()["n"]
            ptfs = connection.execute("SELECT COUNT(*) AS n FROM ptf_index").fetchone()["n"]
            unique = connection.execute(
                "SELECT COUNT(DISTINCT sysmod_id) AS n FROM ptf_index"
            ).fetchone()["n"]
        size = self.path.stat().st_size if self.path.exists() else 0
        return {
            "path": str(self.path),
            "analyses": analyses,
            "ptf_rows": ptfs,
            "unique_ptfs": unique,
            "size_bytes": size,
        }

    def vacuum(self) -> None:
        with self.connect() as connection:
            connection.execute("VACUUM")


_default_store: Optional[AnalysisStore] = None


def get_store(path: Optional[Path] = None) -> AnalysisStore:
    """Process wide store for the default location (created on first use)."""
    global _default_store
    if path is not None:
        return AnalysisStore(path)
    if _default_store is None:
        _default_store = AnalysisStore()
    return _default_store
