"""Focused orchestration tests for the DAQ manifest-to-windowing path."""

from __future__ import annotations

import csv
from pathlib import Path

from ingestion.pipeline import ingest_daq_dataset
from ingestion.quality import CANONICAL_COLUMNS


FOLDER_PATTERN = r"^(?P<condition_id>\d+)_S(?P<S>\d+)_F(?P<F>\d+)_D(?P<D>[\d.]+)$"


def _write_config(path: Path) -> None:
    path.write_text(f"recording_folder_pattern: '{FOLDER_PATTERN}'\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        csv.writer(csv_file).writerows(rows)


def test_pipeline_profiles_before_loading_and_hands_only_canonical_arrays(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "domain.yaml"
    _write_config(config_path)
    condition = tmp_path / "4_S800_F35_D0.25"
    condition.mkdir()
    _write_csv(
        condition / "Recording 1.csv",
        [CANONICAL_COLUMNS, ["1", "2", "3", "4", "5", "6", "7"]],
    )
    _write_csv(condition / "Recording 2.csv", [["1", "2", "3", "4", "5", "6", "7"]])
    handoffs: list[tuple[str, list[list[float]]]] = []

    def windowing_handler(recording, numeric_array):
        handoffs.append((recording.recording_id, numeric_array))
        return {"recording_id": recording.recording_id, "rows": len(numeric_array)}

    run = ingest_daq_dataset(
        str(tmp_path),
        config_path=str(config_path),
        quarantine_log_path=str(tmp_path / "quarantine.jsonl"),
        windowing_handler=windowing_handler,
    )

    assert run.summary.as_dict() == {
        "discovered": 2,
        "canonical": 1,
        "quarantined": 1,
        "quarantined_by_reason": {"no_valid_header_numeric_match": 1},
    }
    assert handoffs == [("4/Recording 1", [[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]])]
    assert run.windowing_outputs == [{"recording_id": "4/Recording 1", "rows": 1}]


def test_full_numeric_load_quarantines_rows_beyond_the_profile_sample(tmp_path: Path) -> None:
    config_path = tmp_path / "domain.yaml"
    _write_config(config_path)
    condition = tmp_path / "4_S800_F35_D0.25"
    condition.mkdir()
    numeric_rows = [[str(value) for value in range(1, 8)] for _ in range(5)]
    _write_csv(condition / "Recording 3.csv", [CANONICAL_COLUMNS, *numeric_rows, ["bad"] * 7])
    handoffs: list[object] = []

    run = ingest_daq_dataset(
        str(tmp_path),
        config_path=str(config_path),
        quarantine_log_path=str(tmp_path / "quarantine.jsonl"),
        windowing_handler=lambda recording, values: handoffs.append((recording, values)),
    )

    assert run.summary.as_dict() == {
        "discovered": 1,
        "canonical": 0,
        "quarantined": 1,
        "quarantined_by_reason": {"non_numeric_signal_value": 1},
    }
    assert handoffs == []
