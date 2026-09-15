"""Split package (``.XofY``) detection, ordering, validation and joining.

Real life SMP/E deliveries arrive as a set of files such as::

    example-package.1of3
    example-package.2of3
    ...
    example-package.3of3

The files usually have no extension at all, and browsers/mail clients happily
rename copies to ``name(1).1of7``.  This module turns whatever the user
uploaded into validated :class:`~ptfanalyzer.models.PackageGroup` objects.

Ordering is **always numeric** - never alphabetic - so ``10of12`` sorts after
``9of12``.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable, Optional

from .errors import PartSetError
from .logging_util import AnalysisLog
from .models import PackageGroup, PartRef
from .progress import NULL_PROGRESS, Progress, format_bytes

# ``name.1of7`` / ``name_01OF07`` / ``name-1 of 7`` / ``name.1of7.Z``
PART_PATTERN = re.compile(
    r"""^(?P<base>.*?)                # package base name (non greedy)
         [._\- ]                      # separator before the part marker
         (?P<index>\d{1,4})           # part number
         \s*(?:of|OF|Of|oF)\s*        # the literal 'of'
         (?P<total>\d{1,4})           # total part count
         (?P<tail>(?:\.(?:z|Z|pax|PAX|pax\.Z|pax\.z))?)$  # optional extension
    """,
    re.VERBOSE,
)

# Trailing copy markers added by Windows / browsers / mail clients.
COPY_PATTERNS = [
    re.compile(r"\s*\((?P<n>\d{1,3})\)\s*$"),
    re.compile(r"\s*-\s*[Cc]opy(?:\s*\(\d+\))?\s*$"),
    re.compile(r"\s*-\s*[Kk]opya(?:\s*\(\d+\))?\s*$"),
    re.compile(r"\s*[-_]\s*copy\s*$", re.IGNORECASE),
]

CHUNK = 1024 * 1024


# ---------------------------------------------------------------------------
# hashing helpers
# ---------------------------------------------------------------------------


def sha256_file(path: Path, chunk_size: int = CHUNK) -> str:
    """Stream a file through SHA-256 (files can be hundreds of megabytes)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# file name parsing
# ---------------------------------------------------------------------------


def strip_copy_marker(name: str) -> tuple[str, Optional[str]]:
    """Remove a trailing ``(1)`` / ``- Copy`` marker from *name*."""
    marker: Optional[str] = None
    changed = True
    result = name
    while changed:
        changed = False
        for pattern in COPY_PATTERNS:
            match = pattern.search(result)
            if match:
                marker = match.group(0).strip()
                result = result[: match.start()]
                changed = True
    return result.rstrip(" ._-"), marker


def parse_part_name(filename: str) -> dict:
    """Split *filename* into base name, part index and total part count.

    Returns a dict with ``base``, ``index``, ``total`` and ``copy_marker``.
    ``index``/``total`` are ``None`` for files that are not part of a split
    set (single ``.Z`` / ``.pax.Z`` packages).
    """
    name = filename.strip().replace("\\", "/").rsplit("/", 1)[-1]

    # A copy marker may sit either after the part marker (``x.1of7(1)``) or
    # inside the base name (``x(1).1of7``); handle both.
    stripped, marker = strip_copy_marker(name)

    match = PART_PATTERN.match(stripped)
    if match:
        base, base_marker = strip_copy_marker(match.group("base"))
        return {
            "base": base,
            "index": int(match.group("index")),
            "total": int(match.group("total")),
            "copy_marker": marker or base_marker,
        }

    base, base_marker = strip_copy_marker(stripped)
    return {"base": base, "index": None, "total": None, "copy_marker": marker or base_marker}


def _group_key(base: str, total: Optional[int]) -> str:
    return f"{base.casefold()}|{total if total is not None else 'single'}"


# ---------------------------------------------------------------------------
# PartRef construction
# ---------------------------------------------------------------------------


def build_part_ref(display_name: str, path: Path) -> PartRef:
    parsed = parse_part_name(display_name)
    path = Path(path)
    return PartRef(
        display_name=display_name,
        path=path,
        size=path.stat().st_size,
        sha256=sha256_file(path),
        index=parsed["index"],
        total=parsed["total"],
        base_name=parsed["base"],
        copy_marker=parsed["copy_marker"],
    )


def build_part_ref_from_buffer(display_name: str, data) -> PartRef:
    """Build a :class:`PartRef` from data already in memory.

    Used by the UI to preview and validate a part set without spooling every
    upload to disk on each interaction.  ``data`` may be ``bytes`` or any
    buffer (``memoryview``, ``bytearray``).
    """
    parsed = parse_part_name(display_name)
    view = memoryview(data)
    return PartRef(
        display_name=display_name,
        path=Path(display_name),
        size=view.nbytes,
        sha256=hashlib.sha256(view).hexdigest(),
        index=parsed["index"],
        total=parsed["total"],
        base_name=parsed["base"],
        copy_marker=parsed["copy_marker"],
    )


