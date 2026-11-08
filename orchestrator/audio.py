"""Audio plumbing for the live date: PCM16 conversion, resampling, a small voice
activity detector, and the bundled sample voice used when no TTS provider is set up.

The microphone arrives as 16 kHz PCM16 mono; the date's voice leaves as 24 kHz PCM16
mono. Everything here works on those raw bytes.
"""

from __future__ import annotations

import io
import wave
from collections import deque
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np

MIC_RATE = 16000
VOICE_RATE = 24000
SAMPLE_VOICE = Path(__file__).with_name("assets") / "sample_voice_24k.wav"


def pcm16_to_float(data: bytes) -> np.ndarray:
    usable = len(data) - len(data) % 2
    return np.frombuffer(data[:usable], dtype="<i2").astype(np.float32) / 32768.0


def float_to_pcm16(samples: np.ndarray) -> bytes:
    return (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def resample(samples: np.ndarray, source: int, target: int) -> np.ndarray:
    """Linear interpolation: plenty for speech going to a recogniser or a speaker."""
    if source == target or samples.size == 0:
        return samples
    duration = samples.size / source
    n = max(1, int(round(duration * target)))
    positions = np.linspace(0, samples.size - 1, n, dtype=np.float64)
    return np.interp(positions, np.arange(samples.size), samples).astype(np.float32)


def wav_bytes(pcm: bytes, rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm)
    return buffer.getvalue()


def duration_seconds(pcm: bytes, rate: int) -> float:
    return len(pcm) / 2 / rate


@cache
def sample_voice() -> bytes:
    """The bundled voice clip as 24 kHz PCM16 mono, or a soft synthetic murmur if the
    file is missing, so offline playback always has something with a mouth shape."""
    try:
        with wave.open(str(SAMPLE_VOICE), "rb") as clip:
            if clip.getnchannels() == 1 and clip.getsampwidth() == 2:
                pcm = clip.readframes(clip.getnframes())
                rate = clip.getframerate()
                return pcm if rate == VOICE_RATE else float_to_pcm16(
                    resample(pcm16_to_float(pcm), rate, VOICE_RATE))
    except (OSError, wave.Error):
        pass
    t = np.arange(int(VOICE_RATE * 2.0)) / VOICE_RATE
    envelope = np.maximum(0.0, np.sin(t * 6 * np.pi))
    voice = (np.sin(2 * np.pi * 150 * t) + 0.5 * np.sin(2 * np.pi * 300 * t)) * envelope * 0.15
    return float_to_pcm16(voice.astype(np.float32))


def sample_speech(text: str) -> bytes:
    """Sample voice stretched to roughly how long the text would take to say."""
    clip = sample_voice()
    seconds = min(8.0, max(0.8, 0.065 * len(text)))
    want = int(seconds * VOICE_RATE) * 2
    gap = b"\x00\x00" * int(0.12 * VOICE_RATE)
    out = bytearray()
    while len(out) < want:
        out += clip + gap
    return bytes(out[:want])


@dataclass
class VadEvent:
    kind: str           # "start" | "end"
    at: float           # stream time in seconds
    audio: bytes = b""  # for "end": the utterance, PCM16 at MIC_RATE, with pre-roll


class EnergyVad:
    """Voice activity from short-term energy and zero-crossing rate.

    Adapts to the room: the noise floor follows the quiet frames, and speech is energy
    well above it with a voice-like crossing rate. Speech must last ``start_ms`` to
    count and silence ``end_ms`` to end, which keeps a cough from being a turn and a
    breath from ending one.
    """

    FRAME = 320  # 20 ms at 16 kHz

    def __init__(self, rate: int = MIC_RATE, start_ms: int = 120, end_ms: int = 700,
                 ratio: float = 3.2, min_level: float = 0.012, preroll_ms: int = 300,
                 max_seconds: float = 20.0):
        self.rate = rate
        self.start_frames = max(1, start_ms // 20)
        self.end_frames = max(1, end_ms // 20)
        self.ratio = ratio
        self.min_level = min_level
        self.floor = 0.004
        self.speaking = False
        self.voiced = 0
        self.silent = 0
        self.pending = np.zeros(0, dtype=np.float32)
        self.preroll: deque[np.ndarray] = deque(maxlen=max(1, preroll_ms // 20))
        self.utterance: list[np.ndarray] = []
        self.max_frames = int(max_seconds * 50)
        self.frames = 0
        self.level = 0.0

    def feed(self, pcm: bytes) -> list[VadEvent]:
        events = []
        samples = np.concatenate([self.pending, pcm16_to_float(pcm)])
        whole = samples.size - samples.size % self.FRAME
        self.pending = samples[whole:]
        for start in range(0, whole, self.FRAME):
            frame = samples[start:start + self.FRAME]
            self.frames += 1
            event = self._frame(frame)
            if event:
                events.append(event)
        return events

    def _frame(self, frame: np.ndarray) -> VadEvent | None:
        rms = float(np.sqrt(np.mean(frame * frame)) + 1e-9)
        self.level = rms
        crossings = float(np.mean(np.abs(np.diff(np.signbit(frame).astype(np.int8)))))
        voiced = rms > max(self.min_level, self.floor * self.ratio) and 0.01 < crossings < 0.5
        at = self.frames * 0.02
        if not self.speaking:
            self.preroll.append(frame)
            if not voiced:
                self.floor = 0.95 * self.floor + 0.05 * rms
            self.voiced = self.voiced + 1 if voiced else 0
            if self.voiced >= self.start_frames:
                self.speaking, self.silent = True, 0
                self.utterance = list(self.preroll)
                return VadEvent("start", at - self.voiced * 0.02)
            return None
        self.utterance.append(frame)
        self.silent = 0 if voiced else self.silent + 1
        if self.silent >= self.end_frames or len(self.utterance) >= self.max_frames:
            self.speaking, self.voiced = False, 0
            audio = float_to_pcm16(np.concatenate(self.utterance))
            self.utterance = []
            self.preroll.clear()
            return VadEvent("end", at, audio)
        return None
