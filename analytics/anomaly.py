"""Unsupervised, per-condition Mahalanobis anomaly detection for DAQ windows."""

from __future__ import annotations

import hashlib
from typing import Iterable, Mapping

import numpy as np

from analytics.baselines import BaselineCollection, ConditionChannelBaseline
from core.schema import Finding, Recording, SignalWindow


MODEL_VERSION = "mahalanobis-diagonal-v1"


class AnomalyInputError(ValueError):
    """A window cannot be compared safely with its condition baseline."""


def diagonal_mahalanobis_distance(
    feature_vector: list[float], baseline: ConditionChannelBaseline
) -> float:
    """Calculate an interpretable Mahalanobis distance from mean/std profile.

    Step 6 provides per-feature standard deviations rather than a covariance
    matrix, so the initial detector explicitly uses a diagonal covariance
    approximation. Zero-variance features retain a small numeric floor instead
    of being discarded.
    """
    vector = np.asarray(feature_vector, dtype=float)
    mean = np.asarray(baseline.mean_vector, dtype=float)
    standard_deviation = np.asarray(baseline.std_vector, dtype=float)
    if vector.shape != mean.shape or mean.shape != standard_deviation.shape:
        raise AnomalyInputError("feature_vector_baseline_shape_mismatch")
    if not (
        np.all(np.isfinite(vector))
        and np.all(np.isfinite(mean))
        and np.all(np.isfinite(standard_deviation))
    ):
        raise AnomalyInputError("non_finite_anomaly_input")
    if np.any(standard_deviation < 0):
        raise AnomalyInputError("negative_baseline_standard_deviation")

    safe_std = np.maximum(standard_deviation, 1e-12)
    standardized_delta = (vector - mean) / safe_std
    return float(np.sqrt(np.sum(standardized_delta**2)))


def _finding_id(window: SignalWindow, score: float) -> str:
    payload = f"{MODEL_VERSION}:{window.window_id}:{score:.12g}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def anomaly_finding(
    window: SignalWindow,
    recording: Recording,
    baseline: ConditionChannelBaseline,
    *,
    threshold: float = 3.0,
) -> Finding | None:
    """Return a traceable anomaly finding when a window exceeds its baseline."""
    if recording.schema_status != "canonical":
        return None
    if window.recording_id != recording.recording_id:
        raise AnomalyInputError("window_recording_id_mismatch")
    if window.channel != baseline.channel or recording.condition_id != baseline.condition_id:
        raise AnomalyInputError("window_baseline_scope_mismatch")
    if window.feature_vector is None:
        raise AnomalyInputError("window_has_no_feature_vector")
    if threshold <= 0:
        raise AnomalyInputError("anomaly_threshold_must_be_positive")

    score = diagonal_mahalanobis_distance(window.feature_vector, baseline)
    if score < threshold:
        return None
    evidence = {
        "recording_id": recording.recording_id,
        "source_path": recording.source_path,
        "channel": window.channel,
        "window_id": window.window_id,
        "sample_range": {
            "sample_start": window.sample_start,
            "sample_end": window.sample_end,
        },
        "time_range": {
            "time_start": window.time_start,
            "time_end": window.time_end,
        },
        "condition_id": recording.condition_id,
        "baseline_recording_ids": baseline.recording_ids,
        "threshold": threshold,
    }
    return Finding(
        finding_id=_finding_id(window, score),
        recording_id=recording.recording_id,
        window_id=window.window_id,
        finding_type="anomaly",
        score=score,
        evidence=evidence,
        model_version=MODEL_VERSION,
    )


def detect_anomalies(
    windows: Iterable[SignalWindow],
    recordings: Mapping[str, Recording],
    baselines: BaselineCollection,
    *,
    threshold: float = 3.0,
) -> list[Finding]:
    """Detect unsupervised outliers using only same-condition normal profiles."""
    findings: list[Finding] = []
    for window in windows:
        recording = recordings.get(window.recording_id)
        if recording is None:
            raise AnomalyInputError(
                f"window_references_unknown_recording:{window.recording_id}"
            )
        if recording.schema_status != "canonical":
            continue
        try:
            baseline = baselines.get(recording.condition_id, window.channel)
        except KeyError as exc:
            raise AnomalyInputError(
                f"missing_condition_channel_baseline:{recording.condition_id}:{window.channel}"
            ) from exc
        finding = anomaly_finding(window, recording, baseline, threshold=threshold)
        if finding is not None:
            findings.append(finding)
    return findings