# ---------------------------------------------------------------------------
# grouping / validation
# ---------------------------------------------------------------------------


def group_parts(parts: Iterable[PartRef], log: Optional[AnalysisLog] = None) -> list[PackageGroup]:
    """Group *parts* into packages and validate every set.

    Detects, per group:

    * identical duplicate files (same SHA-256) - ignored, reported once,
    * conflicting duplicates (same part number, different content) - error,
    * missing part numbers - error ("Part 4 is missing."),
    * inconsistent ``XofY`` totals inside one base name - error.

    Finally, whole packages whose ordered part hashes match another package are
    flagged with ``duplicate_of``.
    """
    log = AnalysisLog("parts") if log is None else log
    buckets: dict[str, list[PartRef]] = {}

    for part in parts:
        key = _group_key(part.base_name, part.total)
        buckets.setdefault(key, []).append(part)

    # Merge groups that share a base name but declare different totals so the
    # inconsistency becomes visible instead of silently producing two packages.
    by_base: dict[str, list[str]] = {}
    for key in buckets:
        base = key.rsplit("|", 1)[0]
        by_base.setdefault(base, []).append(key)

    groups: list[PackageGroup] = []
    for base, keys in sorted(by_base.items()):
        members: list[PartRef] = []
        for key in keys:
            members.extend(buckets[key])
        groups.append(_build_group(base, members, log))

    _flag_duplicate_packages(groups, log)
    return groups


def _build_group(base: str, members: list[PartRef], log: AnalysisLog) -> PackageGroup:
    display = members[0].base_name or base
    group = PackageGroup(key=base, display_name=display)

    totals = {p.total for p in members if p.total is not None}
    singles = [p for p in members if p.total is None]

    if totals and singles:
        group.warnings.append(
            "Both split parts and a stand-alone file share this package name; "
            "the stand-alone file is analyzed separately."
        )

    if len(totals) > 1:
        group.errors.append(
            "Inconsistent part counts for the same package: "
            + ", ".join(f"{t} parts" for t in sorted(totals))
            + ". Files from different deliveries were probably mixed."
        )
        log.error(f"{display}: inconsistent XofY totals {sorted(totals)}")

    group.declared_total = sorted(totals)[0] if totals else (1 if singles else None)

    # ---- duplicate detection inside the group --------------------------
    seen_by_index: dict[int, PartRef] = {}
    seen_by_hash: dict[str, PartRef] = {}
    ordered: list[PartRef] = []

    # Numeric ordering. Single files get index 1 and keep upload order.
    def sort_key(part: PartRef) -> tuple:
        return (part.index if part.index is not None else 1, part.display_name)

    for part in sorted(members, key=sort_key):
        index = part.index if part.index is not None else 1
        previous_same_hash = seen_by_hash.get(part.sha256)
        previous_same_index = seen_by_index.get(index)

        if previous_same_hash is not None:
            group.duplicate_parts.append((part, previous_same_hash))
            group.warnings.append(
                f"Duplicate file ignored: '{part.display_name}' is byte identical to "
                f"'{previous_same_hash.display_name}' (SHA-256 {part.sha256[:16]}...)."
            )
            log.warning(
                f"{display}: duplicate part '{part.display_name}' ignored",
                detail=f"identical to '{previous_same_hash.display_name}'",
            )
            continue

        if previous_same_index is not None:
            group.errors.append(
                f"Part {index} was supplied twice with different content: "
                f"'{previous_same_index.display_name}' and '{part.display_name}'."
            )
            log.error(f"{display}: conflicting copies of part {index}")
            continue

        seen_by_index[index] = part
        seen_by_hash[part.sha256] = part
        ordered.append(part)

    group.parts = ordered

    # ---- completeness --------------------------------------------------
    if group.declared_total and group.declared_total > 1:
        present = sorted(seen_by_index)
        missing = [n for n in range(1, group.declared_total + 1) if n not in seen_by_index]
        group.missing_parts = missing
        if missing:
            listing = ", ".join(str(n) for n in missing)
            word = "Part" if len(missing) == 1 else "Parts"
            group.errors.append(f"{word} {listing} {'is' if len(missing) == 1 else 'are'} missing.")
            log.error(f"{display}: missing part(s) {listing}")
        extra = [n for n in present if n > group.declared_total or n < 1]
        if extra:
            group.errors.append(
                "Part number(s) outside the declared range: " + ", ".join(str(n) for n in extra) + "."
            )

    _check_part_sizes(group, log)

    if ordered and len(group.duplicate_parts) >= len(ordered):
        group.warnings.insert(
            0,
            "Duplicate package detected - a complete second copy of this package was uploaded "
            "and is ignored (only one copy is analyzed).",
        )
        log.warning(f"Duplicate package detected: a full second copy of '{display}' was ignored")

    group.fingerprint = hashlib.sha256(
        "|".join(p.sha256 for p in ordered).encode("ascii")
    ).hexdigest()

    if ordered:
        log.info(
            f"Package '{display}': {len(ordered)} part(s), "
            f"{group.total_size / (1024 * 1024):.1f} MB, status {group.status}"
        )
    return group


