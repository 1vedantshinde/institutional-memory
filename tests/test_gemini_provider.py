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
