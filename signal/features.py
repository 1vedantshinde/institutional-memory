"""Per-channel DAQ time- and frequency-domain feature extraction."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from core.schema import SignalWindow


class FeatureInputError(ValueError):
    """Feature extraction received unusable signal samples or band settings."""


class SamplingRateRequiredError(FeatureInputError):
    """A frequency-domain feature was requested before fs was confirmed."""


TIME_FEATURE_NAMES = (
    "mean",
    "std",
    "rms",
    "peak",
    "crest_factor",
    "kurtosis",
    "skewness",
)
FREQUENCY_FEATURE_NAMES = (
    "band_energy_low",
    "band_energy_mid",
    "band_energy_high",
    "spectral_centroid",
)


@dataclass(frozen=True)
class FeatureExtraction:
    """Named feature evidence and the contract-compatible ordered vector."""

    window_id: str
    features: dict[str, float]
    feature_names: list[str]
    feature_vector: list[float]
    sampling_rate_hz: float | None


def _as_signal(samples: Sequence[float]) -> np.ndarray:
    signal = np.asarray(samples, dtype=float)
    if signal.ndim != 1 or signal.size == 0:
        raise FeatureInputError("signal_must_be_a_non_empty_one_dimensional_sequence")
    if not np.all(np.isfinite(signal)):
        raise FeatureInputError("signal_contains_non_finite_values")
    return signal


def _require_fs(fs: float | None) -> float:
    if fs is None:
        raise SamplingRateRequiredError("sampling_rate_required_for_frequency_features")
    if not math.isfinite(fs) or fs <= 0:
        raise SamplingRateRequiredError("invalid_sampling_rate_for_frequency_features")
    return float(fs)


def rms(x: Sequence[float]) -> float:
    signal = _as_signal(x)
    return float(np.sqrt(np.mean(signal**2)))


def peak(x: Sequence[float]) -> float:
    signal = _as_signal(x)
    return float(np.max(np.abs(signal)))


def crest_factor(x: Sequence[float]) -> float:
    signal = _as_signal(x)
    return peak(signal) / (rms(signal) + 1e-12)


def kurtosis(x: Sequence[float]) -> float:
    signal = _as_signal(x)
    mean = np.mean(signal)
    standard_deviation = np.std(signal) + 1e-12
    return float(np.mean(((signal - mean) / standard_deviation) ** 4) - 3)


def skewness(x: Sequence[float]) -> float:
    signal = _as_signal(x)
    mean = np.mean(signal)
    standard_deviation = np.std(signal) + 1e-12
    return float(np.mean(((signal - mean) / standard_deviation) ** 3))


def band_energy(x: Sequence[float], fs: float | None, low: float, high: float) -> float:
    """Return unnormalised FFT-bin energy within the requested half-open band."""
    signal = _as_signal(x)
    sampling_rate = _require_fs(fs)
    nyquist = sampling_rate / 2
    if low < 0 or high <= low or high > np.nextafter(nyquist, math.inf):
        raise FeatureInputError("invalid_frequency_band")
    frequencies = np.fft.rfftfreq(len(signal), d=1 / sampling_rate)
    spectrum = np.abs(np.fft.rfft(signal)) ** 2
    mask = (frequencies >= low) & (frequencies < high)
    return float(np.sum(spectrum[mask]))


def spectral_centroid(x: Sequence[float], fs: float | None) -> float:
    signal = _as_signal(x)
    sampling_rate = _require_fs(fs)
    frequencies = np.fft.rfftfreq(len(signal), d=1 / sampling_rate)
    spectrum = np.abs(np.fft.rfft(signal))
    return float(np.sum(frequencies * spectrum) / (np.sum(spectrum) + 1e-12))


def default_frequency_bands(fs: float) -> dict[str, tuple[float, float]]:
    """Partition measured Nyquist into low/mid/high bands without guessing fs."""
    sampling_rate = _require_fs(fs)
    nyquist = sampling_rate / 2
    return {
        "band_energy_low": (0.0, nyquist / 3),
        "band_energy_mid": (nyquist / 3, 2 * nyquist / 3),
        "band_energy_high": (2 * nyquist / 3, float(np.nextafter(nyquist, math.inf))),
    }


def time_domain_features(x: Sequence[float]) -> dict[str, float]:
    """Extract rate-independent vibration/load/current diagnostics."""
    signal = _as_signal(x)
    return {
        "mean": float(np.mean(signal)),
        "std": float(np.std(signal)),
        "rms": rms(signal),
        "peak": peak(signal),
        "crest_factor": crest_factor(signal),
        "kurtosis": kurtosis(signal),
        "skewness": skewness(signal),
    }


def frequency_domain_features(
    x: Sequence[float],
    fs: float | None,
    *,
    bands: Mapping[str, tuple[float, float]] | None = None,
) -> dict[str, float]:
    """Extract frequency features only after a data-derived sampling rate exists."""
    sampling_rate = _require_fs(fs)
    active_bands = dict(bands) if bands is not None else default_frequency_bands(sampling_rate)
    required_band_names = FREQUENCY_FEATURE_NAMES[:3]
    missing = [name for name in required_band_names if name not in active_bands]
    if missing:
        raise FeatureInputError(f"missing_frequency_bands:{','.join(missing)}")
    return {
        **{
            name: band_energy(x, sampling_rate, *active_bands[name])
            for name in required_band_names
        },
        "spectral_centroid": spectral_centroid(x, sampling_rate),
    }


def extract_window_features(
    window: SignalWindow,
    samples: Sequence[float],
    *,
    fs: float | None = None,
    bands: Mapping[str, tuple[float, float]] | None = None,
) -> FeatureExtraction:
    """Extract per-window features and persist their ordered vector on the window.

    With no ``fs``, only time-domain features are emitted. Supplying an ``fs``
    enables the frequency-domain set and must represent the rate confirmed from
    the recording's actual Time-column deltas.
    """
    features = time_domain_features(samples)
    feature_names = list(TIME_FEATURE_NAMES)
    if fs is not None:
        features.update(frequency_domain_features(samples, fs, bands=bands))
        feature_names.extend(FREQUENCY_FEATURE_NAMES)
    vector = [features[name] for name in feature_names]
    window.feature_vector = vector
    return FeatureExtraction(
        window_id=window.window_id,
        features=features,
        feature_names=feature_names,
        feature_vector=vector,
        sampling_rate_hz=fs,
    )
