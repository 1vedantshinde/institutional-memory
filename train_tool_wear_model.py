#!/usr/bin/env python3
"""Train and evaluate the DAQ tool-wear regressor on real recordings/labels."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import joblib

from analytics.tool_wear import (
    build_tool_wear_dataset,
    load_tool_wear_labels,
    train_and_evaluate_tool_wear,
)
from core.schema import Condition
from ingestion.manifest import discover_manifest
from ingestion.pipeline import ingest_daq_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", default="Readngs_DAQ_Data")
    parser.add_argument("--wear-workbook", default="Tool_Wear_Value_Table.xlsx")
    parser.add_argument("--config", default="config/domain.yaml")
    parser.add_argument("--max-samples", type=int, default=8192)
    parser.add_argument("--test-fraction", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", default="artifacts/tool_wear")
    arguments = parser.parse_args()

    manifest = discover_manifest(arguments.dataset_root, config_path=arguments.config)
    conditions = {
        entry["condition_id"]: Condition(
            condition_id=entry["condition_id"],
            S=entry["S"], F=entry["F"], D=entry["D"],
            source_folder=Path(entry["source_path"]).parent.name,
        )
        for entry in manifest
    }
    run = ingest_daq_dataset(arguments.dataset_root, config_path=arguments.config)
    labels = load_tool_wear_labels(arguments.wear_workbook)
    dataset = build_tool_wear_dataset(
        run.recordings, conditions, labels, max_samples=arguments.max_samples
    )
    model, evaluation = train_and_evaluate_tool_wear(
        dataset,
        run.recordings,
        test_fraction=arguments.test_fraction,
        seed=arguments.seed,
    )
    output_dir = Path(arguments.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {"model": model, "feature_names": dataset.feature_names, "model_version": evaluation.model_version},
        output_dir / "model.joblib",
    )
    report = {
        "dataset_root": str(Path(arguments.dataset_root).resolve()),
        "wear_workbook": str(Path(arguments.wear_workbook).resolve()),
        "ingestion_summary": run.summary.as_dict(),
        "labelled_canonical_recordings": len(dataset.recording_ids),
        "feature_count": len(dataset.feature_names),
        "evaluation": asdict(evaluation),
    }
    (output_dir / "evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
