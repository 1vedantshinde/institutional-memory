"""Gemini provider resilience without making an external API request."""

from __future__ import annotations

import pytest

from core.registry import GeminiLLM, LLMProviderUnavailableError


class _Config:
    pass


class _Types:
    @staticmethod
    def GenerateContentConfig(**_kwargs):
        return _Config()


class _CapacityError(Exception):
    code = 503


class _UnavailableModels:
    def generate_content(self, **_kwargs):
        raise _CapacityError("busy")


class _Client:
    models = _UnavailableModels()


def test_gemini_transient_capacity_failure_is_explicit(monkeypatch) -> None:
    provider = GeminiLLM.__new__(GeminiLLM)
    provider.client = _Client()
    provider.types = _Types()
    provider.model = "test-model"
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "0")

    with pytest.raises(LLMProviderUnavailableError, match="HTTP 503"):
        provider.generate("evidence-only test")


class _Ok:
    text = "grounded answer"


class _PrimaryBusyFallbackOk:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def generate_content(self, *, model, **_kwargs):
        self.calls.append(model)
        if model == "primary":
            raise _CapacityError("busy")
        return _Ok()


def _provider(models, fallbacks):
    provider = GeminiLLM.__new__(GeminiLLM)
    provider.client = type("C", (), {"models": models})()
    provider.types = _Types()
    provider.model = "primary"
    provider.fallback_models = fallbacks
    return provider


def test_gemini_falls_back_to_next_configured_model_when_primary_is_busy(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "0")
    models = _PrimaryBusyFallbackOk()
    assert _provider(models, ["fallback"]).generate("evidence-only test") == "grounded answer"
    assert models.calls == ["primary", "fallback"]


def test_gemini_reports_every_unavailable_model(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "0")
    with pytest.raises(LLMProviderUnavailableError, match=r"primary \(HTTP 503, 1 attempt\(s\)\), other \(HTTP 503, 1 attempt\(s\)\)"):
        _provider(_UnavailableModels(), ["other"]).generate("evidence-only test")


def test_gemini_moves_on_after_one_failure_and_retries_only_the_last_model(monkeypatch) -> None:
    class _AllBusy:
        calls: list[str] = []

        def generate_content(self, *, model, **_kwargs):
            _AllBusy.calls.append(model)
            raise _CapacityError("busy")

    monkeypatch.setenv("GEMINI_MAX_RETRIES", "2")
    monkeypatch.setattr("core.registry.time.sleep", lambda _s: None)
    with pytest.raises(LLMProviderUnavailableError):
        _provider(_AllBusy(), ["fallback"]).generate("evidence-only test")
    assert _AllBusy.calls == ["primary", "fallback", "fallback", "fallback"]


def test_gemini_does_not_fall_back_on_permanent_errors(monkeypatch) -> None:
    class _BadRequest(Exception):
        code = 400

    class _Models:
        calls = 0

        def generate_content(self, **_kwargs):
            _Models.calls += 1
            raise _BadRequest("invalid")

    monkeypatch.setenv("GEMINI_MAX_RETRIES", "2")
    with pytest.raises(_BadRequest):
        _provider(_Models(), ["fallback"]).generate("evidence-only test")
    assert _Models.calls == 1
