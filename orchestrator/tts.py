"""The date's voice: Fish Audio's live text-to-speech, fed sentence by sentence.

The language model's reply is cut at sentence (and long-clause) boundaries and each
piece is sent to Fish and flushed at once, so the first words are being spoken while
the rest of the reply is still being written. Audio comes back as 24 kHz PCM16 mono,
ready for the client's ring buffer.

One socket is opened ahead of time and kept warm, so a turn does not pay the TLS
handshake. If Fish fails before any audio has gone out, the turn is voiced with the
bundled sample instead; a date never goes silent.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
from collections.abc import AsyncIterator

from . import config
from .audio import VOICE_RATE, sample_speech
from .date_models import VoiceConfig

log = logging.getLogger("orchestrator")

FISH_URL = "wss://api.fish.audio/v1/tts/live"
FRAME_BYTES = int(VOICE_RATE * 0.04) * 2   # 40 ms of PCM16
SENTENCE_END = re.compile(r"(?<=[.!?…。！？])[\"'»”）)]*\s+|(?<=[。！？])")
CLAUSE_BREAK = re.compile(r"(?<=[,;:，、；])\s+")


class SentenceChunker:
    """Splits a token stream into speakable pieces: whole sentences, or a long clause
    when a sentence runs on, so the voice can start early without odd cuts."""

    def __init__(self, first_clause_chars: int = 60, max_chars: int = 160):
        self.buffer = ""
        self.first = True
        self.first_clause_chars = first_clause_chars
        self.max_chars = max_chars

    def push(self, delta: str) -> list[str]:
        self.buffer += delta
        pieces = []
        while True:
            match = SENTENCE_END.search(self.buffer)
            if match and match.end() > 0:
                piece, self.buffer = self.buffer[:match.end()], self.buffer[match.end():]
                if piece.strip():
                    pieces.append(piece.strip())
                    self.first = False
                continue
            limit = self.first_clause_chars if self.first else self.max_chars
            if len(self.buffer) > limit:
                clauses = list(CLAUSE_BREAK.finditer(self.buffer))
                if clauses:
                    cut = clauses[-1].end()
                    piece, self.buffer = self.buffer[:cut], self.buffer[cut:]
                    if piece.strip():
                        pieces.append(piece.strip())
                        self.first = False
                    continue
            return pieces

    def flush(self) -> list[str]:
        rest, self.buffer = self.buffer.strip(), ""
        return [rest] if rest else []


def frames(pcm: bytes) -> list[bytes]:
    return [pcm[i:i + FRAME_BYTES] for i in range(0, len(pcm), FRAME_BYTES)]


class SampleVoice:
    name = "sample"

    async def speak(self, sentences: AsyncIterator[str], voice: VoiceConfig,
                    language: str) -> AsyncIterator[bytes]:
        async for sentence in sentences:
            for frame in frames(sample_speech(sentence)):
                yield frame

    async def prewarm(self):
        return None

    async def aclose(self):
        return None


class FishVoice:
    name = "fish"

    def __init__(self, key: str, model: str):
        self.key = key
        self.model = model
        self.sample_rate = int(os.getenv("FISH_AUDIO_SAMPLE_RATE") or VOICE_RATE)
        self.warm: asyncio.Task | None = None

    async def _connect(self):
        from websockets.asyncio.client import connect
        return await connect(FISH_URL, additional_headers={"Authorization": f"Bearer {self.key}",
                                                           "model": self.model},
                             max_size=16 * 1024 * 1024, open_timeout=6)

    async def prewarm(self):
        """Open the next turn's socket now, while the learner is talking."""
        stale = self.warm is not None and self.warm.done() and (
            self.warm.cancelled() or self.warm.exception() is not None)
        if self.warm is None or stale:
            self.warm = asyncio.create_task(self._connect())
            self.warm.add_done_callback(lambda t: t.cancelled() or t.exception())

    async def _socket(self):
        if self.warm is not None:
            task, self.warm = self.warm, None
            with contextlib.suppress(Exception):
                ws = await task
                if ws.state.name == "OPEN":
                    return ws
                await ws.close()
        return await self._connect()

    async def speak(self, sentences: AsyncIterator[str], voice: VoiceConfig,
                    language: str) -> AsyncIterator[bytes]:
        import ormsgpack
        ws = await self._socket()
        start = {"event": "start", "request": {
            "text": "", "format": "pcm", "sample_rate": self.sample_rate,
            "latency": voice.latency, "reference_id": voice.voice_id or None,
            "prosody": {"speed": voice.speaking_rate, "volume": 0},
            "temperature": voice.temperature, "top_p": 0.7, "normalize": True,
            "language": language, "chunk_length": 100, "min_chunk_length": 0,
            "condition_on_previous_chunks": True}}

        async def send():
            await ws.send(ormsgpack.packb(start))
            async for sentence in sentences:
                await ws.send(ormsgpack.packb({"event": "text", "text": sentence + " "}))
                await ws.send(ormsgpack.packb({"event": "flush"}))
            await ws.send(ormsgpack.packb({"event": "stop"}))

        sender = asyncio.create_task(send())
        remainder = b""
        try:
            async for raw in ws:
                if isinstance(raw, str):
                    continue
                message = ormsgpack.unpackb(raw)
                event = message.get("event")
                if event == "audio" and message.get("audio"):
                    data = remainder + bytes(message["audio"])
                    usable = len(data) - len(data) % 2
                    remainder = data[usable:]
                    for frame in frames(data[:usable]):
                        yield frame
                elif event == "finish":
                    if message.get("reason") == "error":
                        raise RuntimeError("Fish Audio reported an error")
                    break
            if sender.done() and sender.exception() is not None:
                raise sender.exception()
        finally:
            sender.cancel()
            with contextlib.suppress(Exception):
                await ws.close()
            # The next turn's socket opens while this one is being heard.
            await self.prewarm()

    async def aclose(self):
        if self.warm is not None:
            with contextlib.suppress(Exception):
                ws = await self.warm
                await ws.close()


