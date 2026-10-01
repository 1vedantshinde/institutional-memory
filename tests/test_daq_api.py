"""Integration tests for DAQ API inventory, analysis, retrieval, and config routes."""

from __future__ import annotations

import csv
from pathlib import Path

from fastapi.testclient import TestClient

import api.main as api_main
from api.main import app
from ingestion.quality import CANONICAL_COLUMNS


def _write_csv(path: Path, multiplier: float) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(CANONICAL_COLUMNS)
        writer.writerow([0.0, 1 * multiplier, 2, 3, 4, 5, 6])
        writer.writerow([0.1, 2 * multiplier, 3, 4, 5, 6, 7])


class EvidenceOnlyTestLLM:
    """Provider double used to exercise the real-provider API path."""

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        assert "Do not calculate, estimate, derive, or invent statistics" in prompt
        return "The supplied anomaly findings are cited below."


def test_daq_api_exposes_ingest_profile_analyse_and_evidence_query(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "domain.yaml"
    config.write_text(
        "recording_folder_pattern: '^(?P<condition_id>\\d+)_S(?P<S>\\d+)_F(?P<F>\\d+)_D(?P<D>[\\d.]+)$'\n",
        encoding="utf-8",
    )
    condition = tmp_path / "4_S800_F35_D0.25"
    condition.mkdir()
    _write_csv(condition / "Recording 1.csv", 1.0)
    _write_csv(condition / "Recording 2.csv", 10.0)
    monkeypatch.setattr(api_main, "llm", EvidenceOnlyTestLLM())
    client = TestClient(app)

    response = client.post("/ingest", json={"folder_path": str(tmp_path), "config_path": str(config), "wait": True})
    assert response.status_code == 200
    assert response.json()["summary"] == {
        "discovered": 2, "canonical": 2, "quarantined": 0, "quarantined_by_reason": {}
    }
    assert client.get("/profile").json() == {"status": "complete", **response.json()["summary"]}

    response = client.post("/analyse", json={"condition_id": "4", "window_size_samples": 2, "anomaly_threshold": 0.01, "wait": True})
    assert response.status_code == 200, response.text
    assert response.json()["windows"] == 12
    assert response.json()["findings"] >= 1

    response = client.post("/query", json={"question": "Explain the detected signal deviation.", "filters": {"channel": "Vib_Spindle"}})
    assert response.status_code == 200, response.text
    assert response.json()["citations"]
    citation = response.json()["citations"][0]
    assert citation["source_path"].endswith(".csv")
    assert citation["channel"] == "Vib_Spindle"
    assert "sample_range" in citation


def test_daq_ingest_returns_a_client_error_for_a_missing_dataset() -> None:
    response = TestClient(app).post("/ingest", json={"folder_path": "does-not-exist"})

    assert response.status_code == 400
    assert "DAQ dataset directory does not exist" in response.json()["detail"]


def test_daq_ingest_starts_background_profile_by_default(tmp_path: Path) -> None:
    config = tmp_path / "domain.yaml"
    config.write_text(
        "recording_folder_pattern: '^(?P<condition_id>\\d+)_S(?P<S>\\d+)_F(?P<F>\\d+)_D(?P<D>[\\d.]+)$'\n",
        encoding="utf-8",
    )
    condition = tmp_path / "1_S800_F20_D0.10"
    condition.mkdir()
    _write_csv(condition / "Recording 1.csv", 1.0)

    response = TestClient(app).post("/ingest", json={"folder_path": str(tmp_path), "config_path": str(config)})

    assert response.status_code == 202
    assert response.json() == {"status": "running", "profile_url": "/profile"}
    # Let the background job finish: a still-running ingest makes the next
    # test's POST /ingest return 409 "already running" (intermittent failure).
    import time

    deadline = time.monotonic() + 10
    while api_main.daq_state.ingest_status == "running" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert api_main.daq_state.ingest_status != "running"


def test_analysis_starts_in_the_background_by_default(tmp_path: Path) -> None:
    config = tmp_path / "domain.yaml"
    config.write_text(
        "recording_folder_pattern: '^(?P<condition_id>\\d+)_S(?P<S>\\d+)_F(?P<F>\\d+)_D(?P<D>[\\d.]+)$'\n",
        encoding="utf-8",
    )
    condition = tmp_path / "1_S800_F20_D0.10"
    condition.mkdir()
    _write_csv(condition / "Recording 1.csv", 1.0)
    client = TestClient(app)
    assert client.post("/ingest", json={"folder_path": str(tmp_path), "config_path": str(config), "wait": True}).status_code == 200

    response = client.post("/analyse", json={"condition_id": "1", "window_size_samples": 2})

    assert response.status_code == 202
    assert response.json() == {"status": "running", "analysis_status_url": "/analyse/status"}


def test_cache_fingerprint_ignores_glossary_and_ontology_edits(tmp_path) -> None:
    """Editing definitions or graph types must not force every analysis to re-run."""
    import yaml
    import api.main as daq_api

    base = {"recording_folder_pattern": "^(?P<condition_id>\\d+)$", "windowing": {"window_size_samples": 2048},
            "glossary": [], "entity_types": ["Condition"]}
    path = tmp_path / "domain.yaml"
    path.write_text(yaml.safe_dump(base))
    before = daq_api._analysis_config_hash(path)

    path.write_text(yaml.safe_dump({**base, "glossary": [{"term": "RMS", "definition": "strength"}],
                                    "entity_types": ["Condition", "Document"], "system_prompt_template": "x"}))
    assert daq_api._analysis_config_hash(path) == before

    path.write_text(yaml.safe_dump({**base, "windowing": {"window_size_samples": 1024}}))
    assert daq_api._analysis_config_hash(path) != before