def _check_part_sizes(group: PackageGroup, log: AnalysisLog) -> None:
    """Catch a part whose download was cut short.

    A split package is produced by slicing one stream, so every part except the
    last has exactly the same size.  A short part in the middle is the most
    common reason for "the .Z stream ended in the middle of a code": the file
    name is right, the part number is right, but the bytes are missing.
    """
    parts = group.parts
    if len(parts) < 3:
        return  # not enough evidence to call one size "the normal size"

    leading = parts[:-1]
    sizes = [part.size for part in leading]
    expected = max(set(sizes), key=sizes.count)
    if sizes.count(expected) < 2:
        return  # no clear majority: the package was probably not split evenly

    for part in leading:
        if part.size == expected:
            continue
        shortfall = expected - part.size
        if shortfall > 0:
            message = (
                f"Part {part.part_label} ('{part.display_name}') is "
                f"{format_bytes(part.size)} while the other parts are "
                f"{format_bytes(expected)} - it is {shortfall:,} byte(s) short "
                "and looks like an interrupted download or copy."
            )
        else:
            message = (
                f"Part {part.part_label} ('{part.display_name}') is "
                f"{format_bytes(part.size)} while the other parts are "
                f"{format_bytes(expected)} - the files may come from different deliveries."
            )
        group.errors.append(message)
        log.error(f"{group.display_name}: {message}")

    last = parts[-1]
    if last.size > expected:
        message = (
            f"The last part ('{last.display_name}') is larger than the other parts; "
            "the part set looks inconsistent."
        )
        group.warnings.append(message)
        log.warning(f"{group.display_name}: {message}")


def _flag_duplicate_packages(groups: list[PackageGroup], log: AnalysisLog) -> None:
    by_fingerprint: dict[str, PackageGroup] = {}
    for group in groups:
        if not group.parts:
            continue
        original = by_fingerprint.get(group.fingerprint)
        if original is None:
            by_fingerprint[group.fingerprint] = group
            continue
        group.duplicate_of = original.display_name
        group.warnings.append(
            f"Duplicate package detected - byte identical to '{original.display_name}'. "
            "It is listed but not analyzed twice."
        )
        log.warning(
            f"Duplicate package detected: '{group.display_name}' == '{original.display_name}'",
            detail=f"fingerprint {group.fingerprint[:16]}...",
        )


# ---------------------------------------------------------------------------
# joining
# ---------------------------------------------------------------------------


def concatenate(
    group: PackageGroup,
    destination: Path,
    log: Optional[AnalysisLog] = None,
    progress: Optional[Progress] = None,
) -> Path:
    """Join the ordered parts of *group* into *destination* (streamed)."""
    log = AnalysisLog("parts") if log is None else log
    if not group.parts:
        raise PartSetError(
            f"Package '{group.display_name}' has no usable files.",
            hint="Upload every '.XofY' part of the package.",
        )
    if group.errors:
        reasons = " ".join(group.errors)
        raise PartSetError(
            f"Package '{group.display_name}' cannot be joined. {reasons}",
            detail="; ".join(group.errors),
            hint="Supply the complete set of '.XofY' parts and run the analysis again.",
        )

    order = " + ".join(p.part_label for p in group.parts)
    log.info(f"Joining {len(group.parts)} part(s) in numeric order: {order}")

    progress = progress or NULL_PROGRESS
    total = group.total_size
    progress.begin_stage("join", f"Joining {len(group.parts)} part(s)", total)

    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(destination, "wb") as out:
        for part in group.parts:
            progress.note(f"Joining part {part.part_label}: {part.display_name}")
            with open(part.path, "rb") as handle:
                for block in iter(lambda: handle.read(CHUNK), b""):
                    out.write(block)
                    written += len(block)
                    progress.bytes_update(written, total, "Joining parts")
    log.success(f"Joined stream: {written:,} bytes -> {destination.name}")
    return destination
