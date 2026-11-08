"""The scenario's soundscape, served to the game client.

The sounds are generated once by ``tools/make_ambience.py`` and committed; this module
only lists them and hands out the bytes. The list carries mixing guidance (volume,
ducking, whether to place the sound in 3D) so the scenario author, not the Unity
scene, decides how loud the ocean is.

Kept as a router so ``app.py`` needs one line to wire it:

    app.include_router(ambience.build_router())

The pack is read from ``request.app.state.pack`` on every request rather than captured
here, so the router can be built before the pack is loaded and tests can swap it.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from orchestrator.scene import ScenePack


def _pack(request: Request) -> ScenePack:
    pack = getattr(request.app.state, "pack", None)
    if pack is None:
        raise HTTPException(503, "No scenario pack is loaded")
    return pack


def build_router() -> APIRouter:
    router = APIRouter(tags=["ambience"])

    @router.get("/v1/ambience")
    def list_ambience(request: Request) -> dict:
        """Every sound in the scenario, with where to fetch it and how to mix it.

        ``ready`` is false when the file has not been generated yet, so a client can
        skip it instead of discovering a 404 mid-scene.
        """
        pack = _pack(request)
        sounds = []
        for sound in pack.scenario.ambience:
            path = pack.ambience_path(sound.id)
            sounds.append({
                "id": sound.id,
                "url": pack.ambience_url(sound.id),
                "loop": sound.loop,
                "volume": sound.volume,
                "duck_db": sound.duck_db,
                "spatial": sound.spatial,
                "duration_seconds": sound.duration_seconds,
                "ready": bool(path and path.is_file()),
            })
        return {"scenario_id": pack.scenario.scenario_id, "sounds": sounds,
                "action_sfx": {tool: pack.ambience_url(sound)
                               for tool, sound in pack.scenario.action_sfx.items()}}

    @router.get("/v1/ambience/{sound_id}")
    def get_ambience(sound_id: str, request: Request) -> FileResponse:
        # The id is only ever used as a lookup key into the scenario's own list; the
        # filename comes from the scenario. Nothing the caller sends touches the disk,
        # so "../../.env" is simply an unknown id.
        path = _pack(request).ambience_path(sound_id)
        if path is None:
            raise HTTPException(404, f"Unknown ambience sound '{sound_id}'")
        if not path.is_file():
            raise HTTPException(404, f"'{sound_id}' has not been generated yet; "
                                     f"run tools/make_ambience.py --apply")
        # Generated once and committed, so a client may cache it for the whole visit.
        return FileResponse(path, media_type="audio/mpeg",
                            headers={"Cache-Control": "public, max-age=86400"})

    return router
