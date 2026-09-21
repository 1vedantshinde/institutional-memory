"""Tests for canonical-only, per-condition DAQ feature baselines."""

from __future__ import annotations

import pytest

from analytics.baselines import build_per_condition_baselines
from core.schema import Recording, SignalWindow


FEATURE_NAMES = ["rms", "peak"]


def _recording(recording_id: str, condition_id: str, status: str = "canonical") -> Recording:
    return Recording(
        recording_id=recording_id,
        condition_id=condition_id,
        source_path=f"/dataset/{recording_id}.csv",
        checksum="test",
        schema_status=status,
    )


def _window(window_id: str, recording_id: str, channel: str, vector: list[float]) -> SignalWindow:
    return SignalWindow(
        window_id=window_id,
        recording_id=recording_id,
        channel=channel,
        sample_start=0,
        sample_end=10,
        feature_vector=vector,
    )


def test_builds_separate_channel_profiles_per_condition_from_canonical_recordings() -> None:
    records = [
        _recording("4/Recording 1", "4"),
        _recording("4/Recording 2", "4"),
        _recording("5/Recording 1", "5"),
        _recording("4/Recording rejected", "4", "quarantined"),
    ]
    windows = [
        _window("a", "4/Recording 1", "Vib_Spindle", [1.0, 2.0]),
        _window("b", "4/Recording 2", "Vib_Spindle", [3.0, 6.0]),
        _window("c", "5/Recording 1", "Vib_Spindle", [10.0, 20.0]),
        _window("d", "4/Recording rejected", "Vib_Spindle", [100.0, 200.0]),
        _window("e", "4/Recording 1", "Current", [4.0, 8.0]),
    ]

    baselines = build_per_condition_baselines(windows, records, FEATURE_NAMES)

    condition_four = baselines.get("4", "Vib_Spindle")
    assert condition_four.mean_vector == pytest.approx([2.0, 4.0])
    assert condition_four.std_vector == pytest.approx([1.0, 2.0])
    assert condition_four.recording_ids == ["4/Recording 1", "4/Recording 2"]
    assert condition_four.window_count == 2
    assert baselines.get("5", "Vib_Spindle").mean_vector == pytest.approx([10.0, 20.0])
    assert baselines.get("4", "Current").mean_vector == pytest.approx([4.0, 8.0])


def test_baseline_rejects_a_feature_vector_with_an_unexplained_layout() -> None:
    records = [_recording("4/Recording 1", "4")]
    windows = [_window("a", "4/Recording 1", "Vib_Spindle", [1.0])]

    with pytest.raises(ValueError, match="feature_vector_length_mismatch"):
        build_per_condition_baselines(windows, records, FEATURE_NAMES)
