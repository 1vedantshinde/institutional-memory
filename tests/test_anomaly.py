"""Tests for unsupervised, provenance-bearing DAQ anomaly findings."""

from __future__ import annotations

import pytest

from analytics.anomaly import (
    MODEL_VERSION,
    anomaly_finding,
    detect_anomalies,
    diagonal_mahalanobis_distance,
)
from analytics.baselines import BaselineCollection, ConditionChannelBaseline
from core.schema import Recording, SignalWindow


def _recording(status: str = "canonical") -> Recording:
    return Recording(
        recording_id="4/Recording 15",
        condition_id="4",
        source_path="/dataset/4_S800_F35_D0.25/Recording 15.csv",
        checksum="test",
        schema_status=status,
    )


def _baseline() -> ConditionChannelBaseline:
    return ConditionChannelBaseline(
        condition_id="4",
        channel="Vib_Spindle",
        feature_names=["rms", "peak"],
        mean_vector=[0.0, 0.0],
        std_vector=[1.0, 2.0],
        recording_ids=["4/Recording 1", "4/Recording 2"],
        window_count=4,
    )


def _window(vector: list[float]) -> SignalWindow:
    return SignalWindow(
        window_id="4/Recording 15:Vib_Spindle:128:2176",
        recording_id="4/Recording 15",
        channel="Vib_Spindle",
        sample_start=128,
        sample_end=2176,
        time_start=1.28,
        time_end=21.75,
        feature_vector=vector,
    )


def test_mahalanobis_distance_uses_the_condition_channel_standard_deviations() -> None:
    assert diagonal_mahalanobis_distance([1.0, 2.0], _baseline()) == pytest.approx(2**0.5)


def test_anomaly_finding_has_full_raw_data_provenance() -> None:
    finding = anomaly_finding(_window([5.0, 0.0]), _recording(), _baseline(), threshold=3.0)

    assert finding is not None
    assert finding.finding_type == "anomaly"
    assert finding.score == pytest.approx(5.0)
    assert finding.model_version == MODEL_VERSION
    assert finding.evidence == {
        "recording_id": "4/Recording 15",
        "source_path": "/dataset/4_S800_F35_D0.25/Recording 15.csv",
        "channel": "Vib_Spindle",
        "window_id": "4/Recording 15:Vib_Spindle:128:2176",
        "sample_range": {"sample_start": 128, "sample_end": 2176},
        "time_range": {"time_start": 1.28, "time_end": 21.75},
        "condition_id": "4",
        "baseline_recording_ids": ["4/Recording 1", "4/Recording 2"],
        "dominant_feature_deviations": [
            {"feature": "rms", "label": "overall vibration level (RMS)", "window_value": 5.0, "baseline_mean": 0.0, "standardized_deviation": 5.0, "plain_language": "overall vibration level (RMS) was 5.00 standard deviations above the condition baseline"},
            {"feature": "peak", "label": "peak vibration level", "window_value": 0.0, "baseline_mean": 0.0, "standardized_deviation": 0.0, "plain_language": "peak vibration level was 0.00 standard deviations above the condition baseline"},
        ],
        "threshold": 3.0,
    }


def test_detector_is_unsupervised_and_never_emits_for_quarantined_records() -> None:
    baseline = _baseline()
    collection = BaselineCollection({("4", "Vib_Spindle"): baseline})
    canonical = _recording()
    rejected = _recording("quarantined")
    rejected.recording_id = "4/Recording rejected"
    rejected.source_path = "/dataset/rejected.csv"
    rejected_window = _window([100.0, 100.0])
    rejected_window.recording_id = rejected.recording_id

    findings = detect_anomalies(
        [_window([1.0, 2.0]), _window([5.0, 0.0]), rejected_window],
        {canonical.recording_id: canonical, rejected.recording_id: rejected},
        collection,
        threshold=3.0,
    )

    assert len(findings) == 1
    assert findings[0].recording_id == canonical.recording_id
