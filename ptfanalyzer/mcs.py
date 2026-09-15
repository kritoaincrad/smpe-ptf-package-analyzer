"""Tokenizer for SMP/E Modification Control Statements (MCS).

An MCS statement looks like::

    ++PTF(PTF0001) /* short description of the fix */ .
    ++VER(V001) FMID(FMID001) PRE(PTF0002,PTF0003)
        SUP(APR0001) .
    ++HOLD(PTF0001) SYSTEM FMID(FMID001) REASON(ACTION)
        DATE(26001) COMMENT(Restart the address space after APPLY.) .

Rules implemented here, all of which real packages depend on:

* a statement runs until the first ``.`` that is outside parentheses,
  quotes and comments - it may span any number of 80 byte records,
* records are concatenated **without** an implied blank, because SMP/E allows
  an operand to be split across the column 72 boundary,
* ``/* ... */`` comments are captured (they carry the PTF description) and, for
  readability, record breaks inside a comment become blanks,
* free text operands such as ``COMMENT(...)`` are kept verbatim instead of
  being split on commas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .logging_util import AnalysisLog
from .models import MCSStatement
from .progress import NULL_PROGRESS, Progress

IDENT_RE = re.compile(r"[A-Za-z0-9#$@_\-]+")

#: A real MCS statement type starts with a letter and is alphanumeric
#: (``PTF``, ``VER``, ``MOD``, ``PNLENU``...).  Inline binary data inside a
#: member produces plenty of ``++`` pairs followed by noise (``++3L``,
#: ``++#KC``); those are skipped instead of being parsed as statements.
VALID_KIND_RE = re.compile(r"^[A-Z][A-Z0-9]{0,9}$")

#: Operands whose value is prose, not a comma separated list.
FREE_TEXT_KEYWORDS = frozenset({"COMMENT", "DESC", "DESCRIPTION", "TEXT", "MSG", "REASONID"})

MAX_RAW_CHARS = 8000

#: An operand list longer than this is not an operand list; inside inline
#: binary data an unbalanced '(' would otherwise swallow the rest of the member.
MAX_GROUP_CHARS = 6000


class _Scanner:
    """Character scanner over the flattened record stream."""

    def __init__(self, records: list[str]):
        parts: list[str] = []
        record_of: list[int] = []
        for number, record in enumerate(records):
            parts.append(record)
            record_of.extend([number] * len(record))
        self.text = "".join(parts)
        self.record_of = record_of
        self.length = len(self.text)
        self.pos = 0

    # -- helpers ---------------------------------------------------------
    def record_at(self, position: int) -> int:
        if not self.record_of:
            return 0
        position = min(max(position, 0), self.length - 1)
        return self.record_of[position]

    def starts_with(self, needle: str, position: Optional[int] = None) -> bool:
        position = self.pos if position is None else position
        return self.text.startswith(needle, position)

    # -- readers ---------------------------------------------------------
    def read_comment(self) -> str:
        """Read ``/* ... */`` starting at the current position."""
        assert self.starts_with("/*")
        start = self.pos + 2
        end = self.text.find("*/", start)
        if end == -1:
            end = self.length
            self.pos = self.length
        else:
            self.pos = end + 2
        return self._with_record_breaks(start, end)

    def _with_record_breaks(self, start: int, end: int) -> str:
        """Slice the text, inserting a blank at every record boundary."""
        if start >= end:
            return ""
        if not self.record_of:
            return self.text[start:end]
        chunks: list[str] = []
        chunk_start = start
        current = self.record_of[start]
        for index in range(start + 1, end):
            if self.record_of[index] != current:
                chunks.append(self.text[chunk_start:index])
                chunk_start = index
                current = self.record_of[index]
        chunks.append(self.text[chunk_start:end])
        return " ".join(chunk.strip() for chunk in chunks if chunk.strip())

    def read_group(self) -> str:
        """Read a balanced ``( ... )`` group, returning the inner text.

        Gives up after :data:`MAX_GROUP_CHARS` characters so that an unbalanced
        parenthesis in inline binary data cannot consume the whole member.
        """
        assert self.text[self.pos] == "("
        depth = 0
        index = self.pos
        limit = min(self.length, self.pos + MAX_GROUP_CHARS)
        quote: Optional[str] = None
        while index < limit:
            char = self.text[index]
            if quote:
                if char == quote:
                    quote = None
            elif char in "'\"":
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    inner = self._with_record_breaks(self.pos + 1, index)
                    self.pos = index + 1
                    return inner
            index += 1
        # Never closed: step over the '(' and carry on scanning.
        self.pos += 1
        return ""


def split_operand_list(value: str) -> list[str]:
    """Split ``A,B , C`` into ``['A', 'B', 'C']`` respecting quotes/parens."""
    items: list[str] = []
    current: list[str] = []
    depth = 0
    quote: Optional[str] = None
    for char in value:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
            current.append(char)
        elif char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            items.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    items.append("".join(current).strip())
    return [item for item in items if item]


@dataclass
class MCSDocument:
    """Parsed member: the statements plus the file header comment block."""

    statements: list[MCSStatement] = field(default_factory=list)
    prologue: list[str] = field(default_factory=list)


def parse_statements(
    records: list[str],
    log: Optional[AnalysisLog] = None,
    source: str = "",
    progress: Optional[Progress] = None,
) -> MCSDocument:
    """Parse *records* (already stripped of sequence columns) into statements.

    Comments that appear before the very first statement are the package
    header, not a PTF description, so they are kept separately.
    """
    log = AnalysisLog("mcs") if log is None else log
    progress = progress or NULL_PROGRESS
    scanner = _Scanner(records)
    member = source.rsplit("/", 1)[-1] or "member"
    statements: list[MCSStatement] = []
    pending_comments: list[str] = []
    prologue: list[str] = []
    unterminated = 0
    noise = 0

    while scanner.pos < scanner.length:
        if scanner.starts_with("/*"):
            comment = scanner.read_comment()
            if comment:
                pending_comments.append(comment)
            continue
        if scanner.starts_with("++"):
            if not statements and not noise:
                prologue = pending_comments
                pending_comments = []
            statement_start = scanner.pos
            statement, clean_end = _read_statement(scanner, pending_comments)
            pending_comments = []
            if statement is not None and not VALID_KIND_RE.match(statement.kind):
                # Binary noise: rewind so the scan resumes right after the '++'
                # instead of skipping over whatever the bogus statement ate.
                noise += 1
                scanner.pos = statement_start + 2
                continue
            if statement is not None:
                statements.append(statement)
                if not clean_end:
                    unterminated += 1
                if len(statements) % 200 == 0:
                    progress.update(
                        scanner.pos,
                        scanner.length,
                        f"Parsing {member}: {len(statements):,} statements",
                    )
            continue
        scanner.pos += 1

    if noise:
        log.info(
            f"{source or 'Member'}: {noise:,} '++' sequence(s) inside inline data were "
            "skipped (they are not MCS statements)."
        )
    if unterminated:
        log.warning(
            f"{source or 'Member'}: {unterminated} statement(s) were not closed with '.' "
            "and were terminated at the next '++' statement."
        )
    kinds: dict[str, int] = {}
    for statement in statements:
        kinds[statement.kind] = kinds.get(statement.kind, 0) + 1
    summary = ", ".join(f"++{kind} x{count}" for kind, count in sorted(kinds.items())[:12])
    log.info(f"{source or 'Member'}: {len(statements)} MCS statement(s) parsed" + (f" ({summary})" if summary else ""))
    return MCSDocument(statements=statements, prologue=prologue)


def _read_statement(
    scanner: _Scanner, leading_comments: list[str]
) -> tuple[Optional[MCSStatement], bool]:
    start = scanner.pos
    scanner.pos += 2  # consume '++'

    match = IDENT_RE.match(scanner.text, scanner.pos)
    if not match:
        scanner.pos = start + 2
        return None, True
    kind = match.group(0).upper()
    scanner.pos = match.end()

    name: Optional[str] = None
    operands: dict[str, list[str]] = {}
    flags: list[str] = []
    inline_comments: list[str] = []
    pending_ident: Optional[str] = None
    clean_end = False

    while scanner.pos < scanner.length:
        char = scanner.text[scanner.pos]

        if char == "/" and scanner.starts_with("/*"):
            comment = scanner.read_comment()
            if comment:
                inline_comments.append(comment)
            continue

        if char == "+" and scanner.starts_with("++"):
            # A new statement started before this one was terminated.
            break

        if char == "(":
            keyword = pending_ident
            pending_ident = None
            inner = scanner.read_group()
            if keyword is None:
                if name is None:
                    values = split_operand_list(inner)
                    name = values[0] if values else ""
                    if len(values) > 1:
                        operands.setdefault(kind, []).extend(values[1:])
                else:
                    operands.setdefault(kind, []).extend(split_operand_list(inner))
            elif keyword in FREE_TEXT_KEYWORDS:
                operands.setdefault(keyword, []).append(inner.strip())
            else:
                operands.setdefault(keyword, []).extend(split_operand_list(inner))
            continue

        if char == ".":
            scanner.pos += 1
            clean_end = True
            break

        if char in "'\"":
            quote = char
            end = scanner.text.find(quote, scanner.pos + 1)
            scanner.pos = scanner.length if end == -1 else end + 1
            continue

        identifier = IDENT_RE.match(scanner.text, scanner.pos)
        if identifier:
            if pending_ident:
                flags.append(pending_ident)
            pending_ident = identifier.group(0).upper()
            scanner.pos = identifier.end()
            continue

        scanner.pos += 1

    if pending_ident:
        flags.append(pending_ident)

    raw = scanner.text[start : scanner.pos]
    statement = MCSStatement(
        kind=kind,
        name=name,
        operands=operands,
        flags=flags,
        leading_comments=list(leading_comments),
        inline_comments=inline_comments,
        record_start=scanner.record_at(start) + 1,
        record_end=scanner.record_at(max(scanner.pos - 1, start)) + 1,
        raw=raw[:MAX_RAW_CHARS],
    )
    return statement, clean_end
