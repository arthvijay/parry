"""The latency path: streaming, pre-warm, interruption, memory and mouth shapes.

No network. A scripted socket plays the agent, framing its audio the way the live
service does: alignment on every frame and `is_final` on the last.
"""

import asyncio
import base64
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from orchestrator.app import create_app
from orchestrator.elevenlabs_adapter import ElevenLabsSpeech, spoken_text
from orchestrator.metrics import Metrics
from orchestrator.speech import SpeechUnavailable
from orchestrator.speech import SpeechInput, SpeechInputError
from orchestrator.visemes import heard_prefix, timeline

PCM = b"\x01\x00" * 1600  # 100 ms at 16 kHz


def aligned(text: str, per_char_ms: int = 50) -> dict:
    chars = list(text)
    return {"chars": chars, "char_start_times_ms": [i * per_char_ms for i in range(len(chars))],
            "char_durations_ms": [per_char_ms] * len(chars)}


class Agent:
    """A scripted agent socket. `script` maps a learner line to the frames it sends."""

    def __init__(self, replies, *, hang_up_after=None, complete_event=False, tool=None):
        self.queue, self.sent, self.closed = asyncio.Queue(), [], False
        self.replies, self.hang_up_after = list(replies), hang_up_after
        self.complete_event, self.tool, self.turns = complete_event, tool, 0

    async def send(self, raw):
        msg = json.loads(raw)
        self.sent.append(msg)
        if msg.get("type") == "conversation_initiation_client_data":
            await self.queue.put({"type": "conversation_initiation_metadata",
                "conversation_initiation_metadata_event": {
                    "agent_output_audio_format": "pcm_16000", "conversation_id": "conv_1"}})
            await self.say(["¡Hola!"])
        elif msg.get("type") == "user_message":
            self.turns += 1
            if self.tool:
                await self.queue.put({"type": "client_tool_call", "client_tool_call": self.tool})
            await self.say(self.replies.pop(0) if len(self.replies) > 1 else self.replies[0])
            if self.hang_up_after == self.turns:
                await self.queue.put(None)

    async def say(self, parts):
        for i, part in enumerate(parts):
            await self.queue.put({"type": "audio", "audio_event": {
                "audio_base_64": base64.b64encode(PCM).decode(), "event_id": i,
                "alignment": aligned(part), "is_final": i == len(parts) - 1}})
        await self.queue.put({"type": "agent_response",
                              "agent_response_event": {"agent_response": "".join(parts)}})
        if self.complete_event:
            await self.queue.put({"type": "agent_response_complete",
                                  "agent_response_complete_event": {"event_id": 1}})

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self.queue.get()
        if item is None:
            raise StopAsyncIteration
        return json.dumps(item)

    async def close(self):
        self.closed = True


def provider(replies=(["Claro, ", "joven."],), words=None, pack=None, **agent):
    sockets = []
    heard = {"text": "Quiero un café de olla", "language_code": "spa", "words": words or [
        {"text": "Quiero", "type": "word", "logprob": -0.01},
        {"text": " ", "type": "spacing", "logprob": 0.0},
        {"text": "olla", "type": "word", "logprob": -1.9}]}

    def handler(request):
        if request.url.path.endswith("speech-to-text"):
            return httpx.Response(200, json=heard)
        return httpx.Response(200, json={"signed_url": "wss://example.invalid/x"})

    async def connect(url, **_):
        sockets.append(Agent(list(replies), **agent))
        return sockets[-1]

    made = ElevenLabsSpeech("k", {"maria": "agent-maria", "luis": "agent-luis"}, pack=pack,
        client=httpx.AsyncClient(base_url="https://example.invalid",
                                 transport=httpx.MockTransport(handler)),
        connect=connect, quiet=5, grace=.01, idle_seconds=30, languages=("es", "en"))
    return made, sockets


def turn(session=None, npc="maria", **kwargs):
    return SpeechInput(b"\x00\x00" * 1600, "audio/pcm", session or uuid4(), npc,
                       sample_rate=16000, **kwargs)


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ streaming

