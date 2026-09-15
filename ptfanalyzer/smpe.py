"""Turning MCS statements into PTF objects a human can read.

The SYSMOD structure SMP/E defines is::

    ++PTF(id)                  <- starts a SYSMOD
      ++VER(level) FMID(..) PRE(..) REQ(..) SUP(..)
      ++IF FMID(..) THEN REQ(..)
      ++HOLD(id) SYSTEM|ERROR REASON(..) COMMENT(..)
      ++MOD(..) / ++SRC(..) / ++ZAP(..) ...   <- the elements it replaces
      ++JCLIN

Everything between one ``++PTF`` (or ``++APAR`` / ``++USERMOD`` /
``++FUNCTION``) and the next belongs to that SYSMOD.
"""

from __future__ import annotations

import re
from typing import Optional

from .encoding import decode, detect_encoding
from .logging_util import AnalysisLog
from .mcs import parse_statements
from .models import ElementRef, HoldEntry, MCSStatement, PTFEntry, SMPPTFINAnalysis
from .progress import NULL_PROGRESS, Progress
from .records import split_records

SYSMOD_KINDS = frozenset({"PTF", "APAR", "USERMOD", "FUNCTION"})
STRUCTURAL_KINDS = frozenset(
    {"VER", "IF", "HOLD", "RELEASE", "JCLIN", "ASSIGN", "FEATURE", "PRODUCT", "ALIAS"}
)
HOLD_TYPES = ("SYSTEM", "ERROR", "USER", "FIXCAT", "DELETE")

#: AA12345, BB12345, CC54321 ... APAR-like identifiers.
APAR_RE = re.compile(r"^(?:[A-Z]{2}\d{5}|II\d{5})$")

_DECORATION_RE = re.compile(r"^[\s*\-=_+.#/\\|]*$")
_ELEMENT_EXTRA_KEYWORDS = (
    "DISTLIB",
    "SYSLIB",
    "TXLIB",
    "RELFILE",
    "LMOD",
    "DISTMOD",
    "LKLIB",
    "VERSION",
    "MALIAS",
    "DALIAS",
    "PARM",
    "SHSCRIPT",
)


# ---------------------------------------------------------------------------
# comment handling
# ---------------------------------------------------------------------------


def clean_comment(text: str) -> str:
    """Strip decoration from an MCS comment and normalize whitespace."""
    stripped = text.strip()
    stripped = stripped.strip("*").strip()
    stripped = re.sub(r"\s+", " ", stripped)
    if _DECORATION_RE.match(stripped):
        return ""
    return stripped


