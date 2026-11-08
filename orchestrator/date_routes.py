"""HTTP and WebSocket routes for the speed date.

    GET  /v1/matchmaker/catalog        what the onboarding UI can offer
    POST /v1/matchmaker/generate       build one date from the learner's choices
    POST /v1/matchmaker/preset         an authored demo date (Café Rayuela, Cancún)
    GET  /v1/matchmaker/{scenario_id}  a date built earlier (replays, "try again")
    WS   /v1/stream                    the live date (stream_gateway.py)
    WS   /v1/vision                    face tracking alone, for onboarding's vision panel
    POST /v1/avatar/from-selfie        avatar skin and hair colours from a selfie
    POST /v1/date/grade                the verdict receipt (also reachable as /v1/grade)
    GET  /v1/date/runs/{run_id}        what was said and how the chemistry moved
    POST /v1/date/report               "Your date, decoded": the learning report
    GET  /v1/date/report/{run_id}.html the same report as a page
    GET  /v1/face/status               whether webcam face tracking is ready

Kept as a router so ``app.py`` wires it in one line and the café's routes are untouched.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from . import config
from fastapi.responses import FileResponse

from .date_models import (DateGradeRequest, DateReport, DateReportRequest, DateScenario,
                          DateVerdict, MatchmakerRequest, PresetRequest)
from .matchmaker import build_preset
from .stream_gateway import stream_endpoint, vision_endpoint

MAX_JSON_BYTES = 32 * 1024
RUN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


async def _json_body(request: Request, model):
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise HTTPException(415, "Expected application/json")
    body = await request.body()
    if len(body) > MAX_JSON_BYTES:
        raise HTTPException(413, "Request body is too large")
    try:
        return model.model_validate_json(body)
    except ValidationError as error:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
                             for e in error.errors()[:5])
        raise HTTPException(422, problems) from None


async def grade_date(state, payload: DateGradeRequest) -> DateVerdict:
    try:
        scenario = await asyncio.to_thread(state.date_store.get, payload.scenario_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "Unknown scenario_id") from None
    try:
        chemistry = await asyncio.to_thread(state.chemistry_store.get, payload.run_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "No date was recorded under this run_id") from None
    if chemistry.scenario_id != scenario.scenario_id:
        raise HTTPException(422, "That run belongs to a different date")
    try:
        transcript = await asyncio.to_thread(state.transcripts.get, payload.run_id)
    except (FileNotFoundError, ValueError):
        transcript = []
    return await state.date_grader.grade(scenario, chemistry, transcript, payload.run_id)


def build_router() -> APIRouter:
    router = APIRouter(tags=["speed date"])

    @router.get("/v1/matchmaker/catalog")
    async def catalog():
        return config.catalog()

    @router.post("/v1/matchmaker/generate", response_model=DateScenario, openapi_extra={
        "requestBody": {"required": True, "content": {"application/json": {
            "schema": MatchmakerRequest.model_json_schema()}}}})
    async def generate(request: Request):
        payload = await _json_body(request, MatchmakerRequest)
        scenario = await request.app.state.matchmaker.generate(payload)
        try:
            await asyncio.to_thread(request.app.state.date_store.save, scenario)
        except OSError:
            raise HTTPException(500, "Could not save the date") from None
        return scenario

    @router.post("/v1/matchmaker/preset", response_model=DateScenario, openapi_extra={
        "requestBody": {"required": True, "content": {"application/json": {
            "schema": PresetRequest.model_json_schema()}}}})
    async def preset(request: Request):
        """An authored date, the same every time: the demo scenario."""
        payload = await _json_body(request, PresetRequest)
        try:
            scenario = build_preset(payload)
        except (ValueError, KeyError) as error:
            raise HTTPException(404, f"Unknown preset: {error}") from None
        try:
            await asyncio.to_thread(request.app.state.date_store.save, scenario)
        except OSError:
            raise HTTPException(500, "Could not save the date") from None
        return scenario

    @router.get("/v1/matchmaker/{scenario_id}", response_model=DateScenario)
    async def get_date(request: Request, scenario_id: str):
        try:
            return await asyncio.to_thread(request.app.state.date_store.get, scenario_id)
        except (FileNotFoundError, ValueError):
            raise HTTPException(404, "Unknown scenario_id") from None

    @router.post("/v1/date/grade", response_model=DateVerdict, openapi_extra={
        "requestBody": {"required": True, "content": {"application/json": {
            "schema": DateGradeRequest.model_json_schema()}}}})
    async def grade(request: Request):
        return await grade_date(request.app.state, await _json_body(request, DateGradeRequest))

    @router.get("/v1/date/runs/{run_id}")
    async def run(request: Request, run_id: str):
        state = request.app.state
        try:
            chemistry = await asyncio.to_thread(state.chemistry_store.get, run_id)
        except (FileNotFoundError, ValueError):
            raise HTTPException(404, "No date was recorded under this run_id") from None
        try:
            transcript = await asyncio.to_thread(state.transcripts.get, run_id)
        except (FileNotFoundError, ValueError):
            transcript = []
        return {"run_id": run_id, "chemistry": asdict(chemistry),
                "transcript": [t.model_dump() for t in transcript]}

    @router.post("/v1/date/report", response_model=DateReport, openapi_extra={
        "requestBody": {"required": True, "content": {"application/json": {
            "schema": DateReportRequest.model_json_schema()}}}})
    async def report(request: Request):
        """What to say differently next time, in the learner's own words, checked."""
        state = request.app.state
        payload = await _json_body(request, DateReportRequest)
        try:
            scenario = await asyncio.to_thread(state.date_store.get, payload.scenario_id)
            chemistry = await asyncio.to_thread(state.chemistry_store.get, payload.run_id)
        except (FileNotFoundError, ValueError):
            raise HTTPException(404, "No date was recorded under this run_id") from None
        try:
            transcript = await asyncio.to_thread(state.transcripts.get, payload.run_id)
        except (FileNotFoundError, ValueError):
            transcript = []
        return await state.date_reporter.report(scenario, chemistry, transcript, payload.run_id,
                                                getattr(state, "audio_dir", None))

    @router.get("/v1/date/report/{run_id}.html")
    async def report_page(request: Request, run_id: str):
        if not RUN.match(run_id):
            raise HTTPException(422, "Invalid run_id")
        path = request.app.state.date_reporter.page_path(run_id)
        if not path.is_file():
            raise HTTPException(404, "No report yet: POST /v1/date/report first")
        return FileResponse(path, media_type="text/html")

    @router.get("/v1/face/status")
    async def face_status(request: Request):
        face = request.app.state.face_tracker
        if face is None:
            return {"available": False, "reason": "disabled (FACE_TRACKING=0)"}
        ready = await face.start()
        return {"available": ready, "reason": None if ready else face.error}

    @router.post("/v1/avatar/from-selfie", openapi_extra={"requestBody": {"required": True,
                 "content": {"image/jpeg": {"schema": {"type": "string", "format": "binary"}}}}})
    async def from_selfie(request: Request):
        """Avatar colours from a selfie: skin and hair sampled around the face landmarks.
        The client picks the body; nothing about the person is inferred from the photo."""
        if request.headers.get("content-type", "").split(";")[0].strip() not in (
                "image/jpeg", "image/png"):
            raise HTTPException(415, "Send the photo as image/jpeg or image/png")
        body = await request.body()
        if not body or len(body) > 4 * 1024 * 1024:
            raise HTTPException(413, "Photo must be under 4 MB")
        face = request.app.state.face_tracker
        if face is None:
            raise HTTPException(503, "Face tracking is turned off (FACE_TRACKING=0)")
        return await face.selfie(body)

    router.add_api_websocket_route("/v1/stream", stream_endpoint)
    router.add_api_websocket_route("/v1/vision", vision_endpoint)
    return router
