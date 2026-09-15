"""Unix ``.Z`` (LZW / "compress") handling with a layered fallback strategy.

The module provides

* :func:`detect_format` - magic byte inspection with an explicit, readable
  error when the stream is not a ``.Z`` file,
* :func:`unlzw` / :func:`compress_lzw` - a self contained, dependency free
  implementation of the Unix compress format (RFC-less, but compatible with
  ``compress``/``uncompress``/``gzip -d``),
* :func:`decompress_stream` - the production entry point that tries several
  decoders in order and never lets a single decoder failure kill the run.

Decoder order (first success wins)::

    1. unlzw3            (optional third party pure python decoder)
    2. built-in decoder  (this module - always available)
    3. 7-Zip             (7z / 7za / 7zz, Windows + Linux)
    4. uncompress / gzip (typically available on Linux and in Git Bash)

For very large streams the external tools are much faster than any pure python
decoder, so ``prefer_external_for_large`` moves them to the front once the
input exceeds ``external_threshold_mb``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

from .errors import DecompressionError, FormatError
from .logging_util import AnalysisLog
from .models import DecompressionResult, StreamFormat
from .progress import NULL_PROGRESS, Progress

MAGIC_COMPRESS = b"\x1f\x9d"
INIT_BITS = 9
FIRST = 257
CLEAR = 256
FLUSH_SIZE = 4 * 1024 * 1024

ProgressFn = Optional[Callable[[int, int], None]]


# ---------------------------------------------------------------------------
# format detection
# ---------------------------------------------------------------------------


def detect_format(head: bytes) -> StreamFormat:
    """Identify the container format from the first bytes of a stream."""
    magic_hex = " ".join(f"{b:02X}" for b in head[:4])

    if head[:2] == MAGIC_COMPRESS:
        return StreamFormat("unix_compress", "Unix compress (.Z / LZW)", magic_hex, True)
    if head[:2] == b"\x1f\x8b":
        return StreamFormat("gzip", "gzip (.gz)", magic_hex, True)
    if head[:3] == b"BZh":
        return StreamFormat("bzip2", "bzip2 (.bz2)", magic_hex, True)
    if head[:6] == b"\xfd7zXZ\x00":
        return StreamFormat("xz", "xz (.xz)", magic_hex, True)
    if head[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
        return StreamFormat("zip", "ZIP archive", magic_hex, True)
    if len(head) >= 262 and head[257:262] in (b"ustar", b"usta\x00"):
        return StreamFormat("tar", "TAR/PAX archive (uncompressed)", magic_hex, False)
    if b"INMR01" in head[:16] or bytes([0xC9, 0xD5, 0xD4, 0xD9, 0xF0, 0xF1]) in head[:16]:
        return StreamFormat("xmit", "TSO XMIT / TRANSMIT data set", magic_hex, False)

    xml_encoding = looks_like_xml(head)
    if xml_encoding:
        label = "XML document" + (" (EBCDIC)" if xml_encoding.startswith("cp") else "")
        return StreamFormat("xml", label, magic_hex, False)

    return StreamFormat("unknown", "Unrecognized", magic_hex, False)


#: ``<`` is 0x3C in ASCII but 0x4C in EBCDIC, which is why a GIMPAF.XML copied
#: straight off z/OS looks like binary noise to a naive check.
_XML_START_RE = re.compile(r"^<(\?xml|[A-Za-z_][\w.:-]*)")


def looks_like_xml(head: bytes) -> Optional[str]:
    """Return the encoding an XML document appears to be in, or ``None``."""
    for encoding in ("utf-8", "latin-1", "cp037", "cp500"):
        try:
            text = head[:96].decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        candidate = text.replace("\ufeff", "", 1).lstrip()
        if _XML_START_RE.match(candidate):
            return encoding
    return None


def read_head(path: Path, size: int = 512) -> bytes:
    with open(path, "rb") as handle:
        return handle.read(size)


def require_compress_magic(path: Path) -> StreamFormat:
    """Validate the Unix ``.Z`` magic bytes, raising a readable error."""
    head = read_head(path)
    fmt = detect_format(head)
    if fmt.kind == "unix_compress":
        return fmt

    detected = " ".join(f"{b:02X}" for b in head[:2]) if head else "<empty file>"
    message = (
        "Invalid Unix .Z stream.\n"
        "Expected magic bytes: 1F 9D\n"
        f"Detected: {detected}"
    )
    hint = {
        "gzip": "The stream is gzip compressed - rename it to .gz or let the analyzer handle it automatically.",
        "tar": "The stream is already an uncompressed TAR/PAX archive; decompression is not needed.",
        "zip": "The stream is a ZIP archive, not an SMP/E .pax.Z package.",
        "xmit": "The stream looks like a TSO XMIT data set; unpack it with RECEIVE on z/OS first.",
        "unknown": "Check that every '.XofY' part was uploaded and joined in the correct numeric order, "
        "and that the files were transferred in BINARY mode (an ASCII/text FTP transfer corrupts them).",
    }.get(fmt.kind, f"Detected format: {fmt.label}.")
    raise FormatError(message, detail=f"Detected format: {fmt.label} (magic {fmt.magic_hex})", hint=hint)


# ---------------------------------------------------------------------------
# built-in LZW (Unix compress) decoder
# ---------------------------------------------------------------------------


@dataclass
class LZWHeader:
    max_bits: int
    block_mode: bool


def parse_lzw_header(data: bytes) -> LZWHeader:
    if len(data) < 3:
        raise DecompressionError(
            "The .Z stream is too short to contain a valid header.",
            detail=f"only {len(data)} byte(s) available, 3 required",
        )
    if data[:2] != MAGIC_COMPRESS:
        detected = " ".join(f"{b:02X}" for b in data[:2])
        raise DecompressionError(
            "Invalid Unix .Z stream.\nExpected magic bytes: 1F 9D\n" f"Detected: {detected}"
        )
    flags = data[2]
    max_bits = flags & 0x1F
    block_mode = bool(flags & 0x80)
    if not 9 <= max_bits <= 16:
        raise DecompressionError(
            f"Unsupported .Z compression width: {max_bits} bits (expected 9-16).",
            detail=f"header flag byte 0x{flags:02X}",
        )
    return LZWHeader(max_bits=max_bits, block_mode=block_mode)


def unlzw_to(
    data: bytes,
    write: Callable[[bytes], object],
    allow_partial: bool = True,
    progress: ProgressFn = None,
) -> tuple[int, bool]:
    """Decode a Unix compress stream, pushing plain bytes into *write*.

    Returns ``(bytes_written, truncated)``.  When *allow_partial* is true a
    stream that ends in the middle of a code (a frequent symptom of a missing
    or badly transferred part) yields whatever could be decoded plus
    ``truncated=True`` instead of raising.
    """
    header = parse_lzw_header(data)
    max_bits = header.max_bits
    block_mode = header.block_mode
    max_max_code = 1 << max_bits

    body = data[3:]
    total_bits = len(body) << 3

    prefix = [0] * max_max_code
    suffix = bytearray(max_max_code)
    for i in range(256):
        suffix[i] = i

    stack = bytearray(max_max_code + 512)
    stack_size = len(stack)

    n_bits = INIT_BITS
    max_code = (1 << n_bits) - 1
    free_ent = FIRST if block_mode else 256
    old_code = -1
    fin_char = 0
    bit_pos = 0
    group_base = 0
    written = 0
    truncated = False
    out = bytearray()

    while True:
        # Codes get one bit wider every time the dictionary outgrows the
        # current width.  The encoder pads the final group of the old width
        # to a whole number of "8 codes" groups, counted from the start of
        # that width section - hence group_base.
        if n_bits < max_bits and free_ent > max_code:
            bit_pos = _align(bit_pos, group_base, n_bits)
            group_base = bit_pos
            n_bits += 1
            max_code = (1 << n_bits) - 1

        if bit_pos + n_bits > total_bits:
            # A well formed stream ends with zero padding bits.  Anything else
            # left over means the last code was cut in half.  Only the bits
            # *after* bit_pos count - the rest of that byte is real data.
            tail = body[bit_pos >> 3 :]
            if tail and ((tail[0] >> (bit_pos & 7)) or any(tail[1:])):
                truncated = True
            break

        byte_index = bit_pos >> 3
        window = body[byte_index : byte_index + 3]
        if len(window) < 3:
            window = window + b"\x00" * (3 - len(window))
        code = (int.from_bytes(window, "little") >> (bit_pos & 7)) & ((1 << n_bits) - 1)
        bit_pos += n_bits

        if old_code == -1:
            if code >= 256:
                raise DecompressionError(
                    "Corrupt .Z stream: the first code is not a literal character.",
                    detail=f"first code = {code}",
                )
            fin_char = code
            old_code = code
            out.append(code)
            written += 1
            continue

        if block_mode and code == CLEAR:
            prefix = [0] * max_max_code
            free_ent = 256
            bit_pos = _align(bit_pos, group_base, n_bits)
            group_base = bit_pos
            n_bits = INIT_BITS
            max_code = (1 << n_bits) - 1
            continue

        in_code = code
        stack_pointer = stack_size

        if code > free_ent:
            if allow_partial:
                truncated = True
                break
            raise DecompressionError(
                "Corrupt .Z stream: code outside the dictionary.",
                detail=f"code {code} > free entry {free_ent} at bit {bit_pos}",
            )
        if code == free_ent:
            # KwKwK - the classic LZW special case.
            stack_pointer -= 1
            stack[stack_pointer] = fin_char
            code = old_code

        while code >= 256:
            if stack_pointer <= 0:
                if allow_partial:
                    truncated = True
                    break
                raise DecompressionError(
                    "Corrupt .Z stream: dictionary chain is longer than the dictionary.",
                    detail=f"code {code}",
                )
            stack_pointer -= 1
            stack[stack_pointer] = suffix[code]
            code = prefix[code]
        if truncated:
            break

        fin_char = suffix[code]
        stack_pointer -= 1
        stack[stack_pointer] = fin_char

        chunk = stack[stack_pointer:]
        out += chunk
        written += len(chunk)

        if free_ent < max_max_code:
            prefix[free_ent] = old_code
            suffix[free_ent] = fin_char
            free_ent += 1
        old_code = in_code

        if len(out) >= FLUSH_SIZE:
            write(bytes(out))
            out.clear()
            if progress is not None:
                progress(bit_pos >> 3, len(body))

    if out:
        write(bytes(out))
    if progress is not None:
        progress(len(body), len(body))
    return written, truncated


def _align(bit_pos: int, group_base: int, n_bits: int) -> int:
    """Round *bit_pos* up to the next 8 code group boundary.

    Groups are counted from *group_base*, the first bit written at the current
    code width - not from the start of the stream.
    """
    group = n_bits << 3
    offset = (bit_pos - group_base) % group
    return bit_pos + ((group - offset) % group)


def unlzw(data: bytes, allow_partial: bool = True) -> bytes:
    """Convenience wrapper returning the decoded bytes in memory."""
    buffer = bytearray()
    unlzw_to(data, buffer.extend, allow_partial=allow_partial)
    return bytes(buffer)


# ---------------------------------------------------------------------------
# built-in LZW encoder
# ---------------------------------------------------------------------------


def compress_lzw(data: bytes, max_bits: int = 16, block_mode: bool = True) -> bytes:
    """Produce a Unix compress (``.Z``) stream.

    This mirrors :func:`unlzw_to` exactly and produces streams compatible
    with standard ``gzip -d`` / ``uncompress`` implementations.

    ``max_bits=9`` is a degenerate configuration (the dictionary can never
    grow past the initial code width and ``compress`` itself overruns its
    own tables there); real packages use 12-16 bits, 16 being the default.
    """
    if not 9 <= max_bits <= 16:
        raise ValueError("max_bits must be between 9 and 16")

    out = bytearray(MAGIC_COMPRESS)
    out.append(max_bits | (0x80 if block_mode else 0x00))
    if not data:
        return bytes(out)

    max_max_code = 1 << max_bits
    table: dict[tuple[int, int], int] = {}
    free_ent = FIRST if block_mode else 256
    n_bits = INIT_BITS

    bit_buffer = 0
    bit_count = 0
    bits_written = 0
    group_base = 0

    def emit(code: int) -> None:
        nonlocal bit_buffer, bit_count, bits_written
        bit_buffer |= code << bit_count
        bit_count += n_bits
        bits_written += n_bits
        while bit_count >= 8:
            out.append(bit_buffer & 0xFF)
            bit_buffer >>= 8
            bit_count -= 8

    def pad_group() -> None:
        """Pad up to a whole 8 code group, counted from the width change."""
        nonlocal bit_buffer, bit_count, bits_written, group_base
        group = n_bits << 3
        while (bits_written - group_base) % group:
            bit_count += 1
            bits_written += 1
            if bit_count >= 8:
                out.append(bit_buffer & 0xFF)
                bit_buffer >>= 8
                bit_count -= 8
        group_base = bits_written

    def widen_if_needed() -> None:
        """The decoder is always one dictionary entry behind the encoder, so
        the encoder widens as soon as ``free_ent`` passes ``1 << n_bits``."""
        nonlocal n_bits
        if n_bits < max_bits and free_ent > (1 << n_bits):
            pad_group()
            n_bits += 1

    ent = data[0]
    for char in data[1:]:
        key = (ent, char)
        found = table.get(key)
        if found is not None:
            ent = found
            continue
        emit(ent)
        ent = char
        if free_ent < max_max_code:
            table[key] = free_ent
            free_ent += 1
            widen_if_needed()
        elif block_mode:
            # Dictionary is full: tell the decoder to start over.
            table.clear()
            free_ent = FIRST
            emit(CLEAR)
            pad_group()
            n_bits = INIT_BITS

    emit(ent)
    if bit_count:
        out.append(bit_buffer & 0xFF)
    return bytes(out)


# ---------------------------------------------------------------------------
# external decoders
# ---------------------------------------------------------------------------


SEVENZIP_CANDIDATES = [
    "7z",
    "7za",
    "7zz",
    r"C:\Program Files\7-Zip\7z.exe",
    r"C:\Program Files (x86)\7-Zip\7z.exe",
]


def find_sevenzip() -> Optional[str]:
    for candidate in SEVENZIP_CANDIDATES:
        resolved = shutil.which(candidate) if os.sep not in candidate else (candidate if os.path.exists(candidate) else None)
        if resolved:
            return resolved
    return None


def find_uncompress() -> Optional[tuple[str, list[str]]]:
    for name, args in (("uncompress", ["-c"]), ("gzip", ["-d", "-c"]), ("zcat", [])):
        path = shutil.which(name)
        if path:
            return path, args
    return None


def has_unlzw3() -> bool:
    try:  # pragma: no cover - depends on the environment
        import unlzw3  # noqa: F401

        return True
    except Exception:
        return False


def available_decoders() -> list[dict]:
    """Report which decoders this machine can use (shown in the UI sidebar)."""
    seven = find_sevenzip()
    external = find_uncompress()
    return [
        {"name": "unlzw3", "kind": "python", "available": has_unlzw3(), "path": "python package"},
        {"name": "built-in LZW decoder", "kind": "python", "available": True, "path": "ptfanalyzer.compression"},
        {"name": "7-Zip", "kind": "external", "available": bool(seven), "path": seven or "-"},
        {
            "name": "uncompress/gzip",
            "kind": "external",
            "available": bool(external),
            "path": external[0] if external else "-",
        },
    ]


def _run_external(command: list[str], destination: Path, log: AnalysisLog) -> int:
    log.debug("Running: " + " ".join(command))
    with open(destination, "wb") as out:
        process = subprocess.Popen(command, stdout=out, stderr=subprocess.PIPE)
        _, stderr = process.communicate()
    written = destination.stat().st_size if destination.exists() else 0
    if process.returncode != 0:
        message = (stderr or b"").decode("utf-8", "replace").strip()
        raise DecompressionError(
            f"External decoder exited with code {process.returncode}.",
            detail=message or "no stderr output",
        )
    return written


# ---------------------------------------------------------------------------
# decoder orchestration
# ---------------------------------------------------------------------------


@dataclass
class DecompressOptions:
    allow_partial: bool = True
    prefer_external_for_large: bool = True
    external_threshold_mb: int = 96
    only: Optional[str] = None  # force one decoder (debugging)
    max_output_bytes: int = 16 * 1024 * 1024 * 1024
    max_expansion_ratio: int = 2000


def _decoder_unlzw3(
    source: Path,
    destination: Path,
    options: DecompressOptions,
    log: AnalysisLog,
    progress: Optional[Progress] = None,
) -> tuple[int, bool]:
    import unlzw3  # type: ignore

    data = unlzw3.unlzw(source)
    destination.write_bytes(bytes(data))
    return len(data), False


def _decoder_builtin(
    source: Path,
    destination: Path,
    options: DecompressOptions,
    log: AnalysisLog,
    progress: Optional[Progress] = None,
) -> tuple[int, bool]:
    data = source.read_bytes()
    sink = (progress or NULL_PROGRESS).byte_sink(len(data), "Decompressing")
    with open(destination, "wb") as out:
        written, truncated = unlzw_to(
            data, out.write, allow_partial=options.allow_partial, progress=sink
        )
    return written, truncated


def _decoder_sevenzip(
    source: Path,
    destination: Path,
    options: DecompressOptions,
    log: AnalysisLog,
    progress: Optional[Progress] = None,
) -> tuple[int, bool]:
    tool = find_sevenzip()
    if not tool:
        raise DecompressionError("7-Zip was not found on this machine.")
    written = _run_external([tool, "x", "-so", "-bso0", "-bsp0", str(source)], destination, log)
    return written, False


def _decoder_uncompress(
    source: Path,
    destination: Path,
    options: DecompressOptions,
    log: AnalysisLog,
    progress: Optional[Progress] = None,
) -> tuple[int, bool]:
    found = find_uncompress()
    if not found:
        raise DecompressionError("Neither 'uncompress' nor 'gzip' was found on this machine.")
    tool, args = found
    written = _run_external([tool, *args, str(source)], destination, log)
    return written, False


DECODERS: list[tuple[str, str, Callable]] = [
    ("unlzw3", "python", _decoder_unlzw3),
    ("built-in LZW decoder", "python", _decoder_builtin),
    ("7-Zip", "external", _decoder_sevenzip),
    ("uncompress/gzip", "external", _decoder_uncompress),
]


def _decoder_order(source_size: int, options: DecompressOptions) -> list[tuple[str, str, Callable]]:
    decoders = list(DECODERS)
    if options.only:
        decoders = [d for d in decoders if d[0] == options.only]
        if not decoders:
            raise DecompressionError(f"Unknown decoder '{options.only}'.")
        return decoders
    if options.prefer_external_for_large and source_size > options.external_threshold_mb * 1024 * 1024:
        decoders.sort(key=lambda item: 0 if item[1] == "external" else 1)
    return decoders


def decompress_stream(
    source: Path,
    destination: Path,
    options: Optional[DecompressOptions] = None,
    log: Optional[AnalysisLog] = None,
    progress: Optional[Progress] = None,
) -> DecompressionResult:
    """Decompress a ``.Z`` file using the first decoder that succeeds."""
    options = options or DecompressOptions()
    log = AnalysisLog("decompress") if log is None else log
    progress = progress or NULL_PROGRESS

    require_compress_magic(source)
    header = parse_lzw_header(read_head(source, 3))
    source_size = source.stat().st_size
    log.info(
        f"Unix .Z stream accepted: {source_size:,} bytes, "
        f"{header.max_bits}-bit codes, block mode {'on' if header.block_mode else 'off'}"
    )

    attempts: list[dict] = []
    started = time.time()
    order = _decoder_order(source_size, options)
    log.debug("Decoder order: " + " -> ".join(name for name, _, _ in order))

    for position, (name, kind, func) in enumerate(order):
        attempt_started = time.time()
        try:
            if name == "unlzw3" and not has_unlzw3():
                raise DecompressionError("unlzw3 is not installed.")
            progress.begin_stage(
                "decompress", f"Decompressing with '{name}'", float(source_size)
            )
            written, truncated = func(source, destination, options, log, progress)
            allowed = min(options.max_output_bytes, max(source_size * options.max_expansion_ratio, 256 * 1024 * 1024))
            if written > allowed:
                raise DecompressionError(
                    "Decompressed output exceeded the configured safety limit.",
                    detail=f"output={written:,} bytes, limit={allowed:,} bytes",
                )
            progress.update(source_size, source_size, f"Decompressed {written:,} bytes")
            if written == 0:
                raise DecompressionError("The decoder produced no output.")
            elapsed = time.time() - attempt_started
            attempts.append({"decoder": name, "result": "OK", "bytes": written, "seconds": round(elapsed, 2)})
            if truncated:
                log.warning(
                    f"'{name}' decoded {written:,} bytes but the stream ends in the middle of a code - "
                    "the package is probably truncated or a part is missing.",
                )
            log.success(f"Decompressed with '{name}': {written:,} bytes in {elapsed:.2f}s")
            return DecompressionResult(
                method=name,
                output_path=destination,
                input_size=source_size,
                output_size=written,
                truncated=truncated,
                attempts=attempts,
                duration_s=time.time() - started,
            )
        except Exception as exc:  # noqa: BLE001 - deliberate: try the next decoder
            elapsed = time.time() - attempt_started
            detail = exc.message if isinstance(exc, DecompressionError) else f"{type(exc).__name__}: {exc}"
            attempts.append({"decoder": name, "result": "FAILED", "bytes": 0, "seconds": round(elapsed, 2), "error": detail})
            is_last = position == len(order) - 1
            if is_last:
                log.error(f"'{name}' failed: {detail}", exc=exc)
            else:
                log.warning(
                    f"'{name}' failed: {detail}. Trying fallback decoder "
                    f"'{order[position + 1][0]}'...",
                    exc=exc,
                )
            if destination.exists():
                try:
                    destination.unlink()
                except OSError:  # pragma: no cover - Windows file locks
                    pass

    summary = "\n".join(
        f"  - {a['decoder']}: {a.get('error', 'failed')}" for a in attempts
    )
    raise DecompressionError(
        "The .Z package could not be decompressed. Every available decoder failed.",
        detail="Decoder attempts:\n" + summary,
        hint=(
            "Most common causes: a missing '.XofY' part, parts joined in the wrong order, "
            "or a file transferred in text/ASCII mode instead of binary. "
            "Installing 7-Zip adds another decoder to the fallback chain."
        ),
    )
