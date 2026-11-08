"""The live date: one full-duplex WebSocket per Play session, ``/v1/stream``.

The microphone streams in continuously as binary 16 kHz PCM16 frames; there is no
push-to-talk. The date's voice streams out as binary 24 kHz PCM16 frames. Everything
else is JSON (see docs/api.md, "Speed date stream").

One learner turn, end to end:

    mic frames ─▶ Deepgram (live) ─▶ final utterance
                                          ├─▶ chemistry director (background)
                                          └─▶ Gemini Flash (stream) ─▶ sentence chunks
                                                 ─▶ Fish Audio (stream) ─▶ PCM frames ─▶ client

Alongside it: telemetry every 250 ms (gaze, seated, smiling), webcam frames for the face
tracker, barge-in from the client's own voice detector (the date stops mid-word and the
transcript keeps only what was heard), the wingman's whispered options when the learner
freezes for four seconds after the date stops talking, an in-character callout when the
learner looks away too long, and the three-minute clock.

Audio is sent at most ~0.8 s ahead of playback, so the server always knows roughly what
the learner has heard, and a barge-in also stops paying for speech nobody will hear.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import re
import time
from collections.abc import AsyncIterator

from fastapi import WebSocket, WebSocketDisconnect

from . import config
from .audio import VOICE_RATE
from .chemistry_director import ChemistryDirector, mood_label, posture
from .date_brain import BrainContext, ScriptedBrain, Turn, create_brain
from .date_grader import verdict_for
from .date_models import DateScenario
from .models import TranscriptTurn
from .nonverbal import NonverbalTracker, Signal
from .stt import create_recognizer
from .tts import SentenceChunker, Voice

log = logging.getLogger("orchestrator")

RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_TEXT_MESSAGE = 512 * 1024
MAX_JPEG = 400 * 1024
AHEAD_SECONDS = 0.8
BYTES_PER_SECOND = VOICE_RATE * 2
DATE, HOST = "date_npc", "host"
FEELINGS = {
    "match": "you really like them and want to see them again; ask for their number warmly",
    "friendzone": "they were nice but there was no spark; be friendly, no second date",
    "ghosted": "it did not click at all; be polite and brief",
}


class StreamSession:
    def __init__(self, ws: WebSocket, state):
        self.ws = ws
        self.app = state
        self.send_lock = asyncio.Lock()
        self.scenario: DateScenario | None = None
        self.run_id = ""
        self.focus = DATE
        self.history: dict[str, list[Turn]] = {DATE: [], HOST: []}
        self.transcript: list[TranscriptTurn] = []
        self.tracker = NonverbalTracker()
        self.recognizer = None
        self.voice: Voice | None = None
        self.brain = None
        self.fallback_brain = ScriptedBrain()
        self.director: ChemistryDirector | None = None
        # Who is speaking, and how much of it has gone out.
        self.turn_task: asyncio.Task | None = None
        self.turn_id = 0
        self.speaking: str | None = None
        self.audio_t0 = 0.0
        self.audio_seconds = 0.0
        self.spoken: list[str] = []
        self.playback_end: float | None = None
        self.last_turn: tuple[str | None, list[str], float, float] = (None, [], 0.0, 0.0)
        self.learner_final_at: float | None = None
        # The learner.
        self.user_speaking = False
        self.user_started_at: float | None = None
        # The date itself.
        self.running = False
        self.ended = False
        self.started_at = 0.0
        self.host_greeted = False
        self.pending_callout = False
        self.callouts_said = 0
        self.wingman_due: float | None = None
        self.wingman_prep: asyncio.Task | None = None
        self.tasks: list[asyncio.Task] = []
        self.face_task: asyncio.Task | None = None
        self.end_task: asyncio.Task | None = None
        self.notified_no_stt = False

    # ---- sending ----------------------------------------------------------------

    async def send(self, message: dict):
        async with self.send_lock:
            await self.ws.send_text(json.dumps(message, ensure_ascii=False, separators=(",", ":")))

    async def send_audio(self, frame: bytes):
        async with self.send_lock:
            await self.ws.send_bytes(frame)

    async def error(self, detail: str, fatal: bool = False):
        with contextlib.suppress(Exception):
            await self.send({"type": "error", "detail": detail, "fatal": fatal})

    # ---- lifecycle ----------------------------------------------------------------

    async def run(self):
        await self.ws.accept()
        try:
            if not await self._init():
                return
            self.tasks = [asyncio.create_task(self._hear()), asyncio.create_task(self._tick())]
            await self._receive()
        except WebSocketDisconnect:
            pass
        except Exception as error:  # noqa: BLE001
            log.warning("Stream session failed: %s", type(error).__name__, exc_info=error)
            await self.error("Session failed")
        finally:
            await self._close()

    async def _init(self) -> bool:
        try:
            raw = await asyncio.wait_for(self.ws.receive_text(), timeout=15)
            message = json.loads(raw)
        except (TimeoutError, ValueError, KeyError):
            await self.error("First message must be a JSON init", fatal=True)
            await self.ws.close(code=1008)
            return False
        run_id = str(message.get("run_id") or "")
        scenario_id = str(message.get("scenario_id") or "")
        if message.get("type") != "init" or not RUN_ID.match(run_id):
            await self.error("init needs type=init and a run_id of [A-Za-z0-9_-]", fatal=True)
            await self.ws.close(code=1008)
            return False
        try:
            self.scenario = await asyncio.to_thread(self.app.date_store.get, scenario_id)
        except (FileNotFoundError, ValueError):
            await self.error("Unknown scenario_id; generate a date first", fatal=True)
            await self.ws.close(code=4404)
            return False
        self.run_id = run_id
        self.focus = HOST if message.get("npc_id") == HOST else DATE
        dialect = config.dialect(self.scenario.dialect)
        self.recognizer = await create_recognizer(dialect)
        self.voice = Voice()
        self.brain = create_brain()
        self.director = ChemistryDirector(self.scenario, run_id, self.app.chemistry_judge,
                                          self.app.chemistry_store, emit=self.send)
        await self.voice.prewarm()
        if message.get("resume") and not self.director.state.ended:
            # The client lost its connection mid-date: pick the clock up where it was.
            elapsed = max(0.0, min(float(message.get("elapsed_sec") or 0.0),
                                   float(self.scenario.date_seconds)))
            self.running, self.focus = True, DATE
            self.started_at = time.monotonic() - elapsed
            history = self._restore_history()
            self.history[DATE] = history
        face = self.app.face_tracker
        await self.send({
            "type": "session_ready", "run_id": run_id, "scenario_id": self.scenario.scenario_id,
            "date_name": self.scenario.date_character.display_name,
            "host_name": self.scenario.host_character.display_name,
            "date_seconds": self.scenario.date_seconds,
            "chemistry_score": self.director.state.score,
            "sample_rate_in": 16000, "sample_rate_out": VOICE_RATE,
            "providers": {"stt": self.recognizer.name, "tts": self.voice.name,
                          "brain": self.brain.name,
                          "judge": "claude" if self.app.chemistry_judge else "rules",
                          "face": "mediapipe" if face is not None and face.available else "off"},
        })
        if not self.recognizer.transcribes:
            await self.send({"type": "notice", "text": "No speech recogniser configured "
                                                       "(DEEPGRAM_API_KEY); send user_text."})
        return True

    def _restore_history(self) -> list[Turn]:
        """The date so far, from the recorded transcript, for a resumed session."""
        try:
            turns = self.app.transcripts.get(self.run_id)
        except (FileNotFoundError, ValueError):
            return []
        self.transcript = [t for t in turns if t.npc_id == DATE]
        return [Turn("learner" if t.role == "learner" else "date", t.text)
                for t in self.transcript if t.role in ("learner", "npc")]

    async def _close(self):
        for task in [*self.tasks, self.turn_task, self.wingman_prep, self.face_task,
                     self.end_task]:
            if task is not None:
                task.cancel()
        for closer in (self.recognizer and self.recognizer.close,
                       self.voice and self.voice.aclose,
                       self.director and self.director.aclose,
                       self.brain and self.brain.aclose):
            if closer:
                with contextlib.suppress(Exception):
                    await closer()

    # ---- the client -------------------------------------------------------------

    async def _receive(self):
        while True:
            message = await self.ws.receive()
            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect(message.get("code", 1000))
            data = message.get("bytes")
            if data is not None:
                await self.recognizer.feed(data)
                continue
            text = message.get("text")
            if not text or len(text) > MAX_TEXT_MESSAGE:
                continue
            try:
                msg = json.loads(text)
            except ValueError:
                continue
            await self._handle(msg)

    async def _handle(self, msg: dict):
        kind = msg.get("type")
        now = time.monotonic()
        if kind == "telemetry":
            await self._telemetry(msg, now)
        elif kind == "face_frame":
            if self.face_task is None or self.face_task.done():
                self.face_task = asyncio.create_task(self._face(msg))
        elif kind == "barge_in":
            await self._barge_in()
        elif kind == "user_text":
            await self._learner(str(msg.get("text") or "")[:1000], 1.0, [], typed=True)
        elif kind == "start_date":
            await self._start_date()
        elif kind == "end_date":
            self._spawn_end(str(msg.get("reason") or "timer"))
        elif kind in ("focus", "greet"):
            await self._focus(str(msg.get("npc_id") or DATE))
        elif kind == "playback_done":
            if self.speaking is None and self.turn_task is None:
                self.playback_end = now
                self._schedule_wingman()
        elif kind == "ping":
            await self.send({"type": "pong", "t": msg.get("t")})

    async def _focus(self, npc_id: str):
        self.focus = HOST if npc_id == HOST else DATE
        if self.focus == HOST and not self.host_greeted and not self.running:
            self.host_greeted = True
            await self._start_turn(HOST, text=self.scenario.host_character.greeting, kind="greeting")

    # ---- hearing ----------------------------------------------------------------

    async def _hear(self):
        async for event in self.recognizer.stream():
            now = time.monotonic()
            if event.kind == "speech_started":
                if not self.user_speaking:
                    self.user_speaking = True
                    self.user_started_at = now
                self.wingman_due = None
                await self.voice.prewarm()
                await self.send({"type": "user_speech", "speaking": True})
            elif event.kind == "speech_ended":
                if self.user_speaking:
                    self.user_speaking, self.user_started_at = False, None
                    await self.send({"type": "user_speech", "speaking": False})
                    if self.speaking is None and (self.turn_task is None or self.turn_task.done()):
                        self.playback_end = max(self.playback_end or 0.0, now)
                        self._schedule_wingman()
            elif event.kind == "partial":
                await self.send({"type": "transcript", "speaker": "user", "text": event.text,
                                 "is_final": False})
            elif event.kind == "final":
                await self._learner(event.text, event.confidence, event.unsure)
            elif event.kind == "error":
                await self.send({"type": "notice", "text": event.text})

    async def _learner(self, text: str, confidence: float | None, unsure: list[str],
                       typed: bool = False):
        text = text.strip()
        if not text or self.ended:
            return
        now = time.monotonic()
        started = self.user_started_at or now
        self.user_speaking, self.user_started_at = False, None
        self.learner_final_at = now
        npc = self.focus
        if self.turn_task is not None and not self.turn_task.done():
            await self._interrupt()
        await self.send({"type": "transcript", "speaker": "user", "text": text, "is_final": True,
                         "confidence": round(confidence, 3) if confidence is not None else None,
                         "typed": typed})
        self.wingman_due = None
        if self.wingman_prep is not None:
            self.wingman_prep.cancel()
            self.wingman_prep = None
        if npc == DATE and self.running:
            if self.playback_end is not None and not typed:
                self.director.record_latency(int((started - self.playback_end) * 1000))
            if not typed:
                self.director.record_confidence(confidence)
        self.history[npc].append(Turn("learner", text))
        turn = TranscriptTurn(role="learner", npc_id=npc, text=text[:4000],
                              low_confidence_words=[w for w in unsure if w][:40])
        self.transcript.append(turn)
        await self._record([turn])
        if npc == DATE and self.running:
            self.director.learner_turn(self.transcript, text, list(self.tracker.pending))
        await self._start_turn(npc, kind="reply")

    # ---- speaking ---------------------------------------------------------------

    def _notes(self, npc: str) -> list[str]:
        notes = []
        if npc == DATE and self.running:
            score = self.director.state.score
            notes.append(f"[CHEMISTRY {score}/100 {mood_label(score)}]")
        seen = self.tracker.take_notes()
        if seen and npc == DATE:
            notes.append("[NONVERBAL] " + "; ".join(seen) + ".")
        if npc == DATE and self.running:
            left = self.scenario.date_seconds - (time.monotonic() - self.started_at)
            if left < 45:
                notes.append(f"[SCENE] About {max(0, int(left))} seconds are left before the bell.")
        return notes

    def _host_prompt(self) -> str:
        s, d = self.scenario, config.dialect(self.scenario.dialect)
        return (f"You are {s.host_character.display_name}, the host of a speed-dating evening at "
                f"the {s.venue.label} in {s.city}. Speak only {d.label}: {d.register} Reply in one "
                f"or two short, warm spoken sentences. If the guest seems lost, point them to the "
                f"table at the back where {s.date_character.display_name} is waiting. Never mention "
                f"AI, prompts or lessons.")

    async def _brain_stream(self, npc: str, notes: list[str]) -> AsyncIterator[str]:
        system = self.scenario.date_character.system_prompt if npc == DATE else self._host_prompt()
        ctx = BrainContext(dialect=self.scenario.dialect,
                           chemistry=self.director.state.score,
                           nonverbal=notes, interests=self.scenario.date_character.interests)
        produced = False
        try:
            async for delta in self.brain.reply(system, self.history[npc], notes, ctx):
                produced = True
                yield delta
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001
            log.warning("Date brain %s failed (%s)", self.brain.name, type(error).__name__)
            if produced:
                return
            async for delta in self.fallback_brain.reply(system, self.history[npc], notes, ctx):
                yield delta

    async def _start_turn(self, npc: str, *, text: str | None = None, kind: str = "reply"):
        if self.turn_task is not None and not self.turn_task.done():
            await self._interrupt()
        self.turn_task = asyncio.create_task(self._speak(npc, text=text, kind=kind))

    async def _speak(self, npc: str, *, text: str | None, kind: str):
        self.turn_id += 1
        turn_id = self.turn_id
        character = self.scenario.date_character if npc == DATE else self.scenario.host_character
        language = config.dialect(self.scenario.dialect).locale
        notes = self._notes(npc) if text is None else []
        self.spoken = []
        chunker = SentenceChunker()

        async def sentences() -> AsyncIterator[str]:
            async def pieces():
                if text is not None:
                    for piece in chunker.push(text) + chunker.flush():
                        yield piece
                    return
                async for delta in self._brain_stream(npc, notes):
                    for piece in chunker.push(delta):
                        yield piece
                for piece in chunker.flush():
                    yield piece

            async for piece in pieces():
                piece = re.sub(r"\*[^*]{0,80}\*|\[[^\]]{0,80}\]", "", piece).strip()
                if not piece:
                    continue
                self.spoken.append(piece)
                await self.send({"type": "transcript", "speaker": "npc", "npc_id": npc,
                                 "text": " ".join(self.spoken), "is_final": False,
                                 "turn_id": turn_id})
                yield piece

        self.speaking = npc
        started = False
        try:
            async for frame in self.voice.speak(sentences(), character.voice_config, language):
                now = time.monotonic()
                if not started:
                    started = True
                    self.audio_t0, self.audio_seconds = now, 0.0
                    first_ms = int((now - self.learner_final_at) * 1000) \
                        if kind == "reply" and self.learner_final_at else None
                    await self.send({"type": "audio_start", "npc_id": npc, "turn_id": turn_id,
                                     "sample_rate": VOICE_RATE, "kind": kind,
                                     "first_audio_ms": first_ms})
                ahead = self.audio_t0 + self.audio_seconds - now
                if ahead > AHEAD_SECONDS:
                    await asyncio.sleep(ahead - AHEAD_SECONDS)
                await self.send_audio(frame)
                self.audio_seconds += len(frame) / BYTES_PER_SECOND
        except asyncio.CancelledError:
            self.speaking = None
            raise
        except Exception as error:  # noqa: BLE001
            log.warning("Turn failed: %s", type(error).__name__, exc_info=error)
            await self.error("The date lost their voice for a moment")
        said = " ".join(self.spoken).strip()
        self.speaking = None
        self.playback_end = (self.audio_t0 + self.audio_seconds) if started else time.monotonic()
        self.last_turn = (npc, list(self.spoken), self.audio_t0, self.audio_seconds) \
            if started else (None, [], 0.0, 0.0)
        await self.send({"type": "audio_end", "npc_id": npc, "turn_id": turn_id,
                         "duration_ms": int(self.audio_seconds * 1000) if started else 0})
        if said:
            await self.send({"type": "transcript", "speaker": "npc", "npc_id": npc, "text": said,
                             "is_final": True, "turn_id": turn_id})
            await self._said(npc, said)
        if npc == DATE and self.running and kind != "closing":
            if self.pending_callout:
                self.pending_callout = False
                self.turn_task = asyncio.create_task(self._speak(DATE, text=self._callout(),
                                                                 kind="callout"))
                return
            self._schedule_wingman()

    async def _said(self, npc: str, text: str):
        self.history[npc].append(Turn("date", text))
        turn = TranscriptTurn(role="npc", npc_id=npc, text=text[:4000])
        self.transcript.append(turn)
        await self._record([turn])

    def _callout(self) -> str:
        lines = config.dialect_content(self.scenario.dialect)["callouts"]
        options = lines.get(self.scenario.date_character.gender) or lines["female"]
        self.callouts_said += 1
        return options[(self.callouts_said - 1) % len(options)]

    async def _interrupt(self):
        """Stop the current line; keep only what the learner can have heard."""
        task, self.turn_task = self.turn_task, None
        if task is None or task.done():
            return
        npc, spoken = self.speaking, list(self.spoken)
        heard_seconds = max(0.0, min(self.audio_seconds, time.monotonic() - self.audio_t0))
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        self.speaking = None
        await self.send({"type": "clear_audio", "npc_id": npc or self.focus})
        full = " ".join(spoken).strip()
        if npc and full:
            share = heard_seconds / self.audio_seconds if self.audio_seconds > 0 else 0.0
            heard = full[:max(0, int(len(full) * share))].rsplit(" ", 1)[0].strip()
            if heard:
                await self._said(npc, heard + "…")
            event = TranscriptTurn(role="event", npc_id=npc, text=(
                f"learner interrupted; of that line they heard only: {heard or '(nothing)'}")[:4000])
            self.transcript.append(event)
            await self._record([event])
        self.playback_end = time.monotonic()

    async def _barge_in(self):
        if self.turn_task is not None and not self.turn_task.done() and self.speaking:
            if self.speaking == DATE and self.running:
                self.director.record_barge_in()
            await self._interrupt()
            return
        # Everything has been sent but the client may still be playing it (audio runs
        # ahead of playback): stop the playback and record what was actually heard.
        npc, spoken, t0, seconds = self.last_turn
        now = time.monotonic()
        if npc is None or self.playback_end is None or now >= self.playback_end:
            return
        if npc == DATE and self.running:
            self.director.record_barge_in()
        await self.send({"type": "clear_audio", "npc_id": npc})
        full = " ".join(spoken).strip()
        share = max(0.0, min(1.0, (now - t0) / seconds)) if seconds > 0 else 0.0
        heard = full[:int(len(full) * share)].rsplit(" ", 1)[0].strip()
        event = TranscriptTurn(role="event", npc_id=npc, text=(
            f"learner interrupted; of that line they heard only: {heard or '(nothing)'}")[:4000])
        self.transcript.append(event)
        self.history[npc].append(Turn("learner", f"[SCENE] You were cut off after: {heard}…"))
        await self._record([event])
        self.playback_end = now
        self.wingman_due = None

    # ---- the date ---------------------------------------------------------------

    async def _start_date(self):
        if self.running or self.ended:
            return
        self.running, self.started_at, self.focus = True, time.monotonic(), DATE
        score = self.director.state.score
        await self.send({"type": "date_started", "seconds": self.scenario.date_seconds,
                         "date_name": self.scenario.date_character.display_name})
        await self.send({"type": "chemistry_update", "chemistry_score": score, "delta": 0,
                         "mood_label": mood_label(score), "reason": "First impressions",
                         "npc_posture": posture(score), "completed_milestones": [],
                         "evidence_quotes": {}, "green_flags_hit": [], "red_flags_hit": [],
                         "source": "timer"})
        await self._start_turn(DATE, text=self.scenario.date_character.opening_line,
                               kind="opening")

    def _spawn_end(self, reason: str):
        if self.running and (self.end_task is None or self.end_task.done()):
            self.end_task = asyncio.create_task(self._end_date(reason))

    async def _end_date(self, reason: str):
        if not self.running:
            return
        self.running, self.ended = False, True
        self.wingman_due = None
        if self.wingman_prep is not None:
            self.wingman_prep.cancel()
        if self.turn_task is not None and not self.turn_task.done():
            await self._interrupt()
        await self.director.drain(timeout=6.0)
        verdict = verdict_for(self.director.state.score)
        closing = await self._closing_line(verdict)
        self.turn_task = asyncio.create_task(self._speak(DATE, text=closing, kind="closing"))
        with contextlib.suppress(Exception):
            await self.turn_task
        self.director.state.ended = True
        self.director.save()
        await self.send({"type": "date_ended", "reason": reason, "verdict": verdict,
                         "chemistry_score": self.director.state.score, "run_id": self.run_id,
                         "scenario_id": self.scenario.scenario_id,
                         "face": self.tracker.stats()})

    async def _closing_line(self, verdict: str) -> str:
        """A goodbye that remembers the conversation, or the authored one."""
        template = config.dialect_content(self.scenario.dialect)["closings"][verdict]
        if isinstance(self.brain, ScriptedBrain):
            return template
        notes = [f"[SCENE] The bell just rang: the date is over. Say goodbye in one or two short "
                 f"sentences that mention something from the conversation. How you feel: "
                 f"{FEELINGS[verdict]}."]
        ctx = BrainContext(dialect=self.scenario.dialect, chemistry=self.director.state.score)
        parts = []
        try:
            async with asyncio.timeout(5.0):
                async for delta in self.brain.reply(self.scenario.date_character.system_prompt,
                                                    self.history[DATE], notes, ctx):
                    parts.append(delta)
        except Exception as error:  # noqa: BLE001
            log.warning("Closing line fell back to the authored one (%s)", type(error).__name__)
            return template
        return "".join(parts).strip() or template

    def _schedule_wingman(self):
        """Prepare the hint now; show it if the learner is still silent when it is due."""
        if not self.running or self.focus != DATE or self.user_speaking:
            return
        end = self.playback_end or time.monotonic()
        self.wingman_due = end + self.scenario.wingman_seconds
        if self.wingman_prep is not None:
            self.wingman_prep.cancel()
        self.wingman_prep = asyncio.create_task(self.director.wingman(list(self.transcript)))
        self.wingman_prep.add_done_callback(lambda t: t.cancelled() or t.exception())

    async def _tick(self):
        while True:
            await asyncio.sleep(0.1)
            now = time.monotonic()
            if self.running and now - self.started_at > self.scenario.date_seconds + 8:
                # The client normally ends the date; this is the backstop.
                self._spawn_end("timer")
            if (self.wingman_due is not None and now >= self.wingman_due
                    and not self.user_speaking and self.speaking is None and self.running):
                self.wingman_due = None
                await self._show_wingman()

    async def _show_wingman(self):
        task, self.wingman_prep = self.wingman_prep, None
        hint = None
        if task is not None:
            with contextlib.suppress(Exception):
                hint = await asyncio.wait_for(task, timeout=2.5)
        if hint is None:
            hint = await self.director.fallback.wingman(self.scenario, self.transcript)
            self.director.offered = list(hint.options)
        await self.send(hint.model_dump())
        await self.director.nudge(-2, "awkward silence", source="timer")

    # ---- what the date can see -----------------------------------------------------

    async def _telemetry(self, msg: dict, now: float):
        looking = bool(msg.get("is_looking_at_date", True))
        away = float(msg.get("look_away_duration_sec") or 0.0)
        seated = bool(msg.get("is_seated"))
        date_talking = self.speaking == DATE
        # The face can overrule the game camera (head turned, phone in the lap, out of
        # frame); the tracker holds the combined answer, which is what eye contact counts.
        signals = self.tracker.gaze(looking, away, now, date_talking)
        if self.running and seated:
            self.director.record_gaze(self.tracker.looking)
        for signal in signals:
            await self._signal(signal)
        if self.running and self.tracker.look_away_episode(
                now, config.LOOK_AWAY_CALLOUT_SECONDS, date_talking):
            self.pending_callout = True
            self.director.state.look_away_callouts += 1
            name = self.scenario.date_character.display_name
            await self.send({"type": "signal", "kind": "look_away", "label": "Looking away 👀",
                             "effect": f"{name} noticed you looking away"})
            await self.director.nudge(-6, f"looked away while {name} was talking")
        if msg.get("player_smiling") and date_talking:
            self.director.smiled_during_npc = True

    async def _face(self, msg: dict):
        face = self.app.face_tracker
        if face is None:
            return
        try:
            jpeg = base64.b64decode(str(msg.get("jpeg_base64") or ""), validate=True)
        except ValueError:
            return
        if not jpeg or len(jpeg) > MAX_JPEG:
            return
        reading = await face.analyse(jpeg)
        if reading is None:
            if not face.available:
                await self.send({"type": "face_analysis", "found": False,
                                 "unavailable": face.error})
            return
        now = time.monotonic()
        date_talking = self.speaking == DATE
        signals = self.tracker.face(reading, now, date_talking)
        if self.tracker.smiling_now and date_talking:
            self.director.smiled_during_npc = True
        await self.send({"type": "face_analysis", **reading.wire(),
                         "expressions": self.tracker.snapshot()})
        for signal in signals:
            await self._signal(signal)

    async def _signal(self, signal: Signal):
        name = self.scenario.date_character.display_name
        effect = {
            "smile": f"{name} sees you smile" + (" (bonus if it was a joke)" if signal.during_npc else ""),
            "laugh": f"{name} hears you laugh",
            "nod": f"{name} feels listened to",
            "shake": f"{name} notices you disagree",
            "puzzled": f"{name} may slow down for you",
            "surprised": f"{name} sees you react",
            "frown": f"{name} wonders what's wrong",
            "look_back": f"{name} has your attention again",
        }.get(signal.kind, "")
        self.director.note(signal.note)
        await self.send({"type": "signal", "kind": signal.kind, "label": signal.label,
                         "effect": effect, "during_npc": signal.during_npc})

    async def _record(self, turns: list[TranscriptTurn]):
        with contextlib.suppress(Exception):
            await asyncio.to_thread(self.app.transcripts.append, self.run_id, turns)


async def stream_endpoint(websocket: WebSocket):
    await StreamSession(websocket, websocket.app.state).run()


async def vision_endpoint(websocket: WebSocket):
    """Face tracking with no date attached: the onboarding studio's vision panel and the
    avatar mirror. Same face_frame in, face_analysis and signal out, as on /v1/stream."""
    await websocket.accept()
    face = websocket.app.state.face_tracker
    tracker = NonverbalTracker()
    lock = asyncio.Lock()

    async def send(message: dict):
        async with lock:
            await websocket.send_text(json.dumps(message, ensure_ascii=False,
                                                 separators=(",", ":")))

    pending: asyncio.Task | None = None

    async def analyse(jpeg: bytes):
        reading = await face.analyse(jpeg)
        if reading is None:
            if not face.available:
                await send({"type": "face_analysis", "found": False, "unavailable": face.error})
            return
        signals = tracker.face(reading, time.monotonic(), False)
        await send({"type": "face_analysis", **reading.wire(), "expressions": tracker.snapshot()})
        for signal in signals:
            await send({"type": "signal", "kind": signal.kind, "label": signal.label,
                        "effect": "your date will see this", "during_npc": False})

    try:
        await send({"type": "vision_ready",
                    "available": face is not None and await face.start(),
                    "reason": None if face is not None and face.available else
                    (face.error if face is not None else "disabled")})
        while True:
            text = await websocket.receive_text()
            if len(text) > MAX_TEXT_MESSAGE:
                continue
            try:
                msg = json.loads(text)
            except ValueError:
                continue
            if msg.get("type") != "face_frame" or face is None:
                continue
            try:
                jpeg = base64.b64decode(str(msg.get("jpeg_base64") or ""), validate=True)
            except ValueError:
                continue
            if jpeg and len(jpeg) <= MAX_JPEG and (pending is None or pending.done()):
                pending = asyncio.create_task(analyse(jpeg))
    except WebSocketDisconnect:
        pass
    finally:
        if pending is not None:
            pending.cancel()
