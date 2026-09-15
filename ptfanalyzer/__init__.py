"""SMP/E PTF Package Analyzer.

A production oriented toolkit for inspecting IBM z/OS SMP/E service packages
(BMC and IBM style ``.pax.Z`` deliveries, including ``.XofY`` split sets).

Typical use::

    from ptfanalyzer.pipeline import AnalyzerOptions, Workspace, run_analysis, stage_uploads

    workspace = Workspace()
    parts = stage_uploads([(path.name, path.read_bytes()) for path in files], workspace)
    report = run_analysis(parts, workspace, AnalyzerOptions())
"""

from __future__ import annotations

__version__ = "1.0.0"

from .errors import (
    AnalyzerError,
    ArchiveError,
    DecompressionError,
    EncodingError,
    FormatError,
    ParseError,
    PartSetError,
)
from .logging_util import AnalysisLog, LogEntry
from .models import (
    AnalysisReport,
    ArchiveMember,
    ElementRef,
    HoldEntry,
    MCSStatement,
    PackageAnalysis,
    PackageGroup,
    PartRef,
    PTFEntry,
    SMPPTFINAnalysis,
)

__all__ = [
    "__version__",
    "AnalysisLog",
    "AnalysisReport",
    "AnalyzerError",
    "ArchiveError",
    "ArchiveMember",
    "DecompressionError",
    "ElementRef",
    "EncodingError",
    "FormatError",
    "HoldEntry",
    "LogEntry",
    "MCSStatement",
    "PTFEntry",
    "PackageAnalysis",
    "PackageGroup",
    "ParseError",
    "PartRef",
    "PartSetError",
    "SMPPTFINAnalysis",
]
