"""End to end orchestration: uploaded files in, analyzed PTFs out.

    uploads -> parts -> package groups -> join -> decompress -> PAX/TAR
            -> SMPPTFIN / HOLDDATA / GIMFAF -> PTF objects

Every stage reports into an :class:`~ptfanalyzer.logging_util.AnalysisLog` and
failures are contained per package: one broken package never stops the others.
"""

from __future__ import annotations

import gzip
import shutil
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Iterable, Optional, Sequence

from . import archive as archive_mod
from .compression import DecompressOptions, decompress_stream, detect_format, read_head
from .errors import AnalyzerError, ArchiveError, FormatError
from .gimfaf import parse_gimfaf
from .holddata import parse_holddata
from .logging_util import AnalysisLog
from .models import AnalysisReport, PackageAnalysis, PackageGroup, PartRef
from .parts import build_part_ref, concatenate, group_parts
from .progress import NULL_PROGRESS, Progress
from .smpe import analyze_member

CHUNK = 1024 * 1024


@dataclass
class AnalyzerOptions:
    """Everything the UI can tune."""

    allow_partial_decompression: bool = True
    prefer_external_for_large: bool = True
    external_threshold_mb: int = 96
    forced_decoder: Optional[str] = None
    encoding_override: Optional[str] = None
    honor_sequence_columns: bool = True
    max_nested_depth: int = 2
    analyze_duplicates: bool = False
    debug: bool = False

    def decompress_options(self) -> DecompressOptions:
        return DecompressOptions(
            allow_partial=self.allow_partial_decompression,
            prefer_external_for_large=self.prefer_external_for_large,
            external_threshold_mb=self.external_threshold_mb,
            only=self.forced_decoder,
        )


# ---------------------------------------------------------------------------
# workspace
# ---------------------------------------------------------------------------


class Workspace:
    """A temporary directory holding uploads and intermediate files."""

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else Path(tempfile.mkdtemp(prefix="ptfanalyzer_"))
        self.uploads = self.root / "uploads"
        self.work = self.root / "work"
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.work.mkdir(parents=True, exist_ok=True)

    def store(self, name: str, source: BinaryIO | bytes) -> Path:
        """Spool an upload to disk (never keep whole packages in memory)."""
        safe = "".join(c if c.isalnum() or c in "._-()" else "_" for c in name) or "upload"
        target = self.uploads / safe
        counter = 1
        while target.exists():
            target = self.uploads / f"{counter}__{safe}"
            counter += 1
        with open(target, "wb") as out:
            if isinstance(source, (bytes, bytearray)):
                out.write(source)
            else:
                shutil.copyfileobj(source, out, CHUNK)
        return target

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def stage_uploads(
    uploads: Iterable[tuple[str, BinaryIO | bytes]],
    workspace: Workspace,
    log: Optional[AnalysisLog] = None,
    progress: Optional[Progress] = None,
) -> list[PartRef]:
    """Write uploads to the workspace and hash them."""
    log = AnalysisLog("upload") if log is None else log
    progress = progress or NULL_PROGRESS
    uploads = list(uploads)
    progress.begin_stage("read", "Reading the selected files", float(len(uploads)))
    parts: list[PartRef] = []
    for position, (name, source) in enumerate(uploads):
        progress.update(position, message=f"Reading '{name}'")
        path = workspace.store(name, source)
        part = build_part_ref(name, path)
        parts.append(part)
        log.info(
            f"Received '{name}' ({part.size / (1024 * 1024):.1f} MB, part {part.part_label}, "
            f"SHA-256 {part.sha256[:16]}...)"
        )
    return parts


# ---------------------------------------------------------------------------
# per package analysis
# ---------------------------------------------------------------------------


def _decompress_gzip(source: Path, destination: Path, log: AnalysisLog) -> int:
    log.info("Stream is gzip compressed; using the python gzip decoder.")
    written = 0
    with gzip.open(source, "rb") as reader, open(destination, "wb") as out:
        for block in iter(lambda: reader.read(CHUNK), b""):
            out.write(block)
            written += len(block)
    return written


