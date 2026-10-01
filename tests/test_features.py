"""Tests for rate-independent and fs-gated DAQ feature extraction."""

from __future__ import annotations

import math

import pytest

from core.schema import SignalWindow
from signal.features import (
    FREQUENCY_FEATURE_NAMES,
    TIME_FEATURE_NAMES,
    SamplingRateRequiredError,
    band_energy,
    extract_window_features,
    frequency_domain_features,
    spectral_centroid,
    time_domain_features,
)


def _window() -> SignalWindow:
    return SignalWindow(
        window_id="4/Recording 1:Vib_Spindle:0:100",
        recording_id="4/Recording 1",
        channel="Vib_Spindle",
        sample_start=0,
        sample_end=100,
    )


def test_time_domain_features_do_not_require_a_sampling_rate() -> None:
    extraction = extract_window_features(_window(), [1.0, -1.0, 1.0, -1.0])

    assert tuple(extraction.features) == TIME_FEATURE_NAMES
    assert extraction.feature_names == list(TIME_FEATURE_NAMES)
    assert extraction.features["rms"] == pytest.approx(1.0)
    assert extraction.features["peak"] == pytest.approx(1.0)
    assert extraction.features["crest_factor"] == pytest.approx(1.0)
    assert extraction.sampling_rate_hz is None


def test_frequency_features_are_blocked_without_confirmed_fs() -> None:
    with pytest.raises(SamplingRateRequiredError, match="sampling_rate_required"):
        frequency_domain_features([1.0, 2.0, 3.0], None)
    with pytest.raises(SamplingRateRequiredError, match="sampling_rate_required"):
        band_energy([1.0, 2.0, 3.0], None, 0.0, 1.0)


def test_frequency_features_use_the_supplied_data_derived_rate() -> None:
    fs = 100.0
    samples = [math.sin(2 * math.pi * 5 * index / fs) for index in range(100)]
    window = _window()

    extraction = extract_window_features(window, samples, fs=fs)

    assert tuple(extraction.features)[-4:] == FREQUENCY_FEATURE_NAMES
    assert extraction.feature_names[-4:] == list(FREQUENCY_FEATURE_NAMES)
    assert extraction.features["spectral_centroid"] == pytest.approx(5.0, abs=0.1)
    assert extraction.features["band_energy_low"] > 0
    assert extraction.feature_vector == window.feature_vector
    assert spectral_centroid(samples, fs) == pytest.approx(5.0, abs=0.1)


def test_time_feature_functions_return_standard_diagnostics() -> None:
    features = time_domain_features([0.0, 1.0, 2.0, 3.0])

    assert features["mean"] == pytest.approx(1.5)
    assert features["std"] == pytest.approx(math.sqrt(1.25))
    assert features["rms"] == pytest.approx(math.sqrt(3.5))
