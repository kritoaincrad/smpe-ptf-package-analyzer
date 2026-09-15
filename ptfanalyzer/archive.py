"""PAX / TAR handling for decompressed SMP/E packages.

z/OS ships SMP/E service as ``pax -wzf`` archives (``.pax.Z``), so after
decompression we normally get a PAX archive that python's :mod:`tarfile` can
read.  Two things make real packages messy:

* the interesting files live in sub directories such as
  ``SMPPTFIN`` vs ``PTF.2026258/SMPPTFIN``,
* GIMZIP style packages nest another archive inside the outer one.

This module therefore searches by *basename suffix* and can descend into
nested archives up to a configurable depth.
"""

from __future__ import annotations

import io
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from .errors import ArchiveError
from .logging_util import AnalysisLog
from .models import ArchiveMember
from .progress import NULL_PROGRESS, Progress

#: Files we specifically look for, mapped to the role we report in the UI.
ROLE_PATTERNS: list[tuple[str, str]] = [
    ("SMPPTFIN", "SMPPTFIN"),
    ("SMPMCS", "SMPMCS"),
    ("HOLDDATA", "HOLDDATA"),
    ("SMPHOLD", "HOLDDATA"),
    ("GIMFAF.XML", "GIMFAF"),
    ("GIMPAF.XML", "GIMPAF"),
    ("GIMZIP.XML", "GIMZIP"),
    ("SMPRPT", "REPORT"),
    ("README", "README"),
]

NESTED_SUFFIXES = (".pax.z", ".pax", ".tar", ".tar.z", ".z")
MAX_MEMBER_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 100_000


def _unsafe_member_name(name: str) -> bool:
    path = name.replace("\\", "/")
    return path.startswith("/") or any(part == ".." for part in path.split("/")) or (len(path) > 1 and path[1] == ":")


def classify(name: str) -> str:
    """Return the role of an archive member from its name."""
    upper = name.upper().rstrip("/")
    base = upper.rsplit("/", 1)[-1]
    for pattern, role in ROLE_PATTERNS:
        if base == pattern or base.endswith(pattern) or upper.endswith(pattern):
            return role
    if ".RELFILE" in upper or base.startswith("RELFILE") or "/RELFILE" in upper:
        return "RELFILE"
    return ""


@dataclass
class ExtractedFile:
    name: str
    data: bytes
    role: str
    container: str = ""


@dataclass
class ArchiveContents:
    members: list[ArchiveMember] = field(default_factory=list)
    files: dict[str, ExtractedFile] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def by_role(self, role: str) -> list[ExtractedFile]:
        return [f for f in self.files.values() if f.role == role]


def is_tar(path: Path) -> bool:
    try:
        return tarfile.is_tarfile(path)
    except (OSError, tarfile.TarError):
        return False


def _open_tar(source) -> tarfile.TarFile:
    try:
        if isinstance(source, (str, Path)):
            return tarfile.open(source, mode="r:*")
        return tarfile.open(fileobj=source, mode="r:*")
    except tarfile.TarError as exc:
        raise ArchiveError(
            "The decompressed stream is not a readable PAX/TAR archive.",
            detail=f"{type(exc).__name__}: {exc}",
            hint=(
                "The package may be a plain data set image instead of a pax archive, "
                "or a part of the package is missing/out of order."
            ),
        ) from exc


def read_archive(
    source: Path,
    log: Optional[AnalysisLog] = None,
    wanted_roles: Iterable[str] = ("SMPPTFIN", "SMPMCS", "HOLDDATA", "GIMFAF", "GIMPAF", "GIMZIP"),
    max_depth: int = 2,
    max_member_bytes: int = MAX_MEMBER_BYTES,
    progress: Optional[Progress] = None,
) -> ArchiveContents:
    """List an archive and extract the members we care about.

    Only members whose role is in *wanted_roles* are read into memory; the
    rest are merely listed, so a 2 GB package costs almost nothing.
    """
    log = AnalysisLog("archive") if log is None else log
    progress = progress or NULL_PROGRESS
    contents = ArchiveContents()
    wanted = set(wanted_roles)
    progress.begin_stage("archive", "Reading archive")

    _walk_archive(
        _open_tar(source),
        container="",
        contents=contents,
        wanted=wanted,
        depth=0,
        max_depth=max_depth,
        max_member_bytes=max_member_bytes,
        log=log,
        progress=progress,
    )

    log.info(
        f"Archive listed: {len(contents.members)} member(s), "
        f"{len(contents.files)} SMP/E metadata file(s) extracted"
    )
    for extracted in contents.files.values():
        log.debug(f"  {extracted.role:<9} {extracted.name} ({len(extracted.data):,} bytes)")
    return contents