def test_events_arrive_in_the_order_they_happen_and_frames_are_not_batched():
    async def go():
        speech, _ = provider()
        try:
            return [e async for e in speech.stream(turn())]
        finally:
            await speech.aclose()
    events = run(go())
    kinds = [e["type"] for e in events]
    assert kinds == ["transcript", "audio", "audio", "text", "action", "done"]
    assert [e["seq"] for e in events if e["type"] == "audio"] == [0, 1]
    # The second frame starts where the first ended: 100 ms of PCM.
    assert [e["offset_ms"] for e in events if e["type"] == "audio"] == [0, 100]
    assert events[3]["text"] == "Claro, joven."


def test_a_reply_ends_on_its_last_frame_not_on_a_silence_timer():
    """`quiet` is 5 s here. Finishing fast proves the last-frame flag ended the turn."""
    async def go():
        speech, _ = provider()
        try:
            async with asyncio.timeout(1):
                return await speech.respond(turn())
        finally:
            await speech.aclose()
    assert run(go()).agent_transcript == "Claro, joven."


def test_agent_response_complete_ends_the_turn_without_waiting_at_all():
    async def go():
        speech, _ = provider(complete_event=True)
        speech.grace = 5
        try:
            async with asyncio.timeout(1):
                return await speech.respond(turn())
        finally:
            await speech.aclose()
    assert run(go()).agent_transcript == "Claro, joven."


def test_timings_report_where_the_time_went():
    async def go():
        speech, _ = provider()
        seen = []
        speech.on_timings = lambda npc, t: seen.append((npc, t))
        try:
            session = uuid4()
            cold = await speech.respond(turn(session))
            warm = await speech.respond(turn(session))
            return cold, warm, seen
        finally:
            await speech.aclose()
    cold, warm, seen = run(go())
    assert set(cold.timings_ms) >= {"stt", "session_open", "first_audio", "first_sound", "total"}
    assert warm.timings_ms["session_open"] == 0      # the conversation was already open
    assert [npc for npc, _ in seen] == ["maria", "maria"]


def test_words_the_recogniser_was_unsure_of_are_reported():
    async def go():
        speech, _ = provider()
        try:
            return await speech.respond(turn())
        finally:
            await speech.aclose()
    out = run(go())
    assert out.low_confidence_words == ("olla",)
    assert out.min_logprob == pytest.approx(-1.9)


def test_delivery_markup_never_reaches_the_transcript():
    assert spoken_text("<despacio>¿Para aquí</despacio> o [laughs] para llevar?") == \
        "¿Para aquí o para llevar?"

    async def go():
        speech, _ = provider(replies=(["<despacio>Más ", "despacio.</despacio>"],))
        try:
            return await speech.respond(turn())
        finally:
            await speech.aclose()
    out = run(go())
    assert out.agent_transcript == "Más despacio."
    assert all(key["v"] != "sil" or key["d"] >= 0 for key in out.visemes)


# ------------------------------------------------------------------ pre-warm

def test_warming_opens_the_conversation_and_returns_the_greeting_once():
    async def go():
        speech, sockets = provider()
        try:
            session = uuid4()
            hello = await speech.warm(turn(session))
            assert len(sockets) == 1 and not sockets[0].turns
            again = await speech.warm(turn(session))         # already said hello
            out = await speech.respond(turn(session))
            return hello, again, out, len(sockets)
        finally:
            await speech.aclose()
    hello, again, out, opened = run(go())
    assert opened == 1
    # The character's opening line, in their live voice, as one playable clip.
    assert hello.media_type == "audio/wav" and hello.audio[:4] == b"RIFF"
    assert hello.sample_rate == 16000 and hello.agent_transcript == "¡Hola!"
    assert hello.user_transcript is None and hello.timings_ms["open"] >= 0
    assert again is None
    assert out.timings_ms["session_open"] == 0
    assert out.agent_transcript == "Claro, joven."           # the greeting is not in the reply


