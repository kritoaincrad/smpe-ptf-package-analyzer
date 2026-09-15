"""GIMFAF.XML / GIMPAF.XML (GIMZIP package description) parsing.

These files describe what the package contains: the archives, their file
names, sizes and hashes, and the SMP/E order information.  The schema differs
between z/OS levels and vendors, so the parser is deliberately generic: every
element becomes one row of ``tag`` plus its attributes, with a couple of well
known attribute names normalized for display.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Optional

from .logging_util import AnalysisLog

_EBCDIC_CANDIDATES = ("cp037", "cp500", "cp1047")
_NAME_KEYS = ("name", "filename", "archid", "id", "member", "dsname")


def _decode_xml(data: bytes) -> str:
    """GIMZIP XML is normally ASCII, but EBCDIC copies do exist."""
    from .compression import looks_like_xml

    detected = looks_like_xml(data[:96])
    if detected:
        return data.decode(detected, errors="replace")
    if b"<" in data[:512]:
        for encoding in ("utf-8", "latin-1"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
    for encoding in _EBCDIC_CANDIDATES:
        text = data.decode(encoding, errors="replace")
        if "<" in text[:512]:
            return text
    return data.decode("latin-1", errors="replace")


def _unpad_records(text: str, record_length: int = 80) -> str:
    """Drop the blank padding of a fixed length record image.

    A GIMFAF.XML copied off a RECFM=FB data set carries the XML in 80 byte
    records padded with blanks, which puts runs of spaces in the middle of
    tags and makes the document unparseable.
    """
    if len(text) % record_length:
        return text
    records = [text[offset : offset + record_length] for offset in range(0, len(text), record_length)]
    return "".join(record.rstrip() for record in records)


def parse_gimfaf(data: bytes, member: str, log: Optional[AnalysisLog] = None) -> list[dict[str, Any]]:
    """Flatten a GIMFAF/GIMPAF XML document into display rows."""
    log = AnalysisLog("gimfaf") if log is None else log
    text = _decode_xml(data).lstrip("﻿").strip()
    if not text:
        log.warning(f"'{member}' is empty.")
        return []

    root = None
    attempts = [("as decoded", text), ("without record padding", _unpad_records(text))]
    first_error: Optional[ET.ParseError] = None
    for label, candidate in attempts:
        if not candidate:
            continue
        try:
            root = ET.fromstring(candidate)
            if label != "as decoded":
                log.info(f"'{member}': parsed after removing fixed length record padding.")
            break
        except ET.ParseError as exc:
            first_error = first_error or exc
            continue

    if root is None:
        position = getattr(first_error, "position", None)
        where = f" at line {position[0]}, column {position[1]}" if position else ""
        log.warning(
            f"'{member}' is not well formed XML and was skipped{where}.",
            detail=f"{first_error}\nfirst 200 characters: {text[:200]!r}",
        )
        return []

    rows: list[dict[str, Any]] = []

    def walk(element: ET.Element, path: str, depth: int) -> None:
        tag = element.tag.rsplit("}", 1)[-1]
        current = f"{path}/{tag}" if path else tag
        attributes = {key.rsplit("}", 1)[-1]: value for key, value in element.attrib.items()}
        value = (element.text or "").strip()
        # Every element is listed - one with no attributes still shows the
        # structure of the document.
        name = next((attributes[key] for key in _NAME_KEYS if key in attributes), "")
        rows.append(
            {
                "Element": tag,
                "Name": name,
                "Path": current,
                "Depth": depth,
                "Value": value[:200],
                **{f"@{key}": val for key, val in attributes.items()},
            }
        )
        for child in element:
            walk(child, current, depth + 1)

    walk(root, "", 0)
    log.info(f"'{member}': {len(rows)} XML element(s) from <{root.tag.rsplit('}', 1)[-1]}>")
    return rows
