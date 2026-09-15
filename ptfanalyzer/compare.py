"""Deterministic comparison of two stored analysis reports."""

from __future__ import annotations

from typing import Any

from .models import AnalysisReport, PTFEntry


def _snapshot(ptf: PTFEntry) -> dict[str, Any]:
    return {
        "Type": ptf.sysmod_type,
        "FMID": tuple(ptf.fmids),
        "Description": ptf.description,
        "PRE": tuple(ptf.pre),
        "REQ": tuple(ptf.req),
        "SUP": tuple(ptf.sup),
        "APARs": tuple(ptf.apars),
        "Elements": tuple((item.kind, item.name, item.distlib, item.relfile) for item in ptf.elements),
        "HOLD": tuple((item.hold_type, item.reason, item.comment) for item in ptf.holds),
        "PE": ptf.is_pe,
    }


def _index(report: AnalysisReport) -> dict[str, PTFEntry]:
    return {ptf.sysmod_id: ptf for ptf in report.ptfs if ptf.sysmod_id}


def compare_reports(before: AnalysisReport, after: AnalysisReport) -> list[dict[str, Any]]:
    """Return added, removed and materially changed PTF rows."""
    old, new = _index(before), _index(after)
    rows: list[dict[str, Any]] = []
    for sysmod_id in sorted(set(old) | set(new)):
        if sysmod_id not in old:
            status, changed = "ADDED", "New PTF"
            ptf = new[sysmod_id]
        elif sysmod_id not in new:
            status, changed = "REMOVED", "No longer present"
            ptf = old[sysmod_id]
        else:
            before_values, after_values = _snapshot(old[sysmod_id]), _snapshot(new[sysmod_id])
            fields = [key for key in before_values if before_values[key] != after_values[key]]
            status, changed = ("CHANGED", ", ".join(fields)) if fields else ("UNCHANGED", "")
            ptf = new[sysmod_id]
        rows.append(
            {
                "Status": status,
                "PTF": sysmod_id,
                "FMID": ", ".join(ptf.fmids),
                "PE": "YES" if ptf.is_pe else "",
                "Changed fields": changed,
                "Description": ptf.short_description,
            }
        )
    return rows


def comparison_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {name: sum(row["Status"] == name for row in rows) for name in ("ADDED", "REMOVED", "CHANGED", "UNCHANGED")}