class Voice:
    """The session's voice: Fish when configured, the sample otherwise, and the sample
    for any turn Fish fails before a single frame has been sent."""

    def __init__(self):
        p = config.providers()
        self.primary = FishVoice(p.fish_key, p.fish_model) if p.fish_key else None
        self.fallback = SampleVoice()

    @property
    def name(self) -> str:
        return self.primary.name if self.primary else self.fallback.name

    async def prewarm(self):
        if self.primary is not None:
            await self.primary.prewarm()

    async def speak(self, sentences: AsyncIterator[str], voice: VoiceConfig,
                    language: str) -> AsyncIterator[bytes]:
        if self.primary is None or voice.provider != "fish":
            async for frame in self.fallback.speak(sentences, voice, language):
                yield frame
            return
        # Keep every sentence so the sample can voice them if Fish fails early.
        spoken: list[str] = []
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def pump():
            async for sentence in sentences:
                spoken.append(sentence)
                await queue.put(sentence)
            await queue.put(None)

        async def from_queue():
            while (item := await queue.get()) is not None:
                yield item

        feeder = asyncio.create_task(pump())
        sent_any = False
        try:
            async for frame in self.primary.speak(from_queue(), voice, language):
                sent_any = True
                yield frame
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001
            log.warning("Fish Audio failed (%s)%s", type(error).__name__,
                        "" if sent_any else "; sample voice used for this turn")
            if sent_any:
                return
            await feeder

            async def replay():
                for sentence in spoken:
                    yield sentence

            async for frame in self.fallback.speak(replay(), voice, language):
                yield frame
        finally:
            feeder.cancel()

    async def aclose(self):
        if self.primary is not None:
            await self.primary.aclose()
