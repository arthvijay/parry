"""The speed date, offline: matchmaker, chemistry, verdict, signals, voices and the
live stream, with every provider replaced by a local double or a fake server."""

import asyncio
import base64
import json
import random

import httpx2
import anthropic
import pytest
from fastapi.testclient import TestClient

from orchestrator import config, stream_gateway
from orchestrator.app import create_app
from orchestrator.chemistry_director import (ChemistryDirector, ChemistryStore, RulesChemistryJudge,
                                             TurnJudgement, _WireTick,
                                             mood_label, posture)
from orchestrator.claude import Claude
from orchestrator.date_brain import Turn, with_notes
from orchestrator.date_grader import DateGrader, _WirePillar, checked, verdict_for
from orchestrator.date_models import MatchmakerRequest, VoiceConfig
from orchestrator.face_tracker import FaceReading
from orchestrator.matchmaker import Matchmaker, build_scenario, template_draft
from orchestrator.models import TranscriptTurn
from orchestrator.nonverbal import NonverbalTracker
from orchestrator.tts import SentenceChunker

KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY",
        "GOOGLE_CLOUD_PROJECT", "NVIDIA_API_KEY", "NEMOTRON_ASR_SERVER", "NEMOTRON_ASR_LANGUAGE", "OPENAI_API_KEY",
        "ELEVENLABS_API_KEY", "SPEECH_ADAPTER")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    # The sample voice is paced at real time in production; tests do not wait for it.
    monkeypatch.setattr(stream_gateway, "AHEAD_SECONDS", 10_000.0)


def request(**overrides) -> MatchmakerRequest:
    values = dict(learner_name="Arth", language="es-AR", proficiency="B2", venue_style="auto",
                  date_gender="female", date_ethnicity="latina",
                  personality_archetype="playful_sarcastic",
                  custom_notes="Loves indie rock and photography, hates crypto bros",
                  scene_prompt="a rooftop bar at sunset after the rain")
    values.update(overrides)
    return MatchmakerRequest(**values)


def scenario(**overrides):
    req = request(**overrides)
    return build_scenario(req, template_draft(req, random.Random(1)), "template",
                          random.Random(1))


# --------------------------------------------------------------------------- matchmaker

@pytest.mark.parametrize("code", sorted(config.DIALECTS))
def test_every_dialect_builds_a_complete_date(code):
    s = scenario(language=code)
    c = s.date_character
    assert s.scenario_id.startswith("date_") and s.dialect == code
    assert c.opening_line and c.system_prompt and len(c.interests) >= 2
    assert s.host_character.greeting and c.display_name in s.host_character.greeting
    assert [m.id for m in s.milestones] == ["break_ice", "find_common_ground", "cultural_vibe",
                                           "close_the_date"]
    assert c.voice_config.provider == "sample"  # no ElevenLabs key in tests
    assert c.avatar_config.base_model == "Female_Party_02"


def test_scene_prompt_picks_the_venue_and_notes_shape_the_persona():
    s = scenario()
    assert s.venue.id == "rooftop_bar" and s.venue_scene == "SampleScene"
    assert any("crypto" in r for r in s.date_character.red_flags)
    assert "indie rock" in s.date_character.interests
    assert "voseo" in s.date_character.system_prompt
    # Appearance drives the model only, never the persona.
    assert "latina" not in s.date_character.system_prompt.casefold()


