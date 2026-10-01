"""CSV profiler for DAQ recordings.

Profiling terminates at the quality gate.  Canonical records are returned as
metadata only; windowing and feature extraction are intentionally downstream.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Sequence

from core.schema import Recording
from ingestion.quality import (
    CANONICAL_COLUMNS,
    data_rows,
    decode_text,
    has_valid_header,
    is_numeric_row,
    parse_csv_rows,
    read_raw_bytes,
    sanitize_null_bytes,
    validate_columns,
    validate_numeric,
)


DEFAULT_QUARANTINE_LOG = Path("quarantine/quarantine_log.jsonl")


class NumericArrayLoadError(ValueError):
    """A canonical-profiled file failed the required full numeric load."""


def write_quarantine_log(
    source_path: str | Path, reasons: Sequence[str], log_path: str | Path
) -> None:
    """Append a machine-readable quality rejection event for one source file."""
    destination = Path(log_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    event = {"source_path": str(Path(source_path).resolve()), "reasons": list(reasons)}
    with destination.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(event, sort_keys=True) + "\n")


def _recording_id(path: Path, condition_id: str) -> str:
    return f"{condition_id}/{path.stem}"


def _quarantined_recording(
    path: Path,
    condition_id: str,
    checksum: str,
    reasons: list[str],
    quarantine_log_path: str | Path,
) -> Recording:
    write_quarantine_log(path, reasons, quarantine_log_path)
    return Recording(
        recording_id=_recording_id(path, condition_id),
        condition_id=condition_id,
        source_path=str(path.resolve()),
        checksum=checksum,
        schema_status="quarantined",
        quality_issues=reasons,
    )


def profile_file(
    path: str | Path,
    *,
    condition_id: str | None = None,
    canonical_columns: Sequence[str] = CANONICAL_COLUMNS,
    expected_column_count: int | None = None,
    quarantine_log_path: str | Path = DEFAULT_QUARANTINE_LOG,
) -> Recording:
    """Profile one DAQ CSV and return either a canonical or quarantined record.

    No invalid file is normalized into a seven-channel layout.  This function
    performs no windowing or feature work, irrespective of the returned status.
    """
    source_path = Path(path)
    resolved_condition_id = condition_id or source_path.parent.name
    expected_count = expected_column_count or len(canonical_columns)
    quality_issues: list[str] = []

    try:
        raw = read_raw_bytes(source_path)
    except OSError as exc:
        return _quarantined_recording(
            source_path,
            resolved_condition_id,
            checksum="",
            reasons=[f"raw_byte_read_error:{exc.__class__.__name__}"],
            quarantine_log_path=quarantine_log_path,
        )

    checksum = hashlib.sha256(raw).hexdigest()
    sanitized = sanitize_null_bytes(raw, quality_issues)
    text = decode_text(sanitized)

    try:
        rows = parse_csv_rows(text)
    except csv.Error:
        return _quarantined_recording(
            source_path,
            resolved_condition_id,
            checksum,
            [*quality_issues, "unparseable_csv"],
            quarantine_log_path,
        )

    column_issue = validate_columns(rows, expected_count)
    if column_issue == "empty_file":
        return _quarantined_recording(
            source_path,
            resolved_condition_id,
            checksum,
            [*quality_issues, column_issue],
            quarantine_log_path,
        )

    first_row = rows[0]
    if not has_valid_header(first_row, canonical_columns):
        if len(first_row) == expected_count and is_numeric_row(first_row):
            header_issue = "no_valid_header_numeric_match"
        elif column_issue is not None:
            header_issue = column_issue
        else:
            header_issue = "invalid_header"
        return _quarantined_recording(
            source_path,
            resolved_condition_id,
            checksum,
            [*quality_issues, header_issue],
            quarantine_log_path,
        )

    if column_issue is not None:
        return _quarantined_recording(
            source_path,
            resolved_condition_id,
            checksum,
            [*quality_issues, column_issue],
            quarantine_log_path,
        )

    numeric_issue = validate_numeric(rows)
    if numeric_issue is not None:
        return _quarantined_recording(
            source_path,
            resolved_condition_id,
            checksum,
            [*quality_issues, numeric_issue],
            quarantine_log_path,
        )

    return Recording(
        recording_id=_recording_id(source_path, resolved_condition_id),
        condition_id=resolved_condition_id,
        source_path=str(source_path.resolve()),
        checksum=checksum,
        schema_status="canonical",
        row_count=len(data_rows(rows)),
        channel_names=list(canonical_columns),
        quality_issues=quality_issues,
    )


def load_full_numeric_array(
    recording: Recording,
    *,
    canonical_columns: Sequence[str] = CANONICAL_COLUMNS,
    expected_column_count: int | None = None,
) -> list[list[float]]:
    """Load every data row from a canonical recording as numeric values.

    This is intentionally separate from ``profile_file``: the profiler samples
    numeric values for speed, while this final gate validates every value before
    any signal windowing receives the recording.
    """
    if recording.schema_status != "canonical":
        raise NumericArrayLoadError("recording_not_canonical")

    source_path = Path(recording.source_path)
    try:
        raw = read_raw_bytes(source_path)
    except OSError as exc:
        raise NumericArrayLoadError(f"raw_byte_read_error:{exc.__class__.__name__}") from exc

    if hashlib.sha256(raw).hexdigest() != recording.checksum:
        raise NumericArrayLoadError("source_changed_after_profile")

    audit: list[str] = []
    try:
        rows = parse_csv_rows(decode_text(sanitize_null_bytes(raw, audit)))
    except csv.Error as exc:
        raise NumericArrayLoadError("unparseable_csv") from exc

    expected_count = expected_column_count or len(canonical_columns)
    if not rows:
        raise NumericArrayLoadError("empty_file")
    if not has_valid_header(rows[0], canonical_columns):
        raise NumericArrayLoadError("invalid_header")
    column_issue = validate_columns(rows, expected_count)
    if column_issue is not None:
        raise NumericArrayLoadError(column_issue)

    numeric_rows: list[list[float]] = []
    for row in data_rows(rows):
        try:
            numeric_rows.append([float(value) for value in row])
        except ValueError as exc:
            raise NumericArrayLoadError("non_numeric_signal_value") from exc
    return numeric_rows
