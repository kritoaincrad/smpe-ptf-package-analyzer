"""Stand-alone HOLDDATA member parsing.

HOLDDATA uses the same MCS syntax as SMPPTFIN, so the work is: detect the
encoding, cut the 80 byte records, parse the statements and keep the
``++HOLD`` / ``++RELEASE`` entries.
"""

from __future__ import annotations

from typing import Optional

from .encoding import decode, detect_encoding
from .logging_util import AnalysisLog
from .mcs import parse_statements
from .models import HoldEntry
from .progress import NULL_PROGRESS, Progress
from .records import split_records
from .smpe import extract_holds


def parse_holddata(
    data: bytes,
    member: str,
    log: Optional[AnalysisLog] = None,
    encoding_override: Optional[str] = None,
    progress: Optional[Progress] = None,
) -> list[HoldEntry]:
    log = AnalysisLog("holddata") if log is None else log
    progress = progress or NULL_PROGRESS
    progress.note(f"Reading HOLDDATA: {member.rsplit('/', 1)[-1]}")
    if not data.strip():
        log.warning(f"'{member}' is empty.")
        return []

    if encoding_override:
        encoding = encoding_override
    else:
        winner, _ = detect_encoding(data, log=log, member=member)
        encoding = winner.encoding

    text = decode(data, encoding)
    record_set = split_records(text, log=log, source=member)
    document = parse_statements(record_set.records, log=log, source=member)
    holds = extract_holds(document.statements, source=member)

    errors = sum(1 for hold in holds if hold.is_error_hold)
    log.info(
        f"'{member}': {len(holds)} HOLD/RELEASE statement(s)"
        + (f", {errors} ERROR hold(s) (PE)" if errors else "")
    )
    return holds
