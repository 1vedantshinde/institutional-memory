"""Leakage-safe train/test splitting for DAQ recording-level evaluation."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable, Literal

from core.schema import Recording, SignalWindow


class EvaluationSplitError(ValueError):
    """An evaluation split would be invalid or allow recording leakage."""


@dataclass(frozen=True)
class EvaluationSplit:
    """Whole-recording train/test partition with its grouping provenance."""

    train_recording_ids: list[str]
    test_recording_ids: list[str]
    train_condition_ids: list[str]
    test_condition_ids: list[str]
    split_level: Literal["condition", "recording"]

    def assert_no_recording_overlap(self) -> None:
        overlap = set(self.train_recording_ids) & set(self.test_recording_ids)
        if overlap:
            raise EvaluationSplitError(
                f"recording_id_overlap_between_train_and_test:{sorted(overlap)}"
            )


def _canonical_recordings(recordings: Iterable[Recording]) -> list[Recording]:
    canonical = [
        recording for recording in recordings if recording.schema_status == "canonical"
    ]
    identifiers = [recording.recording_id for recording in canonical]
    if len(identifiers) != len(set(identifiers)):
        raise EvaluationSplitError("duplicate_canonical_recording_id")
    return canonical


def _test_group_count(group_count: int, test_fraction: float) -> int:
    if not 0 < test_fraction < 1:
        raise EvaluationSplitError("test_fraction_must_be_between_zero_and_one")
    if group_count < 2:
        raise EvaluationSplitError("at_least_two_groups_are_required_for_a_split")
    return min(group_count - 1, max(1, round(group_count * test_fraction)))


def split_recordings(
    recordings: Iterable[Recording],
    *,
    test_fraction: float = 0.2,
    seed: int = 0,
    prefer_condition_split: bool = True,
) -> EvaluationSplit:
    """Split canonical data by whole condition when possible, else recordings.

    A condition-level split keeps all of its recordings on the same side. When
    fewer than two canonical conditions exist, the fallback still assigns each
    complete recording—not individual windows—to exactly one partition.
    """
    canonical = _canonical_recordings(recordings)
    condition_ids = sorted({recording.condition_id for recording in canonical})
    randomizer = random.Random(seed)

    if prefer_condition_split and len(condition_ids) >= 2:
        shuffled_conditions = condition_ids.copy()
        randomizer.shuffle(shuffled_conditions)
        test_conditions = set(
            shuffled_conditions[: _test_group_count(len(condition_ids), test_fraction)]
        )
        train = [
            recording.recording_id
            for recording in canonical
            if recording.condition_id not in test_conditions
        ]
        test = [
            recording.recording_id
            for recording in canonical
            if recording.condition_id in test_conditions
        ]
        split = EvaluationSplit(
            train_recording_ids=sorted(train),
            test_recording_ids=sorted(test),
            train_condition_ids=sorted(set(condition_ids) - test_conditions),
            test_condition_ids=sorted(test_conditions),
            split_level="condition",
        )
    else:
        recording_ids = [recording.recording_id for recording in canonical]
        test_count = _test_group_count(len(recording_ids), test_fraction)
        randomizer.shuffle(recording_ids)
        test = recording_ids[:test_count]
        train = recording_ids[test_count:]
        condition_by_recording = {
            recording.recording_id: recording.condition_id for recording in canonical
        }
        split = EvaluationSplit(
            train_recording_ids=sorted(train),
            test_recording_ids=sorted(test),
            train_condition_ids=sorted({condition_by_recording[recording_id] for recording_id in train}),
            test_condition_ids=sorted({condition_by_recording[recording_id] for recording_id in test}),
            split_level="recording",
        )
    split.assert_no_recording_overlap()
    if not split.train_recording_ids or not split.test_recording_ids:
        raise EvaluationSplitError("split_must_have_non_empty_train_and_test_partitions")
    return split


def partition_windows_by_recording(
    windows: Iterable[SignalWindow], split: EvaluationSplit
) -> tuple[list[SignalWindow], list[SignalWindow]]:
    """Assign windows using an existing recording split; never split a record."""
    split.assert_no_recording_overlap()
    train_ids = set(split.train_recording_ids)
    test_ids = set(split.test_recording_ids)
    train_windows: list[SignalWindow] = []
    test_windows: list[SignalWindow] = []
    for window in windows:
        if window.recording_id in train_ids:
            train_windows.append(window)
        elif window.recording_id in test_ids:
            test_windows.append(window)
        else:
            raise EvaluationSplitError(
                f"window_recording_not_in_evaluation_split:{window.recording_id}"
            )
    return train_windows, test_windows