def analyze_package(
    group: PackageGroup,
    workspace: Workspace,
    options: AnalyzerOptions,
    log: Optional[AnalysisLog] = None,
    progress: Optional[Progress] = None,
) -> PackageAnalysis:
    """Run the whole chain for one package group."""
    log = (AnalysisLog() if log is None else log).child(group.display_name)
    progress = progress or NULL_PROGRESS
    analysis = PackageAnalysis(group=group)
    started = time.time()

    try:
        analysis.warnings.extend(group.warnings)

        # -- join ---------------------------------------------------------
        joined = workspace.work / f"{_safe(group.display_name)}.joined.Z"
        concatenate(group, joined, log, progress)

        # -- identify and decompress --------------------------------------
        progress.begin_stage("identify", "Identifying stream format")
        stream_format = detect_format(read_head(joined))
        analysis.stream_format = stream_format
        log.info(f"Stream format: {stream_format.label} (magic {stream_format.magic_hex})")

        payload = joined
        if stream_format.kind == "unix_compress":
            expanded = workspace.work / f"{_safe(group.display_name)}.pax"
            analysis.decompression = decompress_stream(
                joined, expanded, options.decompress_options(), log, progress
            )
            if analysis.decompression.truncated:
                analysis.warnings.append(
                    "The .Z stream ended in the middle of a code; the package looks truncated "
                    "and only part of it could be read."
                )
            payload = expanded
        elif stream_format.kind == "gzip":
            expanded = workspace.work / f"{_safe(group.display_name)}.pax"
            progress.begin_stage("decompress", "Decompressing gzip stream")
            _decompress_gzip(joined, expanded, log)
            payload = expanded
        elif stream_format.kind == "xml":
            # GIMPAF.XML / GIMPAF.XSL ship next to the package, not inside it.
            progress.begin_stage("parse", "Reading XML metadata")
            analysis.gimfaf_members.append(group.display_name)
            analysis.gimfaf.extend(
                parse_gimfaf(joined.read_bytes(), group.display_name, log=log)
            )
            log.info(
                f"'{group.display_name}' is a stand-alone {stream_format.label}, "
                "not a service package; it was read as package metadata."
            )
            analysis.duration_s = time.time() - started
            return analysis
        elif stream_format.kind == "tar":
            log.info("Stream is already an uncompressed archive; skipping decompression.")
        else:
            raise FormatError(
                "Invalid Unix .Z stream.\n"
                "Expected magic bytes: 1F 9D\n"
                f"Detected: {' '.join(stream_format.magic_hex.split()[:2])}",
                detail=f"Detected format: {stream_format.label}",
                hint=(
                    "Check that every '.XofY' part was uploaded, that they were joined in numeric "
                    "order, and that the transfer was done in BINARY mode."
                ),
            )

        # -- archive ------------------------------------------------------
        if archive_mod.is_tar(payload):
            contents = archive_mod.read_archive(
                payload, log=log, max_depth=options.max_nested_depth, progress=progress
            )
        else:
            progress.begin_stage("archive", "Reading stream")
            contents = archive_mod.wrap_raw_stream(payload, log=log)
        analysis.members = contents.members
        analysis.warnings.extend(contents.warnings)

        # -- SMP/E metadata ------------------------------------------------
        _analyze_metadata(analysis, contents, options, log, progress)

    except AnalyzerError as exc:
        analysis.errors.append(
            {**exc.as_dict(), "traceback": traceback.format_exc() if options.debug else None}
        )
        log.error(exc.message, detail=exc.detail, exc=exc)
    except Exception as exc:  # noqa: BLE001 - never let one package kill the run
        analysis.errors.append(
            {
                "code": "UNEXPECTED",
                "message": f"Unexpected problem while analyzing '{group.display_name}'.",
                "detail": f"{type(exc).__name__}: {exc}",
                "hint": "Enable Debug Mode to see the full traceback.",
                "traceback": traceback.format_exc(),
            }
        )
        log.error(f"Unexpected problem: {type(exc).__name__}: {exc}", exc=exc)

    analysis.duration_s = time.time() - started
    log.info(f"Package finished in {analysis.duration_s:.2f}s - status {analysis.status}")
    return analysis


def _analyze_metadata(
    analysis: PackageAnalysis,
    contents: archive_mod.ArchiveContents,
    options: AnalyzerOptions,
    log: AnalysisLog,
    progress: Progress = NULL_PROGRESS,
) -> None:
    progress.begin_stage("parse", "Parsing SMP/E metadata")
    smp_members = contents.by_role("SMPPTFIN") + contents.by_role("SMPMCS")
    if not smp_members:
        analysis.warnings.append(
            "No SMPPTFIN or SMPMCS member was found in this package; no PTF metadata to read."
        )
        log.warning("No SMPPTFIN/SMPMCS member found in the archive.")

    for extracted in smp_members:
        try:
            member_analysis = analyze_member(
                extracted.data,
                extracted.name,
                log=log,
                encoding_override=options.encoding_override,
                honor_sequence_columns=options.honor_sequence_columns,
                progress=progress,
            )
            analysis.smpptfin.append(member_analysis)
            analysis.warnings.extend(member_analysis.warnings)
        except AnalyzerError as exc:
            analysis.errors.append(
                {**exc.as_dict(), "traceback": traceback.format_exc() if options.debug else None}
            )
            log.error(f"'{extracted.name}': {exc.message}", detail=exc.detail, exc=exc)

    if contents.by_role("HOLDDATA"):
        progress.begin_stage("holddata", "Reading HOLDDATA")
    for extracted in contents.by_role("HOLDDATA"):
        try:
            analysis.holddata.extend(
                parse_holddata(
                    extracted.data,
                    extracted.name,
                    log=log,
                    encoding_override=options.encoding_override,
                    progress=progress,
                )
            )
        except AnalyzerError as exc:
            analysis.warnings.append(f"HOLDDATA '{extracted.name}' could not be read: {exc.message}")
            log.warning(f"HOLDDATA '{extracted.name}' could not be read", exc=exc)

    for role in ("GIMFAF", "GIMPAF", "GIMZIP"):
        for extracted in contents.by_role(role):
            analysis.gimfaf_members.append(extracted.name)
            analysis.gimfaf.extend(parse_gimfaf(extracted.data, extracted.name, log=log))

    _attach_holds(analysis, log)


