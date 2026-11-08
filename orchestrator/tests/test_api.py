import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from orchestrator.app import create_app
from orchestrator.models import GeneratedScenario
from orchestrator.speech import SpeechOutput


def example():
    return {"scenario": {"title": "Café", "setting": "A café in Cancún",
        "language": "Mexican Spanish", "level": "A2",
        "characters": [{"id": "luis", "name": "Luis", "role": "Barista",
            "instructions": "Stay in character", "opening_line": "¿Qué te doy?"}],
        "goals": [{"id": "order", "description": "Order a drink", "evidence_required":
            "Learner requests a menu item", "npc_id": "luis", "core": True}]},
        "response": "Practice ordering a coffee."}


class Scenarios:
    async def generate(self, request):
        return GeneratedScenario.model_validate(example())


class Speech:
    def __init__(self):
        self.calls = []
        self.greeted = set()

    async def respond(self, request):
        self.calls.append(request)
        return SpeechOutput(b"\x00\x00", "audio/pcm", 16000, "Un café", "Claro")

    async def warm(self, request):
        if request.session_id in self.greeted:
            return None
        self.greeted.add(request.session_id)
        return SpeechOutput(b"RIFF\x00\x00", "audio/wav", 16000, None, "¡Hola!",
                            timings_ms={"open": 700})


def test_warm_returns_the_greeting_once_and_records_it(tmp_path):
    speech = Speech()
    with TestClient(create_app(speech=speech, data_dir=tmp_path, runs_dir=tmp_path / "runs")) as client:
        session = uuid4()
        params = {"npc_id": "luis", "run_id": "visit1"}
        hello = client.post(f"/v1/speech/sessions/{session}/warm", params=params)
        assert hello.status_code == 200
        assert hello.json()["agent_transcript"] == "¡Hola!"
        assert hello.json()["media_type"] == "audio/wav"
        assert hello.json()["user_transcript"] is None and hello.json()["actions"] == []
        assert hello.headers["server-timing"] == "open;dur=700"
        # The conversation is open and has said hello: nothing more to play.
        assert client.post(f"/v1/speech/sessions/{session}/warm", params=params).status_code == 204
    recorded = (tmp_path / "runs" / "visit1.jsonl").read_text().splitlines()
    assert len(recorded) == 1 and '"role":"npc"' in recorded[0] and "¡Hola!" in recorded[0]


def test_scenario_persistence_and_speech_context(tmp_path):
    speech = Speech()
    with TestClient(create_app(scenarios=Scenarios(), speech=speech, data_dir=tmp_path, runs_dir=tmp_path / "runs")) as client:
        result = client.post("/v1/scenarios", json={"prompt": "Order at a café"})
        assert result.status_code == 200
        saved = result.json()
        assert client.get(f"/v1/scenarios/{saved['scenario_id']}").json() == saved
        response = client.post("/v1/speech", params={"session_id": str(uuid4()), "npc_id": "luis",
            "scenario_id": saved["scenario_id"], "response_format": "json"},
            content=b"audio", headers={"Content-Type": "audio/wav"})
        assert response.status_code == 200
        assert response.json()["audio_base64"] == "AAA="
        assert response.json()["user_transcript"] == "Un café"
        assert speech.calls[0].scenario == saved["scenario"]
    with TestClient(create_app(data_dir=tmp_path, runs_dir=tmp_path / "runs")) as client:
        assert client.get(f"/v1/scenarios/{saved['scenario_id']}").json() == saved


@pytest.mark.parametrize("payload", [{}, {"prompt": " "}, {"prompt": "ok", "level": "Z9"},
    {"prompt": "ok", "unknown": 1}])
def test_invalid_scenario_request(payload, tmp_path):
    with TestClient(create_app(scenarios=Scenarios(), data_dir=tmp_path, runs_dir=tmp_path / "runs")) as client:
        assert client.post("/v1/scenarios", json=payload).status_code == 422


def test_unconfigured(monkeypatch, tmp_path):
    for key in ("OPENAI_API_KEY", "SCENARIO_MODEL", "SPEECH_ADAPTER", "ELEVENLABS_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    with TestClient(create_app(data_dir=tmp_path, runs_dir=tmp_path / "runs")) as client:
        assert client.get("/health").json()["speech_ready"] is False
        assert client.post("/v1/scenarios", json={"prompt": "café"}).status_code == 503
        assert client.post("/v1/speech", params={"session_id": str(uuid4()), "npc_id": "luis"},
            content=b"wav", headers={"Content-Type": "audio/wav"}).status_code == 503


@pytest.mark.parametrize("media,data,extra,status", [
    ("text/plain", b"x", {}, 415), ("audio/wav", b"", {}, 422),
    ("audio/pcm", b"00", {}, 422), ("audio/pcm", b"0", {"sample_rate": 16000}, 422),
    ("audio/wav", b"0" * (10 * 1024 * 1024 + 1), {}, 413),
    ("audio/pcm", b"00", {"sample_rate": 16000}, 200),
])
def test_audio_validation(media, data, extra, status, tmp_path):
    speech = Speech()
    with TestClient(create_app(speech=speech, data_dir=tmp_path, runs_dir=tmp_path / "runs")) as client:
        result = client.post("/v1/speech", params={"session_id": str(uuid4()), "npc_id": "luis", **extra},
                             content=data, headers={"Content-Type": media})
        assert result.status_code == status
        assert len(speech.calls) == (1 if status == 200 else 0)
        if status == 200:
            assert result.content == b"\x00\x00"
            assert result.headers["X-Audio-Sample-Rate"] == "16000"


@pytest.mark.parametrize("mode,status", [("error", 502), ("timeout", 504), ("invalid", 502)])
def test_provider_failure(mode, status, tmp_path):
    class Broken:
        async def generate(self, request):
            if mode == "timeout":
                await asyncio.sleep(1)
            if mode == "error":
                raise RuntimeError("SECRET must not be returned")
            return {}
    with TestClient(create_app(scenarios=Broken(), data_dir=tmp_path, runs_dir=tmp_path / "runs", timeout=.01)) as client:
        result = client.post("/v1/scenarios", json={"prompt": "café"})
        assert result.status_code == status
        assert "SECRET" not in result.text
        assert not list(tmp_path.glob("*.json"))


def test_bad_references():
    value = example()
    value["scenario"]["goals"][0]["npc_id"] = "missing"
    with pytest.raises(ValueError):
        GeneratedScenario.model_validate(value)


def test_unknown_scenario_and_npc(tmp_path):
    with TestClient(create_app(scenarios=Scenarios(), speech=Speech(), data_dir=tmp_path, runs_dir=tmp_path / "runs")) as client:
        assert client.get(f"/v1/scenarios/{uuid4()}").status_code == 404
        assert client.get("/v1/scenarios/not-a-uuid").status_code == 422
        saved = client.post("/v1/scenarios", json={"prompt": "café"}).json()
        result = client.post("/v1/speech", params={"session_id": str(uuid4()), "npc_id": "missing",
            "scenario_id": saved["scenario_id"]}, content=b"audio", headers={"Content-Type": "audio/wav"})
        assert result.status_code == 422
