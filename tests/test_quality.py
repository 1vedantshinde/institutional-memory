"""Regression tests for the DAQ CSV quality gate and known exception classes."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pytest

from ingestion.parsers.csv_daq_parser import profile_file
from ingestion.quality import (
    CANONICAL_COLUMNS,
    CSV_FIELD_SIZE_LIMIT,
    decode_text,
    has_valid_header,
    sanitize_null_bytes,
    validate_columns,
    validate_numeric,
)


def _rows(column_count: int = 7) -> list[list[str]]:
    return [[str(index + 1) for index in range(column_count)]]


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        csv.writer(csv_file).writerows(rows)


def _profile(path: Path, quarantine_log: Path):
    return profile_file(
        path,
        condition_id="4",
        quarantine_log_path=quarantine_log,
    )


def _logged_reasons(log_path: Path) -> list[str]:
    event = json.loads(log_path.read_text(encoding="utf-8").strip())
    return event["reasons"]


@pytest.mark.skipif(
    not (
        os.environ.get("DAQ_DATASET_ROOT")
        and os.environ.get("DAQ_EXCEPTION_EXPECTATIONS_JSON")
    ),
    reason=(
        "Set DAQ_DATASET_ROOT and DAQ_EXCEPTION_EXPECTATIONS_JSON to run "
        "exact real-file exception regressions."
    ),
)
def test_real_known_exceptions_are_quarantined_with_exact_reasons(tmp_path: Path) -> None:
    """Bind the synthetic regression suite to the actual discovered exception paths.

    ``DAQ_EXCEPTION_EXPECTATIONS_JSON`` is a JSON object mapping each relative
    CSV path to its exact expected quality-reason list, for example:
    {"4_S800_F35_D0.25/Recording 15.csv": ["no_valid_header_numeric_match"]}.
    The expected value is intentionally external until the actual files reveal
    their final post-field-limit quality status.
    """
    dataset_root = Path(os.environ["DAQ_DATASET_ROOT"])
    expected = json.loads(os.environ["DAQ_EXCEPTION_EXPECTATIONS_JSON"])

    for relative_path, reasons in expected.items():
        source = dataset_root / relative_path
        record = profile_file(
            source,
            quarantine_log_path=tmp_path / "quarantine.jsonl",
        )
        assert record.schema_status == "quarantined", relative_path
        assert record.quality_issues == reasons, relative_path


def test_quality_helpers_are_independent() -> None:
    audit: list[str] = []
    assert sanitize_null_bytes(b"a\x00b", audit) == b"ab"
    assert audit == ["null_bytes_removed"]
    assert decode_text(b"\xff").encode("utf-8", "surrogateescape") == b"\xff"
    assert has_valid_header(CANONICAL_COLUMNS, CANONICAL_COLUMNS)
    assert not has_valid_header(list(reversed(CANONICAL_COLUMNS)), CANONICAL_COLUMNS)
    assert validate_columns([], 7) == "empty_file"
    assert validate_columns([["1", "2"]], 7) == "column_count_mismatch:2"
    assert validate_numeric([CANONICAL_COLUMNS, ["bad"] * 7]) == "non_numeric_signal_value"


def test_oversized_field_is_read_after_field_limit_is_raised(tmp_path: Path) -> None:
    """Regression for Recording 15's former default 131072-character limit."""
    assert csv.field_size_limit() >= CSV_FIELD_SIZE_LIMIT
    source = tmp_path / "Recording 15.csv"
    oversized_number = "1" * 140_000
    _write_csv(source, [CANONICAL_COLUMNS, [oversized_number, "2", "3", "4", "5", "6", "7"]])

    record = _profile(source, tmp_path / "quarantine.jsonl")

    assert record.schema_status == "canonical"
    assert record.row_count == 1


def test_no_header_with_seven_numeric_fields_is_never_assumed_canonical(tmp_path: Path) -> None:
    source = tmp_path / "Recording 16.csv"
    quarantine_log = tmp_path / "quarantine.jsonl"
    _write_csv(source, _rows())

    record = _profile(source, quarantine_log)

    assert record.schema_status == "quarantined"
    assert record.quality_issues == ["no_valid_header_numeric_match"]
    assert _logged_reasons(quarantine_log) == ["no_valid_header_numeric_match"]


@pytest.mark.parametrize("column_count", [2, 3, 4, 6, 6])
def test_noncanonical_column_counts_are_quarantined(tmp_path: Path, column_count: int) -> None:
    """Covers the five known no-header recordings with 2/3/4/6 columns."""
    source = tmp_path / f"Recording {column_count}.csv"
    quarantine_log = tmp_path / f"quarantine-{column_count}.jsonl"
    _write_csv(source, _rows(column_count))

    record = _profile(source, quarantine_log)

    expected_reason = f"column_count_mismatch:{column_count}"
    assert record.schema_status == "quarantined"
    assert record.quality_issues == [expected_reason]
    assert _logged_reasons(quarantine_log) == [expected_reason]


def test_unparseable_csv_is_quarantined(tmp_path: Path) -> None:
    source = tmp_path / "Recording 17.csv"
    quarantine_log = tmp_path / "quarantine.jsonl"
    source.write_text(
        ",".join(CANONICAL_COLUMNS) + "\n1,\"unterminated\n",
        encoding="utf-8",
    )

    record = _profile(source, quarantine_log)

    assert record.schema_status == "quarantined"
    assert record.quality_issues == ["unparseable_csv"]
    assert _logged_reasons(quarantine_log) == ["unparseable_csv"]


def test_raw_byte_read_failure_is_isolated_before_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "Recording 18.csv"
    quarantine_log = tmp_path / "quarantine.jsonl"

    def fail_raw_read(_: Path) -> bytes:
        raise OSError("unreadable")

    monkeypatch.setattr("ingestion.parsers.csv_daq_parser.read_raw_bytes", fail_raw_read)
    record = _profile(source, quarantine_log)

    assert record.schema_status == "quarantined"
    assert record.quality_issues == ["raw_byte_read_error:OSError"]
    assert _logged_reasons(quarantine_log) == ["raw_byte_read_error:OSError"]


def test_null_bytes_are_removed_before_decode_and_recorded(tmp_path: Path) -> None:
    source = tmp_path / "Recording 19.csv"
    source.write_bytes(
        (",".join(CANONICAL_COLUMNS) + "\n1\x000,2,3,4,5,6,7\n").encode("utf-8")
    )

    record = _profile(source, tmp_path / "quarantine.jsonl")

    assert record.schema_status == "canonical"
    assert record.quality_issues == ["null_bytes_removed"]