def _walk_archive(
    tar: tarfile.TarFile,
    container: str,
    contents: ArchiveContents,
    wanted: set[str],
    depth: int,
    max_depth: int,
    max_member_bytes: int,
    log: AnalysisLog,
    progress: Progress = NULL_PROGRESS,
) -> None:
    with tar:
        for info in _iter_members(tar, contents, container, log):
            if len(contents.members) >= MAX_ARCHIVE_MEMBERS:
                message = f"Archive member limit ({MAX_ARCHIVE_MEMBERS:,}) reached; remaining entries were skipped."
                contents.warnings.append(message)
                log.warning(message)
                break
            if _unsafe_member_name(info.name):
                message = f"Unsafe archive path '{info.name}' was rejected."
                contents.warnings.append(message)
                log.warning(message)
                continue
            role = classify(info.name)
            member = ArchiveMember(
                name=info.name,
                size=info.size,
                is_file=info.isfile(),
                mtime=float(info.mtime),
                mode=info.mode,
                role=role,
                container=container,
            )
            contents.members.append(member)
            progress.update(
                len(contents.members),
                message=f"Reading archive: {len(contents.members)} member(s) - {member.basename}",
            )

            if not info.isfile():
                continue

            lowered = info.name.lower()
            nested = depth < max_depth and lowered.endswith(NESTED_SUFFIXES) and not role

            if role in wanted or nested:
                if info.size > max_member_bytes:
                    contents.warnings.append(
                        f"'{info.name}' is {info.size / (1024 * 1024):.0f} MB and was skipped."
                    )
                    log.warning(f"Skipping oversized member '{info.name}'")
                    continue
                try:
                    handle = tar.extractfile(info)
                    if handle is None:
                        continue
                    data = handle.read()
                except (tarfile.TarError, OSError) as exc:
                    contents.warnings.append(f"'{info.name}' could not be read: {exc}")
                    log.warning(f"Member '{info.name}' could not be read", exc=exc)
                    continue

                if role in wanted:
                    key = f"{container}/{info.name}" if container else info.name
                    contents.files[key] = ExtractedFile(
                        name=key, data=data, role=role, container=container
                    )
                    progress.note(f"Found {role}: {member.basename}")
                elif nested:
                    _descend(
                        data, info.name, contents, wanted, depth, max_depth, max_member_bytes, log, progress
                    )


def _iter_members(
    tar: tarfile.TarFile, contents: ArchiveContents, container: str, log: AnalysisLog
):
    """Iterate archive members, surviving a truncated archive.

    A package whose last part is missing decompresses to a valid prefix, so the
    listing simply stops in the middle.  That is worth a warning, not a crash.
    """
    while True:
        try:
            info = tar.next()
        except tarfile.TarError as exc:
            where = f" inside '{container}'" if container else ""
            message = (
                f"The archive{where} ends unexpectedly after "
                f"{len(contents.members)} member(s); it is truncated."
            )
            contents.warnings.append(message)
            log.warning(message, detail=f"{type(exc).__name__}: {exc}")
            return
        if info is None:
            return
        yield info


def _descend(
    data: bytes,
    name: str,
    contents: ArchiveContents,
    wanted: set[str],
    depth: int,
    max_depth: int,
    max_member_bytes: int,
    log: AnalysisLog,
    progress: Progress = NULL_PROGRESS,
) -> None:
    """Try to open a nested archive found inside the outer package."""
    from .compression import MAGIC_COMPRESS, unlzw  # local import: avoid a cycle

    payload = data
    if payload[:2] == MAGIC_COMPRESS:
        try:
            payload = unlzw(payload)
            log.info(f"Nested .Z archive '{name}' decompressed ({len(payload):,} bytes)")
        except Exception as exc:  # noqa: BLE001 - nested archives are best effort
            log.warning(f"Nested archive '{name}' could not be decompressed", exc=exc)
            return

    try:
        nested_tar = tarfile.open(fileobj=io.BytesIO(payload), mode="r:*")
    except tarfile.TarError:
        log.debug(f"Nested member '{name}' is not an archive; ignored")
        return

    log.info(f"Descending into nested archive '{name}'")
    _walk_archive(
        nested_tar,
        container=name,
        contents=contents,
        wanted=wanted,
        depth=depth + 1,
        max_depth=max_depth,
        max_member_bytes=max_member_bytes,
        log=log,
        progress=progress,
    )


def wrap_raw_stream(path: Path, log: Optional[AnalysisLog] = None) -> ArchiveContents:
    """Treat a non-archive stream as a single SMPPTFIN-like member.

    Some deliveries are just a sequential data set image rather than a pax
    archive; the SMP/E metadata is then the whole file.
    """
    log = AnalysisLog("archive") if log is None else log
    data = Path(path).read_bytes()
    contents = ArchiveContents()
    name = Path(path).name
    contents.members.append(ArchiveMember(name=name, size=len(data), is_file=True, role="SMPPTFIN"))
    contents.files[name] = ExtractedFile(name=name, data=data, role="SMPPTFIN")
    contents.warnings.append(
        "The stream is not a PAX/TAR archive; it is analyzed as a single SMP/E input file."
    )
    log.warning("Stream is not an archive - analyzing it as a raw SMP/E input file")
    return contents
