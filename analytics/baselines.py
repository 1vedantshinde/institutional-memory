"""Per-condition normal feature profiles for DAQ anomaly detection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import numpy as np

from core.schema import Recording, SignalWindow


class BaselineInputError(ValueError):
    """Baseline input lacks provenance or a consistent feature layout."""


@dataclass(frozen=True)
class ConditionChannelBaseline:
    """Normal feature distribution for one channel under one S/F/D condition."""

    condition_id: str
    channel: str
    feature_names: list[str]
    mean_vector: list[float]
    std_vector: list[float]
    recording_ids: list[str]
    window_count: int


@dataclass(frozen=True)
class BaselineCollection:
    """All per-condition/channel normal profiles from one canonical corpus."""

    profiles: dict[tuple[str, str], ConditionChannelBaseline]

    def get(self, condition_id: str, channel: str) -> ConditionChannelBaseline:
        try:
            return self.profiles[(condition_id, channel)]
        except KeyError as exc:
            raise KeyError(
                f"No baseline for condition_id={condition_id!r}, channel={channel!r}"
            ) from exc


def _recordings_by_id(
    recordings: Iterable[Recording] | Mapping[str, Recording],
) -> dict[str, Recording]:
    if isinstance(recordings, Mapping):
        return dict(recordings)
    return {recording.recording_id: recording for recording in recordings}


def build_per_condition_baselines(
    windows: Iterable[SignalWindow],
    recordings: Iterable[Recording] | Mapping[str, Recording],
    feature_names: Sequence[str],
) -> BaselineCollection:
    """Aggregate canonical feature vectors by ``(condition_id, channel)``.

    The mean and population standard deviation are calculated across windows
    from canonical recordings only. A quarantined recording is deliberately
    ignored even if a caller accidentally supplies one of its windows.
    """
    names = list(feature_names)
    if not names:
        raise BaselineInputError("feature_names_must_not_be_empty")
    recording_index = _recordings_by_id(recordings)
    grouped_vectors: dict[tuple[str, str], list[list[float]]] = {}
    grouped_recordings: dict[tuple[str, str], set[str]] = {}

    for window in windows:
        recording = recording_index.get(window.recording_id)
        if recording is None:
            raise BaselineInputError(
                f"window_references_unknown_recording:{window.recording_id}"
            )
        if recording.schema_status != "canonical":
            continue
        if window.feature_vector is None:
            continue
        if len(window.feature_vector) != len(names):
            raise BaselineInputError(
                f"feature_vector_length_mismatch:{window.window_id}"
            )
        vector = [float(value) for value in window.feature_vector]
        if not np.all(np.isfinite(vector)):
            raise BaselineInputError(f"non_finite_feature_value:{window.window_id}")

        key = (recording.condition_id, window.channel)
        grouped_vectors.setdefault(key, []).append(vector)
        grouped_recordings.setdefault(key, set()).add(recording.recording_id)

    profiles: dict[tuple[str, str], ConditionChannelBaseline] = {}
    for key, vectors in grouped_vectors.items():
        matrix = np.asarray(vectors, dtype=float)
        condition_id, channel = key
        profiles[key] = ConditionChannelBaseline(
            condition_id=condition_id,
            channel=channel,
            feature_names=names,
            mean_vector=np.mean(matrix, axis=0).tolist(),
            std_vector=np.std(matrix, axis=0, ddof=0).tolist(),
            recording_ids=sorted(grouped_recordings[key]),
            window_count=len(vectors),
        )
    return BaselineCollection(profiles=profiles)
