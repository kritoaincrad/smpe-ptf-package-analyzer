"""EBCDIC code pages that the python standard library does not ship.

Python has ``cp037``, ``cp273``, ``cp500`` and friends, but **not** ``cp1047``
- the Open Systems / z/OS Unix code page that a lot of SMP/E metadata is
written in.  Rather than depend on an extra package we register it here.

IBM-1047 is IBM-037 with three pairs of code points exchanged::

    0x5F  U+00AC NOT SIGN          <->  0xB0  U+005E CIRCUMFLEX ACCENT
    0xBA  U+005B LEFT SQUARE BRACKET  <->  0xAD  U+00DD Y WITH ACUTE
    0xBB  U+005D RIGHT SQUARE BRACKET <->  0xBD  U+00A8 DIAERESIS

which is why z/OS C source code uses X'AD' and X'BD' for ``[`` and ``]``.
Everything a SMP/E statement is made of (letters, digits, ``+ ( ) , . / * '``)
is identical in both code pages, so the difference only ever shows up inside
descriptive text.
"""

from __future__ import annotations

import codecs

#: (byte_a, byte_b) pairs whose meanings are exchanged relative to cp037.
CP1047_SWAPS: tuple[tuple[int, int], ...] = ((0x5F, 0xB0), (0xBA, 0xAD), (0xBB, 0xBD))

_ALIASES = {"cp1047", "ibm1047", "ibm-1047", "1047", "cp-1047"}


def _build_decoding_table() -> str:
    table = list(bytes(range(256)).decode("cp037"))
    for first, second in CP1047_SWAPS:
        table[first], table[second] = table[second], table[first]
    return "".join(table)


DECODING_TABLE = _build_decoding_table()
ENCODING_TABLE = codecs.charmap_build(DECODING_TABLE)


class _Codec(codecs.Codec):
    def encode(self, input, errors="strict"):  # noqa: A002 - codec API
        return codecs.charmap_encode(input, errors, ENCODING_TABLE)

    def decode(self, input, errors="strict"):  # noqa: A002 - codec API
        return codecs.charmap_decode(input, errors, DECODING_TABLE)


class _IncrementalEncoder(codecs.IncrementalEncoder):
    def encode(self, input, final=False):  # noqa: A002 - codec API
        return codecs.charmap_encode(input, self.errors, ENCODING_TABLE)[0]


class _IncrementalDecoder(codecs.IncrementalDecoder):
    def decode(self, input, final=False):  # noqa: A002 - codec API
        return codecs.charmap_decode(input, self.errors, DECODING_TABLE)[0]


class _StreamWriter(_Codec, codecs.StreamWriter):
    pass


class _StreamReader(_Codec, codecs.StreamReader):
    pass


_CODEC_INFO = codecs.CodecInfo(
    name="cp1047",
    encode=_Codec().encode,
    decode=_Codec().decode,
    incrementalencoder=_IncrementalEncoder,
    incrementaldecoder=_IncrementalDecoder,
    streamreader=_StreamReader,
    streamwriter=_StreamWriter,
)

_registered = False


def register() -> None:
    """Make ``cp1047`` usable by :meth:`bytes.decode` (idempotent)."""
    global _registered
    if _registered:
        return

    def search(name: str):
        return _CODEC_INFO if name.replace("_", "-").lower() in _ALIASES else None

    codecs.register(search)
    _registered = True


def available(name: str) -> bool:
    """True when *name* can be used as a codec in this interpreter."""
    try:
        codecs.lookup(name)
        return True
    except LookupError:
        return False
