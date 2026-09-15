"""Exception hierarchy for the SMP/E PTF Package Analyzer.

Every exception carries a *user facing* message (``message``) plus an optional
technical ``detail``.  The UI shows ``message`` to everybody and ``detail`` /
traceback only when Debug Mode is enabled, so an end user never sees a raw
Python traceback.
"""

from __future__ import annotations


class AnalyzerError(Exception):
    """Base class for all errors raised by the analyzer."""

    #: Short, stable identifier used by logs and integrations.
    code = "ANALYZER_ERROR"

    def __init__(self, message: str, detail: str | None = None, hint: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail
        self.hint = hint

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "detail": self.detail,
            "hint": self.hint,
        }


class PartSetError(AnalyzerError):
    """The uploaded ``.XofY`` part set is incomplete or inconsistent."""

    code = "PART_SET_ERROR"


class FormatError(AnalyzerError):
    """The concatenated stream is not in a format we can process."""

    code = "FORMAT_ERROR"


class DecompressionError(AnalyzerError):
    """Every available ``.Z`` decoder failed."""

    code = "DECOMPRESSION_ERROR"


class ArchiveError(AnalyzerError):
    """The decompressed stream is not a readable PAX/TAR archive."""

    code = "ARCHIVE_ERROR"


class EncodingError(AnalyzerError):
    """No usable character encoding could be determined."""

    code = "ENCODING_ERROR"


class ParseError(AnalyzerError):
    """SMP/E MCS input could not be parsed."""

    code = "PARSE_ERROR"
