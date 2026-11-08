"""Hearing the learner: live speech recognition for the date.

Deepgram's streaming API hears the microphone as it arrives and says when the learner
has finished a thought (endpointing plus utterance-end), so the date can answer about
as soon as a person would. Interim words are passed on for live subtitles; a finished
utterance arrives as one ``final`` event with its confidence and the words the
recogniser doubted.

Without a Deepgram key the session still detects speech (for barge-in and the
wingman's silence timer) but cannot transcribe it; the client can send typed lines.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from urllib.parse import urlencode

from . import config
from .audio import MIC_RATE, EnergyVad

log = logging.getLogger("orchestrator")

DEEPGRAM_URL = "wss://api.deepgram.com/v1/listen"
LOW_CONFIDENCE = 0.6


@dataclass
class SttEvent:
    kind: str                     # speech_started | speech_ended | partial | final | error
    text: str = ""
    confidence: float | None = None
    unsure: list[str] = field(default_factory=list)


class SpeechRecognizer:
    """Base: speech detection from energy, no words. Subclasses add transcription."""

    name = "none"
    transcribes = False

    def __init__(self):
        self.events: asyncio.Queue[SttEvent] = asyncio.Queue()
        self.vad = EnergyVad()

    async def start(self):
        return None

    async def feed(self, pcm: bytes):
        for event in self.vad.feed(pcm):
            await self.events.put(SttEvent("speech_started" if event.kind == "start"
                                           else "speech_ended"))

    async def stream(self) -> AsyncIterator[SttEvent]:
        while True:
            yield await self.events.get()

    async def close(self):
        return None


class DeepgramRecognizer(SpeechRecognizer):
    name = "deepgram"
    transcribes = True

    def __init__(self, key: str, dialect: config.Dialect):
        super().__init__()
        self.key = key
        self.dialect = dialect
        self.ws = None
        self.reader: asyncio.Task | None = None
        self.keepalive: asyncio.Task | None = None
        self.finals: list[str] = []
        self.confidences: list[float] = []
        self.unsure: list[str] = []
        self.failed = False

    def url(self) -> str:
        params = {"model": self.dialect.stt_model, "language": self.dialect.stt_language,
                  "encoding": "linear16", "sample_rate": MIC_RATE, "channels": 1,
                  "interim_results": "true", "punctuate": "true", "smart_format": "true",
                  "endpointing": 300, "utterance_end_ms": 1000, "vad_events": "true"}
        return f"{DEEPGRAM_URL}?{urlencode(params)}"

    async def start(self):
        from websockets.asyncio.client import connect
        self.ws = await connect(self.url(), additional_headers={"Authorization": f"Token {self.key}"},
                                max_size=4 * 1024 * 1024, open_timeout=8)
        self.reader = asyncio.create_task(self._read())
        self.keepalive = asyncio.create_task(self._keepalive())

    async def feed(self, pcm: bytes):
        if self.failed or self.ws is None:
            # Recognition is gone: keep detecting speech so the date can still react.
            await super().feed(pcm)
            return
        try:
            await self.ws.send(pcm)
        except Exception as error:  # noqa: BLE001
            await self._fail(error)

    async def _keepalive(self):
        # Deepgram closes a socket that hears nothing for ~10 s; a muted mic must not end it.
        while True:
            await asyncio.sleep(5)
            with contextlib.suppress(Exception):
                await self.ws.send(json.dumps({"type": "KeepAlive"}))

    async def _read(self):
        try:
            async for raw in self.ws:
                if isinstance(raw, bytes):
                    continue
                await self._message(json.loads(raw))
        except Exception as error:  # noqa: BLE001
            await self._fail(error)

    async def _message(self, msg: dict):
        kind = msg.get("type")
        if kind == "SpeechStarted":
            await self.events.put(SttEvent("speech_started"))
        elif kind == "Results":
            alternatives = (msg.get("channel") or {}).get("alternatives") or [{}]
            best = alternatives[0]
            text = (best.get("transcript") or "").strip()
            if not text:
                if msg.get("speech_final"):
                    await self._flush()
                return
            if msg.get("is_final"):
                self.finals.append(text)
                if isinstance(best.get("confidence"), (int, float)):
                    self.confidences.append(float(best["confidence"]))
                self.unsure += [w.get("punctuated_word") or w.get("word", "")
                                for w in best.get("words") or []
                                if isinstance(w.get("confidence"), (int, float))
                                and w["confidence"] < LOW_CONFIDENCE]
                if msg.get("speech_final"):
                    await self._flush()
                else:
                    await self.events.put(SttEvent("partial", " ".join(self.finals)))
            else:
                await self.events.put(SttEvent("partial", " ".join([*self.finals, text])))
        elif kind == "UtteranceEnd":
            await self._flush()

    async def _flush(self):
        if not self.finals:
            # Speech that produced no words still ends; the silence after it counts.
            await self.events.put(SttEvent("speech_ended"))
            return
        text = " ".join(self.finals).strip()
        confidence = sum(self.confidences) / len(self.confidences) if self.confidences else None
        unsure = [w for w in self.unsure if w][:40]
        self.finals, self.confidences, self.unsure = [], [], []
        await self.events.put(SttEvent("final", text, confidence, unsure))

    async def _fail(self, error: Exception):
        if self.failed:
            return
        self.failed = True
        log.warning("Deepgram stream failed: %s", type(error).__name__)
        await self.events.put(SttEvent("error", "Speech recognition dropped; type instead"))

    async def close(self):
        for task in (self.keepalive, self.reader):
            if task is not None:
                task.cancel()
        if self.ws is not None:
            with contextlib.suppress(Exception):
                await self.ws.send(json.dumps({"type": "CloseStream"}))
                await self.ws.close()


async def create_recognizer(dialect: config.Dialect) -> SpeechRecognizer:
    """Deepgram when configured and reachable; otherwise speech detection only."""
    key = config.providers().deepgram_key
    if key:
        recognizer = DeepgramRecognizer(key, dialect)
        try:
            await recognizer.start()
            return recognizer
        except Exception as error:  # noqa: BLE001
            log.warning("Deepgram unavailable (%s); speech detection only", type(error).__name__)
    return SpeechRecognizer()
