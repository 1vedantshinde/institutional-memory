"""Focused tests for Step 1 DAQ manifest discovery."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ingestion.manifest import ManifestConfigurationError, discover_manifest


FOLDER_PATTERN = (
    r"^(?P<condition_id>\d+)_S(?P<S>\d+)_F(?P<F>\d+)_D(?P<D>[\d.]+)$"
)


def _write_config(path: Path, pattern: str = FOLDER_PATTERN) -> None:
    path.write_text(f"recording_folder_pattern: '{pattern}'\n", encoding="utf-8")


def test_discovers_all_recordings_across_runtime_discovered_conditions(tmp_path: Path) -> None:
    """The directory count is discovered, not coupled to an eight-folder list."""
    config_path = tmp_path / "domain.yaml"
    _write_config(config_path)
    first = tmp_path / "1_S800_F35_D0.25"
    ninth = tmp_path / "9_S900_F40_D0.5"
    first.mkdir()
    ninth.mkdir()
    (first / "Recording 1.csv").write_text("placeholder", encoding="utf-8")
    (ninth / "Recording 27.csv").write_text("placeholder", encoding="utf-8")
    (tmp_path / "not_a_condition").mkdir()
    (tmp_path / "not_a_condition" / "Recording 99.csv").write_text(
        "placeholder", encoding="utf-8"
    )

    manifest = discover_manifest(tmp_path, config_path=config_path)

    assert manifest == [
        {
            "source_path": str((first / "Recording 1.csv").resolve()),
            "condition_id": "1",
            "S": 800.0,
            "F": 35.0,
            "D": 0.25,
            "recording_number": 1,
        },
        {
            "source_path": str((ninth / "Recording 27.csv").resolve()),
            "condition_id": "9",
            "S": 900.0,
            "F": 40.0,
            "D": 0.5,
            "recording_number": 27,
        },
    ]


def test_requires_the_configured_folder_pattern(tmp_path: Path) -> None:
    config_path = tmp_path / "domain.yaml"
    config_path.write_text("domain_name: test\n", encoding="utf-8")

    with pytest.raises(ManifestConfigurationError, match="recording_folder_pattern"):
        discover_manifest(tmp_path, config_path=config_path)


@pytest.mark.skipif(
    not os.environ.get("DAQ_DATASET_ROOT"),
    reason="Set DAQ_DATASET_ROOT to run the live DAQ inventory count assertion.",
)
def test_live_dataset_manifest_count() -> None:
    """Assert the current inventory count before any CSV parsing is introduced.

    DAQ_EXPECTED_FILE_COUNT defaults to the currently specified inventory (822)
    and can be deliberately updated after a fresh profiling run changes it.
    """
    dataset_root = Path(os.environ["DAQ_DATASET_ROOT"])
    expected_count = int(os.environ.get("DAQ_EXPECTED_FILE_COUNT", "822"))
    manifest = discover_manifest(dataset_root)

    assert len(manifest) == expected_count