def _merge_hold(ptf, hold) -> bool:
    """Attach *hold* to *ptf*, merging into an equivalent one if present."""
    existing = next(
        (
            candidate
            for candidate in ptf.holds
            if candidate.reason == hold.reason and candidate.hold_type == hold.hold_type
        ),
        None,
    )
    if existing is None:
        ptf.holds.append(hold)
        return True
    # Same hold, richer source: HOLDDATA usually carries CLASS, RESOLVER and
    # the long explanation that SMPPTFIN omits.
    for attribute in ("class_", "resolver", "date", "fmid"):
        if not getattr(existing, attribute) and getattr(hold, attribute):
            setattr(existing, attribute, getattr(hold, attribute))
    if len(hold.comment) > len(existing.comment):
        existing.comment = hold.comment
    if hold.source and hold.source not in existing.source:
        existing.source = f"{existing.source} + {hold.source}".strip(" +")
    return True


def _attach_holds(analysis: PackageAnalysis, log: AnalysisLog) -> None:
    """Link stand-alone HOLDDATA entries to the PTF they belong to."""
    by_id: dict[str, list] = {}
    for ptf in analysis.ptfs:
        by_id.setdefault(ptf.sysmod_id, []).append(ptf)

    linked = 0
    for hold in analysis.holddata:
        for ptf in by_id.get(hold.ptf_id.upper(), []):
            linked += _merge_hold(ptf, hold)
    if linked:
        log.info(f"{linked} HOLDDATA entry/entries linked to PTFs in this package.")


def link_holds_across_packages(report: AnalysisReport, log: AnalysisLog) -> int:
    """Match HOLDDATA shipped as its own package against every PTF found.

    A delivery often ships SMPPTFIN in the service package and HOLDDATA in a
    separate '...HOLDDATA.pax.Z' file, so the PE information is useless until
    the two are joined up.
    """
    by_id: dict[str, list] = {}
    for package in report.packages:
        for ptf in package.ptfs:
            by_id.setdefault(ptf.sysmod_id, []).append(ptf)
    if not by_id:
        return 0

    linked = 0
    matched_packages: set[str] = set()
    for package in report.packages:
        if package.ptfs:
            continue  # its own holds were already linked
        for hold in package.all_holds:
            targets = by_id.get(hold.ptf_id.upper())
            if not targets:
                continue
            for ptf in targets:
                linked += _merge_hold(ptf, hold)
            matched_packages.add(package.group.display_name)

    if linked:
        sources = ", ".join(sorted(matched_packages))
        log.success(
            f"{linked} HOLD entry/entries from '{sources}' matched PTFs in the other "
            "package(s) of this analysis."
        )
    return linked


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name)[:80] or "package"


# ---------------------------------------------------------------------------
# top level
# ---------------------------------------------------------------------------


def run_analysis(
    parts: Sequence[PartRef],
    workspace: Workspace,
    options: Optional[AnalyzerOptions] = None,
    log: Optional[AnalysisLog] = None,
    progress: Optional[Progress] = None,
) -> AnalysisReport:
    """Group the uploaded parts into packages and analyze each of them."""
    options = options or AnalyzerOptions()
    log = AnalysisLog() if log is None else log
    progress = progress or NULL_PROGRESS
    started = time.time()

    progress.begin_package("", 0, 1)
    progress.begin_stage("read", "Grouping the selected files")
    groups = group_parts(parts, log)
    report = AnalysisReport(groups=groups, started_at=started)

    for position, group in enumerate(groups):
        progress.begin_package(group.display_name, position, len(groups))
        if group.is_duplicate and not options.analyze_duplicates:
            log.info(f"Skipping duplicate package '{group.display_name}'.")
            progress.note(f"Skipping duplicate package '{group.display_name}'")
            report.packages.append(PackageAnalysis(group=group, warnings=list(group.warnings)))
            continue
        report.packages.append(analyze_package(group, workspace, options, log, progress))

    link_holds_across_packages(report, log)

    progress.finish(
        f"{len(report.analyzed_packages)} package(s), {len(report.ptfs)} PTF(s) analyzed"
    )

    report.duration_s = time.time() - started
    report.log_entries = log.as_dicts()
    log.success(
        f"Analysis finished: {len(report.analyzed_packages)} package(s), "
        f"{len(report.ptfs)} PTF(s) in {report.duration_s:.2f}s"
    )
    return report
