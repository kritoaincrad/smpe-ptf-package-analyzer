"""Data model shared by every stage of the analysis pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Stage 1 - uploaded files and package grouping
# ---------------------------------------------------------------------------


@dataclass
class PartRef:
    """One physical file uploaded by the user.

    Either one ``.XofY`` piece of a split package, or a whole single file
    package.
    """

    display_name: str
    path: Path
    size: int
    sha256: str
    index: Optional[int] = None
    total: Optional[int] = None
    base_name: str = ""
    copy_marker: Optional[str] = None

    @property
    def part_label(self) -> str:
        if self.index is None or self.total is None:
            return "single"
        return f"{self.index} of {self.total}"


@dataclass
class PackageGroup:
    """A set of parts that belong to one logical SMP/E package."""

    key: str
    display_name: str
    parts: list[PartRef] = field(default_factory=list)
    declared_total: Optional[int] = None
    missing_parts: list[int] = field(default_factory=list)
    duplicate_parts: list[tuple[PartRef, PartRef]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fingerprint: str = ""
    duplicate_of: Optional[str] = None

    @property
    def total_size(self) -> int:
        return sum(p.size for p in self.parts)

    @property
    def is_duplicate(self) -> bool:
        return self.duplicate_of is not None

    @property
    def is_complete(self) -> bool:
        return not self.missing_parts and not self.errors

    @property
    def status(self) -> str:
        if self.is_duplicate:
            return "DUPLICATE"
        if self.errors or self.missing_parts:
            return "INCOMPLETE"
        if self.warnings:
            return "WARNING"
        return "READY"


# ---------------------------------------------------------------------------
# Stage 2/3 - stream format, decompression, archive
# ---------------------------------------------------------------------------


@dataclass
class StreamFormat:
    kind: str  # unix_compress, gzip, tar, zip, xmit, bzip2, xz, unknown
    label: str
    magic_hex: str
    needs_decompression: bool = False


@dataclass
class DecompressionResult:
    method: str
    output_path: Path
    input_size: int
    output_size: int
    truncated: bool = False
    attempts: list[dict[str, Any]] = field(default_factory=list)
    duration_s: float = 0.0


@dataclass
class ArchiveMember:
    name: str
    size: int
    is_file: bool
    mtime: Optional[float] = None
    mode: Optional[int] = None
    role: str = ""  # SMPPTFIN, HOLDDATA, GIMFAF, SMPMCS, RELFILE, other
    container: str = ""  # outer archive name when nested

    @property
    def basename(self) -> str:
        return self.name.rstrip("/").rsplit("/", 1)[-1]


# ---------------------------------------------------------------------------
# Stage 4 - encoding / records
# ---------------------------------------------------------------------------


@dataclass
class EncodingGuess:
    encoding: str
    score: float
    token_hits: int
    printable_ratio: float
    replacement_chars: int
    sample: str = ""

    def as_dict(self) -> dict:
        return {
            "Encoding": self.encoding,
            "Score": round(self.score, 2),
            "SMP/E tokens": self.token_hits,
            "Printable %": round(self.printable_ratio * 100, 1),
            "Bad chars": self.replacement_chars,
        }


@dataclass
class RecordSet:
    records: list[str]
    layout: str  # fixed80, lines, mixed
    truncated_columns: bool
    source: str = ""


# ---------------------------------------------------------------------------
# Stage 5 - SMP/E MCS statements and PTFs
# ---------------------------------------------------------------------------


@dataclass
class MCSStatement:
    kind: str
    name: Optional[str]
    operands: dict[str, list[str]] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    leading_comments: list[str] = field(default_factory=list)
    inline_comments: list[str] = field(default_factory=list)
    record_start: int = 0
    record_end: int = 0
    raw: str = ""

    def first(self, keyword: str) -> Optional[str]:
        values = self.operands.get(keyword.upper())
        return values[0] if values else None

    def values(self, keyword: str) -> list[str]:
        return list(self.operands.get(keyword.upper(), []))

    @property
    def comments(self) -> list[str]:
        return self.leading_comments + self.inline_comments


@dataclass
class HoldEntry:
    ptf_id: str
    hold_type: str  # SYSTEM, ERROR, USER, FIXCAT or blank
    reason: str = ""
    fmid: str = ""
    date: str = ""
    class_: str = ""
    resolver: str = ""
    comment: str = ""
    source: str = ""

    @property
    def is_error_hold(self) -> bool:
        return self.hold_type.upper() == "ERROR"

    def as_dict(self) -> dict:
        """Display row (human readable column names)."""
        return {
            "PTF": self.ptf_id,
            "Hold Type": self.hold_type or "-",
            "Reason": self.reason or "-",
            "FMID": self.fmid or "-",
            "Date": self.date or "-",
            "Class": self.class_ or "-",
            "Resolver": self.resolver or "-",
            "Comment": self.comment,
            "Source": self.source,
        }

    def as_record(self) -> dict:
        """Round-trippable record (field names, no display decoration)."""
        return {
            "ptf_id": self.ptf_id,
            "hold_type": self.hold_type,
            "reason": self.reason,
            "fmid": self.fmid,
            "date": self.date,
            "class": self.class_,
            "resolver": self.resolver,
            "comment": self.comment,
            "source": self.source,
        }

    @classmethod
    def from_record(cls, data: dict) -> "HoldEntry":
        return cls(
            ptf_id=data.get("ptf_id", ""),
            hold_type=data.get("hold_type", ""),
            reason=data.get("reason", ""),
            fmid=data.get("fmid", ""),
            date=data.get("date", ""),
            class_=data.get("class", ""),
            resolver=data.get("resolver", ""),
            comment=data.get("comment", ""),
            source=data.get("source", ""),
        )


@dataclass
class ElementRef:
    kind: str
    name: str
    distlib: str = ""
    sysmod: str = ""
    relfile: str = ""
    extra: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        """Display row."""
        return {
            "Type": self.kind,
            "Element": self.name,
            "DISTLIB": self.distlib or "-",
            "RELFILE": self.relfile or "-",
            "SYSLIB/other": ", ".join(f"{k}={v}" for k, v in self.extra.items()) or "-",
        }

    def as_record(self) -> dict:
        return {
            "kind": self.kind,
            "name": self.name,
            "distlib": self.distlib,
            "sysmod": self.sysmod,
            "relfile": self.relfile,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_record(cls, data: dict) -> "ElementRef":
        return cls(
            kind=data.get("kind", ""),
            name=data.get("name", ""),
            distlib=data.get("distlib", ""),
            sysmod=data.get("sysmod", ""),
            relfile=data.get("relfile", ""),
            extra=dict(data.get("extra") or {}),
        )


@dataclass
class PTFEntry:
    """Everything we know about a single SYSMOD (PTF/APAR/USERMOD/FUNCTION)."""

    sysmod_id: str
    sysmod_type: str = "PTF"
    source: str = ""
    fmids: list[str] = field(default_factory=list)
    vers: list[str] = field(default_factory=list)
    pre: list[str] = field(default_factory=list)
    req: list[str] = field(default_factory=list)
    sup: list[str] = field(default_factory=list)
    delete: list[str] = field(default_factory=list)
    apars: list[str] = field(default_factory=list)
    if_conditions: list[dict[str, list[str]]] = field(default_factory=list)
    holds: list[HoldEntry] = field(default_factory=list)
    elements: list[ElementRef] = field(default_factory=list)
    description: str = ""
    comments: list[str] = field(default_factory=list)
    reworked: str = ""
    has_jclin: bool = False
    statement_count: int = 0
    record_start: int = 0

    # -- derived ---------------------------------------------------------
    @property
    def element_summary(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for element in self.elements:
            out[element.kind] = out.get(element.kind, 0) + 1
        return out

    @property
    def element_summary_text(self) -> str:
        summary = self.element_summary
        if not summary:
            return "-"
        return ", ".join(f"{kind} x{count}" for kind, count in sorted(summary.items()))

    @property
    def error_holds(self) -> list[HoldEntry]:
        return [h for h in self.holds if h.is_error_hold]

    @property
    def is_pe(self) -> bool:
        return bool(self.error_holds)

    @property
    def hold_reasons(self) -> list[str]:
        return sorted({h.reason for h in self.holds if h.reason})

    @property
    def short_description(self) -> str:
        text = " ".join(self.description.split())
        return text[:160] + ("..." if len(text) > 160 else "")

    def as_record(self) -> dict:
        """Everything about this SYSMOD, round-trippable through JSON."""
        return {
            "sysmod_id": self.sysmod_id,
            "sysmod_type": self.sysmod_type,
            "source": self.source,
            "fmids": list(self.fmids),
            "vers": list(self.vers),
            "pre": list(self.pre),
            "req": list(self.req),
            "sup": list(self.sup),
            "delete": list(self.delete),
            "apars": list(self.apars),
            "if_conditions": [dict(condition) for condition in self.if_conditions],
            "holds": [hold.as_record() for hold in self.holds],
            "elements": [element.as_record() for element in self.elements],
            "description": self.description,
            "comments": list(self.comments),
            "reworked": self.reworked,
            "has_jclin": self.has_jclin,
            "statement_count": self.statement_count,
            "record_start": self.record_start,
        }

    @classmethod
    def from_record(cls, data: dict) -> "PTFEntry":
        return cls(
            sysmod_id=data.get("sysmod_id", ""),
            sysmod_type=data.get("sysmod_type", "PTF"),
            source=data.get("source", ""),
            fmids=list(data.get("fmids") or []),
            vers=list(data.get("vers") or []),
            pre=list(data.get("pre") or []),
            req=list(data.get("req") or []),
            sup=list(data.get("sup") or []),
            delete=list(data.get("delete") or []),
            apars=list(data.get("apars") or []),
            if_conditions=[dict(condition) for condition in (data.get("if_conditions") or [])],
            holds=[HoldEntry.from_record(hold) for hold in (data.get("holds") or [])],
            elements=[ElementRef.from_record(element) for element in (data.get("elements") or [])],
            description=data.get("description", ""),
            comments=list(data.get("comments") or []),
            reworked=data.get("reworked", ""),
            has_jclin=bool(data.get("has_jclin")),
            statement_count=int(data.get("statement_count") or 0),
            record_start=int(data.get("record_start") or 0),
        )

    def as_row(self) -> dict:
        return {
            "PTF": self.sysmod_id,
            "Type": self.sysmod_type,
            "FMID": ", ".join(self.fmids) or "-",
            "Description": self.short_description or "-",
            "PRE": len(self.pre),
            "REQ": len(self.req),
            "SUP": len(self.sup),
            "APARs": ", ".join(self.apars) or "-",
            "Elements": self.element_summary_text,
            "HOLD": ", ".join(self.hold_reasons) or "-",
            "PE": "YES" if self.is_pe else "",
            "JCLIN": "YES" if self.has_jclin else "",
            "Source": self.source,
        }


@dataclass
class SMPPTFINAnalysis:
    """Result of parsing one SMPPTFIN / SMPMCS member."""

    member: str
    encoding: EncodingGuess
    encoding_candidates: list[EncodingGuess] = field(default_factory=list)
    layout: str = ""
    record_count: int = 0
    statements: list[MCSStatement] = field(default_factory=list)
    prologue: list[str] = field(default_factory=list)
    ptfs: list[PTFEntry] = field(default_factory=list)
    holds: list[HoldEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class PackageAnalysis:
    """Full analysis of one package group."""

    group: PackageGroup
    stream_format: Optional[StreamFormat] = None
    decompression: Optional[DecompressionResult] = None
    members: list[ArchiveMember] = field(default_factory=list)
    smpptfin: list[SMPPTFINAnalysis] = field(default_factory=list)
    holddata: list[HoldEntry] = field(default_factory=list)
    gimfaf: list[dict[str, Any]] = field(default_factory=list)
    gimfaf_members: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration_s: float = 0.0

    # -- derived ---------------------------------------------------------
    @property
    def ptfs(self) -> list[PTFEntry]:
        out: list[PTFEntry] = []
        for analysis in self.smpptfin:
            out.extend(analysis.ptfs)
        return out

    @property
    def all_holds(self) -> list[HoldEntry]:
        out = list(self.holddata)
        for analysis in self.smpptfin:
            out.extend(analysis.holds)
        return out

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def status(self) -> str:
        if self.group.is_duplicate:
            return "DUPLICATE"
        if self.errors:
            return "FAILED"
        if not self.ptfs:
            if self.stream_format is not None and self.stream_format.kind == "xml":
                return "METADATA ONLY"
            if self.holddata:
                return "HOLDDATA ONLY"
            if self.gimfaf:
                return "METADATA ONLY"
            return "NO PTF FOUND"
        if self.warnings:
            return "COMPLETED WITH WARNINGS"
        return "COMPLETED"


@dataclass
class AnalysisReport:
    """Top level result handed to the UI."""

    packages: list[PackageAnalysis] = field(default_factory=list)
    groups: list[PackageGroup] = field(default_factory=list)
    started_at: float = 0.0
    duration_s: float = 0.0
    log_entries: list[dict] = field(default_factory=list)

    @property
    def ptfs(self) -> list[PTFEntry]:
        out: list[PTFEntry] = []
        for package in self.packages:
            out.extend(package.ptfs)
        return out

    @property
    def unique_ptf_ids(self) -> list[str]:
        return sorted({p.sysmod_id for p in self.ptfs})

    @property
    def analyzed_packages(self) -> list[PackageAnalysis]:
        return [p for p in self.packages if not p.group.is_duplicate]