def test_a_turn_that_arrives_before_warm_drops_the_greeting():
    """The learner spoke straight away, over the opening line; nobody gets to hear it later."""
    async def go():
        speech, sockets = provider()
        try:
            session = uuid4()
            out = await speech.respond(turn(session))
            return out, await speech.warm(turn(session))
        finally:
            await speech.aclose()
    out, hello = run(go())
    assert out.agent_transcript == "Claro, joven." and hello is None


def test_every_variable_a_prompt_uses_is_always_sent():
    """A missing dynamic variable fails the whole conversation on the live service."""
    async def go():
        speech, sockets = provider()
        try:
            await speech.warm(turn(learner_level="B1", learner_name="Alex"))
            await speech.warm(turn(learner_level="nonsense"))
            return [s.sent[0]["dynamic_variables"] for s in sockets]
        finally:
            await speech.aclose()
    first, second = run(go())
    assert first == {"learner_name": "Alex", "learner_level": "B1", "user_order": "nada"}
    assert second["learner_level"] == "A2" and second["learner_name"] == "amigo"


# ------------------------------------------------------------------ robustness

def test_a_silent_clip_does_not_cost_the_learner_their_warm_session():
    async def go():
        speech, sockets = provider()
        session = uuid4()
        try:
            await speech.warm(turn(session))
            with pytest.raises(SpeechInputError):
                await speech.respond(SpeechInput(b"junk", "audio/wav", session, "maria"))
            out = await speech.respond(turn(session))
            return out, len(sockets), sockets[0].closed
        finally:
            await speech.aclose()
    out, opened, closed = run(go())
    assert opened == 1 and not closed
    assert out.agent_transcript


def test_a_character_that_hangs_up_is_reported_and_remembers_the_visit_when_reopened():
    async def go():
        speech, sockets = provider(replies=(["Que te vaya bien."],), hang_up_after=1)
        session = uuid4()
        try:
            first = await speech.respond(turn(session, run_id="visit1"))
            second = await speech.respond(turn(session, run_id="visit1"))
            return first, second, sockets
        finally:
            await speech.aclose()
    first, second, sockets = run(go())
    assert first.ended and len(sockets) == 2
    recap = [m["text"] for m in sockets[1].sent if m.get("type") == "contextual_update"]
    assert any("already talking earlier" in text and "Que te vaya bien." in text for text in recap)


def test_interrupting_tells_the_character_what_was_actually_heard():
    async def go():
        speech, sockets = provider(replies=(["Tenemos café de olla recién hecho y pan dulce."],))
        session = uuid4()
        try:
            await speech.respond(turn(session))
            # 50 ms a character: 1,000 ms is twenty characters in, mid-word.
            out = await speech.respond(turn(session, interrupted_at_ms=1000))
            return out, sockets[0].sent
        finally:
            await speech.aclose()
    out, sent = run(go())
    assert out.previous_reply_heard == "Tenemos café de olla"
    note = [m["text"] for m in sent if m.get("type") == "contextual_update"][-1]
    assert "interrupted" in note and "Tenemos café de olla" in note
    # The note must reach the character before the learner's next line does.
    kinds = [m.get("type") for m in sent]
    assert kinds.index("contextual_update") < len(kinds) - 1 - kinds[::-1].index("user_message")


def test_hearing_the_whole_reply_is_not_an_interruption():
    async def go():
        speech, sockets = provider()
        session = uuid4()
        try:
            await speech.respond(turn(session))
            out = await speech.respond(turn(session, interrupted_at_ms=60000))
            return out, sockets[0].sent
        finally:
            await speech.aclose()
    out, sent = run(go())
    assert out.previous_reply_heard is None
    assert not [m for m in sent if m.get("type") == "contextual_update"]


# ------------------------------------------------------------------ mouth shapes

def test_spanish_spelling_becomes_mouth_shapes():
    a = aligned("¡Buenas!")
    shapes = [key["v"] for key in timeline(a["chars"], a["char_start_times_ms"],
                                           a["char_durations_ms"])]
    assert shapes == ["sil", "PBM", "U", "E", "TD", "A", "S", "sil"]


