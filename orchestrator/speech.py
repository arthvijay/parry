"""Stable boundary for the separately owned ElevenLabs implementation."""

from dataclasses import dataclass
from importlib import import_module
from typing import Any, Protocol
from uuid import UUID


SUPPORTED_AUDIO_TYPES = frozenset({
    "audio/wav", "audio/x-wav", "audio/mpeg", "audio/webm", "audio/ogg",
    "audio/mp4", "audio/pcm",
})


@dataclass(frozen=True)
class SpeechInput:
    audio: bytes
    media_type: str
    session_id: UUID
    npc_id: str
    scenario_id: UUID | None = None
    scenario: dict[str, Any] | None = None
    # Required for raw signed PCM16 little-endian mono; absent for containers.
    sample_rate: int | None = None
    # Groups the conversations of one visit so a character can know what the learner
    # ordered from another character. Defaults to the session when the client omits it.
    run_id: str | None = None
    # Addresses the learner by name in the scenario's prompts.
    learner_name: str | None = None
    # CEFR level (A1, A2, B1, B2): how simply and how fast the characters speak.
    learner_level: str | None = None
    # Set when the learner cut the previous reply short: how many milliseconds of it
    # they actually heard before pressing talk. Lets the character know where it was
    # interrupted instead of believing it finished the sentence.
    interrupted_at_ms: int | None = None


@dataclass(frozen=True)
class SpeechOutput:
    audio: bytes
    media_type: str
    sample_rate: int | None = None
    user_transcript: str | None = None
    agent_transcript: str | None = None
    # Scene actions the character triggered this turn, in order. The game client
    # plays them; the conversation never waits for it.
    actions: tuple[dict[str, Any], ...] = ()
    # Mouth shapes for the whole reply: ({"t": start_ms, "d": duration_ms, "v": viseme}, ...)
    visemes: tuple[dict[str, Any], ...] = ()
    # Words the recogniser was unsure of: a hint at pronunciation, never a verdict.
    low_confidence_words: tuple[str, ...] = ()
    min_logprob: float | None = None
    # Where the time went, in milliseconds, so latency is measured rather than claimed.
    timings_ms: dict[str, int] | None = None
    # True when the character ended the conversation (said goodbye and hung up).
    ended: bool = False
    # What the learner actually heard of the PREVIOUS reply, when they interrupted it.
    previous_reply_heard: str | None = None


class SpeechProvider(Protocol):
    async def respond(self, request: SpeechInput) -> SpeechOutput:
        """Return one complete spoken reply; propagate cancellation on timeout.

        Own session memory keyed by session_id, NPC switching, audio decoding,
        transcription, provider calls, and resource/session cleanup. Never block
        the event loop. The API supplies the validated scenario if one is selected.
        """
        ...


def load_speech_provider(path: str) -> SpeechProvider:
    """Load an operator-configured, zero-argument factory: package.module:create."""
    module, separator, factory = path.partition(":")
    if not separator or not module or not factory:
        raise ValueError("SPEECH_ADAPTER must be package.module:factory")
    provider = getattr(import_module(module), factory)()
    if not callable(getattr(provider, "respond", None)):
        raise TypeError("Speech adapter must provide async respond(request)")
    return provider


class SpeechInputError(ValueError):
    """Audio or session input cannot be processed (safe client-facing message)."""


class SpeechUnavailable(RuntimeError):
    """Requested voice configuration is unavailable (safe client-facing message)."""
