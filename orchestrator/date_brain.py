"""The date's mind during the conversation: streaming replies, token by token.

Claude speaks as the date. Time to first token is what the learner feels, so its stream
goes straight into the sentence chunker and on to the voice. A scripted brain built from
the dialect's authored lines answers a turn Claude cannot, and keeps an offline demo
talking.

Every brain gets the same input: the persona prompt, the conversation as alternating
learner and date turns, and the silent notes for this turn ([CHEMISTRY], [NONVERBAL],
[SCENE]) appended to the newest learner line.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from . import config, costs

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


class ClaudeBrain:
    name = "claude"

    def __init__(self, m: config.Models):
        import anthropic
        self.client = anthropic.AsyncAnthropic(timeout=20.0, max_retries=1)
        self.model = m.date_claude_model

    async def reply(self, system: str, history: list[Turn], notes: list[str],
                    ctx: BrainContext) -> AsyncIterator[str]:
        messages = [{"role": "user" if t.role == "learner" else "assistant", "content": t.text}
                    for t in with_notes(history, notes)]
        async with self.client.messages.stream(
                model=self.model, max_tokens=2000, system=system, messages=messages,
                output_config={"effort": "low"}) as stream:
            async for text in stream.text_stream:
                yield text
            final = await stream.get_final_message()
            costs.claude_usage(self.model, getattr(final, "usage", None))

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


# A provider out of quota is skipped for a while, across sessions, so a turn does not
# wait on a request that is bound to fail.
QUOTA_COOLDOWN = 600.0
FIRST_WORD_SECONDS = 5.0
_resting: dict[str, float] = {}


def out_of_quota(error: Exception) -> bool:
    text = f"{type(error).__name__} {error}"
    return any(mark in text for mark in ("429", "RESOURCE_EXHAUSTED", "RateLimit", "quota"))


class ChainBrain:
    """Tries each brain in order; the first to produce words answers the turn. A brain
    that fails before its first word hands the turn to the next one."""

    def __init__(self, brains: list, first_word_seconds: float | None = None,
                 rest_when_slow: bool = True):
        self.brains = brains
        self.first_word_seconds = first_word_seconds
        self.rest_when_slow = rest_when_slow

    def _ready(self) -> list:
        now = time.monotonic()
        ready = [b for b in self.brains if _resting.get(b.name, 0.0) <= now]
        return ready or self.brains[-1:]

    @property
    def name(self) -> str:
        return self._ready()[0].name

    async def reply(self, system: str, history: list[Turn], notes: list[str],
                    ctx: BrainContext) -> AsyncIterator[str]:
        ready = self._ready()
        for i, brain in enumerate(ready):
            produced = False
            stream = brain.reply(system, history, notes, ctx).__aiter__()
            try:
                # A brain that has not started within FIRST_WORD_SECONDS (a hung request,
                # an SDK quietly retrying) hands over, unless it is the last one left.
                last = i == len(ready) - 1
                limit = self.first_word_seconds or FIRST_WORD_SECONDS
                first = await (stream.__anext__() if last else
                               asyncio.wait_for(stream.__anext__(), limit))
                produced = True
                yield first
                async for delta in stream:
                    yield delta
                return
            except StopAsyncIteration:
                return
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001
                if produced or i == len(ready) - 1:
                    raise
                with contextlib.suppress(Exception):
                    await stream.aclose()
                slow = isinstance(error, asyncio.TimeoutError)
                if out_of_quota(error) or (slow and self.rest_when_slow):
                    _resting[brain.name] = time.monotonic() + QUOTA_COOLDOWN
                    log.warning("Date brain %s is %s; %s answers for the next %d min", brain.name,
                                "too slow" if isinstance(error, asyncio.TimeoutError) else "out of quota",
                                ready[i + 1].name, QUOTA_COOLDOWN // 60)
                else:
                    log.warning("Date brain %s failed (%s: %s); %s answers", brain.name,
                                type(error).__name__, str(error)[:160], ready[i + 1].name)

    async def aclose(self):
        for brain in self.brains:
            await brain.aclose()


def create_brain():
    """Who speaks as the date: Claude, with the scripted brain behind it for a turn Claude
    cannot answer; the scripted brain alone without an Anthropic key."""
    m = config.models()
    if not m.anthropic_ready:
        return ScriptedBrain()
    # Claude is the one real brain here: a slow first word is waited for (up to 12 s)
    # and never benched; only a failure falls to the scripted lines for that turn.
    return ChainBrain([ClaudeBrain(m), ScriptedBrain()], first_word_seconds=12.0,
                      rest_when_slow=False)
