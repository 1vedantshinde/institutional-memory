"""Tests for deterministic frontend question-to-DAQ-scope routing."""

from server import infer_channel, infer_condition_id


def test_chat_scope_inference_uses_explicit_condition_and_canonical_channel() -> None:
    assert infer_condition_id("Explain spindle vibration for condition 4") == "4"
    assert infer_channel("Explain spindle vibration for condition 4") == "Vib_Spindle"
    assert infer_channel("Is the Z-axis load stable for condition 4?") == "Z_Load_Cell"


def test_chat_scope_inference_does_not_guess_ambiguous_signal_or_condition() -> None:
    assert infer_condition_id("Is vibration high?") is None
    assert infer_channel("Compare spindle and table vibration for condition 4") is None


def test_chat_reuses_a_broader_cached_analysis_instead_of_reanalysing(monkeypatch) -> None:
    """A condition-wide (all-channel) cache covers a single-channel question."""
    import api.main as daq_api
    import server

    state = daq_api.daq_state
    monkeypatch.setattr(state, "dataset_fingerprint", "fp")
    monkeypatch.setattr(state, "analysis_status", "idle")
    monkeypatch.setattr(state, "windows", [])
    monkeypatch.setattr(state, "findings", [])
    monkeypatch.setattr(state, "baselines", None)

    condition_wide = daq_api._analysis_cache_path(
        daq_api._analysis_cache_key("fp", daq_api.AnalyseRequest(condition_id="4"))
    )
    payload = {"result": {"findings": 0}, "windows": [], "findings": [], "baselines": []}
    monkeypatch.setattr(daq_api, "_read_cache", lambda path: payload if path == condition_wide else None)
    hydrated: list[tuple] = []
    monkeypatch.setattr(daq_api, "_hydrate_analysis_state", lambda *args: hydrated.append(args))
    started: list[object] = []
    monkeypatch.setattr(server.threading, "Thread", lambda *a, **k: started.append(k) or None)

    assert server._start_automatic_analysis("4", "Vib_Spindle") is True
    assert hydrated, "cache was not restored"
    assert started == [], "a new analysis was started despite a covering cache"
    assert state.analysis_status == "complete"
