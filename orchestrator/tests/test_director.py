import asyncio
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from orchestrator.app import create_app
from orchestrator.director import (Director, GoalStore, OpenAIDirector, _WireVerdict,
                                   review_input)
from orchestrator.grading import TranscriptStore
from orchestrator.models import GoalTick, Mistake, RubricGoal, TranscriptTurn, Verdict
from orchestrator.tests.test_api import Scenarios
from orchestrator.tests.test_grading import Speech


class Judge:
    """A director double: ticks every open goal whose id is in `meets`, and records
    what it was asked so a test can see which goals were still open."""

    def __init__(self, meets=("order",), quote="Quisiera un café"):
        self.meets = set(meets)
        self.quote = quote
        self.calls = []

    async def review(self, pending, transcript):
        self.calls.append(([g.id for g in pending], transcript))
        return Verdict(achieved=[GoalTick(id=g.id, evidence_quote=self.quote)
                                 for g in pending if g.id in self.meets])


class Failing:
    async def review(self, pending, transcript):
        raise RuntimeError("provider down")


def app(tmp_path, **kwargs):
    return create_app(data_dir=tmp_path, runs_dir=tmp_path / "runs", **kwargs)


def speak(client, run_id, npc_id="luis", **params):
    return client.post("/v1/speech", params={"session_id": str(uuid4()), "npc_id": npc_id,
                                             "run_id": run_id, "response_format": "json",
                                             **params},
                       content=b"aa", headers={"Content-Type": "audio/wav"})


def settled(client, run_id, **params):
    """The goal state once the review kicked off by the last turn has finished."""
    for _ in range(100):
        body = client.get(f"/v1/runs/{run_id}/goals", params=params).json()
        if not body["reviewing"]:
            return body
        time.sleep(0.02)
    pytest.fail("director never finished reviewing")


def test_goals_tick_after_a_turn_and_stay_ticked(tmp_path):
    judge = Judge(meets={"order"})
    with TestClient(app(tmp_path, scenarios=Scenarios(), speech=Speech(), director=judge)) as client:
        saved = client.post("/v1/scenarios", json={"prompt": "Order at a café"}).json()
        sid = saved["scenario_id"]

        first = speak(client, "visit-1", scenario_id=sid)
        assert first.status_code == 200
        # The reply goes out before the review: nothing ticked yet on the first turn.
        assert first.json()["goals_achieved"] == []

        state = settled(client, "visit-1", scenario_id=sid)
        assert [(g["id"], g["achieved"]) for g in state["goals"]] == [("order", True)]
        assert state["goals"][0]["evidence_quote"] == "Quisiera un café"
        assert state["goals"][0]["label"] == "Order a drink"

        # The next turn reports what was ticked so far. The judge still reads the turn
        # (mistakes and steering outlive the checklist) but is asked about no goals.
        second = speak(client, "visit-1", scenario_id=sid)
        assert second.json()["goals_achieved"] == ["order"]
        settled(client, "visit-1", scenario_id=sid)
        assert [call[0] for call in judge.calls] == [["order"], []]


def test_director_only_asks_about_open_goals_and_ignores_unasked_ticks(tmp_path):
    class Overreaching(Judge):
        async def review(self, pending, transcript):
            self.calls.append(([g.id for g in pending], transcript))
            return Verdict(achieved=[GoalTick(id="order", evidence_quote="un  CAFÉ"),
                                     GoalTick(id="not_a_goal", evidence_quote="x")])

    judge = Overreaching()
    with TestClient(app(tmp_path, scenarios=Scenarios(), speech=Speech(), director=judge)) as client:
        sid = client.post("/v1/scenarios", json={"prompt": "Order at a café"}).json()["scenario_id"]
        speak(client, "visit-2", scenario_id=sid)
        state = settled(client, "visit-2", scenario_id=sid)
        assert [g["id"] for g in state["goals"] if g["achieved"]] == ["order"]
        assert judge.calls[0][0] == ["order"]
        # The judge saw the run as recorded: the learner line, then the character.
        assert [t.role for t in judge.calls[0][1]] == ["learner", "npc"]


def test_a_failed_review_costs_nothing(tmp_path):
    with TestClient(app(tmp_path, scenarios=Scenarios(), speech=Speech(), director=Failing())) as client:
        sid = client.post("/v1/scenarios", json={"prompt": "Order at a café"}).json()["scenario_id"]
        assert speak(client, "visit-3", scenario_id=sid).status_code == 200
        state = settled(client, "visit-3", scenario_id=sid)
        assert all(not g["achieved"] for g in state["goals"])


