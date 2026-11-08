import asyncio
import base64
import importlib
import inspect
import json
import logging
import os
import wave
import io
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from . import config as date_config
from .config import brand
from .director import RUN_ID, Director, DirectorProvider, GoalStore, create_director_provider
from .grading import (GraderProvider, OpenAIGrader, TranscriptStore, create_grader,
                      event_text, overall_grade, passed, rubric_goals)
from .models import (GeneratedScenario, Grade, GradeRequest, GradeResponse,
                     ScenarioRequest, ScenarioResponse, SceneNote, TranscriptTurn)
from .metrics import Metrics
from .scene import ScenePack, default_pack_dir
from .scenarios import OpenAIScenarios, ScenarioProvider, ScenarioStore
from .speech import SpeechInputError, SpeechUnavailable, SUPPORTED_AUDIO_TYPES, SpeechInput, SpeechOutput, SpeechProvider, load_speech_provider

MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_JSON_BYTES = 32 * 1024
# A whole conversation, not a single prompt.
MAX_TRANSCRIPT_BYTES = 256 * 1024


async def read_limited(request: Request, limit: int) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise HTTPException(413, "Request body is too large")
    return bytes(body)


async def provider_call(awaitable, timeout: float):
    try:
        async with asyncio.timeout(timeout):
            return await awaitable
    except SpeechInputError as error:
        raise HTTPException(422, str(error)) from None
    except SpeechUnavailable as error:
        raise HTTPException(503, str(error)) from None
    except TimeoutError:
        raise HTTPException(504, "Provider timed out") from None
    except Exception as error:
        # Provider exceptions may contain credentials or transcripts, so the client gets
        # a bare 502; the operator gets the class in the server log, which is enough to
        # tell a mistyped model name from a refusal.
        logging.getLogger("orchestrator").warning("Provider call failed: %s", type(error).__name__)
        raise HTTPException(502, "Provider failed or returned invalid output") from None


