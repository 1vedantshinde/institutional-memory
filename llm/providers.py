"""Real LLM provider implementations.

Add new providers here and register them with @llm_registry.register("<key>").
Set the LLM_PROVIDER environment variable to the desired key at runtime.
"""
import os
from typing import Optional
from core.registry import llm_registry, BaseLLM


@llm_registry.register("anthropic")
class AnthropicLLM(BaseLLM):
    """Anthropic Claude backend — requires ANTHROPIC_API_KEY env var."""

    def __init__(self, model: str = "claude-sonnet-4-5", max_tokens: int = 1024):
        from anthropic import Anthropic
        self.client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.model = model
        self.max_tokens = max_tokens

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system_prompt or "",
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in resp.content if block.type == "text")
