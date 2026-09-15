"""EBCDIC / ASCII detection for SMP/E metadata members.

SMPPTFIN, SMPMCS and HOLDDATA come straight off z/OS and are therefore usually
EBCDIC (cp037 in the US, cp500 in most of EMEA, cp1047 for Unix System
Services).  Occasionally a package has already been converted to ASCII by the
distribution chain.

Rather than guessing from byte statistics alone we decode with every candidate
codec and *look for real SMP/E syntax*.  The encoding that produces the most
MCS tokens wins, which is both fast and extremely reliable - random bytes
never produce ``++PTF(``.
"""

from __future__ import annotations

from typing import Iterable, Optional

from . import ebcdic
from .errors import EncodingError
from .logging_util import AnalysisLog
from .models import EncodingGuess

# cp1047 is not part of the python standard library; make it available.
ebcdic.register()

#: Tried in this order; ties are broken by this order as well.
CANDIDATE_ENCODINGS: tuple[str, ...] = (
    "cp037",   # EBCDIC US/Canada - the SMP/E default
    "cp500",   # EBCDIC International
    "cp1047",  # EBCDIC Open Systems (z/OS Unix)
    "cp273",   # EBCDIC Germany/Austria
    "cp870",   # EBCDIC Central Europe
    "utf-8",
    "latin-1",
)

#: Statements and keywords that only appear in genuine SMP/E MCS input.
SMPE_TOKENS: tuple[str, ...] = (
    "++PTF(",
    "++VER(",
    "++APAR(",
    "++HOLD(",
    "++USERMOD(",
    "++FUNCTION(",
    "++MOD(",
    "++SRC(",
    "++MAC(",
    "++ZAP(",
    "++IF ",
    "++JCLIN",
    "++RELEASE(",
    "FMID(",
    "PRE(",
    "SUP(",
    "REQ(",
    "DISTLIB(",
    "RELFILE(",
    "REWORK(",
    "REASON(",
)

_PRINTABLE_EXTRA = set(" \t\r\n")


#: Below this share of printable characters a member is treated as binary
#: instead of being decoded into mojibake.
MIN_PRINTABLE_RATIO = 0.85


def _printable_ratio(text: str) -> tuple[float, int]:
    if not text:
        return 0.0, 0
    printable = 0
    replacements = 0
    for char in text:
        if char == "�":
            replacements += 1
        elif char.isprintable() or char in _PRINTABLE_EXTRA:
            printable += 1
    return printable / len(text), replacements


def score_encoding(data: bytes, encoding: str, sample_bytes: int = 256 * 1024) -> EncodingGuess:
    """Score how plausible *encoding* is for *data*."""
    sample = data[:sample_bytes]
    try:
        text = sample.decode(encoding, errors="replace")
    except LookupError as exc:  # pragma: no cover - unknown codec name
        raise EncodingError(f"Unknown encoding '{encoding}'.", detail=str(exc)) from exc

    upper = text.upper()
    token_hits = sum(upper.count(token) for token in SMPE_TOKENS)
    ratio, replacements = _printable_ratio(text)

    # Token evidence dominates; readability is the tie breaker; unmappable
    # bytes are a strong negative signal.
    score = token_hits * 10.0 + ratio * 25.0 - (replacements / max(len(text), 1)) * 50.0
    return EncodingGuess(
        encoding=encoding,
        score=score,
        token_hits=token_hits,
        printable_ratio=ratio,
        replacement_chars=replacements,
        sample=text[:400],
    )


def detect_encoding(
    data: bytes,
    candidates: Iterable[str] = CANDIDATE_ENCODINGS,
    log: Optional[AnalysisLog] = None,
    member: str = "",
) -> tuple[EncodingGuess, list[EncodingGuess]]:
    """Pick the best encoding for *data*.

    Returns ``(winner, all_candidates_sorted)``.  Raises :class:`EncodingError`
    only when the data cannot be read as text in any candidate encoding.
    """
    log = AnalysisLog("encoding") if log is None else log
    if not data:
        raise EncodingError("The SMP/E member is empty - there is nothing to decode.")

    requested = list(candidates)
    candidate_list = [name for name in requested if ebcdic.available(name)]
    unavailable = [name for name in requested if name not in candidate_list]
    if unavailable:
        log.debug("Codec(s) not available in this interpreter: " + ", ".join(unavailable))
    if not candidate_list:
        raise EncodingError(
            "None of the candidate encodings is available in this python installation.",
            detail="Tried: " + ", ".join(requested),
        )

    guesses = [score_encoding(data, name) for name in candidate_list]
    order = {name: position for position, name in enumerate(candidate_list)}
    ranked = sorted(guesses, key=lambda g: (-g.score, order[g.encoding]))
    winner = ranked[0]

    label = f"'{member}': " if member else ""
    if winner.token_hits == 0:
        # No SMP/E syntax anywhere - fall back to readability but say so.
        readable = max(ranked, key=lambda g: (g.printable_ratio, -order[g.encoding]))
        if readable.printable_ratio < MIN_PRINTABLE_RATIO:
            raise EncodingError(
                f"{label}the member does not look like SMP/E text in any supported encoding.",
                detail="Tried: " + ", ".join(candidate_list),
                hint="The file may be binary (a load module or RELFILE) rather than SMPPTFIN.",
            )
        winner = readable
        log.warning(
            f"{label}no SMP/E keywords found; falling back to '{winner.encoding}' "
            f"({winner.printable_ratio * 100:.0f}% printable)."
        )
    else:
        log.info(
            f"{label}encoding detected as '{winner.encoding}' "
            f"({winner.token_hits} SMP/E tokens, {winner.printable_ratio * 100:.0f}% printable)"
        )
        runner_up = ranked[1] if len(ranked) > 1 else None
        if runner_up is not None:
            log.debug(
                f"{label}runner up '{runner_up.encoding}' scored {runner_up.score:.1f} "
                f"vs {winner.score:.1f}"
            )

    return winner, ranked


def decode(data: bytes, encoding: str) -> str:
    """Decode *data*, never raising: unmappable bytes become U+FFFD."""
    return data.decode(encoding, errors="replace")
