"""Tests for DAQ preprocessing and fixed-length channel windows."""

from __future__ import annotations

import math

import pytest

from core.schema import Recording
from signal.preprocessing import SamplingRateError, compute_sampling_rate, preprocess_channel
from signal.windowing import fixed_window_bounds, window_recording


def _recording() -> Recording:
    return Recording(
        recording_id="4/Recording 1",
        condition_id="4",
        source_path="/dataset/4_S800_F35_D0.25/Recording 1.csv",
        checksum="test",
        schema_status="canonical",
        channel_names=[
            "Time", "Vib_Spindle", "Vib_Table", "X_Load_Cell", "Y_Load_Cell", "Z_Load_Cell", "Current"
        ],
    )


def test_sampling_rate_is_computed_from_time_deltas_and_nans_are_channel_local() -> None:
    time_values = [0.0, 0.1, 0.2, 0.3]

    prepared = preprocess_channel([1.0, math.nan, 3.0, 4.0], time_values=time_values)

    assert compute_sampling_rate(time_values) == pytest.approx(10.0)
    assert prepared.values == [1.0, 2.0, 3.0, 4.0]
    assert prepared.nan_count == 1
    assert prepared.sampling_rate_hz == pytest.approx(10.0)


def test_configured_resampling_rate_must_be_confirmed_from_time() -> None:
    with pytest.raises(SamplingRateError, match="configured_sampling_rate_mismatch"):
        preprocess_channel([1.0, 2.0, 3.0], time_values=[0.0, 0.1, 0.2], confirmed_sampling_hz=20.0)


def test_confirmed_sampling_rate_resamples_every_channel_on_one_time_grid() -> None:
    numeric_array = [
        [index * 0.1, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        for index in range(5)
    ]

    windows = window_recording(
        _recording(), numeric_array, window_size_samples=2, confirmed_sampling_hz=10.0
    )

    assert len(windows) == 24
    assert windows[-1].time_end == pytest.approx(0.4)


def test_fixed_windows_are_channel_aware_and_cite_time_ranges() -> None:
    numeric_array = [
        [index * 0.1, 1.0, math.nan if index == 1 else 2.0, 3.0, 4.0, 5.0, 6.0]
        for index in range(5)
    ]

    windows = window_recording(_recording(), numeric_array, window_size_samples=2, overlap=0.5)

    assert fixed_window_bounds(5, 2, 0.5) == [(0, 2), (1, 3), (2, 4), (3, 5)]
    assert len(windows) == 24  # six physical channels × four windows
    assert windows[0].channel == "Vib_Spindle"
    assert windows[0].sample_start == 0
    assert windows[0].sample_end == 2
    assert windows[0].time_start == pytest.approx(0.0)
    assert windows[0].time_end == pytest.approx(0.1)


def test_windows_omit_times_when_time_semantics_cannot_be_confirmed() -> None:
    numeric_array = [[0.0, 1, 2, 3, 4, 5, 6], [0.0, 1, 2, 3, 4, 5, 6]]

    windows = window_recording(_recording(), numeric_array, window_size_samples=2)

    assert windows[0].time_start is None
    assert windows[0].time_end is None
