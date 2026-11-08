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
from orchestrator.chemistry_director import (ChemistryDirector, ChemistryStore,
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
from orchestrator.tts import FishVoice, SentenceChunker

KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY",
        "GOOGLE_CLOUD_PROJECT", "DEEPGRAM_API_KEY", "FISH_AUDIO_API_KEY", "OPENAI_API_KEY",
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
    assert c.voice_config.provider == "sample"  # no Fish key in tests
    assert c.avatar_config.base_model == "Female_Adult_08"


def test_scene_prompt_picks_the_venue_and_notes_shape_the_persona():
    s = scenario()
    assert s.venue.id == "rooftop_bar" and s.venue_scene == "SampleScene"
    assert any("crypto" in r for r in s.date_character.red_flags)
    assert "indie rock" in s.date_character.interests
    assert "voseo" in s.date_character.system_prompt
    # Appearance drives the model only, never the persona.
    assert "latina" not in s.date_character.system_prompt.casefold()


def test_fish_voice_is_chosen_when_configured(monkeypatch):
    monkeypatch.setenv("FISH_AUDIO_API_KEY", "k")
    monkeypatch.setenv("FISH_VOICE_ES_AR_FEMALE", "voice-ar")
    v = scenario().date_character.voice_config
    assert (v.provider, v.voice_id) == ("fish", "voice-ar")


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


def test_fish_voice_speaks_the_live_protocol(monkeypatch):
    import ormsgpack
    from websockets.asyncio.server import serve

    received = []

    async def fish(ws):
        assert ws.request.headers["Authorization"] == "Bearer k"
        async for raw in ws:
            msg = ormsgpack.unpackb(raw)
            received.append(msg)
            if msg["event"] == "flush":
                await ws.send(ormsgpack.packb({"event": "audio", "audio": b"\x01\x00" * 1500}))
            if msg["event"] == "stop":
                await ws.send(ormsgpack.packb({"event": "finish", "reason": "stop"}))
                return

    async def go():
        async with serve(fish, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            monkeypatch.setattr("orchestrator.tts.FISH_URL", f"ws://127.0.0.1:{port}")
            voice = FishVoice("k", "s2.1-pro")

            async def sentences():
                yield "Hola."
                yield "¿Qué tal?"

            cfg = VoiceConfig(provider="fish", voice_id="v1", speaking_rate=1.0,
                              temperature=0.7, latency="balanced")
            pcm = b"".join([f async for f in voice.speak(sentences(), cfg, "es-AR")])
            await voice.aclose()
            return pcm

    pcm = asyncio.run(go())
    assert len(pcm) == 2 * 3000
    start = received[0]
    assert start["event"] == "start" and start["request"]["format"] == "pcm"
    assert start["request"]["reference_id"] == "v1" and start["request"]["sample_rate"] == 24000
    assert [m["event"] for m in received[1:]] == ["text", "flush", "text", "flush", "stop"]


def test_deepgram_recognizer_assembles_a_final_utterance(monkeypatch):
    from websockets.asyncio.server import serve

    from orchestrator.stt import DeepgramRecognizer

    async def deepgram(ws):
        assert ws.request.headers["Authorization"] == "Token k"
        assert "language=es" in ws.request.path and "encoding=linear16" in ws.request.path
        await ws.recv()
        await ws.send(json.dumps({"type": "SpeechStarted"}))
        await ws.send(json.dumps({"type": "Results", "is_final": True, "speech_final": False,
                                  "channel": {"alternatives": [{"transcript": "Hola che",
                                                                "confidence": 0.9, "words": []}]}}))
        await ws.send(json.dumps({"type": "Results", "is_final": True, "speech_final": True,
                                  "channel": {"alternatives": [{"transcript": "¿cómo andás?",
                                                                "confidence": 0.7,
                                                                "words": [{"word": "andás",
                                                                           "confidence": 0.4}]}]}}))
        await asyncio.sleep(0.5)

    async def go():
        async with serve(deepgram, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            monkeypatch.setattr("orchestrator.stt.DEEPGRAM_URL", f"ws://127.0.0.1:{port}/v1/listen")
            rec = DeepgramRecognizer("k", config.dialect("es-AR"))
            await rec.start()
            await rec.feed(b"\x00\x00" * 320)
            events = []
            async for event in rec.stream():
                events.append(event)
                if event.kind == "final":
                    break
            await rec.close()
            return events

    events = asyncio.run(go())
    final = events[-1]
    assert events[0].kind == "speech_started"
    assert final.text == "Hola che ¿cómo andás?" and final.unsure == ["andás"]
    assert abs(final.confidence - 0.8) < 1e-6


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
        assert catalog["brand"]["name"] == "Parry" and len(catalog["dialects"]) == 8
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
