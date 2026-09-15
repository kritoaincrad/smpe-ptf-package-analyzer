"""Application settings, persisted between runs with :class:`QSettings`."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields

from PySide6.QtCore import QSettings

from ptfanalyzer.pipeline import AnalyzerOptions

ORGANIZATION = "SMPE Tools"
APPLICATION = "PTF Analyzer"

AUTOMATIC = ""  # empty means "let the analyzer decide"


@dataclass
class Settings:
    """Everything the user can tune, in one place."""

    # decompression
    allow_partial: bool = True
    prefer_external: bool = True
    threshold_mb: int = 96
    forced_decoder: str = AUTOMATIC

    # SMP/E metadata
    encoding: str = AUTOMATIC
    honor_columns: bool = True
    nested_depth: int = 2
    analyze_duplicates: bool = False

    # history
    auto_save: bool = True
    history_limit: int = 200

    # appearance and workflow
    dark_theme: bool = False
    notifications: bool = True
    recursive_folders: bool = True
    last_input_dir: str = ""
    last_export_dir: str = ""

    # corporate reports and privacy
    company_name: str = ""
    report_title: str = "SMP/E PTF Analysis Report"
    logo_path: str = ""
    mask_private_paths: bool = True
    offline_mode: bool = True
    encrypt_database: bool = False

    # diagnostics
    debug: bool = False

    # -- persistence -----------------------------------------------------
    @classmethod
    def load(cls) -> "Settings":
        store = QSettings(ORGANIZATION, APPLICATION)
        values = {}
        for field in fields(cls):
            raw = store.value(f"options/{field.name}", None)
            if raw is None:
                continue
            if field.type in ("bool", bool):
                values[field.name] = str(raw).lower() in ("1", "true", "yes")
            elif field.type in ("int", int):
                try:
                    values[field.name] = int(raw)
                except (TypeError, ValueError):
                    continue
            else:
                values[field.name] = str(raw)
        return cls(**values)

    def save(self) -> None:
        store = QSettings(ORGANIZATION, APPLICATION)
        for key, value in asdict(self).items():
            store.setValue(f"options/{key}", value)
        store.sync()

    def copy(self) -> "Settings":
        return Settings(**asdict(self))

    # -- use -------------------------------------------------------------
    def to_analyzer_options(self) -> AnalyzerOptions:
        return AnalyzerOptions(
            allow_partial_decompression=self.allow_partial,
            prefer_external_for_large=self.prefer_external,
            external_threshold_mb=self.threshold_mb,
            forced_decoder=self.forced_decoder or None,
            encoding_override=self.encoding or None,
            honor_sequence_columns=self.honor_columns,
            max_nested_depth=self.nested_depth,
            analyze_duplicates=self.analyze_duplicates,
            debug=self.debug,
            offline_mode=self.offline_mode,
            redact_logs=self.mask_private_paths,
        )
