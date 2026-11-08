import asyncio
import base64
import io
import json
import wave
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from orchestrator.app import create_app
from orchestrator.elevenlabs_adapter import ElevenLabsSpeech
from orchestrator.speech import SpeechInput, SpeechInputError, SpeechUnavailable


class Socket:
    def __init__(self, *, silent=False, bad_format=False):
        self.queue = asyncio.Queue()
        self.sent = []
        self.closed = False
        self.silent = silent
        self.bad_format = bad_format

    async def send(self, raw):
        msg = json.loads(raw)
        self.sent.append(msg)
        if msg.get("type") == "conversation_initiation_client_data":
            await self.queue.put({"type": "conversation_initiation_metadata",
                "conversation_initiation_metadata_event": {"agent_output_audio_format":
                    "mp3_44100" if self.bad_format else "pcm_16000"}})
            await self.reply("Greeting", b"\x01\x01")
        elif msg.get("type") == "user_message" and not self.silent:
            await self.queue.put({"type": "ping", "ping_event": {"event_id": 7}})
            await self.reply("Un café, claro.", b"\x02\x02")

    async def reply(self, text, audio):
        await self.queue.put({"type": "agent_response", "agent_response_event": {"agent_response": text}})
        await self.queue.put({"type": "audio", "audio_event": {
            "audio_base_64": base64.b64encode(audio).decode()}})

    def __aiter__(self):
        return self

    async def __anext__(self):
        return json.dumps(await self.queue.get())

    async def close(self):
        self.closed = True


def make_provider(hears=None, **kwargs):
    sockets, requests = [], []
    # What Scribe says of each upload, in order; the last one repeats.
    hears = list(hears or [{"text": "Quiero un café", "language_code": "spa"}])

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("speech-to-text"):
            assert b"scribe_v2" in request.content
            assert b"RIFF" in request.content
            return httpx.Response(200, json=hears.pop(0) if len(hears) > 1 else hears[0])
        assert request.url.params["agent_id"] in {"agent-luis", "agent-maria"}
        return httpx.Response(200, json={"signed_url": "wss://example.invalid/signed"})

    async def connect(url, **options):
        socket = Socket(silent=kwargs.pop("silent", False), bad_format=kwargs.pop("bad_format", False))
        sockets.append(socket)
        return socket

    provider = ElevenLabsSpeech("test-key", {"luis": "agent-luis", "maria": "agent-maria"},
        client=httpx.AsyncClient(base_url="https://example.invalid", transport=httpx.MockTransport(handler)),
        connect=connect, quiet=.005, idle_seconds=.05, languages=kwargs.pop("languages", ("es", "en")))
    return provider, sockets, requests


def test_by_default_every_clip_is_transcribed_pinned_to_the_scenario_language():
    """Scribe hears accented Spanish as English often enough that guessing is off:
    one request, language_code set, whatever it would have detected."""
    async def run():
        provider, _, requests = make_provider(hears=[
            {"text": "Quiero un café", "language_code": "spa"}], languages=("es",))
        try:
            result = await provider.respond(turn())
            assert result.user_transcript == "Quiero un café"
            uploads = [r for r in requests if r.url.path.endswith("speech-to-text")]
            assert len(uploads) == 1
            assert b'name="language_code"\r\n\r\nes' in uploads[0].content
        finally:
            await provider.aclose()
    asyncio.run(run())


def test_with_several_languages_a_guess_outside_them_is_heard_again_as_the_first():
    async def run():
        provider, _, requests = make_provider(hears=[
            {"text": "Uhm, qual è questa un burrito?", "language_code": "ita"},
            {"text": "¿Cuánto cuesta un burrito?", "language_code": "spa"},
            {"text": "How do I say tip?", "language_code": "eng"}])
        try:
            result = await provider.respond(turn())
            assert result.user_transcript == "¿Cuánto cuesta un burrito?"
            uploads = [r for r in requests if r.url.path.endswith("speech-to-text")]
            assert len(uploads) == 2
            assert b"language_code" not in uploads[0].content
            assert b'name="language_code"\r\n\r\nes' in uploads[1].content
            # English is fine as it is: one call, nothing pinned.
            result = await provider.respond(turn())
            assert result.user_transcript == "How do I say tip?"
            assert len([r for r in requests if r.url.path.endswith("speech-to-text")]) == 3
        finally:
            await provider.aclose()
    asyncio.run(run())


def turn(session=None, npc="luis", **kwargs):
    return SpeechInput(b"\x00\x00" * 1600, "audio/pcm", session or uuid4(), npc, sample_rate=16000, **kwargs)


def test_speech_reuses_session_excludes_greeting_and_switches_npc():
    async def run():
        provider, sockets, requests = make_provider()
        request = turn(scenario_id=uuid4(), scenario={"title": "Café"})
        try:
            result = await provider.respond(request)
            with wave.open(io.BytesIO(result.audio)) as wav:
                assert wav.getframerate() == 16000
                assert wav.readframes(100) == b"\x02\x02"
            assert result.user_transcript == "Quiero un café"
            assert result.agent_transcript == "Un café, claro."
            assert any(m["type"] == "contextual_update" for m in sockets[0].sent)
            assert any(m["type"] == "pong" for m in sockets[0].sent)
            await provider.respond(request)
            assert len(sockets) == 1
            await provider.respond(turn(request.session_id, "maria"))
            assert len(sockets) == 2
            assert sockets[0].closed
            await provider.end_session(request.session_id)
            assert sockets[1].closed
            assert not provider.sessions
        finally:
            await provider.aclose()
    asyncio.run(run())


