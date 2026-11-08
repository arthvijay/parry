"""The date's mind during the conversation: streaming replies, token by token.

Gemini Flash speaks during the date because time to first token is what the learner
feels; its stream goes straight into the sentence chunker and on to the voice. Claude
stands in when no Gemini credentials are set, and a scripted brain built from the
dialect's authored lines keeps an offline demo talking.

Every brain gets the same input: the persona prompt, the conversation as alternating
learner and date turns, and the silent notes for this turn ([CHEMISTRY], [NONVERBAL],
[SCENE]) appended to the newest learner line.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from . import config

log = logging.getLogger("orchestrator")

MAX_REPLY_TOKENS = 400


@dataclass
class Turn:
    role: str      # "learner" | "date"
    text: str


@dataclass
class BrainContext:
    """What the scripted brain needs that a model reads from the prompt instead."""

    dialect: str
    chemistry: int
    nonverbal: list[str] = field(default_factory=list)
    interests: list[str] = field(default_factory=list)


def with_notes(history: list[Turn], notes: list[str]) -> list[Turn]:
    """The conversation with this turn's silent notes folded into the newest learner
    line, starting with a learner turn and alternating, as every provider wants."""
    turns = [Turn(t.role, t.text) for t in history if t.text.strip()]
    if not turns or turns[0].role != "learner":
        turns.insert(0, Turn("learner", "[SCENE] The learner has just sat down across from you."))
    merged: list[Turn] = []
    for turn in turns:
        if merged and merged[-1].role == turn.role:
            merged[-1].text += "\n" + turn.text
        else:
            merged.append(turn)
    if notes:
        block = "\n".join(notes)
        if merged[-1].role == "learner":
            merged[-1].text = f"{merged[-1].text}\n\n{block}"
        else:
            merged.append(Turn("learner", block))
    return merged


class GeminiBrain:
    name = "gemini"

    def __init__(self, m: config.Models):
        from google import genai
        if m.gemini_vertex:
            self.client = genai.Client(enterprise=True, project=m.gemini_project,
                                       location=m.gemini_location)
        else:
            self.client = genai.Client(api_key=m.gemini_key)
        self.model = m.date_brain
        self.thinking = m.date_brain_thinking

    async def reply(self, system: str, history: list[Turn], notes: list[str],
                    ctx: BrainContext) -> AsyncIterator[str]:
        from google.genai import types
        contents = [types.Content(role="user" if t.role == "learner" else "model",
                                  parts=[types.Part(text=t.text)])
                    for t in with_notes(history, notes)]
        generation = types.GenerateContentConfig(
            system_instruction=system, max_output_tokens=MAX_REPLY_TOKENS,
            thinking_config=types.ThinkingConfig(thinking_level=self.thinking))
        stream = await self.client.aio.models.generate_content_stream(
            model=self.model, contents=contents, config=generation)
        async for chunk in stream:
            if chunk.text:
                yield chunk.text

    async def aclose(self):
        return None


class ClaudeBrain:
    name = "claude"

    def __init__(self, m: config.Models):
        import anthropic
        self.client = anthropic.AsyncAnthropic(timeout=20.0, max_retries=1)
        self.model = m.chemistry

    async def reply(self, system: str, history: list[Turn], notes: list[str],
                    ctx: BrainContext) -> AsyncIterator[str]:
        messages = [{"role": "user" if t.role == "learner" else "assistant", "content": t.text}
                    for t in with_notes(history, notes)]
        async with self.client.messages.stream(
                model=self.model, max_tokens=2000, system=system, messages=messages,
                output_config={"effort": "low"}) as stream:
            async for text in stream.text_stream:
                yield text

    async def aclose(self):
        await self.client.close()


class ScriptedBrain:
    """Offline: reactions and questions in the dialect, warmer or drier with chemistry."""

    name = "scripted"

    def __init__(self):
        self.rng = random.Random(7)
        self.turn = 0
        self.reacted: set[str] = set()

    async def reply(self, system: str, history: list[Turn], notes: list[str],
                    ctx: BrainContext) -> AsyncIterator[str]:
        offline = config.dialect_content(ctx.dialect)["offline"]
        self.turn += 1
        learner = next((t.text for t in reversed(history) if t.role == "learner"), "")
        parts = []
        for kind in ("puzzled", "smile"):
            if any(kind in note for note in ctx.nonverbal) and kind not in self.reacted:
                self.reacted.add(kind)
                parts.append(offline[kind])
                break
        if not learner.strip():
            parts.append(self.rng.choice(offline["nudges"]))
        elif ctx.chemistry < 40:
            parts.append(offline["reactions"][self.turn % len(offline["reactions"])])
        else:
            parts.append(offline["reactions"][self.turn % len(offline["reactions"])])
            parts.append(offline["questions"][self.turn % len(offline["questions"])])
        for word in " ".join(parts).split(" "):
            await asyncio.sleep(0)
            yield word + " "

    async def aclose(self):
        return None


def create_brain():
    """Gemini when configured, then Claude, then the scripted brain."""
    m = config.models()
    if m.gemini_ready:
        try:
            return GeminiBrain(m)
        except Exception as error:  # noqa: BLE001
            log.warning("Gemini unavailable (%s)", type(error).__name__)
    if m.anthropic_ready:
        return ClaudeBrain(m)
    return ScriptedBrain()
