"""Report shaping: pandas frames for the UI, JSON/CSV for downloads."""

from __future__ import annotations

import json
from typing import Any, Iterable

import pandas as pd

from .models import AnalysisReport, PackageAnalysis, PTFEntry


def ptf_frame(ptfs: Iterable[PTFEntry]) -> pd.DataFrame:
    rows = [ptf.as_row() for ptf in ptfs]
    if not rows:
        return pd.DataFrame(
            columns=[
                "PTF", "Type", "FMID", "Description", "PRE", "REQ", "SUP",
                "APARs", "Elements", "HOLD", "PE", "JCLIN", "Source",
            ]
        )
    return pd.DataFrame(rows)


def hold_frame(holds: Iterable[Any]) -> pd.DataFrame:
    rows = [hold.as_dict() for hold in holds]
    if not rows:
        return pd.DataFrame(
            columns=["PTF", "Hold Type", "Reason", "FMID", "Date", "Class", "Resolver", "Comment", "Source"]
        )
    return pd.DataFrame(rows)


def member_frame(package: PackageAnalysis) -> pd.DataFrame:
    rows = [
        {
            "Member": member.name,
            "Role": member.role or "-",
            "Size (bytes)": member.size,
            "Type": "file" if member.is_file else "directory",
            "Container": member.container or "-",
        }
        for member in package.members
    ]
    if not rows:
        return pd.DataFrame(columns=["Member", "Role", "Size (bytes)", "Type", "Container"])
    return pd.DataFrame(rows)


def part_frame(report: AnalysisReport) -> pd.DataFrame:
    rows = []
    for group in report.groups:
        for part in group.parts:
            rows.append(
                {
                    "Package": group.display_name,
                    "File": part.display_name,
                    "Part": part.part_label,
                    "Size (MB)": round(part.size / (1024 * 1024), 2),
                    "SHA-256": part.sha256,
                    "Status": group.status,
                }
            )
        for duplicate, original in group.duplicate_parts:
            rows.append(
                {
                    "Package": group.display_name,
                    "File": duplicate.display_name,
                    "Part": f"{duplicate.part_label} (duplicate of {original.display_name})",
                    "Size (MB)": round(duplicate.size / (1024 * 1024), 2),
                    "SHA-256": duplicate.sha256,
                    "Status": "DUPLICATE FILE",
                }
            )
    if not rows:
        return pd.DataFrame(columns=["Package", "File", "Part", "Size (MB)", "SHA-256", "Status"])
    return pd.DataFrame(rows)


def package_summary_frame(report: AnalysisReport) -> pd.DataFrame:
    rows = []
    for package in report.packages:
        group = package.group
        rows.append(
            {
                "Package": group.display_name,
                "Status": package.status,
                "Parts": len(group.parts),
                "Size (MB)": round(group.total_size / (1024 * 1024), 2),
                "Decoder": package.decompression.method if package.decompression else "-",
                "Members": len(package.members),
                "PTFs": len(package.ptfs),
                "HOLDs": len(package.all_holds),
                "Duration (s)": round(package.duration_s, 2),
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=["Package", "Status", "Parts", "Size (MB)", "Decoder", "Members", "PTFs", "HOLDs", "Duration (s)"]
        )
    return pd.DataFrame(rows)


def ptf_detail_dict(ptf: PTFEntry) -> dict[str, Any]:
    """One PTF as a plain dictionary (JSON export, history storage)."""
    return ptf.as_record()


def raw_statements_for(report: AnalysisReport, ptf: PTFEntry, limit: int = 60) -> list[str]:
    """The raw MCS text of the statements that make up one SYSMOD.

    Empty for an analysis reloaded from the history: raw statements are not
    stored, only the information extracted from them.
    """
    from .smpe import SYSMOD_KINDS

    blocks: list[str] = []
    for package in report.packages:
        for analysis in package.smpptfin:
            if analysis.member != ptf.source:
                continue
            collecting = False
            for statement in analysis.statements:
                if statement.kind in SYSMOD_KINDS:
                    if collecting:
                        return blocks[:limit]
                    collecting = statement.record_start == ptf.record_start
                if collecting:
                    blocks.append(f"[record {statement.record_start}] {statement.raw.strip()}")
    return blocks[:limit]


def report_to_dict(report: AnalysisReport) -> dict[str, Any]:
    """Full, round-trippable dictionary (also what the history stores)."""
    from . import __version__
    from .serialize import report_to_record

    return report_to_record(report, app_version=__version__)


def report_to_json(report: AnalysisReport, indent: int = 2) -> str:
    return json.dumps(report_to_dict(report), indent=indent, ensure_ascii=False, default=str)


def frame_to_csv(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8-sig")