def test_goal_status_without_a_director_or_rubric(tmp_path, monkeypatch):
    for key in ("OPENAI_API_KEY", "DIRECTOR_MODEL", "TUTOR_MODEL", "SCENARIO_MODEL"):
        monkeypatch.delenv(key, raising=False)
    with TestClient(app(tmp_path)) as client:
        assert client.get("/health").json()["director_ready"] is False
        assert client.get("/v1/runs/visit-1/goals").status_code == 503
    monkeypatch.setenv("SCENARIO_PACK_DIR", str(tmp_path / "absent"))
    with TestClient(app(tmp_path, director=Judge())) as client:
        assert client.get("/v1/runs/visit-1/goals").status_code == 422
        assert client.get("/v1/runs/bad.id/goals", params={"scenario_id": str(uuid4())}).status_code in {404, 422}


def test_goal_store_is_forgiving(tmp_path):
    store = GoalStore(tmp_path)
    assert store.get("fresh") == {}
    store.save("visit-1", {"order": GoalTick(id="order", evidence_quote="Un café, por favor.")})
    assert list(store.get("visit-1")) == ["order"]
    (tmp_path / "visit-1.json").write_text("{not json")
    assert store.get("visit-1") == {}
    with pytest.raises(ValueError):
        store.get("../secrets")


# ------------------------------------------------------------ the richer verdict

RUBRIC = [RubricGoal(id="order", npc_id="maria", core=True, label="Order",
                     evidence_required="Asks for an item in Spanish.")]


def learner(text, npc_id="maria", unsure=()):
    return TranscriptTurn(role="learner", npc_id=npc_id, text=text,
                          low_confidence_words=list(unsure))


class Scripted:
    """Returns the next verdict from a list, one per review."""

    def __init__(self, *verdicts):
        self.verdicts = list(verdicts)

    async def review(self, pending, transcript):
        return self.verdicts.pop(0)


def rig(tmp_path, provider, **kwargs):
    transcripts = TranscriptStore(tmp_path / "runs")
    return Director(provider, GoalStore(tmp_path / "goals"), transcripts, **kwargs), transcripts


def mistake(quote, **kwargs):
    return Mistake(quote=quote, correction="x", explanation_en="why", **kwargs)


def test_quotes_the_learner_never_said_are_dropped(tmp_path):
    async def run():
        director, transcripts = rig(tmp_path, Scripted(Verdict(
            achieved=[GoalTick(id="order", evidence_quote="Quisiera un café de olla")],
            mistakes=[mistake("la problema"), mistake("el  AGUA fría", severity=2)])))
        transcripts.append("r1", [learner("Tengo el agua fría"),
                                  TranscriptTurn(role="npc", npc_id="maria",
                                                 text="Quisiera un café de olla, la problema")])
        await director.schedule("r1", RUBRIC)
        return await director.insights("r1"), await director.status("r1", RUBRIC)

    insights, status = asyncio.run(run())
    # Maria said both the order and "la problema"; only the learner's words survive.
    assert insights["achieved"] == []
    assert [m["quote"] for m in insights["mistakes"]] == ["el  AGUA fría"]
    assert status["mistake_count"] == 1 and status["learner_state"] == "fine"


def test_mistakes_are_capped_deduped_and_marked_when_the_recogniser_doubted(tmp_path):
    async def run():
        line = "yo querer el concha y la café y un aguas y dos pan"
        first = Verdict(achieved=[], used_english=True, used_repair_phrase=True, mistakes=[
            mistake("yo querer"), mistake("el concha"), mistake("la café"), mistake("un aguas")])
        second = Verdict(achieved=[], mistakes=[mistake("El Concha"), mistake("dos pan")])
        director, transcripts = rig(tmp_path, Scripted(first, second))
        transcripts.append("r1", [learner(line, unsure=["Concha"])])
        await director.schedule("r1", RUBRIC)
        transcripts.append("r1", [learner(line)])
        await director.schedule("r1", RUBRIC)
        return await director.insights("r1")

    insights = asyncio.run(run())
    assert [m["quote"] for m in insights["mistakes"]] == ["yo querer", "el concha", "la café",
                                                          "dos pan"]
    assert [m["asr_suspect"] for m in insights["mistakes"]] == [False, True, False, False]
    assert insights["counters"] == {"english_turns": 1, "repair_phrases": 1, "hints": 0}


