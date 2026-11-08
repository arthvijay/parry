"""One way to ask Claude for structured output.

The matchmaker, the chemistry judge and the date grader all want the same thing: a
system prompt, one JSON payload, and a validated Pydantic object back. This wraps the
Anthropic SDK's ``messages.parse`` with the settings they share: effort per job, a
timeout that fits the job, server-side refusal fallbacks, and a clear error when the
model declines or stops early, so every caller can fall back to its rules.
"""

from __future__ import annotations

import json
import logging
from typing import TypeVar

import anthropic
from pydantic import BaseModel

log = logging.getLogger("orchestrator")

T = TypeVar("T", bound=BaseModel)
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeUnavailable(RuntimeError):
    """Claude declined, ran out of tokens, or returned nothing usable."""


class Claude:
    def __init__(self, *, timeout: float = 30.0, max_retries: int = 1, fallbacks: bool = True,
                 client: anthropic.AsyncAnthropic | None = None):
        # Credentials resolve from the environment (ANTHROPIC_API_KEY, or a profile).
        self.client = client or anthropic.AsyncAnthropic(timeout=timeout, max_retries=max_retries)
        self.fallbacks = fallbacks

    async def parse(self, *, model: str, system: str, payload: dict, schema: type[T],
                    effort: str = "medium", max_tokens: int = 8000,
                    timeout: float | None = None) -> T:
        client = self.client.with_options(timeout=timeout) if timeout else self.client
        request = dict(model=model, max_tokens=max_tokens, system=system,
                       messages=[{"role": "user",
                                  "content": json.dumps(payload, ensure_ascii=False)}],
                       output_format=schema, output_config={"effort": effort})
        if self.fallbacks:
            # On a safety decline the API retries on a fallback model inside the call.
            response = await client.beta.messages.parse(
                **request, betas=[FALLBACK_BETA], fallbacks="default")
        else:
            response = await client.messages.parse(**request)
        if response.stop_reason == "refusal":
            raise ClaudeUnavailable("Claude declined the request")
        if response.stop_reason == "max_tokens":
            raise ClaudeUnavailable("Claude ran out of output tokens")
        parsed = response.parsed_output
        if parsed is None:
            raise ClaudeUnavailable("Claude returned no structured output")
        return parsed

    async def aclose(self):
        await self.client.close()
