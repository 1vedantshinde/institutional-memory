"""Tests for deterministic frontend question-to-DAQ-scope routing."""

from server import infer_channel, infer_condition_id


def test_chat_scope_inference_uses_explicit_condition_and_canonical_channel() -> None:
    assert infer_condition_id("Explain spindle vibration for condition 4") == "4"
    assert infer_channel("Explain spindle vibration for condition 4") == "Vib_Spindle"
    assert infer_channel("Is the Z-axis load stable for condition 4?") == "Z_Load_Cell"


def test_chat_scope_inference_does_not_guess_ambiguous_signal_or_condition() -> None:
    assert infer_condition_id("Is vibration high?") is None
    assert infer_channel("Compare spindle and table vibration for condition 4") is None
