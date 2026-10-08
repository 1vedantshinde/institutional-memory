"""Per-channel DAQ preprocessing with data-derived sampling-rate validation."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Sequence
import numpy as np


class SamplingRateError(ValueError):
    """Time values cannot support a trustworthy sampling-rate calculation."""


class ChannelPreprocessingError(ValueError):
    """A signal channel cannot be safely prepared for windowing."""


@dataclass(frozen=True)
class PreprocessedChannel:
    values: Sequence[float]
    nan_count: int
    sampling_rate_hz: float | None = None


def compute_sampling_rate(time_values: Sequence[float]) -> float:
    """Compute Hz from measured, strictly positive Time-column deltas.

    The median delta makes the estimate robust to small timestamp jitter, but
    no sampling rate is emitted for non-finite, repeated, or decreasing times.
    """
    if len(time_values) < 2:
        raise SamplingRateError("insufficient_time_samples")
    if isinstance(time_values, np.ndarray) and time_values.dtype == float:
        if not np.all(np.isfinite(time_values)):
            raise SamplingRateError("non_finite_time_value")
        deltas = np.diff(time_values)
        if np.any(deltas <= 0):
            raise SamplingRateError("non_monotonic_time")
        median_delta = float(np.median(deltas))
        if median_delta <= 0 or not math.isfinite(median_delta):
            raise SamplingRateError("invalid_time_delta")
        return 1.0 / median_delta
    if any(not math.isfinite(value) for value in time_values):
        raise SamplingRateError("non_finite_time_value")

    deltas = [later - earlier for earlier, later in zip(time_values, time_values[1:])]
    if any(delta <= 0 for delta in deltas):
        raise SamplingRateError("non_monotonic_time")
    median_delta = statistics.median(deltas)
    if median_delta <= 0 or not math.isfinite(median_delta):
        raise SamplingRateError("invalid_time_delta")
    return 1.0 / median_delta


def confirm_sampling_rate(
    measured_hz: float, configured_hz: float, *, relative_tolerance: float = 0.02
) -> float:
    """Accept a configured resampling rate only when Time data confirms it."""
    if configured_hz <= 0 or not math.isfinite(configured_hz):
        raise SamplingRateError("invalid_configured_sampling_rate")
    if not math.isclose(measured_hz, configured_hz, rel_tol=relative_tolerance):
        raise SamplingRateError(
            f"configured_sampling_rate_mismatch:measured={measured_hz:g},configured={configured_hz:g}"
        )
    return configured_hz


def interpolate_nans(values: Sequence[float]) -> tuple[Sequence[float], int]:
    """Fill NaNs per channel by linear interpolation while preserving indices."""
    if isinstance(values, np.ndarray) and values.dtype == float:
        if not np.isnan(values).any():
            return values, 0
    prepared = [float(value) for value in values]
    missing = [index for index, value in enumerate(prepared) if math.isnan(value)]
    if not missing:
        return prepared, 0
    if len(missing) == len(prepared):
        raise ChannelPreprocessingError("channel_all_nan")

    first_valid = next(index for index, value in enumerate(prepared) if not math.isnan(value))
    for index in range(first_valid):
        prepared[index] = prepared[first_valid]

    last_valid = first_valid
    for index in range(first_valid + 1, len(prepared)):
        if math.isnan(prepared[index]):
            continue
        next_valid = index
        if next_valid - last_valid > 1:
            start_value = prepared[last_valid]
            end_value = prepared[next_valid]
            gap = next_valid - last_valid
            for missing_index in range(last_valid + 1, next_valid):
                fraction = (missing_index - last_valid) / gap
                prepared[missing_index] = start_value + fraction * (end_value - start_value)
        last_valid = next_valid

    for index in range(last_valid + 1, len(prepared)):
        prepared[index] = prepared[last_valid]
    return prepared, len(missing)


def resample_channel(
    time_values: Sequence[float], values: Sequence[float], target_hz: float
) -> tuple[list[float], list[float]]:
    """Linearly resample a prepared channel onto a uniform data-confirmed grid."""
    if len(time_values) != len(values):
        raise ChannelPreprocessingError("time_value_length_mismatch")
    if not time_values:
        return [], []
    if target_hz <= 0:
        raise SamplingRateError("invalid_configured_sampling_rate")

    step = 1.0 / target_hz
    uniform_times: list[float] = []
    current = float(time_values[0])
    final = float(time_values[-1])
    while current <= final + (step * 1e-9):
        uniform_times.append(current)
        current += step

    resampled: list[float] = []
    source_index = 0
    for target_time in uniform_times:
        while (
            source_index < len(time_values) - 2
            and time_values[source_index + 1] < target_time
        ):
            source_index += 1
        left_time, right_time = time_values[source_index], time_values[source_index + 1] if source_index + 1 < len(time_values) else time_values[source_index]
        left_value, right_value = values[source_index], values[source_index + 1] if source_index + 1 < len(values) else values[source_index]
        if right_time == left_time:
            resampled.append(float(left_value))
        else:
            fraction = (target_time - left_time) / (right_time - left_time)
            resampled.append(float(left_value + fraction * (right_value - left_value)))
    return uniform_times, resampled


def preprocess_channel(
    values: Sequence[float],
    *,
    time_values: Sequence[float] | None = None,
    confirmed_sampling_hz: float | None = None,
) -> PreprocessedChannel:
    """Interpolate per-channel NaNs and optionally resample after confirmation."""
    prepared, nan_count = interpolate_nans(values)
    if time_values is None:
        if confirmed_sampling_hz is not None:
            raise SamplingRateError("time_values_required_for_resampling")
        return PreprocessedChannel(values=prepared, nan_count=nan_count)

    measured_hz = compute_sampling_rate(time_values)
    if confirmed_sampling_hz is None:
        return PreprocessedChannel(
            values=prepared, nan_count=nan_count, sampling_rate_hz=measured_hz
        )
    target_hz = confirm_sampling_rate(measured_hz, confirmed_sampling_hz)
    _, resampled = resample_channel(time_values, prepared, target_hz)
    return PreprocessedChannel(
        values=resampled, nan_count=nan_count, sampling_rate_hz=target_hz
    )
