"""Scripted lines, spoken once.

The host's greeting, the date's opening line, the look-away callouts and the authored
closings are fixed text. The first time one is voiced by ElevenLabs its audio is kept,
keyed by everything that shapes the sound (text, voice, speed, stability, similarity,
language, TTS model, sample rate); after that it plays from disk, instantly and free. A
"try again" with the same date replays its opener from here.

Only a line that finished playing is kept: a barge-in or a provider failure leaves
nothing behind, so the cache never holds half a sentence.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

from .date_models import VoiceConfig

log = logging.getLogger("orchestrator")

KEY = re.compile(r"^[0-9a-f]{64}$")
MAX_LINE_BYTES = 8 * 1024 * 1024     # ~2.9 minutes at 24 kHz PCM16; no line is that long


class VoiceCache:
    def __init__(self, directory: Path):
        self.directory = directory

    @staticmethod
    def key(text: str, voice: VoiceConfig, language: str, model: str, sample_rate: int) -> str:
        shape = [text.strip(), voice.voice_id, round(voice.speaking_rate, 3),
                 round(voice.stability, 3), round(voice.similarity_boost, 3), language,
                 model, int(sample_rate)]
        return hashlib.sha256(json.dumps(shape, ensure_ascii=False).encode()).hexdigest()

    def _path(self, key: str) -> Path:
        if not KEY.match(key):
            raise ValueError("Invalid voice cache key")
        return self.directory / key[:2] / f"{key}.pcm"

    def get(self, key: str) -> bytes | None:
        try:
            path = self._path(key)
            return path.read_bytes() if path.is_file() else None
        except (OSError, ValueError):
            return None

    def put(self, key: str, pcm: bytes):
        if not pcm or len(pcm) > MAX_LINE_BYTES:
            return
        try:
            path = self._path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".tmp")
            temp.write_bytes(pcm)
            temp.replace(path)
        except (OSError, ValueError) as error:
            log.warning("Voice line not cached: %s", type(error).__name__)
