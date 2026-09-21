"""Composable quality checks for DAQ CSV recordings.

This module validates only; it does not reshape, fill, or otherwise coerce
recordings into the canonical channel layout.
"""

from __future__ import annotations

import csv
import io
import logging
from pathlib import Path
from typing import Sequence


CSV_FIELD_SIZE_LIMIT = 1_048_576
CANONICAL_COLUMNS = [
    "Time",
    "Vib_Spindle",
    "Vib_Table",
    "X_Load_Cell",
    "Y_Load_Cell",
    "Z_Load_Cell",
    "Current",
]

# This must execute before any csv.reader is created in the DAQ ingestion path.
csv.field_size_limit(CSV_FIELD_SIZE_LIMIT)

LOGGER = logging.getLogger(__name__)


def read_raw_bytes(path: str | Path) -> bytes:
    """Read a source file without decoding or modifying its bytes."""
    with Path(path).open("rb") as source_file:
        return source_file.read()


def sanitize_null_bytes(raw: bytes, log: list[str]) -> bytes:
    """Remove embedded NUL bytes before decoding and retain an audit marker."""
    if b"\x00" in raw:
        log.append("null_bytes_removed")
        LOGGER.info("Removed embedded NUL bytes before CSV decoding")
        return raw.replace(b"\x00", b"")
    return raw


def decode_text(raw: bytes) -> str:
    """Decode without discarding undecodable bytes."""
    return raw.decode("utf-8", errors="surrogateescape")


def parse_csv_rows(text: str) -> list[list[str]]:
    """Parse decoded CSV text with strict CSV syntax handling."""
    return list(csv.reader(io.StringIO(text, newline=""), strict=True))


def has_valid_header(first_row: list[str], canonical: Sequence[str]) -> bool:
    """Return true only for an exact canonical header match and ordering."""
    return first_row == list(canonical)


def validate_columns(rows: list[list[str]], expected_count: int) -> str | None:
    """Ensure every parsed row has the configured canonical column count."""
    if not rows:
        return "empty_file"
    for row in rows:
        if len(row) != expected_count:
            return f"column_count_mismatch:{len(row)}"
    return None


def validate_numeric(rows: list[list[str]]) -> str | None:
    """Sample up to five data rows; the parser's later full pass checks all rows."""
    for row in rows[1:6]:
        for value in row:
            try:
                float(value)
            except ValueError:
                return "non_numeric_signal_value"
    return None


def is_numeric_row(row: list[str]) -> bool:
    """Check whether one potential header row contains only numeric values."""
    if not row:
        return False
    try:
        for value in row:
            float(value)
    except ValueError:
        return False
    return True
