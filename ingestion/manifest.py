"""Runtime discovery of DAQ recordings and their condition metadata.

This module deliberately inventories files only.  It does not read CSV
contents, infer schemas, or apply quality decisions; those belong to later
ingestion stages.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TypedDict

import yaml


class ManifestEntry(TypedDict):
    """The stable, flat inventory record emitted for each DAQ CSV."""

    source_path: str
    condition_id: str
    S: float
    F: float
    D: float
    recording_number: int


class ManifestConfigurationError(ValueError):
    """Raised when the config cannot supply the required folder pattern."""


_RECORDING_FILE_PATTERN = re.compile(r"^Recording (?P<recording_number>\d+)\.csv$")


def _load_recording_folder_pattern(config_path: str | Path) -> re.Pattern[str]:
    """Load and compile the condition-folder regex from ``domain.yaml``."""
    path = Path(config_path)
    try:
        with path.open("r", encoding="utf-8") as config_file:
            config = yaml.safe_load(config_file) or {}
    except OSError as exc:
        raise ManifestConfigurationError(
            f"Unable to read manifest configuration at {path}"
        ) from exc

    if not isinstance(config, dict):
        raise ManifestConfigurationError("domain.yaml must contain a mapping")

    pattern = config.get("recording_folder_pattern")
    if not isinstance(pattern, str) or not pattern.strip():
        raise ManifestConfigurationError(
            "domain.yaml must define a non-empty recording_folder_pattern"
        )

    try:
        return re.compile(pattern.strip())
    except re.error as exc:
        raise ManifestConfigurationError(
            "domain.yaml recording_folder_pattern is not a valid regular expression"
        ) from exc


def _find_condition_match(
    csv_path: Path, root: Path, condition_pattern: re.Pattern[str]
) -> re.Match[str] | None:
    """Return the nearest configured condition directory containing a CSV."""
    for parent in csv_path.parents:
        if parent == root.parent:
            break
        match = condition_pattern.fullmatch(parent.name)
        if match is not None:
            return match
    return None


def discover_manifest(
    dataset_root: str | Path,
    *,
    config_path: str | Path = "config/domain.yaml",
) -> list[ManifestEntry]:
    """Discover every ``Recording <number>.csv`` under configured conditions.

    A matching condition directory supplies all process parameters through the
    named groups in ``recording_folder_pattern``.  No condition count or
    parameter parsing is hardcoded here.  Results are sorted by source path so
    repeated runs produce the same flat inventory.
    """
    root = Path(dataset_root)
    if not root.is_dir():
        raise FileNotFoundError(f"Dataset root is not a directory: {root}")

    condition_pattern = _load_recording_folder_pattern(config_path)
    manifest: list[ManifestEntry] = []

    for csv_path in sorted(root.rglob("Recording *.csv")):
        file_match = _RECORDING_FILE_PATTERN.fullmatch(csv_path.name)
        if file_match is None:
            # The glob is intentionally broad enough for filesystem discovery;
            # only files with an explicit numeric recording number are inventory
            # records.
            continue

        condition_match = _find_condition_match(csv_path, root, condition_pattern)
        if condition_match is None:
            continue

        groups = condition_match.groupdict()
        required_groups = ("condition_id", "S", "F", "D")
        missing_groups = [name for name in required_groups if not groups.get(name)]
        if missing_groups:
            raise ManifestConfigurationError(
                "recording_folder_pattern must provide named groups "
                f"condition_id, S, F, D; missing: {', '.join(missing_groups)}"
            )

        try:
            entry: ManifestEntry = {
                "source_path": str(csv_path.resolve()),
                "condition_id": groups["condition_id"],
                "S": float(groups["S"]),
                "F": float(groups["F"]),
                "D": float(groups["D"]),
                "recording_number": int(file_match.group("recording_number")),
            }
        except ValueError as exc:
            raise ManifestConfigurationError(
                "recording_folder_pattern captured non-numeric S, F, or D values"
            ) from exc
        manifest.append(entry)

    return manifest