@pytest.mark.parametrize("word,expected", [
    ("que", ["KG", "E"]),            # silent u
    ("hola", ["O", "L", "A"]),       # silent h
    ("leche", ["L", "E", "CH", "E"]),
    ("cinco", ["S", "I", "TD", "KG", "O"]),
    ("calle", ["KG", "A", "I", "E"]),  # ll is a y sound
    ("vaso", ["PBM", "A", "S", "O"]),  # v is b in Spanish
])
def test_spanish_pronunciation_rules(word, expected):
    a = aligned(word)
    assert [k["v"] for k in timeline(a["chars"], a["char_start_times_ms"],
                                     a["char_durations_ms"])] == expected


def test_shapes_sit_on_the_replys_clock_and_skip_markup():
    a = aligned("<despacio>sí</despacio>")
    keys = timeline(a["chars"], a["char_start_times_ms"], a["char_durations_ms"], offset_ms=400)
    assert [k["v"] for k in keys] == ["S", "I"]
    assert keys[0]["t"] == 400 + 10 * 50


def test_heard_prefix_cuts_at_a_whole_word():
    a = aligned("Son ochenta pesos, joven.")
    assert heard_prefix(a["chars"], a["char_start_times_ms"], 0) == ""
    assert heard_prefix(a["chars"], a["char_start_times_ms"], 420) == "Son"
    assert heard_prefix(a["chars"], a["char_start_times_ms"], 99999) == "Son ochenta pesos, joven."


# ------------------------------------------------------------------ metrics + HTTP

def test_metrics_prefer_warm_turns_and_report_percentiles():
    metrics = Metrics()
    metrics.record("maria", {"stt": 400, "session_open": 2500, "first_sound": 3400, "total": 5000})
    for ms in (900, 1000, 1100):
        metrics.record("maria", {"stt": 400, "session_open": 0, "first_sound": ms, "total": 2000})
    maria = metrics.summary()["maria"]
    assert maria["turns"] == 4 and maria["warm_turns"] == 3
    assert maria["stages_ms"]["first_sound"] == {"p50": 1000, "p90": 1100}


def client_with(speech):
    return TestClient(create_app(speech=speech))


