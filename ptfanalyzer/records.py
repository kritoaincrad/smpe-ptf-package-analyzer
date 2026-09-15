"""Turning a decoded SMP/E member into logical 80 byte card images.

Data sets coming off z/OS are RECFM=FB LRECL=80 and frequently arrive with no
line terminators at all - just one long stream of 80 byte records.  SMP/E also
reserves columns 73-80 for sequence numbers and ignores them, so a parser that
reads all 80 columns will happily glue a sequence number onto an operand.

A real SMPPTFIN additionally carries inline binary data (``++DATA`` blocks,
RELFILE content).  Those bytes decode to characters that look like line
terminators - 0x25 is a line feed in EBCDIC - which would shred the member into
hundreds of thousands of bogus records.  :func:`split_records` detects that and
falls back to fixed length records.
"""

from __future__ import annotations

import re
from typing import Optional

from .logging_util import AnalysisLog
from .models import RecordSet

RECORD_LENGTH = 80
DATA_COLUMNS = 72

#: Above this share of unprintable characters a member is inline data, not text.
BINARY_THRESHOLD = 0.05

_SEQUENCE_RE = re.compile(r"^[A-Z0-9#$@. ]{0,8}$")
_NUL = chr(0)


def looks_like_sequence_field(value: str) -> bool:
    """Columns 73-80 normally hold blanks or a sequence number."""
    stripped = value.strip()
    if not stripped:
        return True
    return bool(_SEQUENCE_RE.match(value.upper())) and any(c.isdigit() for c in stripped)


def strip_padding(record: str) -> str:
    """Drop NUL padding and trailing blanks from one record."""
    return record.replace(_NUL, "").rstrip()


def binary_share(text: str, sample: int = 200_000) -> float:
    """Fraction of characters that no text member would contain."""
    head = text[:sample]
    if not head:
        return 0.0
    printable = sum(1 for char in head if char.isprintable() or char in " \t\r\n")
    return 1.0 - printable / len(head)


def split_records(
    text: str,
    honor_sequence_columns: bool = True,
    record_length: int = RECORD_LENGTH,
    data_columns: int = DATA_COLUMNS,
    log: Optional[AnalysisLog] = None,
    source: str = "",
) -> RecordSet:
    """Split *text* into logical records.

    * If the text has line terminators they define the records - unless the
      member is an exact multiple of ``record_length`` and looks like card
      images with inline data, in which case the terminators are data.
    * Otherwise the text is cut into fixed ``record_length`` chunks.

    Columns beyond ``data_columns`` are dropped for card image records, exactly
    as SMP/E does, unless *honor_sequence_columns* is disabled.

    NUL padding is removed per record, never before the layout decision: a
    member full of inline binary data is only recognizable as fixed length
    records while its original length is intact.
    """
    log = AnalysisLog("records") if log is None else log
    label = source or "Member"

    def cut_fixed(payload: str) -> list[str]:
        return [
            payload[offset : offset + record_length]
            for offset in range(0, len(payload), record_length)
        ]

    if "\n" in text or "\r" in text:
        raw_records = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if raw_records and raw_records[-1] == "":
            raw_records.pop()
        layout = "lines"

        over_long = sum(1 for record in raw_records if len(record) > record_length)
        share = binary_share(text)
        if len(text) % record_length == 0 and (over_long or share > BINARY_THRESHOLD):
            reason = (
                f"{over_long:,} line(s) are longer than {record_length} characters"
                if over_long
                else f"{share * 100:.0f}% of the characters are not printable"
            )
            log.warning(
                f"{label}: {reason} and the member is an exact multiple of {record_length} "
                "bytes - reading it as fixed length records instead (the line breaks are "
                "inline data, not structure)."
            )
            raw_records = cut_fixed(text)
            layout = "fixed80"
    else:
        raw_records = cut_fixed(text)
        layout = "fixed80"
        remainder = len(text) % record_length
        if remainder:
            log.warning(
                f"{label}: length {len(text):,} is not a multiple of {record_length}; "
                f"the last record holds {remainder} character(s)."
            )

    truncated = False
    if honor_sequence_columns and raw_records:
        card_images = [r for r in raw_records if len(r) >= record_length]
        is_card_layout = layout == "fixed80" or len(card_images) >= max(1, len(raw_records) // 2)
        if is_card_layout:
            sample = [r[data_columns:record_length] for r in card_images[:500]]
            odd = [s for s in sample if not looks_like_sequence_field(s)]
            if sample and len(odd) > len(sample) * 0.3:
                log.warning(
                    f"{label}: columns {data_columns + 1}-{record_length} do not look like "
                    "sequence numbers, but they are ignored anyway (SMP/E rule)."
                )
            raw_records = [r[:data_columns] if len(r) > data_columns else r for r in raw_records]
            truncated = True

    records = [strip_padding(record) for record in raw_records]
    log.info(
        f"{label}: {len(records):,} record(s), layout '{layout}'"
        + (", columns 73-80 ignored" if truncated else "")
    )
    return RecordSet(records=records, layout=layout, truncated_columns=truncated, source=source)
