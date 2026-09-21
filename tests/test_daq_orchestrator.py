"""Tests for evidence-only DAQ explanation prompting and orchestration."""

from __future__ import annotations

import pytest

from core.schema import Condition, Finding, Recording, SignalWindow
from knowledge.graph_store import Neo4jSimulationDriver
from knowledge.ontology import populate_provenance_graph
from llm.orchestrator import DAQExplanationError, DAQExplanationOrchestrator
from llm.prompt_builder import build_daq_explanation_prompt


class CapturingLLM:
    def __init__(self) -> None:
        self.prompt = ""
        self.system_prompt = ""

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        self.prompt = prompt
        self.system_prompt = system_prompt or ""
        return "The supplied anomaly is cited as [finding-1]."


def _evidence() -> dict:
    return {
        "recording_id": "4/Recording 1",
        "source_path": "/dataset/4_S800_F35_D0.25/Recording 1.csv",
        "channel": "Vib_Spindle",
        "window_id": "window-1",
        "sample_range": {"sample_start": 0, "sample_end": 2048},
        "time_range": {"time_start": 0.0, "time_end": 20.47},
        "condition_id": "4",
    }


def _finding() -> Finding:
    return Finding(finding_id="finding-1", recording_id="4/Recording 1", window_id="window-1", finding_type="anomaly", score=4.2, evidence=_evidence(), model_version="mahalanobis-diagonal-v1")


def test_orchestrator_explains_only_computed_facts_and_returns_fixed_citations() -> None:
    condition = Condition(condition_id="4", S=800, F=35, D=0.25, source_folder="4_S800_F35_D0.25")
    recording = Recording(recording_id="4/Recording 1", condition_id="4", source_path=_evidence()["source_path"], checksum="test", schema_status="canonical")
    window = SignalWindow(window_id="window-1", recording_id=recording.recording_id, channel="Vib_Spindle", sample_start=0, sample_end=2048)
    driver = Neo4jSimulationDriver()
    populate_provenance_graph(driver, [condition], [recording], [window], [_finding()])
    llm = CapturingLLM()

    result = DAQExplanationOrchestrator(llm, driver).explain("Explain this anomaly", [_finding()], {"4": condition})

    assert "Do not calculate, estimate, derive, or invent statistics" in llm.prompt
    assert "raw signal" not in llm.prompt.lower()
    assert result["citations"] == [{"finding_id": "finding-1", **_evidence()}]
    assert result["graph_context"]


def test_orchestrator_refuses_to_call_llm_without_a_path_channel_and_range() -> None:
    incomplete = _finding()
    incomplete.evidence.pop("source_path")
    llm = CapturingLLM()

    with pytest.raises(DAQExplanationError, match="finding_missing_traceable_evidence"):
        DAQExplanationOrchestrator(llm, Neo4jSimulationDriver()).explain("Explain", [incomplete], {})
    assert llm.prompt == ""
