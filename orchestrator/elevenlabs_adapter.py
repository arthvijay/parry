"""ElevenLabs voice adapter: one learner utterance in, the character's reply streamed out.

The reply is forwarded frame by frame as the agent produces it, so the learner hears
the first word about a second after they stop talking instead of after the whole
reply has been generated. `respond()` is the same path, collected into one WAV, for
clients that have not switched to streaming.


Uploads are transcribed with ElevenLabs Scribe, then sent as user_message to the
existing voice agent. Left to guess, Scribe hears a learner's accented Spanish as
Italian, Portuguese or English, so every clip is transcribed pinned to the scenario's
language: the learner is here to speak it, and a Spanish transcript of an English
sentence is a better prompt for the character than a confident English one. Pass
several `languages` to fall back to detection (with a re-transcription when the guess
is outside them). The scripts remain standalone; importing them would load
credentials and (for the beginner demo) mutate shared agent configuration.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
import time
import wave
from collections import deque
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, field
from uuid import UUID

import httpx

from .gestures import infer as infer_gesture
from .scene import RunState, ScenePack, default_pack_dir
from .speech import SpeechInput, SpeechOutput, SpeechInputError, SpeechUnavailable
from .visemes import heard_prefix, timeline

log = logging.getLogger("orchestrator")

MAX_REPLY = 10 * 1024 * 1024 - 44  # leave room for a WAV header
# Scribe reports ISO-639-3; the scenario is written with two-letter codes.
ISO_639 = {"spa": "es", "eng": "en", "ita": "it", "por": "pt", "fra": "fr", "deu": "de",
           "cat": "ca", "glg": "gl", "ron": "ro", "nld": "nl", "jpn": "ja", "zho": "zh"}
MAX_RUNS = 64
MAX_ACTIONS_PER_TURN = 16
LEVELS = {"A1", "A2", "B1", "B2"}
# Below this log-probability Scribe was unsure of a word. It is a hint that the word
# may have been mispronounced, never proof: noise and rare words look the same.
LOW_CONFIDENCE_LOGPROB = float(os.getenv("LOW_CONFIDENCE_LOGPROB", "-0.4"))
# Direction the voice model acts on but nobody should read: <despacio>, [laughs].
MARKUP = re.compile(r"</?[A-Za-z_][\w-]*>|\[[a-z][a-z ]{0,28}\]")


def _letters(text: str) -> int:
    """How much speech a string holds, ignoring markup, spacing and punctuation."""
    return sum(ch.isalnum() for ch in MARKUP.sub("", text))


def spoken_text(text: str | None) -> str:
    """A reply as the learner heard it, without delivery markup."""
    return " ".join(MARKUP.sub("", text or "").split())


@dataclass(frozen=True)
class Heard:
    """What the recogniser made of one learner clip."""

    text: str
    low_confidence_words: tuple[str, ...] = ()
    min_logprob: float | None = None


def wav_bytes(pcm: bytes, rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(pcm)
    return buffer.getvalue()


@dataclass
class Session:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=256))
    ws: object | None = None
    reader: asyncio.Task | None = None
    context: tuple | None = None
    rate: int | None = None
    touched: float = field(default_factory=time.monotonic)
    # Scene actions the character triggered during the turn in flight. The reader
    # task appends; respond() drains. Cleared before each turn so actions are never
    # attributed to the wrong one.
    actions: list = field(default_factory=list)
    # The visit this conversation belongs to, and who is speaking. Both are needed by
    # the reader task, which handles tool calls off the request path.
    run: RunState | None = None
    npc_id: str = ""
    run_id: str = ""
    conversation_id: str | None = None
    # The last reply's characters and when each was spoken, on that reply's clock.
    # Kept so an interruption can be turned into "this is what they actually heard".
    chars: list = field(default_factory=list)
    starts: list = field(default_factory=list)
    last_text: str = ""
    last_gesture: str | None = None
    # The character's opening line, spoken by the agent the moment its conversation
    # opens. Held until `warm` hands it to the client; a turn that arrives first means
    # the learner spoke over it, and it is dropped.
    greeting: tuple[bytes, str] | None = None


class ElevenLabsSpeech:
    def __init__(self, key: str, agents: dict[str, str], *, stt_model="scribe_v2",
                 client=None, connect=None, quiet=0.8, idle_seconds=120, pack=None,
                 languages: tuple[str, ...] | None = None, grace=0.35):
        self.agents = agents
        self.stt_model = stt_model
        # What the learner may be heard speaking, target language first. One language
        # (the default) pins every transcription to it; more than one lets Scribe pick
        # among them; None means take Scribe's word.
        if languages is None and pack is not None:
            languages = (pack.scenario.language,)
        self.languages = tuple(dict.fromkeys(languages)) if languages else None
        self.http = client or httpx.AsyncClient(
            base_url="https://api.elevenlabs.io", headers={"xi-api-key": key}, timeout=30)
        self.connect = connect
        self.quiet = quiet
        self.idle_seconds = idle_seconds
        self.sessions: dict[UUID, Session] = {}
        # One RunState per visit, shared by that visit's characters so Luis can be
        # told what the learner ordered from Maria.
        self.runs: dict[str, RunState] = {}
        self.pack: ScenePack | None = pack
        self.reaper = None
        # `quiet` is only the fallback for ending a reply: frames normally say when
        # they are the last one. `grace` is how long to keep listening after that last
        # frame in case the character speaks again once a tool call has returned.
        self.grace = grace
        # What each character and the learner have said to each other this visit, so a
        # conversation that reopens (they walked away and came back, or the character
        # hung up) picks up where it left off instead of greeting a stranger.
        self.history: dict[tuple[str, str], deque] = {}
        self.conversations: dict[str, list[tuple[str, str]]] = {}
        self.on_timings = None  # callable(npc_id, timings_ms), set by the app

    def _run_state(self, run_id: str) -> RunState:
        state = self.runs.get(run_id)
        if state is None:
            if len(self.runs) >= MAX_RUNS:  # oldest-first, so a long demo never leaks
                self.runs.pop(next(iter(self.runs)), None)
            state = self.runs[run_id] = RunState()
        return state

    async def _transcribe(self, request: SpeechInput) -> str:
        return (await self._hear(request)).text

    async def _hear(self, request: SpeechInput) -> Heard:
        return await self._recognise(self._upload(request))

    def _upload(self, request: SpeechInput) -> tuple:
        """Check the clip locally. Costs nothing, so it runs before anything is opened:
        a clip that is plainly not audio must not open a billed conversation."""
        data, media = request.audio, request.media_type
        extensions = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/mpeg": "mp3",
                      "audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a"}
        if media == "audio/pcm":
            if not request.sample_rate or len(data) % 2:
                raise SpeechInputError("PCM requires whole samples and a sample rate")
            data, media = wav_bytes(data, request.sample_rate), "audio/wav"
        if media in {"audio/wav", "audio/x-wav"}:
            try:
                with wave.open(io.BytesIO(data), "rb") as audio:
                    if audio.getnframes() == 0:
                        raise ValueError("Empty WAV")
            except (wave.Error, EOFError, ValueError):
                raise SpeechInputError("Upload a valid nonempty PCM WAV file") from None
        return ("input." + extensions[media], data, media)

    async def _recognise(self, upload: tuple) -> Heard:
        if self.languages and len(self.languages) == 1:
            body = await self._scribe(upload, language=self.languages[0])
        else:
            body = await self._scribe(upload)
        heard = ISO_639.get(body.get("language_code") or "", body.get("language_code"))
        if self.languages and heard and heard not in self.languages:
            # Scribe drifts to a sibling language on accented speech: hear it again
            # as the target language rather than answer to Italian.
            log.info("Scribe heard %s; re-transcribing as %s", heard, self.languages[0])
            body = await self._scribe(upload, language=self.languages[0])
        text = body.get("text", "").strip()
        if not text:
            raise SpeechInputError("No speech was detected")
        scored = [(w.get("text", "").strip(" .,;:!?¿¡\"'"), w.get("logprob"))
                  for w in body.get("words") or [] if w.get("type") == "word"]
        scored = [(word, lp) for word, lp in scored if word and isinstance(lp, (int, float))]
        unsure = tuple(dict.fromkeys(w for w, lp in scored if lp < LOW_CONFIDENCE_LOGPROB))
        return Heard(text, unsure[:40], min((lp for _, lp in scored), default=None))

    async def _scribe(self, upload: tuple, language: str | None = None) -> dict:
        data = {"model_id": self.stt_model, "tag_audio_events": "false", "diarize": "false"}
        if language:
            data["language_code"] = language
        result = await self.http.post("/v1/speech-to-text", data=data, files={"file": upload})
        if result.status_code in {400, 422}:
            raise SpeechInputError("ElevenLabs could not transcribe this audio")
        result.raise_for_status()
        return result.json()

    async def _handle_tool(self, session: Session, event: dict):
        """Answer a tool call at once and record what the scene should do.

        Always replies before returning. A blocking tool left unanswered stalls the
        conversation for up to its timeout, and that time is billed, so the price is
        computed here rather than anywhere that could wait on a game client.
        """
        name = str(event.get("tool_name") or "")
        call_id = event.get("tool_call_id")
        outcome = None
        if self.pack is not None and session.run is not None:
            outcome = self.pack.dispatch(session.npc_id, name, event.get("parameters"),
                                         session.run)
        if outcome is not None and outcome.action is not None:
            if len(session.actions) < MAX_ACTIONS_PER_TURN:
                session.actions.append(outcome.action)

        # Absent expects_response we answer anyway: an unanswered blocking call is
        # far more costly than a redundant result.
        if call_id is not None and event.get("expects_response", True):
            if outcome is None:
                result, is_error = "Scene actions are unavailable right now.", True
            else:
                result = outcome.result or "Done."
                is_error = outcome.is_error
            with suppress(Exception):
                await session.ws.send(json.dumps({
                    "type": "client_tool_result", "tool_call_id": call_id,
                    "result": result, "is_error": is_error}))

    async def _pump(self, session: Session):
        try:
            async for raw in session.ws:
                message = json.loads(raw)
                kind = message.get("type")
                if kind == "ping":
                    # Answer promptly; don't let ping delays block audio consumption.
                    await session.ws.send(json.dumps({"type": "pong",
                        "event_id": message["ping_event"]["event_id"]}))
                elif kind == "client_tool_call":
                    await self._handle_tool(session, message["client_tool_call"])
                    session.queue.put_nowait({"type": "_tool", "blocking": bool(
                        message["client_tool_call"].get("expects_response", True))})
                else:
                    session.queue.put_nowait(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass  # Closed/invalid sockets are surfaced by the sentinel below.
        finally:
            if session.queue.full():
                session.queue.get_nowait()
            session.queue.put_nowait(None)

    @staticmethod
    def _closed_for_quota(ws) -> bool:
        """ElevenLabs hangs up with close code 3000 and a `quota_exceeded` reason the
        moment the account's characters run out. Every other close is a plain outage."""
        code = getattr(ws, "close_code", None)
        reason = str(getattr(ws, "close_reason", "") or "").lower()
        return code == 3000 or "quota" in reason

    def _raise_closed(self, session: Session, what: str):
        if self._closed_for_quota(session.ws):
            raise SpeechUnavailable("The ElevenLabs account is out of credits; switch ELEVENLABS_API_KEY "
                                    "to another account (tools/switch_account.py)")
        raise RuntimeError(what)

    async def _turn(self, session: Session, *, greeting=False):
        audio, text, final, voiced = bytearray(), "", False, ""
        deadline = time.monotonic() + (10 if greeting else 40)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if greeting and not audio and not text:
                    return b"", ""
                raise TimeoutError("No complete agent turn")
            # Only declare a reply complete after both text and audio arrive.
            if audio and text and (final or (voiced and _letters(voiced) >= _letters(text))):
                break
            wait = min(self.quiet, remaining) if audio and text else remaining
            try:
                message = await asyncio.wait_for(session.queue.get(), wait)
            except TimeoutError:
                if audio and text:
                    break
                if greeting and not audio and not text:
                    return b"", ""
                raise
            if message is None:
                if audio and text:
                    break
                self._raise_closed(session, "Agent connection closed before reply")
            kind = message.get("type")
            if kind == "conversation_initiation_metadata":
                fmt = message["conversation_initiation_metadata_event"]["agent_output_audio_format"]
                if not fmt.startswith("pcm_") or not fmt[4:].isdigit():
                    raise ValueError("Agent must use PCM output")
                session.rate = int(fmt[4:])
                if not 8000 <= session.rate <= 48000:
                    raise ValueError("Unsupported agent sample rate")
                session.conversation_id = (
                    message["conversation_initiation_metadata_event"].get("conversation_id"))
            elif kind == "agent_response":
                text = message["agent_response_event"]["agent_response"]
            elif kind == "agent_response_correction":
                text = message["agent_response_correction_event"]["corrected_agent_response"]
            elif kind == "audio":
                audio.extend(base64.b64decode(message["audio_event"]["audio_base_64"], validate=True))
                final = bool(message["audio_event"].get("is_final"))
                voiced += "".join((message["audio_event"].get("alignment") or {}).get("chars") or [])
                if len(audio) > MAX_REPLY:
                    raise ValueError("Agent reply exceeds audio limit")
            elif kind == "interruption":
                audio.clear()
                text, final, voiced = "", False, ""
            elif kind in {"error", "conversation_error"}:
                raise RuntimeError("Agent reported an error")
        if session.rate is None or len(audio) % 2:
            raise ValueError("Missing or invalid PCM metadata")
        return bytes(audio), text

    async def _close(self, session: Session):
        if session.reader:
            session.reader.cancel()
            with suppress(asyncio.CancelledError):
                await session.reader
        if session.ws:
            with suppress(Exception):
                await session.ws.close()
        session.ws = session.reader = None
        session.queue = asyncio.Queue(maxsize=256)
        session.rate = None

    async def _open(self, session: Session, agent: str, request: SpeechInput):
        result = await self.http.get("/v1/convai/conversation/get-signed-url", params={"agent_id": agent})
        result.raise_for_status()
        connect = self.connect
        if connect is None:
            from websockets.asyncio.client import connect
        session.ws = await connect(result.json()["signed_url"], max_size=16 * 1024 * 1024)
        session.reader = asyncio.create_task(self._pump(session))
        order = "nada"
        if self.pack is not None and session.run is not None:
            order = session.run.order_summary_es(self.pack.menu)
        await session.ws.send(json.dumps({"type": "conversation_initiation_client_data",
            "dynamic_variables": {
                "learner_name": (request.learner_name or "amigo")[:60],
                # Every variable a prompt mentions must be sent: a missing one fails
                # the whole conversation rather than degrading.
                "learner_level": request.learner_level if request.learner_level in LEVELS
                                 else (self.pack.scenario.level if self.pack
                                       and self.pack.scenario.level in LEVELS else "A2"),
                # Set when the socket opens, which is why talking to Maria first and
                # then walking to Luis lets him mention what you ordered.
                "user_order": order}}))
        # The agent speaks first. Keep its opening line for `warm` to return, and keep
        # it out of the first reply.
        audio, text = await self._turn(session, greeting=True)
        session.greeting = (audio, text) if audio else None
        if session.rate is None:
            raise ValueError("Agent did not negotiate its output format")
        if request.scenario:
            await session.ws.send(json.dumps({"type": "contextual_update", "text":
                "Current practice scenario and active character " + request.npc_id + ": " +
                json.dumps(request.scenario, ensure_ascii=False)}))
        for text in session.run.notes.get(session.npc_id, {}).values():
            await session.ws.send(json.dumps({"type": "contextual_update", "text": text}))
        if session.conversation_id:
            self.conversations.setdefault(session.run_id, []).append(
                (session.npc_id, session.conversation_id))
        past = self.history.get((session.run_id, session.npc_id))
        if past:
            recap = " ".join(f"They said: \u00ab{heard}\u00bb. You said: \u00ab{said}\u00bb." for heard, said in past)
            await session.ws.send(json.dumps({"type": "contextual_update", "text": (
                "You and this learner were already talking earlier in this same visit; this "
                "is the same conversation continuing, so do not greet them as if they had "
                "just arrived. So far: " + recap)[:3000]}))

    def _session_for(self, request: SpeechInput) -> tuple[str, str, Session]:
        # A client may still be using an older name for a character; the scenario
        # declares those, so accept them rather than failing the turn.
        npc_id = self.pack.resolve(request.npc_id) if self.pack else request.npc_id
        agent = self.agents.get(npc_id) or self.agents.get(request.npc_id)
        if not agent:
            raise SpeechUnavailable("No ElevenLabs agent configured for this NPC")
        if self.reaper is None:
            self.reaper = asyncio.create_task(self._reap())
        if request.session_id not in self.sessions:
            if len(self.sessions) >= 64:
                raise SpeechUnavailable("Voice session capacity reached; close an idle session")
            self.sessions[request.session_id] = Session()
        return npc_id, agent, self.sessions[request.session_id]

    async def _ensure_open(self, session: Session, agent: str, npc_id: str,
                           request: SpeechInput) -> int:
        """Open the character's conversation if it is not already. Returns the ms it cost."""
        session.npc_id = npc_id
        session.run_id = request.run_id or str(request.session_id)
        session.run = self._run_state(session.run_id)
        context = (npc_id, request.scenario_id)
        if session.ws is not None and session.context == context and not session.reader.done():
            return 0
        began = time.monotonic()
        await self._close(session)
        try:
            await self._open(session, agent, request)
        except Exception:
            # A socket ElevenLabs shut for lack of credits fails on the first send, as a
            # websockets ConnectionClosedError. Name the cause rather than a bare 502.
            if self._closed_for_quota(session.ws):
                self._raise_closed(session, "")
            raise
        session.context = context
        return int((time.monotonic() - began) * 1000)

    async def warm(self, request: SpeechInput) -> SpeechOutput | None:
        """Open the conversation before the learner speaks and return the character's
        opening line, in their own live voice. Called when the player walks up. The
        learner's first turn then costs the same as every other one. `request.audio`
        is ignored. None when there is nothing to say: the conversation was already
        open (the greeting has been given, or a turn is running), or the agent opened
        without speaking."""
        npc_id, agent, session = self._session_for(request)
        if session.lock.locked():
            return None
        async with session.lock:
            began = time.monotonic()
            try:
                # The first transcription after a quiet spell takes well over a second;
                # later ones take a third of that. Spend that second now, on silence.
                await asyncio.gather(self._ensure_open(session, agent, npc_id, request),
                                     self._warm_hearing())
            except BaseException:
                await self._close(session)
                self.sessions.pop(request.session_id, None)
                raise
            finally:
                session.touched = time.monotonic()
            greeting, session.greeting = session.greeting, None
        if greeting is None:
            return None
        audio, text = greeting
        return SpeechOutput(wav_bytes(audio, session.rate), "audio/wav", session.rate, None,
                            spoken_text(text),
                            timings_ms={"open": int((time.monotonic() - began) * 1000)})

    async def _warm_hearing(self):
        with suppress(Exception):
            await self._scribe(("warm.wav", wav_bytes(b"\x00\x00" * 4800, 16000), "audio/wav"),
                               language=self.languages[0] if self.languages else None)

    async def stream(self, request: SpeechInput) -> AsyncIterator[dict]:
        """One learner turn, as events in the order they happen.

        `transcript` (what we heard), then `audio` frames as the agent produces them,
        each with its mouth shapes, interleaved with `text` and any scene `action`,
        and finally `done` with where the time went. The first `audio` event is the
        moment the learner hears the character, so nothing here waits for the whole
        reply before yielding.
        """
        npc_id, agent, session = self._session_for(request)
        # Reject overlaps instead of queuing turns that may arrive out of order.
        if session.lock.locked():
            raise SpeechInputError("A speech turn is already running for this session")
        async with session.lock:
            sent = False
            try:
                began = time.monotonic()
                # Hearing the learner and opening the conversation do not depend on
                # each other, so a cold first turn pays for the slower of the two.
                hearing = asyncio.create_task(self._recognise(self._upload(request)))
                try:
                    open_ms = await self._ensure_open(session, agent, npc_id, request)
                    heard = await hearing
                except BaseException:
                    hearing.cancel()
                    with suppress(BaseException):
                        await hearing
                    raise
                stt_ms = int((time.monotonic() - began) * 1000)
                yield {"type": "transcript", "text": heard.text, "stt_ms": stt_ms,
                       "low_confidence_words": list(heard.low_confidence_words),
                       "min_logprob": heard.min_logprob}

                session.greeting = None  # spoken over, if it was ever heard
                previous_heard = await self._interrupted(session, request.interrupted_at_ms)
                # Discard unsolicited idle messages before sending the next turn.
                while not session.queue.empty():
                    session.queue.get_nowait()
                session.actions.clear()  # only this turn's actions reach the client
                session.chars, session.starts = [], []
                await session.ws.send(json.dumps({"type": "user_message", "text": heard.text}))
                sent, sent_at = True, time.monotonic()

                replies: list[str] = []
                # The reply as the model writes it, which runs well ahead of the audio,
                # and whether the character still owes us speech after a tool call.
                streamed, open_parts, awaiting = "", 0, False
                can_act = bool(self.pack and npc_id in self.pack.npcs and self.pack.npcs[npc_id].tools)
                spoken_ms, frames, emitted = 0, 0, 0
                first_audio_ms = None
                final = complete = ended = False
                deadline = sent_at + 40
                while True:
                    while emitted < len(session.actions):
                        yield {"type": "action", "action": session.actions[emitted]}
                        emitted += 1
                    have = bool(frames and replies)
                    # The reliable end of a reply: every character of its text has been
                    # spoken. Each frame says which characters it carries, so this needs
                    # no timer. (`is_final` exists but is not set in practice.)
                    # A character may speak, call a tool, then speak again ("Claro, un
                    # café de olla." · serve_order · "Ahorita te lo traigo."). That is one
                    # reply, so a pending tool follow-up or an unfinished sentence keeps
                    # the turn open.
                    voiced = have and session.chars and not awaiting and open_parts <= 0 and \
                        _letters("".join(session.chars)) >= _letters(streamed or " ".join(replies))
                    done_speaking = have and (voiced or (complete and final))
                    if done_speaking and session.queue.empty() and not can_act:
                        break  # nothing more can follow: end without waiting at all
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("No complete agent turn")
                    # A character with tools may call one right behind its sentence and
                    # then speak again, so linger a moment before closing the turn. This
                    # delays only `done`, never the first sound. Without any end signal,
                    # fall back to waiting for silence.
                    wait = min(self.grace if done_speaking or final else self.quiet, remaining) \
                        if have else remaining
                    try:
                        message = await asyncio.wait_for(session.queue.get(), wait)
                    except TimeoutError:
                        if have:
                            break
                        raise
                    if message is None:
                        if have:
                            ended = True  # the character said goodbye and hung up
                            break
                        raise RuntimeError("Agent connection closed before reply")
                    kind = message.get("type")
                    if kind == "audio":
                        event = message["audio_event"]
                        pcm = base64.b64decode(event["audio_base_64"], validate=True)
                        if len(pcm) % 2 or (spoken_ms * session.rate // 500) + len(pcm) > MAX_REPLY:
                            raise ValueError("Invalid or oversized agent audio")
                        if first_audio_ms is None:
                            first_audio_ms = int((time.monotonic() - sent_at) * 1000)
                        shapes: list[dict] = []
                        align = event.get("alignment") or {}
                        if align.get("chars"):
                            starts = [spoken_ms + int(s) for s in align.get("char_start_times_ms", [])]
                            session.chars += list(align["chars"])[:len(starts)]
                            session.starts += starts[:len(align["chars"])]
                            shapes = timeline(align["chars"], align.get("char_start_times_ms", []),
                                              align.get("char_durations_ms", []), spoken_ms)
                        yield {"type": "audio", "seq": frames, "pcm": pcm, "offset_ms": spoken_ms,
                               "sample_rate": session.rate, "visemes": shapes}
                        frames += 1
                        spoken_ms += len(pcm) * 500 // session.rate
                        final = bool(event.get("is_final"))
                    elif kind == "agent_response":
                        replies.append(message["agent_response_event"]["agent_response"])
                        yield {"type": "text", "text": spoken_text(" ".join(replies))}
                        self._gesture(session, replies[-1])
                    elif kind == "agent_response_correction":
                        # The service keeps its own playback clock. A learner who answers
                        # before the previous line has "finished" there is treated as
                        # interrupting it, and the correction describes THAT line, not
                        # this reply. Only a correction to this reply's own text counts.
                        if replies:
                            fixed = message["agent_response_correction_event"]["corrected_agent_response"]
                            replies = replies[:-1] + [fixed]
                            yield {"type": "text", "text": spoken_text(" ".join(replies))}
                    elif kind == "agent_chat_response_part":
                        part = message.get("text_response_part") or {}
                        if part.get("type") == "start":
                            open_parts += 1
                            if streamed and not streamed[-1].isspace():
                                streamed += " "  # a second sentence, after a tool call
                        elif part.get("type") == "stop":
                            open_parts -= 1
                        elif part.get("text"):
                            streamed += part["text"]
                            awaiting = awaiting and not part["text"].strip()
                    elif kind == "_tool":
                        awaiting = awaiting or message["blocking"]
                    elif kind == "agent_response_complete":
                        complete = True
                        if not frames:
                            final = True
                    elif kind == "interruption":
                        if frames:  # only audio already sent for this reply needs dropping
                            yield {"type": "flush"}
                            replies, frames, spoken_ms, final = [], 0, 0, False
                            session.chars, session.starts = [], []
                    elif kind in {"error", "conversation_error"}:
                        raise RuntimeError("Agent reported an error")
                # A character that said goodbye hangs up right behind its last word.
                # Look, without waiting: if the line has not dropped yet, the next turn
                # finds it closed and reopens with the visit's memory anyway.
                await asyncio.sleep(0)
                while not ended and not session.queue.empty():
                    ended = session.queue.get_nowait() is None
                ended = ended or session.reader.done()
                while emitted < len(session.actions):
                    yield {"type": "action", "action": session.actions[emitted]}
                    emitted += 1

                said = spoken_text(" ".join(replies))
                if _letters(streamed) > _letters(said):
                    # The last sentence's text event can trail its audio; the streamed
                    # text is already whole.
                    said = spoken_text(streamed)
                    yield {"type": "text", "text": said}
                    self._gesture(session, streamed)
                session.last_text = said
                self.history.setdefault((session.run_id, npc_id), deque(maxlen=8)).append(
                    (heard.text, said))
                await self._overhear(session, heard.text, said)
                timings = {"stt": stt_ms, "session_open": open_ms,
                           "first_audio": first_audio_ms or 0,
                           "first_sound": int((sent_at - began) * 1000) + (first_audio_ms or 0),
                           "complete": int((time.monotonic() - sent_at) * 1000),
                           "total": int((time.monotonic() - began) * 1000),
                           "reply_audio": spoken_ms}
                if self.on_timings:
                    with suppress(Exception):
                        self.on_timings(npc_id, timings)
                if ended:
                    self.sessions.pop(request.session_id, None)
                    await self._close(session)
                yield {"type": "done", "timings_ms": timings, "ended": ended,
                       "previous_reply_heard": previous_heard,
                       "conversation_id": session.conversation_id}
            except SpeechInputError:
                # Nothing was said to the character, so the conversation is untouched:
                # a silent or garbled clip must not cost the learner a warm session.
                if sent:
                    await self._close(session)
                    self.sessions.pop(request.session_id, None)
                raise
            except BaseException:
                # Also close on request cancellation/timeout to avoid stale replies.
                await self._close(session)
                self.sessions.pop(request.session_id, None)
                raise
            finally:
                session.touched = time.monotonic()

    def _gesture(self, session: Session, reply: str):
        """Body language for this reply, chosen here rather than by the character's
        model: as a tool call it cost a second model round trip, about a second of
        silence, on most turns. Skipped when the character gestured by itself."""
        if any(a.get("action") == "play_gesture" for a in session.actions):
            return
        allowed = self.pack.scenario.gestures if self.pack else None
        gesture = infer_gesture(reply, allowed, session.last_gesture)
        if gesture and len(session.actions) < MAX_ACTIONS_PER_TURN:
            session.last_gesture = gesture
            session.actions.append({"action": "play_gesture", "npc_id": session.npc_id,
                                    "gesture": gesture, "source": "inferred"})

    async def _interrupted(self, session: Session, heard_ms: int | None) -> str | None:
        """The learner cut the last reply short. Work out what they actually heard and
        tell the character, which otherwise believes it finished the sentence."""
        if heard_ms is None or not session.chars or session.ws is None:
            return None
        heard = heard_prefix(session.chars, session.starts, max(heard_ms, 0))
        if heard == session.last_text:
            return None
        past = self.history.get((session.run_id, session.npc_id))
        if past:
            past[-1] = (past[-1][0], heard + "\u2014")
        with suppress(Exception):
            await session.ws.send(json.dumps({"type": "contextual_update", "text": (
                "The learner interrupted your last reply. They only heard: "
                f"\u00ab{heard}\u00bb. The rest was never said aloud, so do not assume they know it. "
                "React the way a person does when cut off, briefly, then answer them.")}))
        return heard

    async def respond(self, request: SpeechInput) -> SpeechOutput:
        """The same turn as `stream`, collected into one WAV for non-streaming clients."""
        audio, shapes, actions = bytearray(), [], []
        heard, text, done, rate = {}, "", {}, None
        async for event in self.stream(request):
            kind = event["type"]
            if kind == "transcript":
                heard = event
            elif kind == "audio":
                audio += event["pcm"]
                shapes += event["visemes"]
                rate = event["sample_rate"]
            elif kind == "text":
                text = event["text"]
            elif kind == "action":
                actions.append(event["action"])
            elif kind == "flush":
                audio.clear()
                shapes.clear()
            elif kind == "done":
                done = event
        if rate is None or not audio:
            raise ValueError("Missing or invalid PCM metadata")
        return SpeechOutput(wav_bytes(bytes(audio), rate), "audio/wav", rate, heard.get("text"),
                            text, tuple(actions), tuple(shapes),
                            tuple(heard.get("low_confidence_words") or ()),
                            heard.get("min_logprob"), done.get("timings_ms"),
                            bool(done.get("ended")), done.get("previous_reply_heard"))

    async def _overhear(self, speaker: Session, heard: str, said: str):
        """Tell the other characters at this table what was just said.

        Each character has its own conversation, so without this Luis has no idea
        Maria took the order a moment ago. A contextual_update is context, not a
        turn: the listener does not answer it, it just knows. Only characters whose
        conversation is already open hear anything; a character met later starts
        from the run state instead.
        """
        if not said:
            return
        name = self.pack.npcs[speaker.npc_id].name if self.pack and speaker.npc_id in self.pack.npcs \
            else speaker.npc_id
        text = (f"Overheard just now at the same table (not addressed to you, do not reply to "
                f"it, but you know it happened): the learner said to {name}: \u00ab{heard}\u00bb. "
                f"{name} answered: \u00ab{said}\u00bb.")
        for other in list(self.sessions.values()):
            if other is speaker or other.run is not speaker.run or other.ws is None \
                    or other.npc_id == speaker.npc_id or other.lock.locked():
                continue
            with suppress(Exception):  # a listener that misses a line is not the turn's problem
                await other.ws.send(json.dumps({"type": "contextual_update", "text": text[:2000]}))

    async def note(self, run_id: str, npc_id: str, key: str, text: str):
        """Tell one character something about the scene, now and whenever their
        conversation (re)opens while the note stands: Maria is walking over to take the
        order, so Luis should not end his next line on a question the learner will
        never answer. An empty text withdraws the note."""
        npc_id = self.pack.resolve(npc_id) if self.pack else npc_id
        run = self._run_state(run_id)
        if not text.strip():
            run.notes.get(npc_id, {}).pop(key, None)
            return
        line = f"Scene note ({key}): {text.strip()}"
        run.notes.setdefault(npc_id, {})[key] = line
        for session in list(self.sessions.values()):
            if session.run is run and session.npc_id == npc_id and session.ws is not None \
                    and not session.lock.locked():
                with suppress(Exception):
                    await session.ws.send(json.dumps({"type": "contextual_update", "text": line}))

    async def end_session(self, session_id: UUID):
        session = self.sessions.get(session_id)
        if session:
            if session.lock.locked():
                raise SpeechInputError("A speech turn is already running for this session")
            self.sessions.pop(session_id, None)
            await self._close(session)

    async def _reap(self):
        while True:
            await asyncio.sleep(min(10, self.idle_seconds))
            for key, session in list(self.sessions.items()):
                if not session.lock.locked() and time.monotonic() - session.touched > self.idle_seconds:
                    self.sessions.pop(key, None)
                    await self._close(session)

    async def aclose(self):
        if self.reaper:
            self.reaper.cancel()
            with suppress(asyncio.CancelledError):
                await self.reaper
        for session in list(self.sessions.values()):
            await self._close(session)
        self.sessions.clear()
        await self.http.aclose()


def create_provider() -> ElevenLabsSpeech:
    agents = {key[len("AGENT_ID_"):].lower(): value for key, value in os.environ.items()
              if key.startswith("AGENT_ID_") and value}
    if "luis" not in agents and os.getenv("SMOKE_AGENT_ID"):
        agents["luis"] = os.environ["SMOKE_AGENT_ID"]
    pack = None
    with suppress(Exception):  # no scenario pack still gives a talking character
        pack = ScenePack.load(default_pack_dir())
    return ElevenLabsSpeech(os.environ["ELEVENLABS_API_KEY"], agents,
                           stt_model=os.getenv("ELEVENLABS_STT_MODEL", "scribe_v2"),
                           pack=pack)
