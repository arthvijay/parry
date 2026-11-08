"""The date's voice: ElevenLabs' streaming text-to-speech, fed sentence by sentence.

The language model's reply is cut at sentence (and long-clause) boundaries and each
piece is sent to ElevenLabs and flushed at once, so the first words are being spoken
while the rest of the reply is still being written. Audio comes back as 24 kHz PCM16
mono, ready for the client's ring buffer.

One socket is opened ahead of time and kept warm, so a turn does not pay the TLS
handshake. If ElevenLabs fails before any audio has gone out, the turn is voiced with
the bundled sample instead; a date never goes silent.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import re
from collections.abc import AsyncIterator

from . import config
from .audio import VOICE_RATE, sample_speech
from .date_models import VoiceConfig

log = logging.getLogger("orchestrator")

ELEVENLABS_URL = "wss://api.elevenlabs.io/v1/text-to-speech"
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

    async def prewarm(self, voice: VoiceConfig | None = None):
        return None

    async def aclose(self):
        return None


class ElevenLabsVoice:
    """ElevenLabs text-to-speech over its input-streaming WebSocket.

    The voice is part of the URL, so a socket opened ahead of time only serves the voice
    it was opened for; the date's voice is the one kept warm, since it speaks most."""

    name = "elevenlabs"

    def __init__(self, key: str, model: str):
        self.key = key
        self.model = model
        self.warm: tuple[str, asyncio.Task] | None = None

    def url(self, voice_id: str) -> str:
        return (f"{ELEVENLABS_URL}/{voice_id}/stream-input?model_id={self.model}"
                f"&output_format=pcm_{VOICE_RATE}&inactivity_timeout=60")

    async def _connect(self, voice_id: str):
        from websockets.asyncio.client import connect
        return await connect(self.url(voice_id), additional_headers={"xi-api-key": self.key},
                             max_size=16 * 1024 * 1024, open_timeout=6)

    async def prewarm(self, voice: VoiceConfig | None = None):
        """Open the next turn's socket now, while the learner is talking."""
        if voice is None or not voice.voice_id:
            return
        if self.warm is not None:
            warm_voice, task = self.warm
            stale = task.done() and (task.cancelled() or task.exception() is not None)
            if warm_voice == voice.voice_id and not stale:
                return
            if not task.done():
                task.cancel()
        task = asyncio.create_task(self._connect(voice.voice_id))
        task.add_done_callback(lambda t: t.cancelled() or t.exception())
        self.warm = (voice.voice_id, task)

    async def _socket(self, voice_id: str):
        if self.warm is not None and self.warm[0] == voice_id:
            task, self.warm = self.warm[1], None
            with contextlib.suppress(Exception):
                ws = await task
                if ws.state.name == "OPEN":
                    return ws
                await ws.close()
        return await self._connect(voice_id)

    async def speak(self, sentences: AsyncIterator[str], voice: VoiceConfig,
                    language: str) -> AsyncIterator[bytes]:
        ws = await self._socket(voice.voice_id)
        start = {"text": " ",
                 "voice_settings": {"stability": voice.stability,
                                    "similarity_boost": voice.similarity_boost,
                                    "speed": voice.speaking_rate},
                 # Small first chunks: the first words are spoken sooner.
                 "generation_config": {"chunk_length_schedule": [50, 90, 120, 150]}}

        async def send():
            await ws.send(json.dumps(start))
            async for sentence in sentences:
                await ws.send(json.dumps({"text": sentence + " ", "flush": True}))
            await ws.send(json.dumps({"text": ""}))

        sender = asyncio.create_task(send())
        remainder = b""
        try:
            async for raw in ws:
                message = json.loads(raw)
                if message.get("audio"):
                    data = remainder + base64.b64decode(message["audio"])
                    usable = len(data) - len(data) % 2
                    remainder = data[usable:]
                    for frame in frames(data[:usable]):
                        yield frame
                elif message.get("error") or (message.get("message") and not message.get("isFinal")):
                    # A bad voice id, quota or key: ElevenLabs says why, then closes.
                    raise RuntimeError(str(message.get("message") or message.get("error"))[:200])
                if message.get("isFinal"):
                    break
            if sender.done() and sender.exception() is not None:
                raise sender.exception()
        finally:
            sender.cancel()
            with contextlib.suppress(Exception):
                await ws.close()
            # The next turn's socket opens while this one is being heard.
            await self.prewarm(voice)

    async def aclose(self):
        if self.warm is not None:
            with contextlib.suppress(Exception):
                ws = await self.warm[1]
                await ws.close()


class Voice:
    """The session's voice: ElevenLabs when configured, the sample otherwise, and the
    sample for any turn ElevenLabs fails before a single frame has been sent."""

    def __init__(self):
        p = config.providers()
        self.primary = ElevenLabsVoice(p.elevenlabs_key, p.elevenlabs_model) \
            if p.elevenlabs_key else None
        self.fallback = SampleVoice()

    @property
    def name(self) -> str:
        return self.primary.name if self.primary else self.fallback.name

    async def prewarm(self, voice: VoiceConfig | None = None):
        if self.primary is not None and voice is not None and voice.provider == "elevenlabs":
            await self.primary.prewarm(voice)

    async def speak(self, sentences: AsyncIterator[str], voice: VoiceConfig,
                    language: str) -> AsyncIterator[bytes]:
        if self.primary is None or voice.provider != "elevenlabs":
            async for frame in self.fallback.speak(sentences, voice, language):
                yield frame
            return
        # Keep every sentence so the sample can voice them if ElevenLabs fails early.
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
            log.warning("ElevenLabs failed (%s: %s)%s", type(error).__name__, error,
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
