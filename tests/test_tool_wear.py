"""Tests for exact workbook label joins and leakage-safe wear model evaluation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from openpyxl import Workbook

from analytics.tool_wear import ToolWearDataset, load_tool_wear_labels, train_and_evaluate_tool_wear
from core.schema import Recording


def _recording(recording_id: str, condition_id: str) -> Recording:
    return Recording(recording_id=recording_id, condition_id=condition_id, source_path="/tmp/source.csv", checksum="x", schema_status="canonical")


def test_reads_case_columns_and_joins_runs_from_tool_wear_workbook(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Tool_Wear"
    sheet.append(["Number of runs", "Case_1", "case12_wear (um)"])
    sheet.append([1, 11.0, 22.0])
    path = tmp_path / "wear.xlsx"
    workbook.save(path)

    labels = load_tool_wear_labels(path)

    assert labels[("1", 1)].wear_um == 11.0
    assert labels[("12", 1)].wear_um == 22.0


def test_supervised_wear_evaluation_keeps_whole_recordings_separate() -> None:
    recordings = [_recording(f"1/Recording {index}", "1") for index in range(1, 6)]
    dataset = ToolWearDataset(
        feature_names=["x"],
        feature_matrix=np.asarray([[float(index)] for index in range(1, 6)]),
        targets_um=np.asarray([10.0, 20.0, 30.0, 40.0, 50.0]),
        recording_ids=[recording.recording_id for recording in recordings],
        condition_ids=["1"] * 5,
    )

    _, evaluation = train_and_evaluate_tool_wear(dataset, recordings, test_fraction=0.4, seed=2)

    assert set(evaluation.split.train_recording_ids).isdisjoint(evaluation.split.test_recording_ids)
    assert evaluation.train_size + evaluation.test_size == 5
