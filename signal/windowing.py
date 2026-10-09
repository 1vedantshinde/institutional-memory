"""Channel-aware, fixed-length DAQ signal windows."""

from __future__ import annotations

from typing import Sequence
import numpy as np

from core.schema import Recording, SignalWindow
from ingestion.quality import CANONICAL_COLUMNS
from signal.preprocessing import (
    SamplingRateError,
    compute_sampling_rate,
    confirm_sampling_rate,
    preprocess_channel,
    resample_channel,
)


def fixed_window_bounds(
    sample_count: int, window_size_samples: int = 2048, overlap: float = 0.5
) -> list[tuple[int, int]]:
    """Return full, end-exclusive sample ranges for fixed-length windows."""
    if window_size_samples <= 0:
        raise ValueError("window_size_samples must be positive")
    if not 0 <= overlap < 1:
        raise ValueError("overlap must be in [0, 1)")
    step = int(window_size_samples * (1 - overlap))
    if step <= 0:
        raise ValueError("overlap produces a zero sample step")
    return [
        (start, start + window_size_samples)
        for start in range(0, sample_count - window_size_samples + 1, step)
    ]


def window_recording(
    recording: Recording,
    numeric_array: Sequence[Sequence[float]],
    *,
    window_size_samples: int = 2048,
    overlap: float = 0.5,
    confirmed_sampling_hz: float | None = None,
    channels: Sequence[str] | None = None,
) -> list[SignalWindow]:
    """Create fixed windows for each non-Time canonical DAQ channel.

    ``sample_end`` is exclusive. Time ranges are included only when the Time
    column has valid monotonic semantics and therefore yields a measured fs.
    """
    if recording.schema_status != "canonical":
        raise ValueError("only canonical recordings can be windowed")
    if isinstance(numeric_array, np.ndarray):
        if numeric_array.ndim != 2 or numeric_array.shape[1] != len(CANONICAL_COLUMNS):
            raise ValueError("numeric_array does not match the canonical seven-column schema")
        time_values = numeric_array[:, 0]
    else:
        if any(len(row) != len(CANONICAL_COLUMNS) for row in numeric_array):
            raise ValueError("numeric_array does not match the canonical seven-column schema")
        time_values = [float(row[0]) for row in numeric_array]

    window_time_values = time_values
    resampling_hz: float | None = None
    try:
        measured_hz = compute_sampling_rate(time_values)
        if confirmed_sampling_hz is not None:
            resampling_hz = confirm_sampling_rate(measured_hz, confirmed_sampling_hz)
            window_time_values, _ = resample_channel(
                time_values, time_values, resampling_hz
            )
        time_is_confirmed = True
    except SamplingRateError:
        if confirmed_sampling_hz is not None:
            raise
        time_is_confirmed = False

    bounds = fixed_window_bounds(
        len(window_time_values), window_size_samples, overlap
    )
    selected_channels = list(channels) if channels is not None else list(CANONICAL_COLUMNS[1:])
    invalid_channels = set(selected_channels) - set(CANONICAL_COLUMNS[1:])
    if invalid_channels:
        raise ValueError(f"unsupported_window_channels:{','.join(sorted(invalid_channels))}")
    windows: list[SignalWindow] = []
    for channel_name in selected_channels:
        channel_index = CANONICAL_COLUMNS.index(channel_name)
        if resampling_hz is not None:
            channel_values = [float(row[channel_index]) for row in numeric_array]
            prepared = preprocess_channel(channel_values)
            _, window_values = resample_channel(
                time_values, prepared.values, resampling_hz
            )
        else:
            # Full-channel preprocessing occurs once in the analysis layer;
            # window construction here needs only sample/time metadata.
            window_values = time_values
        if len(window_values) != len(window_time_values):
            raise ValueError("resampled channel does not align with the Time grid")
        for sample_start, sample_end in bounds:
            windows.append(
                SignalWindow(
                    window_id=(
                        f"{recording.recording_id}:{channel_name}:{sample_start}:{sample_end}"
                    ),
                    recording_id=recording.recording_id,
                    channel=channel_name,
                    sample_start=sample_start,
                    sample_end=sample_end,
                    time_start=window_time_values[sample_start] if time_is_confirmed else None,
                    time_end=window_time_values[sample_end - 1] if time_is_confirmed else None,
                )
            )
    return windows