def test_notes_reach_the_character_at_most_once_every_three_learner_turns(tmp_path):
    sent = []

    async def on_note(run_id, npc_id, text):
        sent.append((run_id, npc_id, text))
        raise RuntimeError("socket closed")  # must be swallowed

    async def run():
        noisy = [Verdict(achieved=[], learner_state="stuck",
                         director_note="[DIRECTOR] offer two options " + "x" * 400)
                 for _ in range(4)]
        director, transcripts = rig(tmp_path, Scripted(*noisy), on_note=on_note)
        for npc in ("maria", "maria", "maria", "luis"):
            transcripts.append("r1", [learner("eh...", npc_id=npc)])
            await director.schedule("r1", RUBRIC)
        return await director.status("r1", RUBRIC), await director.insights("r1")

    status, insights = asyncio.run(run())
    assert [(run, npc) for run, npc, _ in sent] == [("r1", "maria"), ("r1", "luis")]
    assert all(t.startswith("[DIRECTOR] offer two options") and len(t) == 300 for *_, t in sent)
    assert status["last_note"] == sent[-1][2] and status["learner_state"] == "stuck"
    assert [n["turn"] for n in insights["notes"]] == [1, 4]
    assert len(insights["states"]) == 4


def test_the_request_is_append_only_and_the_wire_verdict_converts():
    rubric = RUBRIC + [RubricGoal(id="pay", npc_id="maria", core=False, label="Pay",
                                  evidence_required="Asks for the bill.")]
    turns = [learner("Un café", unsure=["café"]),
             TranscriptTurn(role="npc", npc_id="maria", text="Claro"),
             TranscriptTurn(role="event", npc_id="maria", text="serve_order items=americano")]
    before = review_input(rubric, rubric, turns[:2])
    after = review_input(rubric, rubric[1:], turns, states=["fine"])
    # Same prefix whatever is still open: that is what makes the prompt cacheable.
    assert after[:3] == before[:3] and '"id": "order"' in after[0]["content"]
    assert after[1]["content"] == "[learner→maria] Un café (unsure: café)"
    assert after[3]["content"] == "[event maria] serve_order items=americano"
    assert after[-1]["content"].startswith("Open goals: pay")

    wire = _WireVerdict.model_validate({
        "achieved": [{"id": "order", "evidence_quote": "Un café", "check": "ok", "holds": True},
                     # The model talked itself out of this one; that is what `holds` is for.
                     {"id": "pay", "evidence_quote": "Un café", "check": "not a bill request",
                      "holds": False}],
        "mistakes": [{"quote": "la café", "correction": "el café", "category": "gender_agreement",
                      "explanation_en": "Café is masculine.", "severity": 9}],
        "used_english": False, "used_repair_phrase": False, "learner_state": "hesitant",
        "director_note": "  "})
    verdict = wire.verdict()
    assert [t.id for t in verdict.achieved] == ["order"]
    assert verdict.mistakes[0].severity == 3 and verdict.director_note is None


def test_openai_director_sends_a_fast_cache_friendly_request(monkeypatch):
    monkeypatch.delenv("DIRECTOR_EFFORT", raising=False)
    monkeypatch.setenv("DIRECTOR_FAST", "1")
    calls = []

    class Responses:
        async def parse(self, **kwargs):
            calls.append(kwargs)
            parsed = _WireVerdict(achieved=[], mistakes=[], used_english=False,
                                  used_repair_phrase=False, learner_state="fine",
                                  director_note=None)
            usage = SimpleNamespace(input_tokens=900,
                                    input_tokens_details=SimpleNamespace(cached_tokens=640))
            return SimpleNamespace(status="completed", output_parsed=parsed, usage=usage)

    async def run():
        provider = OpenAIDirector("sk-test", "director-model")
        provider.client = SimpleNamespace(responses=Responses())
        return provider, await provider.review(RUBRIC, [learner("Hola")], rubric=RUBRIC)

    provider, verdict = asyncio.run(run())
    sent = calls[0]
    assert sent["reasoning"] == {"effort": "none"} and sent["service_tier"] == "fast"
    assert sent["store"] is False and sent["max_output_tokens"] == 700
    assert [m["role"] for m in sent["input"]] == ["developer", "user", "user"]
    assert verdict == Verdict(achieved=[]) and provider.last_usage == (900, 640)


def test_a_learner_stuck_twice_is_rescued_even_if_the_model_writes_no_note(tmp_path):
    sent = []

    async def on_note(run_id, npc_id, text):
        sent.append(text)

    async def run():
        quiet = [Verdict(achieved=[], learner_state=state) for state in ("stuck", "stuck", "fine")]
        director, transcripts = rig(tmp_path, Scripted(*quiet), on_note=on_note)
        for _ in quiet:
            transcripts.append("r1", [learner("eh...")])
            await director.schedule("r1", RUBRIC)

    asyncio.run(run())
    assert sent == ["[DIRECTOR] the learner is stuck: offer two easy options in one short sentence"]