def clean_comments(comments: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for comment in comments:
        cleaned = clean_comment(comment)
        if cleaned and cleaned.upper() not in seen:
            seen.add(cleaned.upper())
            out.append(cleaned)
    return out


# ---------------------------------------------------------------------------
# HOLD / RELEASE
# ---------------------------------------------------------------------------


def build_hold(statement: MCSStatement, source: str = "") -> HoldEntry:
    hold_type = next((flag for flag in statement.flags if flag in HOLD_TYPES), "")
    if statement.kind == "RELEASE":
        hold_type = "RELEASE"
    comments = clean_comments(statement.comments)
    comment_operand = statement.first("COMMENT") or ""
    comment = " ".join(part for part in [comment_operand.strip(), *comments] if part)
    return HoldEntry(
        ptf_id=(statement.name or "").upper(),
        hold_type=hold_type,
        reason=(statement.first("REASON") or "").upper(),
        fmid=(statement.first("FMID") or "").upper(),
        date=statement.first("DATE") or "",
        class_=(statement.first("CLASS") or "").upper(),
        resolver=(statement.first("RESOLVER") or "").upper(),
        comment=re.sub(r"\s+", " ", comment).strip(),
        source=source,
    )


def extract_holds(statements: list[MCSStatement], source: str = "") -> list[HoldEntry]:
    return [
        build_hold(statement, source)
        for statement in statements
        if statement.kind in ("HOLD", "RELEASE")
    ]


# ---------------------------------------------------------------------------
# element / SYSMOD assembly
# ---------------------------------------------------------------------------


def build_element(statement: MCSStatement) -> ElementRef:
    extra = {}
    for keyword in _ELEMENT_EXTRA_KEYWORDS:
        value = statement.first(keyword)
        if value and keyword not in ("DISTLIB", "RELFILE"):
            extra[keyword] = value.upper()
    return ElementRef(
        kind=statement.kind,
        name=(statement.name or "").upper(),
        distlib=(statement.first("DISTLIB") or "").upper(),
        sysmod=(statement.first("SYSMOD") or "").upper(),
        relfile=statement.first("RELFILE") or "",
        extra=extra,
    )


def _uniq(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        upper = value.strip().upper()
        if upper and upper not in seen:
            seen.add(upper)
            out.append(upper)
    return out


def build_ptfs(
    statements: list[MCSStatement], source: str = "", log: Optional[AnalysisLog] = None
) -> tuple[list[PTFEntry], list[HoldEntry]]:
    """Group *statements* into :class:`PTFEntry` objects.

    Returns ``(ptfs, orphan_holds)`` - holds that belong to no SYSMOD in this
    member are returned separately instead of being dropped.
    """
    log = AnalysisLog("smpe") if log is None else log
    ptfs: list[PTFEntry] = []
    orphan_holds: list[HoldEntry] = []
    current: Optional[PTFEntry] = None
    by_id: dict[str, PTFEntry] = {}

    for statement in statements:
        kind = statement.kind

        if kind in SYSMOD_KINDS:
            current = PTFEntry(
                sysmod_id=(statement.name or "UNKNOWN").upper(),
                sysmod_type=kind,
                source=source,
                record_start=statement.record_start,
                comments=clean_comments(statement.comments),
                reworked=statement.first("REWORK") or "",
            )
            current.description = "\n".join(current.comments)
            if kind == "APAR":
                current.apars = [current.sysmod_id]
            ptfs.append(current)
            by_id[current.sysmod_id] = current
            continue

        if current is None:
            if kind in ("HOLD", "RELEASE"):
                orphan_holds.append(build_hold(statement, source))
            continue

        current.statement_count += 1

        if kind == "VER":
            if statement.name:
                current.vers = _uniq([*current.vers, statement.name])
            current.fmids = _uniq([*current.fmids, *statement.values("FMID")])
            current.pre = _uniq([*current.pre, *statement.values("PRE")])
            current.req = _uniq([*current.req, *statement.values("REQ"), *statement.values("NPRE")])
            current.sup = _uniq([*current.sup, *statement.values("SUP")])
            current.delete = _uniq([*current.delete, *statement.values("DELETE")])
            if not current.reworked and statement.first("REWORK"):
                current.reworked = statement.first("REWORK") or ""
            extra_comments = clean_comments(statement.comments)
            if extra_comments:
                current.comments.extend(c for c in extra_comments if c not in current.comments)
                current.description = "\n".join(current.comments)

        elif kind == "IF":
            current.if_conditions.append(
                {
                    "FMID": _uniq(statement.values("FMID")),
                    "REQ": _uniq(statement.values("REQ")),
                }
            )

        elif kind in ("HOLD", "RELEASE"):
            hold = build_hold(statement, source)
            target = by_id.get(hold.ptf_id, current)
            target.holds.append(hold)

        elif kind == "JCLIN":
            current.has_jclin = True

        elif kind not in STRUCTURAL_KINDS:
            current.elements.append(build_element(statement))

    # APARs fixed by a PTF are carried in SUP() alongside superseded PTFs.
    for ptf in ptfs:
        apars = [value for value in ptf.sup if APAR_RE.match(value)]
        ptf.apars = _uniq([*ptf.apars, *apars])
        if not ptf.description:
            hold_text = " ".join(h.comment for h in ptf.holds if h.comment)
            if hold_text:
                ptf.description = re.sub(r"\s+", " ", hold_text).strip()

    log.info(
        f"{source or 'Member'}: {len(ptfs)} SYSMOD(s) assembled"
        + (f", {len(orphan_holds)} stand-alone HOLD statement(s)" if orphan_holds else "")
    )
    return ptfs, orphan_holds


# ---------------------------------------------------------------------------
# full member pipeline
# ---------------------------------------------------------------------------


def analyze_member(
    data: bytes,
    member: str,
    log: Optional[AnalysisLog] = None,
    encoding_override: Optional[str] = None,
    honor_sequence_columns: bool = True,
    progress: Optional[Progress] = None,
) -> SMPPTFINAnalysis:
    """Decode, split and parse one SMPPTFIN / SMPMCS member end to end."""
    log = AnalysisLog("smpe") if log is None else log
    progress = progress or NULL_PROGRESS
    short_name = member.rsplit("/", 1)[-1]
    progress.note(f"Detecting encoding of {short_name}")

    if encoding_override:
        guess_list: list = []
        from .models import EncodingGuess

        winner = EncodingGuess(
            encoding=encoding_override, score=0.0, token_hits=0, printable_ratio=1.0, replacement_chars=0
        )
        log.info(f"'{member}': encoding forced to '{encoding_override}'")
    else:
        winner, guess_list = detect_encoding(data, log=log, member=member)

    text = decode(data, winner.encoding)
    progress.note(f"Splitting {short_name} into records ({winner.encoding})")
    record_set = split_records(
        text, honor_sequence_columns=honor_sequence_columns, log=log, source=member
    )
    progress.note(f"Parsing {short_name}: {len(record_set.records):,} records")
    document = parse_statements(record_set.records, log=log, source=member, progress=progress)
    progress.note(f"Building PTF list from {short_name}")
    ptfs, orphan_holds = build_ptfs(document.statements, source=member, log=log)

    analysis = SMPPTFINAnalysis(
        member=member,
        encoding=winner,
        encoding_candidates=guess_list,
        layout=record_set.layout,
        record_count=len(record_set.records),
        statements=document.statements,
        prologue=document.prologue,
        ptfs=ptfs,
        holds=orphan_holds,
    )
    if not ptfs:
        analysis.warnings.append(
            "No ++PTF / ++APAR / ++USERMOD statement was found in this member."
        )
    return analysis
