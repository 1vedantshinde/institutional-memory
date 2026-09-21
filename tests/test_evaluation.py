"""Tests for leakage-safe whole-condition and whole-recording evaluation splits."""

from __future__ import annotations

import pytest

from analytics.evaluation import EvaluationSplitError, partition_windows_by_recording, split_recordings
from core.schema import Recording, SignalWindow


def _recording(recording_id: str, condition_id: str) -> Recording:
    return Recording(
        recording_id=recording_id,
        condition_id=condition_id,
        source_path=f"/dataset/{recording_id}.csv",
        checksum="test",
        schema_status="canonical",
    )


def _window(window_id: str, recording_id: str) -> SignalWindow:
    return SignalWindow(
        window_id=window_id,
        recording_id=recording_id,
        channel="Vib_Spindle",
        sample_start=0,
        sample_end=10,
    )


def test_prefers_a_whole_condition_split_and_keeps_all_its_recordings_together() -> None:
    recordings = [
        _recording("1/a", "1"),
        _recording("1/b", "1"),
        _recording("2/a", "2"),
        _recording("2/b", "2"),
        _recording("3/a", "3"),
        _recording("4/a", "4"),
    ]

    split = split_recordings(recordings, test_fraction=0.25, seed=7)

    assert split.split_level == "condition"
    assert not (set(split.train_recording_ids) & set(split.test_recording_ids))
    for condition_id in split.test_condition_ids:
        condition_records = {
            record.recording_id for record in recordings if record.condition_id == condition_id
        }
        assert condition_records <= set(split.test_recording_ids)


def test_falls_back_to_whole_recordings_when_only_one_condition_exists() -> None:
    recordings = [_recording(f"4/{index}", "4") for index in range(5)]
    windows = [_window(f"window-{index}", f"4/{index // 2}") for index in range(10)]

    split = split_recordings(recordings, test_fraction=0.4, seed=2)
    train_windows, test_windows = partition_windows_by_recording(windows, split)

    assert split.split_level == "recording"
    assert {window.recording_id for window in train_windows}.isdisjoint(
        {window.recording_id for window in test_windows}
    )
    assert len(train_windows) + len(test_windows) == len(windows)


def test_rejects_a_split_with_fewer_than_two_canonical_groups() -> None:
    with pytest.raises(EvaluationSplitError, match="at_least_two_groups"):
        split_recordings([_recording("4/only", "4")])