def test_http_real_adapter_contract(tmp_path):
    provider, sockets, _ = make_provider()
    with TestClient(create_app(speech=provider, data_dir=tmp_path, runs_dir=tmp_path / "runs")) as client:
        sid = str(uuid4())
        result = client.post("/v1/speech", params={"session_id": sid, "npc_id": "luis",
            "sample_rate": 16000, "response_format": "json"}, content=b"\0\0" * 1600,
            headers={"Content-Type": "audio/pcm"})
        assert result.status_code == 200
        assert base64.b64decode(result.json()["audio_base64"]).startswith(b"RIFF")
        assert result.json()["agent_transcript"] == "Un café, claro."
        assert client.delete(f"/v1/speech/sessions/{sid}").status_code == 204
        assert sockets[0].closed


def test_timeout_closes_socket():
    async def run():
        provider, sockets, _ = make_provider(silent=True)
        try:
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(.03):
                    await provider.respond(turn())
            assert sockets[0].closed
            assert not provider.sessions
        finally:
            await provider.aclose()
    asyncio.run(run())


def test_bad_audio_and_unknown_npc_do_not_connect():
    async def run():
        provider, sockets, requests = make_provider()
        try:
            with pytest.raises(SpeechInputError):
                await provider.respond(SpeechInput(b"invalid", "audio/wav", uuid4(), "luis"))
            with pytest.raises(SpeechUnavailable):
                await provider.respond(turn(npc="unknown"))
            assert not sockets and not requests
        finally:
            await provider.aclose()
    asyncio.run(run())


def test_idle_expiry():
    async def run():
        provider, sockets, _ = make_provider()
        try:
            await provider.respond(turn())
            await asyncio.sleep(.13)
            assert sockets[0].closed
            assert not provider.sessions
        finally:
            await provider.aclose()
    asyncio.run(run())


def test_format_mismatch_closes():
    async def run():
        provider, sockets, _ = make_provider(bad_format=True)
        try:
            with pytest.raises(ValueError, match="PCM"):
                await provider.respond(turn())
            assert sockets[0].closed
        finally:
            await provider.aclose()
    asyncio.run(run())


def test_overlap_rejected():
    async def run():
        provider, _, _ = make_provider(silent=True)
        request = turn()
        active = asyncio.create_task(provider.respond(request))
        try:
            await asyncio.sleep(.015)
            with pytest.raises(SpeechInputError, match="already running"):
                await provider.respond(request)
        finally:
            active.cancel()
            with pytest.raises(asyncio.CancelledError):
                await active
            await provider.aclose()
    asyncio.run(run())


def test_the_other_character_at_the_table_overhears_a_turn():
    async def run():
        provider, sockets, _ = make_provider()
        try:
            luis, maria = turn(run_id="visit-9"), turn(npc="maria", run_id="visit-9")
            await provider.respond(luis)
            await provider.respond(maria)
            heard = [m for m in sockets[0].sent if m["type"] == "contextual_update"]
            assert len(heard) == 1
            assert "Quiero un café" in heard[0]["text"] and "Un café, claro." in heard[0]["text"]
            # Maria's socket opened after Luis spoke, so she heard nothing of his turn.
            assert not [m for m in sockets[1].sent if m["type"] == "contextual_update"]
            # A character on another visit hears nothing.
            await provider.respond(turn(run_id="visit-10"))
            assert len([m for m in sockets[0].sent if m["type"] == "contextual_update"]) == 1
        finally:
            await provider.aclose()
    asyncio.run(run())


def test_a_scene_note_reaches_the_character_now_and_when_they_open_later():
    async def run():
        provider, sockets, _ = make_provider()
        try:
            await provider.respond(turn(run_id="visit-11"))              # Luis is open
            await provider.note("visit-11", "luis", "floor", "Maria is walking over to take the order.")
            await provider.note("visit-11", "maria", "floor", "The customer is talking to Luis.")
            notes = [m["text"] for m in sockets[0].sent if m["type"] == "contextual_update"]
            assert notes == ["Scene note (floor): Maria is walking over to take the order."]
            # Maria's conversation opens later and is told what stands for her.
            await provider.respond(turn(npc="maria", run_id="visit-11"))
            assert [m["text"] for m in sockets[1].sent if m["type"] == "contextual_update"][:1] \
                == ["Scene note (floor): The customer is talking to Luis."]
            # A withdrawn note is not repeated on reopen; another visit hears nothing.
            await provider.note("visit-11", "maria", "floor", "")
            await provider.respond(turn(run_id="visit-12"))
            assert not [m for m in sockets[2].sent if m["type"] == "contextual_update"]
            assert provider.runs["visit-11"].notes == {"luis": {"floor": "Scene note (floor): Maria is walking over to take the order."},
                                                       "maria": {}}
        finally:
            await provider.aclose()
    asyncio.run(run())


def test_scene_note_endpoint(tmp_path):
    provider, sockets, _ = make_provider()
    with TestClient(create_app(speech=provider, data_dir=tmp_path, runs_dir=tmp_path / "runs")) as client:
        body = {"npc_id": "luis", "key": "floor", "text": "Maria is on her way."}
        assert client.post("/v1/runs/visit-1/notes", json=body).status_code == 204
        assert client.post("/v1/runs/bad.id/notes", json=body).status_code == 422
        assert client.post("/v1/runs/visit-1/notes", json={"npc_id": "luis"}).status_code == 422
        assert provider.runs["visit-1"].notes["luis"]["floor"].endswith("Maria is on her way.")
