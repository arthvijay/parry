"""Hearing the learner: live speech recognition for the date, with NVIDIA Nemotron ASR.

The microphone streams into Nemotron ASR Streaming over NVIDIA Riva's gRPC API, either
NVIDIA's hosted endpoint (build.nvidia.com, an API key and a function id) or a
self-hosted Speech NIM. Interim words become live subtitles; each final result is one
finished utterance, with its confidence and the words the model doubted.

Riva reports words, not the moment speech starts, so speech start and end come from a
small local voice detector on the same audio: that is what lets barge-in and the
wingman's silence timer react before the words arrive.

Without NVIDIA credentials (or a reachable server) the session still detects speech but
cannot transcribe it; the client can send typed lines.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import re
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from . import config
from .audio import MIC_RATE, EnergyVad

log = logging.getLogger("orchestrator")

LOW_CONFIDENCE = 0.6
# In auto-detect mode the model appends the language it heard, e.g. "<es-US>".
LANG_TAG = re.compile(r"\s*<[a-z]{2,3}(-[A-Za-z]{2,4})?>\s*")
MAX_RESTARTS = 20


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


def clean(text: str) -> str:
    return LANG_TAG.sub(" ", text or "").strip()


class NemotronRecognizer(SpeechRecognizer):
    """Nemotron ASR Streaming through Riva's StreamingRecognize, on a worker thread.

    Riva's Python client is blocking, so audio goes through a thread-safe queue into a
    generator the client consumes, and responses are handed back to the event loop. If
    the server ends a stream (time limits, a cold worker) it is reopened; audio that
    arrives meanwhile waits in the queue."""

    name = "nemotron"
    transcribes = True

    def __init__(self, p: config.Providers, language: str):
        super().__init__()
        self.providers = p
        self.language = language
        self.audio: queue.Queue[bytes | None] = queue.Queue(maxsize=1500)  # ~30 s of 20 ms frames
        self.loop: asyncio.AbstractEventLoop | None = None
        self.thread: threading.Thread | None = None
        self.closed = threading.Event()
        self.ready = threading.Event()
        self.failed = False
        self.service = None
        self.streaming_config = None

    def _connect(self):
        import riva.client
        metadata = []
        if self.providers.asr_function_id:
            metadata.append(["function-id", self.providers.asr_function_id])
        if self.providers.nvidia_key:
            metadata.append(["authorization", f"Bearer {self.providers.nvidia_key}"])
        auth = riva.client.Auth(uri=self.providers.asr_server, use_ssl=self.providers.asr_ssl,
                                metadata_args=metadata or None)
        self.service = riva.client.ASRService(auth)
        recognition = riva.client.RecognitionConfig(
            encoding=riva.client.AudioEncoding.LINEAR_PCM, sample_rate_hertz=MIC_RATE,
            audio_channel_count=1, language_code=self.language, max_alternatives=1,
            enable_automatic_punctuation=True, enable_word_time_offsets=True)
        self.streaming_config = riva.client.StreamingRecognitionConfig(
            config=recognition, interim_results=True)

    async def start(self):
        self.loop = asyncio.get_running_loop()
        await asyncio.to_thread(self._connect)
        self.thread = threading.Thread(target=self._run, name="nemotron-asr", daemon=True)
        self.thread.start()

    async def feed(self, pcm: bytes):
        # Speech start and end always come from the local detector.
        await super().feed(pcm)
        if self.failed:
            return
        try:
            self.audio.put_nowait(pcm)
        except queue.Full:
            # The stream has stalled for ~30 s: drop the oldest audio, never block the socket.
            try:
                self.audio.get_nowait()
                self.audio.put_nowait(pcm)
            except (queue.Empty, queue.Full):
                pass

    def _chunks(self):
        """What the Riva client sends: microphone audio until the session closes."""
        while not self.closed.is_set():
            try:
                chunk = self.audio.get(timeout=0.5)
            except queue.Empty:
                continue
            if chunk is None:
                return
            yield chunk

    def _emit(self, event: SttEvent):
        if self.loop is not None and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.events.put_nowait, event)

    def _run(self):
        restarts = 0
        while not self.closed.is_set() and restarts <= MAX_RESTARTS:
            started = time.monotonic()
            try:
                responses = self.service.streaming_response_generator(
                    audio_chunks=self._chunks(), streaming_config=self.streaming_config)
                for response in responses:
                    self.ready.set()
                    for result in response.results:
                        self._result(result)
                if self.closed.is_set():
                    return
            except Exception as error:  # noqa: BLE001
                if self.closed.is_set():
                    return
                log.warning("Nemotron ASR stream ended: %s", type(error).__name__)
            # A stream that lived a while just hit a server limit; one that died at once
            # counts towards giving up.
            restarts = 0 if time.monotonic() - started > 30 else restarts + 1
            time.sleep(min(5.0, 0.5 * (restarts + 1)))
        if not self.closed.is_set():
            self.failed = True
            log.warning("Nemotron ASR unavailable; speech detection only")
            self._emit(SttEvent("error", "Speech recognition dropped; type instead"))

    def _result(self, result):
        if not result.alternatives:
            return
        best = result.alternatives[0]
        text = clean(best.transcript)
        if not text:
            return
        if not result.is_final:
            self._emit(SttEvent("partial", text))
            return
        confidence = float(best.confidence) if best.confidence and best.confidence > 0 else None
        unsure = [clean(w.word) for w in best.words
                  if 0 < w.confidence < LOW_CONFIDENCE and clean(w.word)][:40]
        self._emit(SttEvent("final", text, confidence, unsure))

    async def close(self):
        self.closed.set()
        try:
            self.audio.put_nowait(None)
        except queue.Full:
            pass


def asr_language(dialect: config.Dialect) -> str:
    override = config.providers().asr_language
    return override or dialect.asr_language


async def create_recognizer(dialect: config.Dialect) -> SpeechRecognizer:
    """Nemotron ASR when configured; otherwise speech detection only."""
    p = config.providers()
    hosted = p.asr_server == config.NEMOTRON_HOSTED_SERVER
    if p.nvidia_key or not hosted:
        recognizer = NemotronRecognizer(p, asr_language(dialect))
        try:
            await recognizer.start()
            return recognizer
        except Exception as error:  # noqa: BLE001
            log.warning("Nemotron ASR unavailable (%s); speech detection only", type(error).__name__)
    return SpeechRecognizer()
