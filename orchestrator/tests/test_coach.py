import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestrator.brain_routes import build_router
from orchestrator.coach import OpenAICoach, _WireHint, create_coach, hint_input
from orchestrator.director import Director, GoalStore
from orchestrator.grading import TranscriptStore
from orchestrator.models import GoalTick, Hint, RubricGoal, Suggestion, TranscriptTurn, Verdict
from orchestrator.scene import ScenePack, default_pack_dir

HINT = Hint(meaning_en="What would you like?", tip="Short answers are fine.",
            suggestions=[Suggestion(es="Un café de olla, por favor.", en="A café de olla, please."),
                         Suggestion(es="¿Qué me recomiendas?", en="What do you recommend?")])


class Helper:
    def __init__(self):
        self.calls = []

    async def hint(self, transcript, npc_name, level, open_goals):
        self.calls.append((list(transcript), npc_name, level, [g.id for g in open_goals]))
        return HINT


class Quiet:
    async def review(self, pending, transcript):
        return Verdict(achieved=[])


def client(tmp_path, coach=None, with_director=True):
    app = FastAPI()
    app.include_router(build_router())
    app.state.transcripts = TranscriptStore(tmp_path / "runs")
    app.state.director = Director(Quiet(), GoalStore(tmp_path / "goals"),
                                  app.state.transcripts) if with_director else None
    app.state.pack = ScenePack.load(default_pack_dir())
    app.state.coach, app.state.feedback, app.state.grader = coach, None, None
    return TestClient(app), app


def test_hint_uses_the_run_and_records_that_help_was_asked_for(tmp_path):
    coach = Helper()
    http, app = client(tmp_path, coach)
    pack = app.state.pack
    first = pack.scenario.goals[0].id
    app.state.transcripts.append("visit-1", [
        TranscriptTurn(role="learner", npc_id="maria", text="Hola"),
        TranscriptTurn(role="npc", npc_id="maria", text="¿Qué te doy?")])
    app.state.director.store.save("visit-1", {first: GoalTick(id=first, evidence_quote="Hola")})

    result = http.post("/v1/hint", json={"run_id": "visit-1", "npc_id": "maria", "level": "A1"})
    assert result.status_code == 200 and result.json() == HINT.model_dump()
    transcript, name, level, open_goals = coach.calls[0]
    assert [t.text for t in transcript] == ["Hola", "¿Qué te doy?"]
    assert (name, level) == (pack.npcs["maria"].name, "A1")
    assert first not in open_goals and len(open_goals) == len(pack.scenario.goals) - 1

    # The grader sees the hint; the counter feeds the report. Level falls back to the pack's.
    assert app.state.transcripts.get("visit-1")[-1].text == "hint requested"
    assert http.post("/v1/hint", json={"run_id": "visit-1", "npc_id": "luis"}).status_code == 200
    assert coach.calls[1][2] == pack.scenario.level
    assert asyncio.run(app.state.director.insights("visit-1"))["counters"]["hints"] == 2


def test_hint_errors(tmp_path, monkeypatch):
    http, _ = client(tmp_path, Helper(), with_director=False)
    assert http.post("/v1/hint", json={"run_id": "nobody", "npc_id": "maria"}).status_code == 404
    assert http.post("/v1/hint", json={"run_id": "../x", "npc_id": "maria"}).status_code == 422
    assert http.post("/v1/hint", json={"run_id": "v", "npc_id": "maria",
                                       "level": "C2"}).status_code == 422
    http, _ = client(tmp_path)
    assert http.post("/v1/hint", json={"run_id": "visit-1", "npc_id": "maria"}).status_code == 503
    for key in ("OPENAI_API_KEY", "DIRECTOR_MODEL", "TUTOR_MODEL", "SCENARIO_MODEL"):
        monkeypatch.delenv(key, raising=False)
    assert create_coach() is None


def test_a_failing_coach_is_a_502_and_records_nothing(tmp_path):
    class Broken:
        async def hint(self, *args):
            raise RuntimeError("sk-secret")

    http, app = client(tmp_path, Broken())
    app.state.transcripts.append("visit-1", [TranscriptTurn(role="npc", npc_id="maria", text="Hola")])
    result = http.post("/v1/hint", json={"run_id": "visit-1", "npc_id": "maria"})
    assert result.status_code == 502 and "secret" not in result.text
    assert len(app.state.transcripts.get("visit-1")) == 1


def test_openai_coach_request_is_small_and_fast():
    calls = []

    class Responses:
        async def parse(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(status="completed", output_parsed=_WireHint(
                meaning_en="m", tip="t", suggestions=[Suggestion(es=f"es{i}", en=f"en{i}")
                                                      for i in range(5)]))

    async def run():
        coach = OpenAICoach("sk-test", "director-model")
        coach.client = SimpleNamespace(responses=Responses())
        turns = [TranscriptTurn(role="npc", npc_id="maria", text=f"línea {i}") for i in range(30)]
        goal = RubricGoal(id="order", npc_id="maria", core=True, label="Order something",
                          evidence_required="Asks for an item.")
        return await coach.hint(turns, "Maria", "A2", [goal])

    hint = asyncio.run(run())
    assert len(hint.suggestions) == 3
    sent = calls[0]
    assert sent["reasoning"] == {"effort": "none"} and sent["store"] is False
    body = sent["input"][1]["content"]
    assert "línea 29" in body and "línea 17" not in body and "Order something" in body
    assert hint_input([], "Maria", "A1", [])[1]["content"].count("nothing in particular") == 1
