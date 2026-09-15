"""Corporate report shaping for Excel and printable HTML/PDF output."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd

from .compare import comparison_summary
from .export import hold_frame, package_summary_frame, ptf_frame
from .models import AnalysisReport
from .security import redact_sensitive


def executive_summary(report: AnalysisReport) -> dict[str, Any]:
    holds = [hold for package in report.packages for hold in package.all_holds]
    critical = [hold for hold in holds if hold.is_error_hold or hold.class_.upper() == "HIPER"]
    actions = [hold for hold in holds if hold.hold_type.upper() in {"SYSTEM", "USER", "FIXCAT"}]
    return {
        "Packages": len(report.analyzed_packages),
        "PTFs": len(report.ptfs),
        "Unique PTFs": len(report.unique_ptf_ids),
        "PE": sum(ptf.is_pe for ptf in report.ptfs),
        "Critical HOLD": len(critical),
        "Action required": len(actions),
        "Errors": sum(len(package.errors) for package in report.packages),
        "Duration (s)": round(report.duration_s, 2),
    }


def _masked_frame(frame: pd.DataFrame, mask_paths: bool) -> pd.DataFrame:
    if not mask_paths or frame.empty:
        return frame
    result = frame.copy()
    for column in result.columns:
        if result[column].dtype == object:
            result[column] = result[column].map(lambda value: redact_sensitive(value, True))
    return result


def write_excel_report(
    report: AnalysisReport,
    destination: Path,
    comparison: Optional[list[dict[str, Any]]] = None,
    mask_paths: bool = True,
) -> None:
    """Write a multi-sheet, filterable Excel workbook."""
    summary = pd.DataFrame([executive_summary(report)])
    holds = hold_frame(hold for package in report.packages for hold in package.all_holds)
    critical = holds[
        holds.get("Hold Type", pd.Series(dtype=str)).isin(["ERROR", "SYSTEM", "USER", "FIXCAT"])
    ] if not holds.empty else holds
    sheets = {
        "Executive Summary": summary,
        "PTFs": ptf_frame(report.ptfs),
        "Critical and Actions": critical,
        "HOLDDATA": holds,
        "Packages": package_summary_frame(report),
    }
    if comparison is not None:
        sheets["Changes"] = pd.DataFrame(comparison)
    with pd.ExcelWriter(destination, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame = _masked_frame(frame, mask_paths)
            frame.to_excel(writer, sheet_name=name[:31], index=False)
            sheet = writer.sheets[name[:31]]
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for cells in sheet.columns:
                width = min(max(len(str(cell.value or "")) for cell in cells) + 2, 60)
                sheet.column_dimensions[cells[0].column_letter].width = max(width, 10)


def printable_html(
    report: AnalysisReport,
    company: str = "",
    title: str = "SMP/E PTF Analysis Report",
    logo_path: str = "",
    comparison: Optional[list[dict[str, Any]]] = None,
    mask_paths: bool = True,
) -> str:
    """Build self-contained HTML suitable for preview, printing or PDF."""
    summary = executive_summary(report)
    logo = ""
    if logo_path and Path(logo_path).is_file():
        logo = f'<img class="logo" src="{Path(logo_path).resolve().as_uri()}">'
    metrics = "".join(
        f'<div class="metric"><b>{html.escape(str(value))}</b><span>{html.escape(key)}</span></div>'
        for key, value in summary.items()
    )
    pe_rows = [ptf for ptf in report.ptfs if ptf.is_pe]
    action_rows = [
        hold for package in report.packages for hold in package.all_holds
        if hold.is_error_hold or hold.hold_type.upper() in {"SYSTEM", "USER", "FIXCAT"}
    ]

    def table(headers: Iterable[str], rows: Iterable[Iterable[object]]) -> str:
        head = "".join(f"<th>{html.escape(str(item))}</th>" for item in headers)
        body = "".join(
            "<tr>" + "".join(f"<td>{html.escape(redact_sensitive(value, mask_paths))}</td>" for value in row) + "</tr>"
            for row in rows
        )
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    changes = ""
    if comparison is not None:
        counts = comparison_summary(comparison)
        changes = "<h2>Delivery changes</h2><p>" + ", ".join(f"{k}: {v}" for k, v in counts.items()) + "</p>"
        changes += table(("Status", "PTF", "FMID", "Changed fields"), ((r["Status"], r["PTF"], r["FMID"], r["Changed fields"]) for r in comparison if r["Status"] != "UNCHANGED"))
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
    @page {{ size: A4; margin: 14mm; }} body {{ font: 10pt 'Segoe UI', sans-serif; color:#1f2933; }}
    header {{ display:flex; align-items:center; border-bottom:3px solid #0b3d62; margin-bottom:18px; }}
    .logo {{ max-height:48px; max-width:150px; margin-right:16px; }} h1 {{ color:#0b3d62; margin:0; }}
    .metrics {{ display:flex; flex-wrap:wrap; gap:8px; }} .metric {{ border:1px solid #ccd6df; padding:8px 12px; min-width:90px; }}
    .metric b {{ display:block; font-size:16pt; color:#0b3d62; }} .metric span {{ color:#5b6b7a; }}
    h2 {{ color:#0b3d62; margin-top:20px; }} table {{ border-collapse:collapse; width:100%; font-size:8.5pt; }}
    th,td {{ border:1px solid #ccd6df; padding:5px; text-align:left; vertical-align:top; }} th {{ background:#e8f0f6; }}
    tr {{ page-break-inside:avoid; }} .critical {{ color:#b3261e; }}
    </style></head><body><header>{logo}<div><h1>{html.escape(title)}</h1><p>{html.escape(company)}</p></div></header>
    <h2>Executive summary</h2><div class="metrics">{metrics}</div>
    <h2 class="critical">PE / in-error PTFs</h2>{table(("PTF", "FMID", "Description"), ((p.sysmod_id, ', '.join(p.fmids), p.short_description) for p in pe_rows))}
    <h2>Critical HOLD and actions required</h2>{table(("PTF", "Type", "Reason", "Class", "Action"), ((h.ptf_id, h.hold_type, h.reason, h.class_, h.comment) for h in action_rows))}
    {changes}<h2>All PTFs</h2>{table(("PTF", "Type", "FMID", "PE", "Description"), ((p.sysmod_id, p.sysmod_type, ', '.join(p.fmids), 'YES' if p.is_pe else '', p.short_description) for p in report.ptfs))}
    </body></html>"""
