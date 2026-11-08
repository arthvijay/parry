"""The soundscape endpoints.

Run against a bare FastAPI app that only sets ``app.state.pack``: the router must not
depend on anything else ``create_app`` builds, because another lane owns the wiring.
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestrator.ambience import build_router
from orchestrator.scene import ScenePack

PACK_DIR = Path(__file__).resolve().parent.parent.parent / "scenarios" / "cafe_cancun"


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.state.pack = ScenePack.load(PACK_DIR)
    app.include_router(build_router())
    return TestClient(app)


def test_list_describes_every_sound_with_mixing_guidance(client):
    body = client.get("/v1/ambience").json()
    sounds = {s["id"]: s for s in body["sounds"]}
    assert set(sounds) == {"ocean_loop", "cafe_murmur_loop", "cup_on_table", "receipt"}
    ocean = sounds["ocean_loop"]
    assert ocean["url"] == "/v1/ambience/ocean_loop"
    assert ocean["loop"] is True and ocean["spatial"] is False
    # Never louder than a whisper under the voices, and ducked while anyone speaks.
    assert ocean["volume"] == 0.12 and sounds["cafe_murmur_loop"]["volume"] == 0.08
    assert ocean["duck_db"] == -6
    assert sounds["cup_on_table"]["loop"] is False
    assert body["action_sfx"] == {"serve_order": "/v1/ambience/cup_on_table",
                                  "show_bill": "/v1/ambience/receipt"}


def test_every_listed_sound_is_committed_and_downloads_as_mp3(client):
    for sound in client.get("/v1/ambience").json()["sounds"]:
        assert sound["ready"], f"{sound['id']} missing: run tools/make_ambience.py --apply"
        response = client.get(sound["url"])
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mpeg"
        head = response.content[:3]
        assert head == b"ID3" or (head[0] == 0xFF and head[1] & 0xE0 == 0xE0)
        assert len(response.content) > 5_000 * sound["duration_seconds"]


@pytest.mark.parametrize("sound_id", [
    "nope", "ocean_loop.mp3", "..", "%2e%2e%2f%2e%2e%2fmenu.json", "..%2Fscenario.json",
    "OCEAN_LOOP",
])
def test_unknown_ids_and_traversal_attempts_are_404(client, sound_id):
    assert client.get(f"/v1/ambience/{sound_id}").status_code == 404


def test_listed_but_not_generated_is_404_and_flagged_not_ready(tmp_path):
    real = ScenePack.load(PACK_DIR)
    app = FastAPI()
    app.state.pack = ScenePack(real.scenario, real.menu, real.prompts, root=tmp_path)
    app.include_router(build_router())
    client = TestClient(app)
    assert not any(s["ready"] for s in client.get("/v1/ambience").json()["sounds"])
    assert client.get("/v1/ambience/ocean_loop").status_code == 404


def test_no_pack_is_503():
    app = FastAPI()
    app.state.pack = None
    app.include_router(build_router())
    client = TestClient(app)
    assert client.get("/v1/ambience").status_code == 503
    assert client.get("/v1/ambience/ocean_loop").status_code == 503