def test_stream_endpoint_sends_one_json_event_per_line(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_DIR", str(tmp_path / "transcripts"))
    monkeypatch.setenv("RUN_AUDIO_DIR", str(tmp_path / "audio"))
    speech, _ = provider()
    with client_with(speech) as client:
        response = client.post(f"/v1/speech/stream?session_id={uuid4()}&npc_id=maria&run_id=r1"
                               "&sample_rate=16000&learner_level=A2",
                               content=b"\x00\x00" * 1600, headers={"Content-Type": "audio/pcm"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")
        events = [json.loads(line) for line in response.text.splitlines()]
        assert [e["type"] for e in events] == ["transcript", "audio", "audio", "text", "action", "done"]
        assert base64.b64decode(events[1]["pcm_base64"]) == PCM and "pcm" not in events[1]
        assert events[1]["visemes"] and events[-1]["timings_ms"]["first_sound"] >= 0
        assert events[-1]["goals_achieved"] == []
        # The recogniser's doubts travel with the transcript, never as a verdict.
        recorded = (tmp_path / "transcripts" / "r1.jsonl").read_text().splitlines()
        assert json.loads(recorded[0])["low_confidence_words"] == ["olla"]
        # The learner's own voice is kept for the end-of-visit pronunciation pass.
        assert (tmp_path / "audio" / "r1" / "turn_001.wav").is_file()
        sidecar = json.loads((tmp_path / "audio" / "r1" / "turn_001.json").read_text())
        assert sidecar["low_confidence_words"] == ["olla"]
        assert client.get("/v1/metrics").json()["characters"]["maria"]["turns"] == 1


def test_stream_endpoint_rejects_bad_input_with_a_status_not_an_event():
    speech, _ = provider()
    with client_with(speech) as client:
        bad_type = client.post(f"/v1/speech/stream?session_id={uuid4()}&npc_id=maria",
                               content=b"hi", headers={"Content-Type": "text/plain"})
        unknown = client.post(f"/v1/speech/stream?session_id={uuid4()}&npc_id=nobody"
                              "&sample_rate=16000", content=b"\x00\x00" * 160,
                              headers={"Content-Type": "audio/pcm"})
        level = client.post(f"/v1/speech/stream?session_id={uuid4()}&npc_id=maria&learner_level=C9",
                            content=b"\x00\x00", headers={"Content-Type": "audio/pcm"})
    assert (bad_type.status_code, unknown.status_code, level.status_code) == (415, 503, 422)


def test_warm_endpoint_and_classic_endpoint_report_timings():
    speech, sockets = provider()
    with client_with(speech) as client:
        session = uuid4()
        hello = client.post(f"/v1/speech/sessions/{session}/warm?npc_id=maria")
        assert hello.status_code == 200 and hello.json()["agent_transcript"] == "¡Hola!"
        assert base64.b64decode(hello.json()["audio_base64"])[:4] == b"RIFF"
        assert "open;dur=" in hello.headers["server-timing"]
        assert client.post(f"/v1/speech/sessions/{session}/warm?npc_id=maria").status_code == 204
        assert len(sockets) == 1
        reply = client.post(f"/v1/speech?session_id={session}&npc_id=maria&sample_rate=16000"
                            "&response_format=json", content=b"\x00\x00" * 1600,
                            headers={"Content-Type": "audio/pcm"})
        body = reply.json()
        assert len(sockets) == 1 and body["timings_ms"]["session_open"] == 0
        assert "first_sound;dur=" in reply.headers["server-timing"]
        assert body["visemes"] and body["low_confidence_words"] == ["olla"] and body["ended"] is False


def test_a_reply_ends_the_moment_all_its_text_has_been_voiced():
    """The live service never sets `is_final`. With both timers at 5 s, only the
    character count can end this turn quickly."""
    class NoFinal(Agent):
        async def say(self, parts):
            for i, part in enumerate(parts):
                await self.queue.put({"type": "audio", "audio_event": {
                    "audio_base_64": base64.b64encode(PCM).decode(), "event_id": i,
                    "alignment": aligned(part), "is_final": False}})
            await self.queue.put({"type": "agent_response",
                                  "agent_response_event": {"agent_response": "".join(parts)}})

    async def go():
        speech, _ = provider()
        speech.grace = 5

        async def connect(url, **_):
            return NoFinal([["Claro, ", "joven."]])
        speech.connect = connect
        try:
            async with asyncio.timeout(1):
                return await speech.respond(turn())
        finally:
            await speech.aclose()
    assert run(go()).agent_transcript == "Claro, joven."


def test_a_correction_to_the_previous_line_does_not_leak_into_this_reply():
    """Answering before the greeting has 'finished' on the service's clock makes it
    send an interruption and a correction of the GREETING. Neither belongs here."""
    class Eager(Agent):
        async def send(self, raw):
            if json.loads(raw).get("type") == "user_message":
                await self.queue.put({"type": "interruption", "interruption_event": {"event_id": 2}})
                await self.queue.put({"type": "agent_response_correction",
                    "agent_response_correction_event": {"original_agent_response": "¡Hola!",
                                                        "corrected_agent_response": "¡Ho"}})
            await super().send(raw)

    async def go():
        speech, _ = provider()

        async def connect(url, **_):
            return Eager([["Claro, ", "joven."]])
        speech.connect = connect
        try:
            return [e async for e in speech.stream(turn())]
        finally:
            await speech.aclose()
    events = run(go())
    assert [e["type"] for e in events] == ["transcript", "audio", "audio", "text", "action", "done"]
    assert events[3]["text"] == "Claro, joven."


# ------------------------------------------------------------------ gestures

@pytest.mark.parametrize("reply,expected", [
    ("¡Buenas tardes! Pásale, joven.", "wave"),
    ("Claro, ahorita te lo traigo.", "nod"),
    ("Uy, se me acabó el pay. ¿Te ofrezco una concha?", "shake_head"),
    ("Tenemos café de olla y horchata.", "point_menu"),
    ("¿Neta? ¡Qué padre!", "lean_in"),
    ("Jajaja, no manches.", "laugh"),
    ("Son ochenta pesos.", None),
])
def test_a_gesture_is_read_off_the_reply_instead_of_costing_a_model_round_trip(reply, expected):
    from orchestrator.gestures import infer
    assert infer(reply) == expected


def test_gestures_respect_the_scenario_list_and_do_not_repeat_back_to_back():
    from orchestrator.gestures import infer
    assert infer("Claro que sí.", allowed=["wave"]) is None
    assert infer("Claro que sí.", last="nod") is None
    assert infer("Claro que sí.", last="wave") == "nod"


def test_an_inferred_gesture_travels_with_the_turn_as_a_scene_action():
    async def go():
        speech, _ = provider(replies=(["Claro, ", "joven."],))
        try:
            return [e async for e in speech.stream(turn())]
        finally:
            await speech.aclose()
    actions = [e["action"] for e in run(go()) if e["type"] == "action"]
    assert actions == [{"action": "play_gesture", "npc_id": "maria", "gesture": "nod",
                        "source": "inferred"}]


# ------------------------------------------------------------------ speech around a tool call

def test_speaking_then_calling_a_tool_then_speaking_again_is_one_reply():
    """With pre-tool speech forced, Maria says the order back, serves it, then says it
    is coming. Ending the turn after the first sentence lost the second, which then
    arrived as the answer to the learner's NEXT question."""
    class Waitress(Agent):
        async def part(self, kind, text=""):
            await self.queue.put({"type": "agent_chat_response_part",
                                  "text_response_part": {"type": kind, "text": text}})

        async def voice(self, text):
            await self.queue.put({"type": "audio", "audio_event": {
                "audio_base_64": base64.b64encode(PCM).decode(), "alignment": aligned(text)}})
            await self.queue.put({"type": "agent_response",
                                  "agent_response_event": {"agent_response": text}})

        async def send(self, raw):
            msg = json.loads(raw)
            if msg.get("type") != "user_message":
                return await super().send(raw)
            self.sent.append(msg)
            await self.part("start")
            await self.part("delta", "Claro, un café de olla.")
            await self.part("stop")
            await self.voice("Claro, un café de olla.")
            await self.queue.put({"type": "client_tool_call", "client_tool_call": {
                "tool_name": "serve_order", "tool_call_id": "t1", "expects_response": True,
                "parameters": {"items": ["cafe_olla"]}}})
            await asyncio.sleep(.05)        # the model thinks again after the tool result
            await self.part("start")
            await self.part("delta", " Ahorita te lo traigo.")
            await self.part("stop")
            await self.voice("Ahorita te lo traigo.")

    async def go():
        from pathlib import Path

        from orchestrator.scene import ScenePack
        pack = ScenePack.load(Path(__file__).resolve().parents[2] / "scenarios" / "cafe_cancun")
        speech, _ = provider(pack=pack)

        async def connect(url, **_):
            return Waitress([["unused"]])
        speech.connect = connect
        try:
            async with asyncio.timeout(3):
                return await speech.respond(turn())
        finally:
            await speech.aclose()
    out = run(go())
    assert out.agent_transcript == "Claro, un café de olla. Ahorita te lo traigo."
    assert [a["action"] for a in out.actions if a["action"] != "play_gesture"] == ["serve_order"]


# ------------------------------------------------------------------ quota

def test_a_socket_closed_for_quota_is_reported_as_unavailable_not_a_bare_failure():
    """ElevenLabs hangs up with close code 3000 `quota_exceeded` when the account is
    out of characters. The first send then fails; the learner should be told why."""
    class OutOfCredits(Agent):
        close_code, close_reason = 3000, "quota_exceeded"

        async def send(self, raw):
            raise ConnectionError("sent 3000 (registered) quota_exceeded")

    async def go():
        speech, _ = provider()

        async def connect(url, **_):
            return OutOfCredits([])
        speech.connect = connect
        try:
            with pytest.raises(SpeechUnavailable, match="out of credits"):
                await speech.warm(turn())
        finally:
            await speech.aclose()
    run(go())
