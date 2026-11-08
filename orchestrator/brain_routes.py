"""The learner-facing teaching routes: a hint when asked, a report at the end.

They live in their own router so the speech path in app.py stays about speech. Nothing
here is on the reply path, and nothing here ever speaks through a character: help sits
beside the conversation, never inside it. Dependencies come from `request.app.state`,
so the app decides what is configured and tests can swap in doubles.
"""

import asyncio
import logging
from contextlib import suppress

from fastapi import APIRouter, HTTPException, Request

from .grading import rubric_goals
from .models import FeedbackReport, FeedbackRequest, Hint, HintRequest, TranscriptTurn

log = logging.getLogger("orchestrator")
EMPTY_INSIGHTS = {"achieved": [], "mistakes": [], "states": [], "notes": [], "counters": {}}


async def recorded(request: Request, run_id: str) -> list[TranscriptTurn]:
    try:
        turns = await asyncio.to_thread(request.app.state.transcripts.get, run_id)
    except (FileNotFoundError, ValueError):
        turns = []
    if not turns:
        raise HTTPException(404, "No recorded transcript for this run")
    return turns


async def insights_for(request: Request, run_id: str) -> dict:
    director = getattr(request.app.state, "director", None)
    if director is None:
        return EMPTY_INSIGHTS
    return await director.insights(run_id)


async def provider_call(awaitable, timeout: float):
    try:
        async with asyncio.timeout(timeout):
            return await awaitable
    except TimeoutError:
        raise HTTPException(504, "Provider timed out") from None
    except Exception as error:  # noqa: BLE001 — may carry transcripts or keys; log the class only
        log.warning("Brain provider call failed: %s", type(error).__name__)
        raise HTTPException(502, "Provider failed or returned invalid output") from None


def build_router() -> APIRouter:
    router = APIRouter()

    @router.post("/v1/hint", response_model=Hint)
    async def hint(payload: HintRequest, request: Request):
        """What the character just said, and two or three things to say next.

        Call it when the learner presses the help key. The character is not told, but
        the run records that help was asked for.
        """
        state = request.app.state
        coach = getattr(state, "coach", None)
        if coach is None:
            raise HTTPException(503, "Configure OPENAI_API_KEY and DIRECTOR_MODEL")
        transcript = await recorded(request, payload.run_id)
        pack = getattr(state, "pack", None)
        rubric = rubric_goals(pack.scenario.goals) if pack is not None else []
        done = {tick["id"] for tick in (await insights_for(request, payload.run_id))["achieved"]}
        npc = pack.npcs.get(payload.npc_id) if pack is not None else None
        result = await provider_call(coach.hint(
            transcript, getattr(npc, "name", None) or payload.npc_id,
            payload.level or getattr(getattr(pack, "scenario", None), "level", None) or "A2",
            [goal for goal in rubric if goal.id not in done]), 6)
        # Best effort: the learner asked for help and must get it even if we cannot log it.
        with suppress(Exception):
            await asyncio.to_thread(state.transcripts.append, payload.run_id, [
                TranscriptTurn(role="event", npc_id=payload.npc_id, text="hint requested")])
            if getattr(state, "director", None) is not None:
                await state.director.count(payload.run_id, "hints")
        return result

    @router.post("/v1/feedback", response_model=FeedbackReport)
    async def feedback(payload: FeedbackRequest, request: Request):
        """The written report for a finished run: what to say differently next time.

        Also saved as JSON and as a self-contained page; `html_path` says where.
        """
        state = request.app.state
        service = getattr(state, "feedback", None)
        if service is None:
            raise HTTPException(503, "Configure OPENAI_API_KEY and TUTOR_MODEL")
        pack, level, goals = getattr(state, "pack", None), "A2", None
        store = getattr(state, "scenario_store", None)
        if payload.scenario_id is not None and store is not None:
            try:
                saved = (await asyncio.to_thread(store.get, payload.scenario_id)).scenario
            except FileNotFoundError:
                raise HTTPException(404, "Scenario not found") from None
            goals, level = saved.goals, saved.level
        elif pack is not None:
            goals, level = pack.scenario.goals, pack.scenario.level
        if not goals:
            raise HTTPException(422, "No goals to report on: pass scenario_id or load a pack")
        transcript = await recorded(request, payload.run_id)
        return await provider_call(service.report(
            payload.run_id, rubric_goals(goals), transcript,
            await insights_for(request, payload.run_id), level,
            getattr(state, "audio_dir", None)), 90)

    return router
