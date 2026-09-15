"""Turning an :class:`AnalysisReport` into JSON and back.

This is what makes the local history database work: an analysis is stored as
one JSON document and reopened later with the same objects the UI uses for a
fresh run.

Not stored, because they are large and only used while analyzing:

* the raw MCS statement objects (the *Raw MCS* view is empty on a reloaded
  analysis),
* the extracted member payloads and the temporary workspace files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .models import (
    AnalysisReport,
    ArchiveMember,
    DecompressionResult,
    EncodingGuess,
    HoldEntry,
    PackageAnalysis,
    PackageGroup,
    PartRef,
    PTFEntry,
    SMPPTFINAnalysis,
    StreamFormat,
)

SCHEMA_VERSION = 1

#: Guards against a pathological package filling the database.
MAX_STORED_MEMBERS = 20000
MAX_STORED_LOG_ENTRIES = 5000


# ---------------------------------------------------------------------------
# to record
# ---------------------------------------------------------------------------


def part_to_record(part: PartRef) -> dict:
    return {
        "display_name": part.display_name,
        "path": str(part.path),
        "size": part.size,
        "sha256": part.sha256,
        "index": part.index,
        "total": part.total,
        "base_name": part.base_name,
        "copy_marker": part.copy_marker,
    }


def part_from_record(data: dict) -> PartRef:
    return PartRef(
        display_name=data.get("display_name", ""),
        path=Path(data.get("path", "")),
        size=int(data.get("size") or 0),
        sha256=data.get("sha256", ""),
        index=data.get("index"),
        total=data.get("total"),
        base_name=data.get("base_name", ""),
        copy_marker=data.get("copy_marker"),
    )


def group_to_record(group: PackageGroup) -> dict:
    return {
        "key": group.key,
        "display_name": group.display_name,
        "parts": [part_to_record(part) for part in group.parts],
        "declared_total": group.declared_total,
        "missing_parts": list(group.missing_parts),
        "duplicate_files": [
            {"duplicate": duplicate.display_name, "original": original.display_name}
            for duplicate, original in group.duplicate_parts
        ],
        "errors": list(group.errors),
        "warnings": list(group.warnings),
        "fingerprint": group.fingerprint,
        "duplicate_of": group.duplicate_of,
    }


def group_from_record(data: dict) -> PackageGroup:
    return PackageGroup(
        key=data.get("key", ""),
        display_name=data.get("display_name", ""),
        parts=[part_from_record(part) for part in (data.get("parts") or [])],
        declared_total=data.get("declared_total"),
        missing_parts=list(data.get("missing_parts") or []),
        errors=list(data.get("errors") or []),
        warnings=list(data.get("warnings") or []),
        fingerprint=data.get("fingerprint", ""),
        duplicate_of=data.get("duplicate_of"),
    )


def member_to_record(member: ArchiveMember) -> dict:
    return {
        "name": member.name,
        "size": member.size,
        "is_file": member.is_file,
        "role": member.role,
        "container": member.container,
    }


def member_from_record(data: dict) -> ArchiveMember:
    return ArchiveMember(
        name=data.get("name", ""),
        size=int(data.get("size") or 0),
        is_file=bool(data.get("is_file", True)),
        role=data.get("role", ""),
        container=data.get("container", ""),
    )


def encoding_to_record(guess: EncodingGuess) -> dict:
    return {
        "encoding": guess.encoding,
        "score": guess.score,
        "token_hits": guess.token_hits,
        "printable_ratio": guess.printable_ratio,
        "replacement_chars": guess.replacement_chars,
        "sample": guess.sample,
    }


def encoding_from_record(data: dict) -> EncodingGuess:
    return EncodingGuess(
        encoding=data.get("encoding", "cp037"),
        score=float(data.get("score") or 0.0),
        token_hits=int(data.get("token_hits") or 0),
        printable_ratio=float(data.get("printable_ratio") or 0.0),
        replacement_chars=int(data.get("replacement_chars") or 0),
        sample=data.get("sample", ""),
    )


def member_analysis_to_record(analysis: SMPPTFINAnalysis) -> dict:
    return {
        "member": analysis.member,
        "encoding": encoding_to_record(analysis.encoding),
        "encoding_candidates": [encoding_to_record(g) for g in analysis.encoding_candidates],
        "layout": analysis.layout,
        "record_count": analysis.record_count,
        "statement_count": len(analysis.statements),
        "prologue": list(analysis.prologue),
        "warnings": list(analysis.warnings),
        "ptfs": [ptf.as_record() for ptf in analysis.ptfs],
        "holds": [hold.as_record() for hold in analysis.holds],
    }


def member_analysis_from_record(data: dict) -> SMPPTFINAnalysis:
    return SMPPTFINAnalysis(
        member=data.get("member", ""),
        encoding=encoding_from_record(data.get("encoding") or {}),
        encoding_candidates=[encoding_from_record(g) for g in (data.get("encoding_candidates") or [])],
        layout=data.get("layout", ""),
        record_count=int(data.get("record_count") or 0),
        statements=[],  # raw statements are not stored
        prologue=list(data.get("prologue") or []),
        ptfs=[PTFEntry.from_record(ptf) for ptf in (data.get("ptfs") or [])],
        holds=[HoldEntry.from_record(hold) for hold in (data.get("holds") or [])],
        warnings=list(data.get("warnings") or []),
    )


def package_to_record(package: PackageAnalysis) -> dict:
    decompression = package.decompression
    return {
        "group": group_to_record(package.group),
        "status": package.status,
        "stream_format": (
            {
                "kind": package.stream_format.kind,
                "label": package.stream_format.label,
                "magic_hex": package.stream_format.magic_hex,
                "needs_decompression": package.stream_format.needs_decompression,
            }
            if package.stream_format
            else None
        ),
        "decompression": (
            {
                "method": decompression.method,
                "output_path": str(decompression.output_path),
                "input_size": decompression.input_size,
                "output_size": decompression.output_size,
                "truncated": decompression.truncated,
                "attempts": decompression.attempts,
                "duration_s": decompression.duration_s,
            }
            if decompression
            else None
        ),
        "members": [member_to_record(member) for member in package.members[:MAX_STORED_MEMBERS]],
        "members_truncated": len(package.members) > MAX_STORED_MEMBERS,
        "member_count": len(package.members),
        "smpptfin": [member_analysis_to_record(analysis) for analysis in package.smpptfin],
        "holddata": [hold.as_record() for hold in package.holddata],
        "gimfaf": package.gimfaf,
        "gimfaf_members": list(package.gimfaf_members),
        "errors": package.errors,
        "warnings": list(package.warnings),
        "duration_s": package.duration_s,
    }


def package_from_record(data: dict) -> PackageAnalysis:
    stream = data.get("stream_format")
    decompression = data.get("decompression")
    return PackageAnalysis(
        group=group_from_record(data.get("group") or {}),
        stream_format=(
            StreamFormat(
                kind=stream.get("kind", ""),
                label=stream.get("label", ""),
                magic_hex=stream.get("magic_hex", ""),
                needs_decompression=bool(stream.get("needs_decompression")),
            )
            if stream
            else None
        ),
        decompression=(
            DecompressionResult(
                method=decompression.get("method", ""),
                output_path=Path(decompression.get("output_path", "")),
                input_size=int(decompression.get("input_size") or 0),
                output_size=int(decompression.get("output_size") or 0),
                truncated=bool(decompression.get("truncated")),
                attempts=list(decompression.get("attempts") or []),
                duration_s=float(decompression.get("duration_s") or 0.0),
            )
            if decompression
            else None
        ),
        members=[member_from_record(member) for member in (data.get("members") or [])],
        smpptfin=[member_analysis_from_record(item) for item in (data.get("smpptfin") or [])],
        holddata=[HoldEntry.from_record(hold) for hold in (data.get("holddata") or [])],
        gimfaf=list(data.get("gimfaf") or []),
        gimfaf_members=list(data.get("gimfaf_members") or []),
        errors=list(data.get("errors") or []),
        warnings=list(data.get("warnings") or []),
        duration_s=float(data.get("duration_s") or 0.0),
    )


def report_to_record(report: AnalysisReport, app_version: str = "") -> dict[str, Any]:
    """Full fidelity dictionary for storage and for the JSON export."""
    packages = [package_to_record(package) for package in report.packages]
    return {
        "schema": SCHEMA_VERSION,
        "app_version": app_version,
        "generated_at": report.started_at,
        "duration_seconds": round(report.duration_s, 3),
        "packages": packages,
        "log": report.log_entries[:MAX_STORED_LOG_ENTRIES],
        "log_truncated": len(report.log_entries) > MAX_STORED_LOG_ENTRIES,
        "totals": {
            "packages": len(report.analyzed_packages),
            "ptfs": len(report.ptfs),
            "unique_ptfs": len(report.unique_ptf_ids),
            "holds": sum(len(package.all_holds) for package in report.packages),
            "errors": sum(len(package.errors) for package in report.packages),
        },
    }


def report_from_record(data: dict) -> AnalysisReport:
    """Rebuild a report previously produced by :func:`report_to_record`."""
    schema = int(data.get("schema") or 0)
    if schema > SCHEMA_VERSION:
        raise ValueError(
            f"This analysis was stored by a newer version of the application "
            f"(schema {schema}, this build understands {SCHEMA_VERSION})."
        )
    packages = [package_from_record(item) for item in (data.get("packages") or [])]
    return AnalysisReport(
        packages=packages,
        groups=[package.group for package in packages],
        started_at=float(data.get("generated_at") or 0.0),
        duration_s=float(data.get("duration_seconds") or 0.0),
        log_entries=list(data.get("log") or []),
    )


def describe_sources(report: AnalysisReport) -> str:
    """Short text naming what was analyzed (used as the history label)."""
    names = [group.display_name for group in report.groups]
    if not names:
        return "(no package)"
    if len(names) == 1:
        return names[0]
    return f"{names[0]} (+{len(names) - 1} more)"