def test_elevenlabs_voice_is_chosen_when_configured(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setenv("ELEVENLABS_VOICE_ES_AR_FEMALE", "voice-ar")
    v = scenario().date_character.voice_config
    assert (v.provider, v.voice_id) == ("elevenlabs", "voice-ar")
    assert 0.7 <= v.speaking_rate <= 1.2
    monkeypatch.delenv("ELEVENLABS_VOICE_ES_AR_FEMALE")
    assert scenario().date_character.voice_config.voice_id == config.ELEVENLABS_DEFAULT_VOICES["female"]


def test_matchmaker_falls_back_to_templates_when_the_model_fails():
    class Broken:
        async def draft(self, req):
            raise RuntimeError("down")

    s = asyncio.run(Matchmaker(Broken()).generate(request()))
    assert s.generated_by == "template"


def test_matchmaker_rejects_unknown_options():
    with pytest.raises(ValueError):
        request(language="xx-XX")
    with pytest.raises(ValueError):
        request(date_ethnicity="martian")


# --------------------------------------------------------------------------- Claude

def test_claude_parse_sends_structured_output_effort_and_fallbacks():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        seen["beta"] = req.headers.get("anthropic-beta")
        body = {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
                "content": [{"type": "text", "text": json.dumps({"a": "hola"})}],
                "stop_reason": "end_turn", "stop_sequence": None,
                "usage": {"input_tokens": 3, "output_tokens": 3}}
        return httpx2.Response(200, json=body)

    from pydantic import BaseModel

    class Out(BaseModel):
        a: str

    client = anthropic.AsyncAnthropic(api_key="k", http_client=anthropic.DefaultAsyncHttpxClient(
        transport=httpx2.MockTransport(handler)))
    out = asyncio.run(Claude(client=client).parse(model="claude-sonnet-5-5", system="s",
                                                  payload={"x": 1}, schema=Out, effort="low"))
    assert out.a == "hola"
    assert seen["output_config"]["effort"] == "low"
    assert seen["output_config"]["format"]["type"] == "json_schema"
    assert seen["fallbacks"] == "default" and "server-side-fallback" in seen["beta"]


# --------------------------------------------------------------------------- chemistry

def director(tmp_path, judge=None, **overrides):
    events = []

    async def emit(message):
        events.append(message)

    d = ChemistryDirector(scenario(**overrides), "run_1", judge, ChemistryStore(tmp_path), emit)
    return d, events


def learner(text):
    return TranscriptTurn(role="learner", npc_id="date_npc", text=text)


def test_rules_judge_ticks_milestones_with_the_learners_own_words(tmp_path):
    d, events = director(tmp_path)
    line = "Hola, me llamo Arth, che, ¿y vos qué sacás con la cámara? Me encanta la fotografía."
    async def go():
        await d.learner_turn([learner(line)], line, [])

    asyncio.run(go())
    state = d.state
    assert {"break_ice", "cultural_vibe", "find_common_ground"} <= set(state.milestones)
    assert all(q in line for q in state.milestones.values())
    assert state.score > 50 and events[-1]["type"] == "chemistry_update"


def test_a_quote_the_learner_never_said_is_not_a_tick(tmp_path):
    class Liar:
        async def judge(self, ctx):
            return TurnJudgement(delta=5, reason="x", green_flags_hit=[], red_flags_hit=[],
                                 milestones=[_WireTick(id="break_ice", evidence_quote="Soy Brad Pitt",
                                                       check="", holds=True)],
                                 date_was_joking=False, used_local_slang=False,
                                 used_english=False, mistake=None)

    d, _ = director(tmp_path, judge=Liar())

    async def go():
        await d.learner_turn([learner("hola")], "hola", [])

    asyncio.run(go())
    assert d.state.milestones == {}


def test_english_and_one_word_answers_cost_chemistry(tmp_path):
    d, _ = director(tmp_path)

    async def go():
        await d.learner_turn([learner("yes")], "yes", [])
        await d.learner_turn([learner("yes"), learner("I like the music and the city")],
                             "I like the music and the city", [])

    asyncio.run(go())
    assert d.state.score < 50 and d.state.english_turns >= 1


def test_wingman_use_is_detected_and_the_meter_moods(tmp_path):
    d, _ = director(tmp_path)
    hint = asyncio.run(d.wingman([]))
    assert len(hint.options) == 3 and d.state.wingman_hints == 1
    assert d.check_wingman_use(hint.options[1].target.lower())
    assert d.state.wingman_lines_used == 1
    assert mood_label(80) == "Vibing 🔥" and posture(30) == "lean_back_glance_away"


# --------------------------------------------------------------------------- verdict

def test_verdict_thresholds():
    assert (verdict_for(65), verdict_for(64), verdict_for(45), verdict_for(44)) == \
        ("match", "friendzone", "friendzone", "ghosted")


def test_unquotable_pass_is_capped_at_d_plus():
    transcript = [learner("hola che")]
    p = checked("icebreaker", _WirePillar(grade="A", comment="ok", evidence_quote="invented"),
                transcript)
    assert p.grade == "D+" and p.evidence_quote is None
    p = checked("icebreaker", _WirePillar(grade="A", comment="ok", evidence_quote="hola che"),
                transcript)
    assert p.grade == "A"


def test_rules_grader_writes_the_whole_receipt(tmp_path):
    d, _ = director(tmp_path)
    line = "Hola, me llamo Arth, che. ¿Qué fotos sacás?"

    async def go():
        await d.learner_turn([learner(line)], line, [])
        d.record_latency(900)
        d.record_confidence(0.93)
        return await DateGrader().grade(d.scenario, d.state, [learner(line)], "run_1")

    verdict = asyncio.run(go())
    assert verdict.verdict in ("match", "friendzone", "ghosted")
    assert [p.id for p in verdict.pillars] == ["icebreaker", "dialect_authenticity",
                                              "active_listening", "agility_pacing"]
    assert verdict.metrics.avg_response_latency_ms == 900
    assert verdict.followup.text and verdict.stamp and verdict.graded_by == "rules"


# --------------------------------------------------------------------------- signals

def face(smile=0.0, jaw=0.0, pitch=0.0, yaw=0.0, brow_down=0.0):
    return FaceReading(found=True, blendshapes={"mouthSmileLeft": smile, "mouthSmileRight": smile,
                                                "jawOpen": jaw, "browDownLeft": brow_down,
                                                "browDownRight": brow_down},
                       pitch=pitch, yaw=yaw)


def test_a_held_smile_is_one_signal_and_a_flicker_is_none():
    t = NonverbalTracker()
    assert t.face(face(smile=0.8), 0.0, True) == []
    kinds = [s.kind for i in range(1, 10) for s in t.face(face(smile=0.8), i * 0.1, True)]
    assert kinds == ["smile"]
    assert "they smiled while you were talking" in t.take_notes()


def test_nod_detection_from_head_pitch():
    t = NonverbalTracker()
    kinds = []
    for i in range(14):
        pitch = 8.0 if (i // 2) % 2 else -8.0
        kinds += [s.kind for s in t.face(face(pitch=pitch), i * 0.1, False)]
    assert "nod" in kinds


def test_look_away_callout_fires_once_per_episode():
    t = NonverbalTracker()
    t.gaze(False, 0.0, 0.0, True)
    assert not t.look_away_episode(3.0, 4.5, True)
    assert t.look_away_episode(5.0, 4.5, True)
    assert not t.look_away_episode(6.0, 4.5, True)
    assert [s.kind for s in t.gaze(True, 0.0, 7.0, True)] == ["look_back"]


# --------------------------------------------------------------------------- voice

def test_sentence_chunker_speaks_early_and_cleanly():
    c = SentenceChunker()
    out = c.push("¡Hola! Qué bueno ") + c.push("que viniste. Oye, una cosa,") + c.flush()
    assert out == ["¡Hola!", "Qué bueno que viniste.", "Oye, una cosa,"]
    assert SentenceChunker().push("你好！我叫林悦。") == ["你好！", "我叫林悦。"]


def test_notes_join_the_newest_learner_line():
    turns = with_notes([Turn("date", "Hola"), Turn("learner", "Hola, soy Arth")],
                       ["[CHEMISTRY 60/100]"])
    assert turns[0].role == "learner" and turns[-1].text.endswith("[CHEMISTRY 60/100]")


def test_elevenlabs_voice_speaks_the_streaming_protocol(monkeypatch):
    from websockets.asyncio.server import serve

    from orchestrator.tts import ElevenLabsVoice
    received, seen = [], {}

    async def elevenlabs(ws):
        seen["key"] = ws.request.headers["xi-api-key"]
        seen["path"] = ws.request.path
        async for raw in ws:
            msg = json.loads(raw)
            received.append(msg)
            if msg.get("flush"):
                await ws.send(json.dumps({"audio": base64.b64encode(b"\x01\x00" * 1500).decode(),
                                          "isFinal": None}))
            if msg.get("text") == "":
                await ws.send(json.dumps({"audio": None, "isFinal": True}))
                return

    async def go():
        async with serve(elevenlabs, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            monkeypatch.setattr("orchestrator.tts.ELEVENLABS_URL", f"ws://127.0.0.1:{port}/v1/text-to-speech")
            voice = ElevenLabsVoice("k", "eleven_flash_v2_5")

            async def sentences():
                yield "Hola."
                yield "¿Qué tal?"

            cfg = VoiceConfig(provider="elevenlabs", voice_id="v1", stability=0.4,
                              similarity_boost=0.8, speaking_rate=1.05)
            pcm = b"".join([f async for f in voice.speak(sentences(), cfg, "es-US")])
            await voice.aclose()
            return pcm

    pcm = asyncio.run(go())
    assert len(pcm) == 2 * 3000
    assert seen["key"] == "k" and seen["path"].startswith("/v1/text-to-speech/v1/stream-input")
    assert "output_format=pcm_24000" in seen["path"] and "model_id=eleven_flash_v2_5" in seen["path"]
    start = received[0]
    assert start["text"] == " " and start["voice_settings"] == {"stability": 0.4, "similarity_boost": 0.8, "speed": 1.05}
    assert [m["text"] for m in received[1:]] == ["Hola. ", "¿Qué tal? ", ""]
    assert all(m.get("flush") for m in received[1:3])


def test_an_elevenlabs_refusal_falls_back_to_the_sample(monkeypatch):
    from websockets.asyncio.server import serve

    from orchestrator.tts import Voice

    async def refuses(ws):
        await ws.recv()
        await ws.send(json.dumps({"message": "voice_id not found", "error": "voice_not_found"}))

    async def go():
        async with serve(refuses, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            monkeypatch.setattr("orchestrator.tts.ELEVENLABS_URL", f"ws://127.0.0.1:{port}/v1/text-to-speech")
            monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
            voice = Voice()

            async def sentences():
                yield "Hola, ¿qué tal?"

            cfg = VoiceConfig(provider="elevenlabs", voice_id="missing", stability=0.5,
                              similarity_boost=0.8, speaking_rate=1.0)
            pcm = b"".join([f async for f in voice.speak(sentences(), cfg, "es-US")])
            await voice.aclose()
            return pcm

    assert len(asyncio.run(go())) > 24000  # the sample voice spoke instead


def test_nemotron_recognizer_speaks_riva_streaming(monkeypatch):
    grpc = pytest.importorskip("grpc")
    from concurrent import futures

    from riva.client.proto import riva_asr_pb2 as rasr
    from riva.client.proto import riva_asr_pb2_grpc as rasr_grpc

    from orchestrator.stt import create_recognizer
    seen = {}

    class Riva(rasr_grpc.RivaSpeechRecognitionServicer):
        def StreamingRecognize(self, request_iterator, context):
            seen["meta"] = dict(context.invocation_metadata())
            seen["config"] = next(request_iterator).streaming_config
            audio = 0
            for request in request_iterator:
                audio += len(request.audio_content)
                if audio >= 3200:
                    break
            seen["audio"] = audio
            alt = rasr.SpeechRecognitionAlternative
            yield rasr.StreamingRecognizeResponse(results=[rasr.StreamingRecognitionResult(
                alternatives=[alt(transcript="Hola che")], is_final=False)])
            yield rasr.StreamingRecognizeResponse(results=[rasr.StreamingRecognitionResult(
                alternatives=[alt(transcript="Hola che, ¿cómo andás? <es-US>", confidence=0.8,
                                  words=[rasr.WordInfo(word="Hola", confidence=0.95),
                                         rasr.WordInfo(word="andás", confidence=0.4)])],
                is_final=True)])
            for _ in request_iterator:
                pass

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    rasr_grpc.add_RivaSpeechRecognitionServicer_to_server(Riva(), server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    monkeypatch.setenv("NEMOTRON_ASR_SERVER", f"127.0.0.1:{port}")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setenv("NEMOTRON_ASR_FUNCTION_ID", "fn-123")

    async def go():
        rec = await create_recognizer(config.dialect("es-AR"))
        assert rec.name == "nemotron"
        for _ in range(10):
            await rec.feed(b"\x00\x00" * 320)
        events = []
        async with asyncio.timeout(10):
            async for event in rec.stream():
                events.append(event)
                if event.kind == "final":
                    break
        await rec.close()
        return events

    try:
        events = asyncio.run(go())
    finally:
        server.stop(0)
    final = events[-1]
    assert [e.kind for e in events if e.kind in ("partial", "final")] == ["partial", "final"]
    assert final.text == "Hola che, ¿cómo andás?" and final.unsure == ["andás"]
    assert abs(final.confidence - 0.8) < 1e-6
    cfg = seen["config"].config
    assert (cfg.language_code, cfg.sample_rate_hertz, seen["config"].interim_results) == ("es-US", 16000, True)
    assert seen["meta"]["authorization"] == "Bearer nvapi-test" and seen["meta"]["function-id"] == "fn-123"
    assert seen["audio"] >= 3200


# --------------------------------------------------------------------------- the stream

def app(tmp_path):
    return create_app(data_dir=tmp_path, runs_dir=tmp_path / "runs", face_tracking=False)


def generate(client, **overrides):
    body = request(**overrides).model_dump()
    response = client.post("/v1/matchmaker/generate", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def until(ws, kind, frames=None, limit=4000):
    """Read messages until one of `kind` arrives; collect binary audio on the way."""
    for _ in range(limit):
        message = ws.receive()
        if message.get("bytes") is not None:
            if frames is not None:
                frames.append(message["bytes"])
            continue
        data = json.loads(message["text"])
        if data["type"] == kind:
            return data
    raise AssertionError(f"no {kind}")


def test_matchmaker_routes(tmp_path):
    with TestClient(app(tmp_path)) as client:
        catalog = client.get("/v1/matchmaker/catalog").json()
        assert catalog["brand"]["name"] == "Parry" and len(catalog["dialects"]) == len(config.DIALECTS)
        date = generate(client, language="ja-JP-kansai")
        assert client.get(f"/v1/matchmaker/{date['scenario_id']}").json() == date
        assert client.post("/v1/matchmaker/generate", json={"language": "xx"}).status_code == 422
        health = client.get("/health").json()["date"]
        assert health["tts"] == "sample" and health["brain"] == "scripted"


def test_a_whole_date_over_the_stream(tmp_path):
    with TestClient(app(tmp_path)) as client:
        date = generate(client)
        sid = date["scenario_id"]
        path = tmp_path / "dates" / f"{sid}.json"
        data = json.loads(path.read_text())
        data["wingman_seconds"] = 0.3  # do not wait four seconds in a test
        path.write_text(json.dumps(data))
        with client.websocket_connect("/v1/stream") as ws:
            ws.send_text(json.dumps({"type": "init", "run_id": "run_t", "scenario_id": sid,
                                     "npc_id": "host"}))
            ready = until(ws, "session_ready")
            assert ready["providers"]["stt"] == "none" and ready["providers"]["tts"] == "sample"
            ws.send_text(json.dumps({"type": "focus", "npc_id": "host"}))
            assert until(ws, "audio_start")["kind"] == "greeting"
            until(ws, "audio_end")

            ws.send_text(json.dumps({"type": "start_date"}))
            assert until(ws, "date_started")["seconds"] == 180
            frames = []
            opening = until(ws, "audio_start", frames)
            assert opening["kind"] == "opening" and opening["sample_rate"] == 24000
            until(ws, "audio_end", frames)
            assert sum(len(f) for f in frames) > 24000  # at least half a second of voice

            # Silence after the date speaks: the wingman whispers three options.
            hint = until(ws, "wingman_hint")
            assert len(hint["options"]) == 3

            ws.send_text(json.dumps({"type": "user_text",
                                     "text": hint["options"][1]["target"]}))
            assert until(ws, "transcript")["speaker"] == "user"
            update = until(ws, "chemistry_update")
            assert "wingman" in update["reason"]
            until(ws, "audio_start")
            ws.send_text(json.dumps({"type": "barge_in", "timestamp_ms": 1}))
            assert until(ws, "clear_audio")["npc_id"] == "date_npc"

            ws.send_text(json.dumps({"type": "user_text",
                                     "text": "Me llamo Arth, che, y me encanta la fotografía. ¿Y vos?"}))
            update = until(ws, "chemistry_update")
            assert "break_ice" in update["completed_milestones"]

            ws.send_text(json.dumps({"type": "end_date", "reason": "timer"}))
            ended = until(ws, "date_ended")
            assert ended["run_id"] == "run_t" and ended["verdict"] in ("match", "friendzone", "ghosted")

        verdict = client.post("/v1/grade", json={"run_id": "run_t", "scenario_id": sid})
        assert verdict.status_code == 200, verdict.text
        body = verdict.json()
        assert body["milestones"][0]["achieved"] and body["metrics"]["wingman_hints_used"] >= 1
        assert body["metrics"]["wingman_lines_used"] == 1 and body["metrics"]["barge_ins"] == 1
        run = client.get("/v1/date/runs/run_t").json()
        roles = [t["role"] for t in run["transcript"]]
        assert "event" in roles  # the interruption is on the record


def test_looking_away_while_the_date_talks_gets_called_out(tmp_path, monkeypatch):
    # Hold the opening line on the air long enough to look away during it.
    monkeypatch.setattr(stream_gateway, "AHEAD_SECONDS", 0.2)
    with TestClient(app(tmp_path)) as client:
        sid = generate(client)["scenario_id"]
        with client.websocket_connect("/v1/stream") as ws:
            ws.send_text(json.dumps({"type": "init", "run_id": "run_l", "scenario_id": sid}))
            until(ws, "session_ready")
            ws.send_text(json.dumps({"type": "start_date"}))
            until(ws, "audio_start")
            for away in (0.0, 5.0):
                ws.send_text(json.dumps({"type": "telemetry", "is_looking_at_date": False,
                                         "look_away_duration_sec": away, "is_seated": True,
                                         "player_smiling": False, "distance_m": 1.1}))
            signal = until(ws, "signal")
            assert signal["kind"] == "look_away"
            update = until(ws, "chemistry_update")
            assert update["delta"] < 0 and "looked away" in update["reason"]
            callout = until(ws, "audio_start")
            assert callout["kind"] == "callout"


def test_stream_rejects_an_unknown_date(tmp_path):
    with TestClient(app(tmp_path)) as client, client.websocket_connect("/v1/stream") as ws:
        ws.send_text(json.dumps({"type": "init", "run_id": "r", "scenario_id": "date_nope"}))
        message = json.loads(ws.receive()["text"])
        assert message["type"] == "error" and message["fatal"]


def test_face_frames_come_back_analysed(tmp_path):
    pytest.importorskip("mediapipe")
    import cv2
    import numpy as np
    ok, jpeg = cv2.imencode(".jpg", np.full((240, 320, 3), 128, np.uint8))
    with TestClient(create_app(data_dir=tmp_path, runs_dir=tmp_path / "runs",
                               face_tracking=True)) as client:
        if not client.get("/v1/face/status").json()["available"]:
            pytest.skip("face model not downloadable here")
        sid = generate(client)["scenario_id"]
        with client.websocket_connect("/v1/stream") as ws:
            ws.send_text(json.dumps({"type": "init", "run_id": "run_f", "scenario_id": sid}))
            until(ws, "session_ready")
            ws.send_text(json.dumps({"type": "face_frame",
                                     "jpeg_base64": base64.b64encode(jpeg.tobytes()).decode()}))
            analysis = until(ws, "face_analysis")
            assert analysis["found"] is False and analysis["frame"]["width"] == 320


def test_vision_socket_and_selfie_without_a_face(tmp_path):
    pytest.importorskip("mediapipe")
    import cv2
    import numpy as np
    ok, jpeg = cv2.imencode(".jpg", np.full((240, 320, 3), 90, np.uint8))
    with TestClient(create_app(data_dir=tmp_path, runs_dir=tmp_path / "runs",
                               face_tracking=True)) as client:
        if not client.get("/v1/face/status").json()["available"]:
            pytest.skip("face model not downloadable here")
        with client.websocket_connect("/v1/vision") as ws:
            assert json.loads(ws.receive_text())["type"] == "vision_ready"
            ws.send_text(json.dumps({"type": "face_frame",
                                     "jpeg_base64": base64.b64encode(jpeg.tobytes()).decode()}))
            analysis = json.loads(ws.receive_text())
            assert analysis["type"] == "face_analysis" and analysis["found"] is False
        response = client.post("/v1/avatar/from-selfie", content=jpeg.tobytes(),
                               headers={"content-type": "image/jpeg"})
        assert response.status_code == 200 and response.json()["face_found"] is False
        assert client.post("/v1/avatar/from-selfie", content=b"x",
                           headers={"content-type": "text/plain"}).status_code == 415


def test_a_dropped_connection_resumes_the_date(tmp_path):
    with TestClient(app(tmp_path)) as client:
        sid = generate(client)["scenario_id"]
        with client.websocket_connect("/v1/stream") as ws:
            ws.send_text(json.dumps({"type": "init", "run_id": "run_r", "scenario_id": sid}))
            until(ws, "session_ready")
            ws.send_text(json.dumps({"type": "start_date"}))
            until(ws, "audio_end")
            ws.send_text(json.dumps({"type": "user_text", "text": "Hola, me llamo Arth, che."}))
            until(ws, "chemistry_update")
            until(ws, "audio_end")
        with client.websocket_connect("/v1/stream") as ws:
            ws.send_text(json.dumps({"type": "init", "run_id": "run_r", "scenario_id": sid,
                                     "resume": True, "elapsed_sec": 60}))
            until(ws, "session_ready")
            ws.send_text(json.dumps({"type": "user_text", "text": "¿Y vos qué hacés?"}))
            start = until(ws, "audio_start")
            assert start["kind"] == "reply"  # no second opening line
            update = until(ws, "chemistry_update")
            assert "break_ice" in update["completed_milestones"]  # remembered across the drop
            ws.send_text(json.dumps({"type": "end_date", "reason": "timer"}))
            assert until(ws, "date_ended")["run_id"] == "run_r"


# --------------------------------------------------------------------------- the demo café

def preset(client, **overrides):
    body = {"preset": "cafe_cancun_ar", "learner_name": "Arth", **overrides}
    response = client.post("/v1/matchmaker/preset", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_cafe_preset_is_a_complete_porteno_date(tmp_path):
    with TestClient(app(tmp_path)) as client:
        date = preset(client)
        c = date["date_character"]
        assert (c["display_name"], date["host_character"]["display_name"]) == ("Valeria", "Don Julio")
        assert date["dialect"] == "es-AR" and date["city"] == "Cancún" and date["venue_scene"] == "CancunCafe"
        assert date["generated_by"] == "authored" and len(date["menu"]) == 10
        assert "order_together" in [m["id"] for m in date["milestones"]]
        assert "Medialunas (35 MXN)" in c["system_prompt"] and "voseo" in c["system_prompt"]
        assert preset(client, date_gender="male")["date_character"]["display_name"] == "Tomás"
        assert client.post("/v1/matchmaker/preset", json={"preset": "nope"}).status_code == 404
        assert client.get("/v1/matchmaker/catalog").json()["presets"][0]["id"] == "cafe_cancun_ar"


def test_ordering_sends_the_host_who_serves_at_the_table(tmp_path):
    with TestClient(app(tmp_path)) as client:
        sid = preset(client)["scenario_id"]
        with client.websocket_connect("/v1/stream") as ws:
            ws.send_text(json.dumps({"type": "init", "run_id": "run_o", "scenario_id": sid}))
            until(ws, "session_ready")
            ws.send_text(json.dumps({"type": "start_date"}))
            until(ws, "audio_end")
            ws.send_text(json.dumps({"type": "user_text",
                                     "text": "Dale, pedimos unas medialunas y yo quiero un cortado, che."}))
            action = until(ws, "scene_action")
            assert action["action"] == "order_placed" and action["npc_id"] == "host"
            assert set(action["items"]) == {"Medialunas", "Cortado"}
            ws.send_text(json.dumps({"type": "scene_event", "event": "host_at_table"}))
            serve = until(ws, "audio_start")
            while serve["kind"] != "serve":
                serve = until(ws, "audio_start")
            assert serve["npc_id"] == "host"
            line = until(ws, "transcript")
            while not (line.get("npc_id") == "host" and line["is_final"]):
                line = until(ws, "transcript")
            assert "Medialunas" in line["text"] and "Cortado" in line["text"]

            ws.send_text(json.dumps({"type": "help"}))
            card = until(ws, "help_card")
            assert len(card["suggestions"]) == 3 and card["said"]


def test_spoken_lines_are_kept_for_the_pronunciation_pass(tmp_path, monkeypatch):
    from orchestrator import stt

    class Ears(stt.SpeechRecognizer):
        name, transcribes = "fake", True

        async def feed(self, pcm):
            self.fed = getattr(self, "fed", 0) + len(pcm)
            if self.fed >= 32000 and not getattr(self, "done", False):
                self.done = True
                await self.events.put(stt.SttEvent("speech_started"))
                await self.events.put(stt.SttEvent("final", "Hola, soy Arth", 0.62, ["Arth"]))

    async def recognizer(dialect):
        return Ears()

    monkeypatch.setattr(stream_gateway, "create_recognizer", recognizer)
    with TestClient(app(tmp_path)) as client:
        sid = preset(client)["scenario_id"]
        with client.websocket_connect("/v1/stream") as ws:
            ws.send_text(json.dumps({"type": "init", "run_id": "run_c", "scenario_id": sid}))
            until(ws, "session_ready")
            for _ in range(60):
                ws.send_bytes(b"\x10\x00" * 640)
            assert until(ws, "transcript")["text"] == "Hola, soy Arth"
        clip = tmp_path / "audio" / "run_c" / "turn_001.json"
        assert json.loads(clip.read_text())["confidence"] == 0.62
        assert (tmp_path / "audio" / "run_c" / "turn_001.wav").stat().st_size > 16000


def test_the_report_decodes_the_date(tmp_path):
    with TestClient(app(tmp_path)) as client:
        sid = preset(client)["scenario_id"]
        with client.websocket_connect("/v1/stream") as ws:
            ws.send_text(json.dumps({"type": "init", "run_id": "run_d", "scenario_id": sid}))
            until(ws, "session_ready")
            ws.send_text(json.dumps({"type": "start_date"}))
            until(ws, "audio_end")
            ws.send_text(json.dumps({"type": "user_text", "text": "Hola, soy Arth, che. ¿Vos sacás fotos del arrecife?"}))
            until(ws, "chemistry_update")
            ws.send_text(json.dumps({"type": "end_date", "reason": "timer"}))
            until(ws, "date_ended")
        response = client.post("/v1/date/report", json={"run_id": "run_d", "scenario_id": sid})
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["written_by"] == "rules" and report["date_name"] == "Valeria"
        assert report["went_well"]["quote"].startswith("Hola, soy Arth")
        assert len(report["useful_phrases"]) == 3 and report["culture_notes"][0]["title"] == "Voseo is the default"
        assert [t["speaker"] for t in report["transcript"]][:2] == ["date", "learner"]
        page = client.get("/v1/date/report/run_d.html")
        assert page.status_code == 200 and "Your date with Valeria, decoded" in page.text
        assert "<polyline" in page.text  # the chemistry chart
        assert client.get("/v1/date/report/nobody.html").status_code == 404


def test_usted_is_stiff_in_buenos_aires_but_not_everywhere():
    from orchestrator.chemistry_director import JudgeContext

    async def judge(code):
        s = scenario(language=code)
        line = "Hola, ¿usted qué hace los domingos?"
        return await RulesChemistryJudge().judge(JudgeContext(s, [learner(line)], line, [], [], False))

    assert "too formal" in asyncio.run(judge("es-AR")).reason
    assert "too formal" not in asyncio.run(judge("ja-JP")).reason


def test_pronunciation_impressions_only_name_words_that_were_said(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from orchestrator.date_report import DateReporter, _WireListen
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    folder = tmp_path / "run_p"
    folder.mkdir()
    (folder / "turn_001.wav").write_bytes(b"RIFF" + b"\x00" * 40000)
    (folder / "turn_001.json").write_text(json.dumps({"text": "quiero un cortado", "confidence": 0.5}))

    class Models:
        async def generate_content(self, **kwargs):
            return SimpleNamespace(parsed=_WireListen(problem_words=["cortado", "invented"],
                                                      impression="Tap the r in cortado."))

    reporter = DateReporter()
    reporter.gemini = SimpleNamespace(aio=SimpleNamespace(models=Models()))
    notes = asyncio.run(reporter._pronunciation(scenario(), folder))
    assert notes[0].problem_words == ["cortado"] and "Tap the r" in notes[0].impression


def test_spanish_goes_to_the_hosted_multilingual_asr(monkeypatch):
    from orchestrator.stt import clean, function_for
    p = config.providers()
    assert function_for(p, "es-US") == config.NVIDIA_MULTILINGUAL_FUNCTION
    assert function_for(p, "en-US") == config.NEMOTRON_HOSTED_FUNCTION
    monkeypatch.setenv("NVIDIA_ASR_MULTILINGUAL_FUNCTION_ID", "custom")
    assert function_for(config.providers(), "ja-JP") == "custom"
    assert clean("Qué¿ quieres tomar? <es-US>") == "¿Qué quieres tomar?"
    assert clean("Hola , buenas tardes .") == "Hola, buenas tardes."


def test_the_date_cannot_hear_you_before_the_date_starts(tmp_path):
    with TestClient(app(tmp_path)) as client:
        sid = generate(client)["scenario_id"]
        with client.websocket_connect("/v1/stream") as ws:
            ws.send_text(json.dumps({"type": "init", "run_id": "run_far", "scenario_id": sid,
                                     "npc_id": "date_npc"}))
            until(ws, "session_ready")
            ws.send_text(json.dumps({"type": "user_text", "text": "how do I move"}))
            line = until(ws, "transcript")
            assert line["speaker"] == "user" and line["unheard"]
            # The host still answers when faced.
            ws.send_text(json.dumps({"type": "focus", "npc_id": "host"}))
            assert until(ws, "audio_start")["kind"] == "greeting"
            until(ws, "audio_end")
            ws.send_text(json.dumps({"type": "user_text", "text": "Muchas gracias."}))
            assert until(ws, "audio_start")["npc_id"] == "host"
        run = client.get("/v1/date/runs/run_far").json()
        assert all(t["npc_id"] != "date_npc" for t in run["transcript"] if t["role"] == "learner")


class _FailingBrain:
    def __init__(self, name, error):
        self.name, self.error, self.calls = name, error, 0

    async def reply(self, system, history, notes, ctx):
        self.calls += 1
        raise self.error
        yield ""  # pragma: no cover

    async def aclose(self):
        return None


class _EchoBrain:
    name = "claude"

    async def reply(self, system, history, notes, ctx):
        yield "Hola, "
        yield "¿qué tal?"

    async def aclose(self):
        return None


def test_an_out_of_quota_brain_hands_over_and_rests(monkeypatch):
    from orchestrator import date_brain
    monkeypatch.setattr(date_brain, "_resting", {})
    gemini = _FailingBrain("gemini", RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded"))
    chain = date_brain.ChainBrain([gemini, _EchoBrain(), date_brain.ScriptedBrain()])
    ctx = date_brain.BrainContext(dialect="es-AR", chemistry=50, nonverbal=[], interests=[])

    async def say():
        return "".join([d async for d in chain.reply("sys", [Turn("learner", "Hola")], [], ctx)])

    assert asyncio.run(say()) == "Hola, ¿qué tal?"
    # Resting: the next turn goes straight to Claude, without asking Gemini again.
    assert chain.name == "claude"
    assert asyncio.run(say()) == "Hola, ¿qué tal?" and gemini.calls == 1


def test_a_failing_brain_without_quota_trouble_is_tried_again(monkeypatch):
    from orchestrator import date_brain
    monkeypatch.setattr(date_brain, "_resting", {})
    gemini = _FailingBrain("gemini", ConnectionError("reset"))
    chain = date_brain.ChainBrain([gemini, date_brain.ScriptedBrain()])
    ctx = date_brain.BrainContext(dialect="es-AR", chemistry=50, nonverbal=[], interests=[])

    async def say():
        return "".join([d async for d in chain.reply("sys", [Turn("learner", "Hola")], [], ctx)])

    assert asyncio.run(say()).strip()
    assert asyncio.run(say()).strip() and gemini.calls == 2 and chain.name == "gemini"


class _HangingBrain:
    name = "gemini"

    async def reply(self, system, history, notes, ctx):
        await asyncio.sleep(60)
        yield "too late"

    async def aclose(self):
        return None


def test_a_hanging_brain_hands_over_after_the_first_word_deadline(monkeypatch):
    from orchestrator import date_brain
    monkeypatch.setattr(date_brain, "_resting", {})
    monkeypatch.setattr(date_brain, "FIRST_WORD_SECONDS", 0.05)
    chain = date_brain.ChainBrain([_HangingBrain(), _EchoBrain()])
    ctx = date_brain.BrainContext(dialect="es-AR", chemistry=50, nonverbal=[], interests=[])

    async def say():
        return "".join([d async for d in chain.reply("sys", [Turn("learner", "Hola")], [], ctx)])

    assert asyncio.run(say()) == "Hola, ¿qué tal?" and chain.name == "claude"


def test_the_microphone_hearing_the_date_is_not_the_learner():
    session = stream_gateway.StreamSession.__new__(stream_gateway.StreamSession)
    session.transcript = [TranscriptTurn(role="npc", npc_id="date_npc",
                                         text="Che, ¿tan aburrida soy que mirás para otro lado?")]
    session.spoken, session.speaking, session.playback_end = [], None, 100.0
    assert session._echo("otro lado", 101.0)                 # just after her line: echo
    assert not session._echo("otro lado", 110.0)             # long after: the learner
    assert not session._echo("Perdón, me distraje", 101.0)   # new words: the learner


def test_asking_the_wingman_brings_three_options_without_a_penalty(tmp_path):
    with TestClient(app(tmp_path)) as client:
        sid = generate(client)["scenario_id"]
        path = tmp_path / "dates" / f"{sid}.json"
        data = json.loads(path.read_text())
        data["wingman_seconds"] = 60  # the silence timer must not be what answers
        path.write_text(json.dumps(data))
        with client.websocket_connect("/v1/stream") as ws:
            ws.send_text(json.dumps({"type": "init", "run_id": "run_w", "scenario_id": sid,
                                     "npc_id": "date_npc"}))
            until(ws, "session_ready")
            ws.send_text(json.dumps({"type": "start_date"}))
            until(ws, "date_started")
            until(ws, "audio_end")
            ws.send_text(json.dumps({"type": "wingman"}))
            hint = until(ws, "wingman_hint")
            assert len(hint["options"]) == 3
            ws.send_text(json.dumps({"type": "end_date", "reason": "quit"}))
            ended = until(ws, "date_ended")
            # Asking is not an awkward silence: chemistry is where the opening left it.
            assert ended["chemistry_score"] >= 50


def test_claude_speaks_as_the_date_by_default(monkeypatch):
    from orchestrator import date_brain
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("DATE_BRAIN", raising=False)
    brain = date_brain.create_brain()
    assert isinstance(brain, date_brain.ChainBrain)
    assert [b.name for b in brain.brains] == ["claude", "scripted"]
    assert brain.rest_when_slow is False  # a slow Claude is waited for, not benched
    monkeypatch.setenv("DATE_BRAIN", "gemini")
    assert [b.name for b in date_brain.create_brain().brains][0] == "gemini"