def create_app(*, speech: SpeechProvider | None = None,
               scenarios: ScenarioProvider | None = None,
               grader: GraderProvider | None = None,
               director: DirectorProvider | None = None,
               data_dir: Path | None = None, runs_dir: Path | None = None,
               timeout: float = 60,
               pack: "ScenePack | None" = None,
               face_tracking: bool | None = None) -> FastAPI:
    store = ScenarioStore(data_dir or Path(os.getenv("SCENARIO_DIR", "runs/scenarios")))
    transcripts = TranscriptStore(runs_dir or Path(os.getenv("RUN_DIR", "runs/transcripts")))
    goals = GoalStore(Path(os.getenv("GOAL_DIR", str(transcripts.directory / "goals"))))
    if pack is None:
        # An authored scenario is optional: without one the API still relays speech,
        # it just cannot price an order or describe its cast.
        with suppress(Exception):
            pack = ScenePack.load(default_pack_dir())

    audio_dir = Path(os.getenv("RUN_AUDIO_DIR", str(transcripts.directory.parent / "audio")))
    metrics = Metrics()

    def optional(module: str):
        """A lane's module, if it is there. The voice path must keep working when the
        coaching or ambience code is missing or fails to import."""
        try:
            return importlib.import_module(f".{module}", __package__)
        except Exception as error:  # noqa: BLE001
            logging.getLogger("orchestrator").warning("%s unavailable: %s", module,
                                                      type(error).__name__)
            return None

    brain, ambience = optional("brain_routes"), optional("ambience")
    dates = optional("date_routes")
    date_dir = Path(os.getenv("DATE_DIR", str(transcripts.directory.parent / "dates")))
    chemistry_dir = Path(os.getenv("CHEMISTRY_DIR", str(transcripts.directory.parent / "chemistry")))

    @asynccontextmanager
    async def lifespan(app):
        configured = scenarios
        if configured is None and os.getenv("OPENAI_API_KEY") and os.getenv("SCENARIO_MODEL"):
            configured = OpenAIScenarios(os.environ["OPENAI_API_KEY"], os.environ["SCENARIO_MODEL"])
        app.state.scenarios = configured
        app.state.grader = grader if grader is not None else create_grader()
        judge = director if director is not None else create_director_provider()
        async def steer(run_id: str, npc_id: str, text: str):
            # The director's stage direction rides the same channel as a scene note,
            # so it reaches the character now and again if their conversation reopens.
            if hasattr(app.state.speech, "note"):
                await app.state.speech.note(run_id, npc_id, "director", text)

        extra = {"on_note": steer} if "on_note" in inspect.signature(Director).parameters else {}
        app.state.director = Director(judge, goals, transcripts, timeout, **extra) if judge else None
        if judge is not None and hasattr(judge, "warm_up"):
            # The first call with a new schema is slow; pay for it before anyone speaks.
            warming = asyncio.create_task(judge.warm_up())
            warming.add_done_callback(lambda task: task.cancelled() or task.exception())
        app.state.transcripts, app.state.pack, app.state.scenario_store = transcripts, pack, store
        app.state.metrics, app.state.audio_dir = metrics, audio_dir
        # The coach (hints) and the tutor (written report) are optional: without an
        # OpenAI key the café still talks, it just cannot explain itself afterwards.
        app.state.feedback = app.state.coach = None
        for name, module, factory in (("coach", "coach", "create_coach"),
                                      ("feedback", "feedback", "create_feedback_service")):
            loaded = optional(module) if brain is not None else None
            with suppress(Exception):
                setattr(app.state, name, getattr(loaded, factory)() if loaded else None)
        if app.state.coach is not None and hasattr(app.state.coach, "warm_up"):
            # A learner who asks for a hint is already lost; do not make the first one slow.
            hinting = asyncio.create_task(app.state.coach.warm_up())
            hinting.add_done_callback(lambda task: task.cancelled() or task.exception())
        # The speed date: matchmaker, live chemistry, verdict, and the face tracker.
        app.state.matchmaker = app.state.chemistry_judge = app.state.date_grader = None
        app.state.face_tracker = None
        if dates is not None:
            from .chemistry_director import ChemistryStore, create_judge
            from .date_grader import create_date_grader
            from .face_tracker import FaceTracker
            from .matchmaker import DateStore, create_matchmaker
            app.state.matchmaker = create_matchmaker()
            app.state.date_store = DateStore(date_dir)
            app.state.chemistry_store = ChemistryStore(chemistry_dir)
            app.state.chemistry_judge = create_judge()
            app.state.date_grader = create_date_grader()
            tracking = face_tracking if face_tracking is not None \
                else os.getenv("FACE_TRACKING", "1") != "0"
            if tracking:
                app.state.face_tracker = FaceTracker()
                # Load MediaPipe in the background so the first webcam frame is fast.
                loading = asyncio.create_task(app.state.face_tracker.start())
                loading.add_done_callback(lambda task: task.cancelled() or task.exception())
        app.state.speech = speech
        if speech is None and os.getenv("SPEECH_ADAPTER"):
            app.state.speech = load_speech_provider(os.environ["SPEECH_ADAPTER"])
        elif speech is None and os.getenv("ELEVENLABS_API_KEY"):
            from .elevenlabs_adapter import ElevenLabsSpeech, create_provider
            app.state.speech = create_provider()
            if pack is not None and isinstance(app.state.speech, ElevenLabsSpeech):
                app.state.speech.pack = pack  # one loaded pack, shared
        if hasattr(app.state.speech, "on_timings"):
            app.state.speech.on_timings = metrics.record
        try:
            yield
        finally:
            if isinstance(configured, OpenAIScenarios):
                await configured.aclose()
            if isinstance(app.state.grader, OpenAIGrader):
                await app.state.grader.aclose()
            if app.state.director is not None:
                await app.state.director.aclose()
            for extra in (app.state.coach, app.state.feedback):
                if extra is not None and hasattr(extra, "aclose"):
                    with suppress(Exception):
                        await extra.aclose()
            if app.state.speech is not None and hasattr(app.state.speech, "aclose"):
                await app.state.speech.aclose()
            for service in (app.state.matchmaker, app.state.chemistry_judge, app.state.date_grader):
                if service is not None and hasattr(service, "aclose"):
                    with suppress(Exception):
                        await service.aclose()
            if app.state.face_tracker is not None:
                app.state.face_tracker.close()

    app = FastAPI(title=f"{brand().name} API", version="0.3.0", lifespan=lifespan)
    for module in (brain, ambience, dates):
        if module is not None and hasattr(module, "build_router"):
            app.include_router(module.build_router())

    @app.get("/v1/metrics")
    async def latency():
        """Median and 90th-percentile latency per stage, per character, since start.

        `first_sound` is the one a learner feels: from the end of their upload to the
        first audio frame of the reply. Warm turns only, when there are any.
        """
        return {"targets_ms": {"first_sound_p50": 1200, "first_sound_p90": 1800},
                "characters": metrics.summary()}

    @app.get("/health")
    async def health():
        return {"status": "ok", "scenarios_ready": app.state.scenarios is not None,
                "speech_ready": app.state.speech is not None,
                "grader_ready": app.state.grader is not None,
                "director_ready": app.state.director is not None,
                "scenario_pack": pack.scenario.scenario_id if pack else None,
                "date": date_health()}

    def date_health() -> dict:
        m, p = date_config.models(), date_config.providers()
        face = getattr(app.state, "face_tracker", None)
        return {"matchmaker": "claude" if m.anthropic_ready else "templates",
                "chemistry": "claude" if m.anthropic_ready else "rules",
                "grader": "claude" if m.anthropic_ready else "rules",
                "brain": "gemini" if m.gemini_ready else "claude" if m.anthropic_ready
                else "scripted",
                "stt": "deepgram" if p.deepgram_key else "none",
                "tts": "fish" if p.fish_key else "sample",
                "face": "off" if face is None else "ready" if face.landmarker is not None
                else "loading" if face.available else "unavailable"}

    @app.get("/v1/npcs")
    async def npcs():
        """Who the client can talk to, and what to send as npc_id.

        Lets the game discover the cast instead of hardcoding ids, and shows at a
        glance which characters actually have an agent configured.
        """
        if pack is None:
            raise HTTPException(503, "No scenario pack is loaded")
        configured = getattr(app.state.speech, "agents", {}) or {}
        return {
            "scenario_id": pack.scenario.scenario_id,
            "title": pack.scenario.title,
            "setting": pack.scenario.setting,
            "language": pack.scenario.language,
            "language_label": pack.scenario.language_label,
            "level": pack.scenario.level,
            "currency": pack.scenario.currency,
            "gestures": pack.scenario.gestures,
            "npcs": [{
                "npc_id": npc.npc_id,
                "aliases": npc.aliases,
                "name": npc.name,
                "role": npc.role,
                "gender": npc.gender,
                "greeting": npc.first_message,
                "actions": npc.tools,
                "max_duration_seconds": npc.max_duration_seconds,
                "ready": npc.npc_id in configured,
            } for npc in pack.scenario.npcs],
            "goals": [g.model_dump() for g in pack.scenario.goals],
            "menu": [{"item_id": k, "name_es": v.name_es, "price_mxn": v.price_mxn,
                      "available": v.available} for k, v in pack.menu.items.items()],
        }

    @app.post("/v1/scenarios", response_model=ScenarioResponse, openapi_extra={
        "requestBody": {"required": True, "content": {"application/json": {
            "schema": ScenarioRequest.model_json_schema()}}}})
    async def generate(request: Request):
        if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
            raise HTTPException(415, "Expected application/json")
        from pydantic import ValidationError
        try:
            payload = ScenarioRequest.model_validate_json(await read_limited(request, MAX_JSON_BYTES))
        except ValidationError:
            raise HTTPException(422, "Expected a nonempty prompt, language, and valid CEFR level") from None
        if app.state.scenarios is None:
            raise HTTPException(503, "Configure OPENAI_API_KEY and SCENARIO_MODEL")

        async def validated():
            generated = await app.state.scenarios.generate(payload)
            result = GeneratedScenario.model_validate(generated)
            if result.scenario.level != payload.level or result.scenario.language != payload.language:
                raise ValueError("Provider changed requested language or level")
            return result

        result = await provider_call(validated(), timeout)
        saved = ScenarioResponse(scenario_id=uuid4(), **result.model_dump())
        try:
            await asyncio.to_thread(store.save, saved)
        except OSError:
            raise HTTPException(500, "Could not save scenario") from None
        return saved

    @app.get("/v1/scenarios/{scenario_id}", response_model=ScenarioResponse)
    async def get_scenario(scenario_id: UUID):
        try:
            return await asyncio.to_thread(store.get, scenario_id)
        except FileNotFoundError:
            raise HTTPException(404, "Scenario not found") from None

    @app.get("/v1/runs/{run_id}")
    async def get_run(run_id: str):
        """What the server recorded for one visit: the evidence /v1/grade reads.

        Every speech turn appends to it automatically, so a client that already sends
        `run_id` gets goal tracking without doing anything else.
        """
        try:
            turns = await asyncio.to_thread(transcripts.get, run_id)
        except ValueError:
            raise HTTPException(422, "Invalid run_id") from None
        except FileNotFoundError:
            raise HTTPException(404, "No recorded transcript for this run") from None
        return {"run_id": run_id, "turn_count": len(turns),
                "transcript": [turn.model_dump() for turn in turns]}

    async def rubric_for(scenario_id: UUID | None):
        """The goals a run is played against: a saved scenario's, else the pack's."""
        if scenario_id is not None:
            saved = await get_scenario(scenario_id)
            return rubric_goals(saved.scenario.goals)
        return rubric_goals(pack.scenario.goals) if pack is not None else []

    @app.get("/v1/runs/{run_id}/goals")
    async def run_goals(run_id: str, scenario_id: UUID | None = None):
        """Which goals the run has met so far, as the director ticks them.

        Poll this a second or two after a speech turn: `reviewing` is true while the
        latest turn is still being judged. Goals are ticked from what the learner
        said, not from scene actions; the client may still tick those itself.
        """
        if app.state.director is None:
            raise HTTPException(503, "Configure OPENAI_API_KEY and DIRECTOR_MODEL (or TUTOR_MODEL)")
        rubric = await rubric_for(scenario_id)
        if not rubric:
            raise HTTPException(422, "No goals to track: pass scenario_id or load a scenario pack")
        try:
            return await app.state.director.status(run_id, rubric)
        except ValueError:
            raise HTTPException(422, "Invalid run_id") from None

    @app.post("/v1/grade", response_model=GradeResponse, openapi_extra={
        "requestBody": {"required": True, "content": {"application/json": {
            "schema": GradeRequest.model_json_schema()}}}})
    async def grade(request: Request):
        """Grade a finished run against its goals, in the shape the receipt prints.

        The rubric comes from inline `goals`, else a saved `scenario_id`, else the
        loaded scenario pack. The conversation comes from an inline `transcript`,
        else whatever the server recorded for `run_id`.
        """
        if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
            raise HTTPException(415, "Expected application/json")
        from pydantic import ValidationError
        body = await read_limited(request, MAX_TRANSCRIPT_BYTES)
        with suppress(ValueError):
            peek = json.loads(body)
            if (dates is not None and isinstance(peek, dict)
                    and str(peek.get("scenario_id") or "").startswith("date_")):
                # A speed date: the verdict receipt instead of the café's bill.
                from .date_models import DateGradeRequest
                try:
                    date_request = DateGradeRequest.model_validate(peek)
                except ValidationError:
                    raise HTTPException(422, "A date grade needs run_id and scenario_id") from None
                verdict = await dates.grade_date(app.state, date_request)
                return JSONResponse(verdict.model_dump(mode="json"))
        try:
            payload = GradeRequest.model_validate_json(body)
        except ValidationError:
            raise HTTPException(422, "Expected goals or a scenario_id, and a "
                                     "transcript or a run_id") from None
        if app.state.grader is None:
            raise HTTPException(503, "Configure OPENAI_API_KEY and TUTOR_MODEL")

        rubric = payload.goals
        if rubric is None and payload.scenario_id is not None:
            saved = await get_scenario(payload.scenario_id)
            rubric = rubric_goals(saved.scenario.goals)
        if rubric is None and pack is not None:
            rubric = rubric_goals(pack.scenario.goals)
        if not rubric:
            raise HTTPException(422, "No goals to grade: send goals, a scenario_id, "
                                     "or load a scenario pack")

        transcript = payload.transcript
        if transcript is None and payload.run_id is not None:
            try:
                transcript = await asyncio.to_thread(transcripts.get, payload.run_id)
            except (FileNotFoundError, ValueError):
                raise HTTPException(404, "No recorded transcript for this run") from None
        if not transcript:
            raise HTTPException(422, "No conversation to grade: send a transcript, "
                                     "or a run_id the server recorded")

        async def validated():
            result = await app.state.grader.grade(rubric, transcript)
            if not isinstance(result, Grade):
                raise ValueError("Grader returned an unexpected type")
            judged = [score.id for score in result.scores]
            if sorted(judged) != sorted(goal.id for goal in rubric):
                raise ValueError("Grader did not judge exactly the requested goals")
            # No quote, no pass: a grade we cannot show the learner the reason for is
            # not a grade.
            if any(passed(s) and not (s.evidence_quote or "").strip() for s in result.scores):
                raise ValueError("Grader passed a goal without evidence")
            return result

        result = await provider_call(validated(), timeout)
        return GradeResponse(**result.model_dump(), overall=overall_grade(rubric, result.scores),
                             scenario_id=payload.scenario_id, run_id=payload.run_id,
                             goals_passed=sum(passed(s) for s in result.scores),
                             goals_total=len(result.scores))

    @app.post("/v1/runs/{run_id}/notes", status_code=204)
    async def note_run(run_id: str, note: SceneNote):
        """Tell a character about the scene without taking a turn (see SceneNote)."""
        if not RUN_ID.match(run_id):
            raise HTTPException(422, "run_id must be [A-Za-z0-9_-], up to 64 characters")
        provider = app.state.speech
        if provider is None:
            raise HTTPException(503, "Speech adapter is not configured")
        if not hasattr(provider, "note"):
            raise HTTPException(501, "Speech adapter does not support scene notes")
        await provider_call(provider.note(run_id, note.npc_id, note.key, note.text), timeout)
        return Response(status_code=204)

    @app.delete("/v1/speech/sessions/{session_id}", status_code=204)
    async def end_speech_session(session_id: UUID):
        provider = app.state.speech
        if provider is None:
            raise HTTPException(503, "Speech adapter is not configured")
        if not hasattr(provider, "end_session"):
            raise HTTPException(501, "Speech adapter does not support ending sessions")
        await provider_call(provider.end_session(session_id), timeout)
        return Response(status_code=204)

    AUDIO_BODY = {"requestBody": {"required": True, "content": {media: {
        "schema": {"type": "string", "format": "binary"}} for media in sorted(SUPPORTED_AUDIO_TYPES)}}}
    RUN = Query(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    NPC = Query(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    LEVEL = Query(default=None, pattern=r"^(A1|A2|B1|B2)$")

    async def parse_turn(request: Request, session_id, npc_id, scenario_id, sample_rate,
                         run_id, learner_name, learner_level, interrupted_at_ms,
                         need_audio: bool = True) -> SpeechInput:
        """Everything that can be rejected before a provider is touched."""
        media_type, audio = "audio/wav", b""
        if need_audio:
            media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
            if media_type not in SUPPORTED_AUDIO_TYPES:
                raise HTTPException(415, "Unsupported audio Content-Type")
            if media_type == "audio/pcm" and sample_rate is None:
                raise HTTPException(422, "Raw PCM requires sample_rate (PCM16 LE mono)")
            audio = await read_limited(request, MAX_AUDIO_BYTES)
            if not audio or (media_type == "audio/pcm" and len(audio) % 2):
                raise HTTPException(422, "Audio must be nonempty; PCM16 must contain whole samples")
        context = None
        if scenario_id:
            saved = await get_scenario(scenario_id)
            if npc_id not in {c.id for c in saved.scenario.characters}:
                raise HTTPException(422, "NPC does not belong to this scenario")
            context = saved.scenario.model_dump()
        if app.state.speech is None:
            raise HTTPException(503, "Speech adapter is not configured")
        return SpeechInput(audio, media_type, session_id, npc_id, scenario_id, context,
                           sample_rate, run_id, learner_name, learner_level, interrupted_at_ms)

    def keep_clip(run: str, turn: SpeechInput, heard: str, unsure, min_logprob):
        """The learner's own voice, kept for the end-of-visit pronunciation pass."""
        if (not turn.audio or not RUN_ID.match(run)
                or turn.media_type not in {"audio/wav", "audio/x-wav", "audio/pcm"}):
            return
        folder = audio_dir / run
        folder.mkdir(parents=True, exist_ok=True)
        index = len(list(folder.glob("turn_*.wav"))) + 1
        if index > 200:
            return
        data = turn.audio
        if turn.media_type == "audio/pcm":
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(turn.sample_rate)
                out.writeframes(data)
            data = buffer.getvalue()
        (folder / f"turn_{index:03d}.wav").write_bytes(data)
        (folder / f"turn_{index:03d}.json").write_text(json.dumps({
            "text": heard, "npc_id": turn.npc_id, "low_confidence_words": list(unsure),
            "min_logprob": min_logprob}, ensure_ascii=False), encoding="utf-8")

    async def after_turn(turn: SpeechInput, heard, said, actions, unsure, min_logprob,
                         previous_heard=None) -> list[str]:
        """Record the evidence and wake the director. Best effort: none of this may
        cost the learner the turn they just paid for."""
        run = turn.run_id or str(turn.session_id)
        record = []
        if previous_heard is not None:
            record.append(TranscriptTurn(role="event", npc_id=turn.npc_id, text=(
                f"learner interrupted; of the previous reply they heard only: {previous_heard}")[:4000]))
        if heard and heard.strip():
            record.append(TranscriptTurn(role="learner", npc_id=turn.npc_id,
                                         text=heard.strip()[:4000],
                                         low_confidence_words=list(unsure or ())[:40]))
        if said and said.strip():
            record.append(TranscriptTurn(role="npc", npc_id=turn.npc_id, text=said.strip()[:4000]))
        record += [TranscriptTurn(role="event", npc_id=turn.npc_id, text=event_text(action))
                   for action in actions]
        with suppress(Exception):
            await asyncio.to_thread(transcripts.append, run, record)
        with suppress(Exception):
            await asyncio.to_thread(keep_clip, run, turn, heard or "", unsure or (), min_logprob)
        # The director reads the run back and ticks goals after the reply has gone
        # out; the list returned here is therefore the state before this turn.
        achieved: list[str] = []
        if app.state.director is not None and any(t.role == "learner" for t in record):
            with suppress(Exception):
                rubric = await rubric_for(turn.scenario_id)
                achieved = [g["id"] for g in (await app.state.director.status(run, rubric))["goals"]
                            if g["achieved"]]
                app.state.director.schedule(run, rubric)
        return achieved

    @app.post("/v1/speech/sessions/{session_id}/warm")
    async def warm(request: Request, session_id: UUID, npc_id: str = NPC,
                   scenario_id: UUID | None = None, run_id: str | None = RUN,
                   learner_name: str | None = Query(default=None, max_length=60),
                   learner_level: str | None = LEVEL):
        """Open the character's conversation and get their opening line.

        Call this when the player walks up. The character greets them in their own
        live voice (200, the same JSON shape as `/v1/speech?response_format=json`
        without a `user_transcript`), and the learner's first turn then costs the
        same as every other one instead of also paying to connect. Safe to repeat: a
        conversation that is already open has already said hello, so this is 204.
        """
        turn = await parse_turn(request, session_id, npc_id, scenario_id, None, run_id,
                                learner_name, learner_level, None, need_audio=False)
        if not hasattr(app.state.speech, "warm"):
            raise HTTPException(501, "Speech adapter cannot pre-warm sessions")
        output = await provider_call(app.state.speech.warm(turn), timeout)
        if output is None:
            return Response(status_code=204)
        if (not isinstance(output, SpeechOutput) or not isinstance(output.audio, bytes)
                or not output.audio or len(output.audio) > MAX_AUDIO_BYTES
                or output.media_type not in SUPPORTED_AUDIO_TYPES):
            raise ValueError("Invalid speech output")
        await after_turn(turn, None, output.agent_transcript, [], (), None)
        headers = {"X-Session-ID": str(session_id), "Cache-Control": "no-store"}
        if output.timings_ms:
            headers["Server-Timing"] = ", ".join(
                f"{stage};dur={ms}" for stage, ms in output.timings_ms.items())
        return JSONResponse({"session_id": str(session_id), "npc_id": npc_id,
            "audio_base64": base64.b64encode(output.audio).decode("ascii"),
            "media_type": output.media_type, "sample_rate": output.sample_rate,
            "user_transcript": None, "agent_transcript": output.agent_transcript,
            "actions": [], "visemes": list(output.visemes), "goals_achieved": [],
            "timings_ms": output.timings_ms or {}}, headers=headers)

    @app.post("/v1/speech", openapi_extra=AUDIO_BODY)
    async def respond(request: Request, session_id: UUID, npc_id: str = NPC,
                      scenario_id: UUID | None = None,
                      sample_rate: int | None = Query(default=None, ge=8000, le=48000),
                      response_format: Literal["audio", "json"] = "audio",
                      run_id: str | None = RUN,
                      learner_name: str | None = Query(default=None, max_length=60),
                      learner_level: str | None = LEVEL,
                      interrupted_at_ms: int | None = Query(default=None, ge=0, le=600000)):
        turn = await parse_turn(request, session_id, npc_id, scenario_id, sample_rate, run_id,
                                learner_name, learner_level, interrupted_at_ms)

        async def validated():
            result = await app.state.speech.respond(turn)
            if (not isinstance(result, SpeechOutput) or not isinstance(result.audio, bytes)
                    or not result.audio or len(result.audio) > MAX_AUDIO_BYTES
                    or result.media_type not in SUPPORTED_AUDIO_TYPES):
                raise ValueError("Invalid speech output")
            if result.media_type == "audio/pcm" and (
                not isinstance(result.sample_rate, int) or not 8000 <= result.sample_rate <= 48000
                or len(result.audio) % 2
            ):
                raise ValueError("Invalid PCM metadata")
            return result

        output = await provider_call(validated(), timeout)
        actions = [a for a in output.actions if isinstance(a, dict)]
        achieved = await after_turn(turn, output.user_transcript, output.agent_transcript,
                                    actions, output.low_confidence_words, output.min_logprob,
                                    output.previous_reply_heard)
        headers = {"X-Session-ID": str(session_id), "Cache-Control": "no-store"}
        if output.sample_rate is not None:
            headers["X-Audio-Sample-Rate"] = str(output.sample_rate)
        if output.timings_ms:
            headers["Server-Timing"] = ", ".join(
                f"{stage};dur={ms}" for stage, ms in output.timings_ms.items())
        if response_format == "json":
            return JSONResponse({"session_id": str(session_id), "npc_id": npc_id,
                "audio_base64": base64.b64encode(output.audio).decode("ascii"),
                "media_type": output.media_type, "sample_rate": output.sample_rate,
                "user_transcript": output.user_transcript,
                "agent_transcript": output.agent_transcript,
                "actions": actions,
                "goals_achieved": achieved,
                "visemes": list(output.visemes),
                "low_confidence_words": list(output.low_confidence_words),
                "timings_ms": output.timings_ms,
                "ended": output.ended,
                "previous_reply_heard": output.previous_reply_heard},
                headers=headers)
        # Raw-audio callers still need the scene actions, and a header is the only
        # place left to put them. Skipped entirely if it would be unreasonably large.
        if actions:
            encoded = json.dumps(actions, separators=(",", ":"))
            if len(encoded) <= 2000:
                headers["X-Scene-Actions"] = encoded
        return Response(output.audio, media_type=output.media_type, headers=headers)

    @app.post("/v1/speech/stream", openapi_extra=AUDIO_BODY)
    async def respond_stream(request: Request, session_id: UUID, npc_id: str = NPC,
                             scenario_id: UUID | None = None,
                             sample_rate: int | None = Query(default=None, ge=8000, le=48000),
                             run_id: str | None = RUN,
                             learner_name: str | None = Query(default=None, max_length=60),
                             learner_level: str | None = LEVEL,
                             interrupted_at_ms: int | None = Query(default=None, ge=0, le=600000)):
        """The same turn as `/v1/speech`, delivered as it happens.

        Newline-delimited JSON, one event per line, flushed immediately: `transcript`,
        then `audio` frames (base64 PCM16 mono with their mouth shapes) interleaved
        with `text` and `action`, then `done`. Play each audio frame as it arrives:
        the learner hears the character about a second after they stop talking.
        """
        turn = await parse_turn(request, session_id, npc_id, scenario_id, sample_rate, run_id,
                                learner_name, learner_level, interrupted_at_ms)
        if not hasattr(app.state.speech, "stream"):
            raise HTTPException(501, "Speech adapter cannot stream")
        events = app.state.speech.stream(turn)
        # Anything that fails before the first event is an ordinary HTTP error; after
        # that the status line has gone, so failures travel as an `error` event.
        first = await provider_call(anext(events), timeout)

        def line(event: dict) -> bytes:
            return (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode()

        async def body():
            heard = said = ""
            unsure, min_logprob, actions = (), None, []
            try:
                async with asyncio.timeout(timeout):
                    pending = first
                    while pending is not None:
                        event, kind = pending, pending["type"]
                        if kind == "transcript":
                            heard, unsure = event["text"], event["low_confidence_words"]
                            min_logprob = event.get("min_logprob")
                        elif kind == "audio":
                            event = {**event, "pcm_base64": base64.b64encode(event["pcm"]).decode("ascii")}
                            del event["pcm"]
                        elif kind == "text":
                            said = event["text"]
                        elif kind == "action":
                            actions.append(event["action"])
                        elif kind == "done":
                            event = {**event, "session_id": str(session_id), "npc_id": npc_id,
                                     "goals_achieved": await after_turn(
                                         turn, heard, said, actions, unsure, min_logprob,
                                         event.get("previous_reply_heard"))}
                        yield line(event)
                        pending = await anext(events, None)
            except (TimeoutError, Exception) as error:  # noqa: BLE001
                logging.getLogger("orchestrator").warning("Stream failed: %s", type(error).__name__)
                detail = str(error) if isinstance(error, (SpeechInputError, SpeechUnavailable)) \
                    else "Provider failed or timed out"
                yield line({"type": "error", "detail": detail})
            finally:
                with suppress(Exception):
                    await events.aclose()

        return StreamingResponse(body(), media_type="application/x-ndjson", headers={
            "X-Session-ID": str(session_id), "Cache-Control": "no-store",
            "X-Accel-Buffering": "no"})

    return app


app = create_app()
