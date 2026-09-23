"""Supervised, recording-level tool-wear modelling from computed DAQ features.

The workbook supplies observed wear labels; DAQ signals remain the evidence
source. Labels are joined by condition/case ID and Recording number only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from openpyxl import load_workbook
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from analytics.evaluation import EvaluationSplit, split_recordings
from core.schema import Condition, Recording
from ingestion.parsers.csv_daq_parser import load_full_numeric_array
from signal.features import time_domain_features
from signal.preprocessing import SamplingRateError, compute_sampling_rate


WEAR_MODEL_VERSION = "hist-gradient-boosting-tool-wear-v1"
_CASE_NUMBER_PATTERN = re.compile(r"case[_ ]*(?P<condition_id>\d+)", re.IGNORECASE)
_RECORDING_NUMBER_PATTERN = re.compile(r"Recording (?P<recording_number>\d+)$")


class ToolWearError(ValueError):
    """Tool-wear labels, feature rows, or fitting inputs are invalid."""


@dataclass(frozen=True)
class ToolWearLabel:
    condition_id: str
    recording_number: int
    wear_um: float


@dataclass(frozen=True)
class ToolWearDataset:
    feature_names: list[str]
    feature_matrix: np.ndarray
    targets_um: np.ndarray
    recording_ids: list[str]
    condition_ids: list[str]


@dataclass(frozen=True)
class ToolWearEvaluation:
    model_version: str
    split: EvaluationSplit
    train_size: int
    test_size: int
    mae_um: float
    rmse_um: float
    r2: float | None
    predictions: list[dict[str, float | str]]


def load_tool_wear_labels(workbook_path: str | Path) -> dict[tuple[str, int], ToolWearLabel]:
    """Read case-column wear labels from the supplied xlsx without text RAG."""
    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    if "Tool_Wear" not in workbook.sheetnames:
        raise ToolWearError("missing_Tool_Wear_worksheet")
    sheet = workbook["Tool_Wear"]
    rows = sheet.iter_rows(values_only=True)
    headers = next(rows, None)
    if headers is None:
        raise ToolWearError("empty_tool_wear_worksheet")

    case_columns: dict[int, str] = {}
    for index, header in enumerate(headers):
        if not isinstance(header, str):
            continue
        match = _CASE_NUMBER_PATTERN.search(header)
        if match:
            case_columns[index] = match.group("condition_id")
    if not case_columns:
        raise ToolWearError("no_case_columns_in_tool_wear_worksheet")

    labels: dict[tuple[str, int], ToolWearLabel] = {}
    for row in rows:
        run_number = row[0] if row else None
        if not isinstance(run_number, (int, float)) or int(run_number) != run_number:
            continue
        for index, condition_id in case_columns.items():
            value = row[index] if index < len(row) else None
            if isinstance(value, (int, float)) and np.isfinite(value):
                key = (condition_id, int(run_number))
                labels[key] = ToolWearLabel(condition_id, int(run_number), float(value))
    return labels


def recording_number(recording: Recording) -> int:
    match = _RECORDING_NUMBER_PATTERN.fullmatch(recording.recording_id.split("/", 1)[-1])
    if match is None:
        raise ToolWearError(f"recording_id_has_no_recording_number:{recording.recording_id}")
    return int(match.group("recording_number"))


def recording_feature_row(
    recording: Recording,
    condition: Condition,
    *,
    max_samples: int = 8192,
) -> tuple[list[str], list[float]]:
    """Aggregate per-channel time features from a canonical recording.

    Evenly spaced samples cap memory/compute per 40+ GB corpus while retaining
    full-recording coverage. Frequency features are deliberately omitted here:
    their rate confirmation is per recording and this baseline wear model uses
    rate-independent diagnostics.
    """
    if recording.schema_status != "canonical":
        raise ToolWearError("cannot_extract_features_from_quarantined_recording")
    numeric = np.asarray(load_full_numeric_array(recording), dtype=float)
    if numeric.size == 0:
        raise ToolWearError(f"recording_has_no_data_rows:{recording.recording_id}")
    if max_samples <= 0:
        raise ToolWearError("max_samples_must_be_positive")
    try:
        # fs must come from adjacent original Time deltas, not the decimated
        # feature sample used to cap model-training cost.
        fs = compute_sampling_rate(numeric[:, 0].tolist())
    except SamplingRateError:
        fs = None
    indexes = np.linspace(0, len(numeric) - 1, min(len(numeric), max_samples), dtype=int)
    sampled = numeric[indexes]
    names = ["S", "F", "D"]
    values = [condition.S, condition.F, condition.D]
    for channel_index, channel_name in enumerate(recording.channel_names[1:], start=1):
        diagnostics = time_domain_features(sampled[:, channel_index])
        for name, value in diagnostics.items():
            names.append(f"{channel_name}__{name}")
            values.append(value)
    names.append("measured_fs_hz")
    values.append(fs if fs is not None else 0.0)
    return names, values


def build_tool_wear_dataset(
    recordings: Iterable[Recording],
    conditions: dict[str, Condition],
    labels: dict[tuple[str, int], ToolWearLabel],
    *,
    max_samples: int = 8192,
) -> ToolWearDataset:
    """Join canonical recordings to observed wear and derive recording features."""
    feature_names: list[str] | None = None
    vectors: list[list[float]] = []
    targets: list[float] = []
    recording_ids: list[str] = []
    condition_ids: list[str] = []
    for recording in recordings:
        if recording.schema_status != "canonical":
            continue
        condition = conditions.get(recording.condition_id)
        label = labels.get((recording.condition_id, recording_number(recording)))
        if condition is None or label is None:
            continue
        names, vector = recording_feature_row(recording, condition, max_samples=max_samples)
        if feature_names is None:
            feature_names = names
        elif names != feature_names:
            raise ToolWearError("inconsistent_recording_feature_layout")
        vectors.append(vector)
        targets.append(label.wear_um)
        recording_ids.append(recording.recording_id)
        condition_ids.append(recording.condition_id)
    if not vectors or feature_names is None:
        raise ToolWearError("no_labelled_canonical_recordings")
    return ToolWearDataset(
        feature_names=feature_names,
        feature_matrix=np.asarray(vectors, dtype=float),
        targets_um=np.asarray(targets, dtype=float),
        recording_ids=recording_ids,
        condition_ids=condition_ids,
    )


def train_and_evaluate_tool_wear(
    dataset: ToolWearDataset,
    recordings: Sequence[Recording],
    *,
    test_fraction: float = 0.2,
    seed: int = 42,
) -> tuple[HistGradientBoostingRegressor, ToolWearEvaluation]:
    """Fit a supervised wear regressor with an evaluation split by recording."""
    selected_ids = set(dataset.recording_ids)
    split = split_recordings(
        [recording for recording in recordings if recording.recording_id in selected_ids],
        test_fraction=test_fraction,
        seed=seed,
        prefer_condition_split=False,
    )
    index_by_id = {recording_id: index for index, recording_id in enumerate(dataset.recording_ids)}
    train_indexes = [index_by_id[recording_id] for recording_id in split.train_recording_ids]
    test_indexes = [index_by_id[recording_id] for recording_id in split.test_recording_ids]
    model = HistGradientBoostingRegressor(random_state=seed, l2_regularization=1.0)
    model.fit(dataset.feature_matrix[train_indexes], dataset.targets_um[train_indexes])
    predictions = model.predict(dataset.feature_matrix[test_indexes])
    actual = dataset.targets_um[test_indexes]
    evaluation = ToolWearEvaluation(
        model_version=WEAR_MODEL_VERSION,
        split=split,
        train_size=len(train_indexes),
        test_size=len(test_indexes),
        mae_um=float(mean_absolute_error(actual, predictions)),
        rmse_um=float(mean_squared_error(actual, predictions) ** 0.5),
        r2=float(r2_score(actual, predictions)) if len(test_indexes) >= 2 else None,
        predictions=[
            {
                "recording_id": dataset.recording_ids[index],
                "condition_id": dataset.condition_ids[index],
                "actual_wear_um": float(dataset.targets_um[index]),
                "predicted_wear_um": float(prediction),
            }
            for index, prediction in zip(test_indexes, predictions)
        ],
    )
    return model, evaluation
