"""The ten additions, offline: culture-aware body language, memory across dates, no
corrections on misheard words, fillers and register, wrong-region slang, cultural
moments, the self-play scorer, costs and plans, the voice cache, and the share pages."""

import asyncio
import json
import random
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient

from orchestrator import config, costs, stream_gateway
from orchestrator.app import create_app
from orchestrator.chemistry_director import (ChemistryDirector, ChemistryStore,
                                             RulesChemistryJudge, JudgeContext,
                                             create_judge, other_region_words, persona_context)
from orchestrator.claude import Claude
from orchestrator.date_grader import (DateGrader, asr_suspect, choose_correction,
                                      count_fillers, speech_habits, words_to_practise)
from orchestrator.date_models import MatchmakerRequest, PracticeTarget, VoiceConfig
from orchestrator.face_tracker import FaceReading
from orchestrator.learner_profile import LearnerProfileStore, learner_key
from orchestrator.matchmaker import build_scenario, template_draft
from orchestrator.models import TranscriptTurn
from orchestrator.nonverbal import NonverbalTracker
from orchestrator.share_routes import card_html
from orchestrator.tts import Voice, frames
from orchestrator.voice_cache import VoiceCache

KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY",
        "GOOGLE_CLOUD_PROJECT", "DEEPGRAM_API_KEY", "FISH_AUDIO_API_KEY", "OPENAI_API_KEY",
        "ELEVENLABS_API_KEY", "SPEECH_ADAPTER", "PLAN", "CLAUDE_PRICE_INPUT",
        "DEEPGRAM_PRICE_PER_MINUTE", "FISH_PRICE_PER_MILLION_CHARS")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(stream_gateway, "AHEAD_SECONDS", 10_000.0)


def scenario(practice=(), **overrides):
    values = dict(learner_name="Arth", language="es-AR", proficiency="B2", venue_style="auto",
                  date_gender="female", date_ethnicity="latina",
                  personality_archetype="playful_sarcastic", custom_notes="Loves indie rock",
                  scene_prompt="a rooftop bar")
    values.update(overrides)
    req = MatchmakerRequest(**values)
    return build_scenario(req, template_draft(req, random.Random(1)), "template",
                          random.Random(1), practice)


def learner(text, unsure=()):
    return TranscriptTurn(role="learner", npc_id="date_npc", text=text,
                          low_confidence_words=list(unsure))


def director(tmp_path, s=None):
    events = []

    async def emit(message):
        events.append(message)

    return ChemistryDirector(s or scenario(), "run_1", None, ChemistryStore(tmp_path), emit), events


# --------------------------------------------------------------------------- 1. body language

def test_every_dialect_has_body_language_norms_and_they_differ():
    for code in config.DIALECTS:
        n = config.norms(code)
        assert n.note and n.look_away_seconds > 0 and n.look_away_penalty > 0
    assert config.norms("ja-JP").look_away_seconds > config.norms("es-AR").look_away_seconds
    assert config.norms("ja-JP").look_away_penalty < config.norms("es-AR").look_away_penalty
    assert config.norms("hi-IN").head_wobble and not config.norms("es-MX").head_wobble
    assert "Body language where you live" in scenario(language="ja-JP").date_character.system_prompt


def wobble(tracker, roll_amplitude=8.0):
    kinds = []
    for i in range(14):
        roll = roll_amplitude if (i // 2) % 2 else -roll_amplitude
        kinds += [s.kind for s in tracker.face(FaceReading(found=True, roll=roll), i * 0.1, True)]
    return kinds


def test_the_head_wobble_is_read_only_where_it_means_yes():
    assert "wobble" in wobble(NonverbalTracker(head_wobble=True))
    assert "wobble" not in wobble(NonverbalTracker())
    t = NonverbalTracker(head_wobble=True)
    wobble(t)
    assert any("go on" in note for note in t.take_notes())


def test_the_judge_sees_the_norms_in_a_stable_cached_block():
    s = scenario(language="ja-JP")
    block = persona_context(s)
    assert config.norms("ja-JP").note in block and block == persona_context(s)


# --------------------------------------------------------------------------- 2. memory across dates

def test_a_missed_phrase_is_carried_to_the_next_date_and_credited_when_said(tmp_path):
    store = LearnerProfileStore(tmp_path / "learners")
    first = scenario()
    d, _ = director(tmp_path / "c1", first)
    line = "Yo soy muy contenta de estar acá."
    d.state.mistakes.append({"heard": "soy muy contenta", "better": "estoy muy contenta",
                             "why_en": "Feelings take estar."})
    verdict = asyncio.run(DateGrader().grade(first, d.state, [learner(line)], "run_1"))
    store.record(first, d.state, [learner(line)], verdict)
    targets = store.practice_targets("Arth", "es-AR")
    assert [t.better for t in targets] == ["estoy muy contenta"]
    assert store.practice_targets("Arth", "es-MX") == []

    second = scenario(practice=targets)
    assert second.practice[0].better == "estoy muy contenta"
    assert "estoy muy contenta" in second.date_character.system_prompt
    assert "Never say them first" in second.date_character.system_prompt
    d2, events = director(tmp_path / "c2", second)
    fixed_line = "¡Estoy muy contenta, che! ¿Y vos?"

    async def go():
        await d2.learner_turn([learner(fixed_line)], fixed_line, [])

    asyncio.run(go())
    assert d2.state.fixed == [{"better": "estoy muy contenta", "quote": fixed_line}]
    assert "right this time" in events[-1]["reason"]
    v2 = asyncio.run(DateGrader().grade(second, d2.state, [learner(fixed_line)], "run_2"))
    assert v2.progress[0].quote == fixed_line and "right this time" in v2.summary
    profile = store.record(second, d2.state, [learner(fixed_line)], v2)
    assert [p["status"] for p in profile["practice"]] == ["fixed"]
    assert len(profile["dates"]) == 2
    assert store.record(second, d2.state, [learner(fixed_line)], v2)["dates"][-1]["run_id"] == "run_2"
    assert len(store.get("Arth")["dates"]) == 2  # idempotent per run


def test_a_phrase_only_half_said_is_not_a_fix(tmp_path):
    s = scenario(practice=[PracticeTarget(heard="soy contenta", better="estoy muy contenta",
                                          why_en="estar")])
    d, _ = director(tmp_path, s)
    assert d.practice_hits("Estoy contenta") == []
    assert d.practice_hits("estoy muy contenta.")


def test_learner_keys_are_file_safe():
    assert learner_key("Arth") == "arth" and learner_key("  ") is None
    assert learner_key("小明").startswith("u_") and learner_key("José María") == "jose_maria"


# --------------------------------------------------------------------------- 3. misheard words

def test_no_correction_is_built_on_a_word_the_recogniser_doubted():
    transcript = [learner("Quiero un café de olla", unsure=["olla"]),
                  learner("Me gusta mucho la fotografía")]
    assert asr_suspect("café de olla", transcript)
    assert not asr_suspect("me gusta mucho", transcript)
    chosen = choose_correction([
        {"heard": "café de olla", "better": "un cafecito de olla", "why_en": "x"},
        {"heard": "me gusta mucho", "better": "me encanta", "why_en": "Warmer."}], transcript)
    assert chosen.heard == "me gusta mucho"
    assert choose_correction([{"heard": "café de olla", "better": "x", "why_en": ""}],
                             transcript) is None
    assert words_to_practise(transcript) == ["olla"]


# --------------------------------------------------------------------------- 4. fillers and register

def test_fillers_count_only_where_a_pause_is():
    assert count_fillers(["este", "o sea"], ["Este… no sé, o sea, me gusta.",
                                             "Me gusta este café."], True) == 2
    assert count_fillers(["えーと"], ["えーと、映画が好きです"], False) == 1
    habits = speech_habits("es-AR", ["Um, me gusta el rock.", "Este… sí."])
    assert habits["foreign_fillers"] == 1 and habits["local_fillers"] == 1


def test_register_tips_follow_the_dialect():
    assert speech_habits("es-AR", ["¿Tú eres de acá?"])["register_tip"].startswith("Porteños")
    formal = speech_habits("es-MX", ["¿Usted vive aquí?"])
    assert formal["register"] == "formal" and "usted" in formal["register_tip"]
    assert speech_habits("ja-JP", ["映画が好きです", "そうなんだ、すごいじゃん"])["register_tip"] is None
    assert speech_habits("fr-FR", ["Vous habitez ici ?", "Tu aimes le cinéma ?"])["register"] == "mixed"


def test_register_note_never_changes_a_grade(tmp_path):
    s = scenario(language="es-MX")
    d, _ = director(tmp_path, s)
    line = "¿Usted vive aquí? Me llamo Arth."
    verdict = asyncio.run(DateGrader().grade(s, d.state, [learner(line)], "run_1"))
    auth = next(p for p in verdict.pillars if p.id == "dialect_authenticity")
    assert "usted" in auth.comment and verdict.metrics.register_used == "formal"
    plain = asyncio.run(DateGrader().grade(s, d.state, [learner("Me llamo Arth, ¿y tú?")], "r2"))
    assert auth.grade == next(p for p in plain.pillars if p.id == "dialect_authenticity").grade


# --------------------------------------------------------------------------- 5. wrong-region slang

def test_other_region_slang_is_whole_words_and_never_local():
    assert other_region_words("es-AR", "¡Qué onda, güey!") == ["güey"]
    assert other_region_words("es-ES", "Buenas noches") == []          # "che" inside "noches"
    assert "güey" not in config.other_region_slang("es-MX")             # local there
    assert other_region_words("ja-JP", "なんでやねん！") == ["なんでやねん"]


def test_the_date_notices_slang_from_somewhere_else(tmp_path):
    d, events = director(tmp_path)
    line = "Me llamo Arth, güey."

    async def go():
        await d.learner_turn([learner(line)], line, [], other_region_words("es-AR", line))

    asyncio.run(go())
    assert d.state.other_region == ["güey"] and "sounds like Mexico" in events[-1]["reason"]


# --------------------------------------------------------------------------- 6. cultural moments

@pytest.mark.parametrize("code", sorted(config.DIALECTS))
def test_every_date_carries_its_local_moment(code):
    s = scenario(language=code)
    vibe = next(m for m in s.milestones if m.id == "cultural_vibe")
    assert s.cultural_moment is not None and vibe.text == s.cultural_moment.milestone
    assert vibe.evidence_required.startswith("Either:")
    assert [m.id for m in s.milestones] == ["break_ice", "find_common_ground", "cultural_vibe",
                                           "close_the_date"]


def test_the_offline_judge_ticks_the_moment_with_the_learners_words():
    s = scenario(language="es-MX")
    line = "Me encanta el picante, ¡pásame la salsa!"
    ctx = JudgeContext(s, [learner(line)], line, ["cultural_vibe"], [], False)
    j = asyncio.run(RulesChemistryJudge().judge(ctx))
    assert [(t.id, t.check, t.evidence_quote) for t in j.milestones] == \
        [("cultural_vibe", "the local moment", line)]


def test_the_cue_reaches_the_date_once_after_the_ice_is_broken():
    session = stream_gateway.StreamSession(ws=None, state=None)
    session.scenario = scenario()
    session.director = SimpleNamespace(state=SimpleNamespace(score=50))
    session.running, session.started_at = True, time.monotonic() - 10
    assert not any("natural moment" in n for n in session._notes("date_npc"))
    session.started_at = time.monotonic() - 70
    assert any("mate" in n for n in session._notes("date_npc"))
    assert not any("natural moment" in n for n in session._notes("date_npc"))


# --------------------------------------------------------------------------- 7. self-play scorer

def test_selfplay_scores_false_awards_for_adversarial_learners():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "eval"))
    import date_selfplay

    verdict = {"milestones": [{"id": "break_ice", "achieved": True,
                               "evidence_quote": "¿Y vos de qué laburás?"}],
               "followup": {"correction": None}, "final_chemistry": 60, "metrics": {}}
    echo = {"behaviour": "echo", "said": ["¿Y vos de qué laburás?"], "verdict": verdict}
    assert date_selfplay.score(echo)["false_awards"] == ["break_ice: awarded to a echo learner"]
    engaged = {**echo, "behaviour": "engaged"}
    assert date_selfplay.score(engaged)["false_awards"] == []
    never = {**engaged, "said": ["hola"]}
    assert date_selfplay.score(never)["false_awards"] == ["break_ice: quote never said"]


# --------------------------------------------------------------------------- 8. costs and plans

def test_claude_calls_are_cached_and_charged_to_the_running_ledger():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        body = {"id": "m", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
                "content": [{"type": "text", "text": json.dumps({"a": "x"})}],
                "stop_reason": "end_turn", "stop_sequence": None,
                "usage": {"input_tokens": 100, "output_tokens": 50,
                          "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 0}}
        return httpx2.Response(200, json=body)

    from pydantic import BaseModel

    class Out(BaseModel):
        a: str

    client = anthropic.AsyncAnthropic(api_key="k", http_client=anthropic.DefaultAsyncHttpxClient(
        transport=httpx2.MockTransport(handler)))
    with costs.charging(costs.Ledger()) as ledger:
        asyncio.run(Claude(client=client).parse(model="claude-sonnet-5-5",
                                                system=["rules", "persona"], payload={},
                                                schema=Out))
    assert [b["text"] for b in seen["system"]] == ["rules", "persona"]
    assert seen["system"][-1]["cache_control"] == {"type": "ephemeral"}
    report = ledger.report()
    line = report.lines[0]
    assert (line.provider, line.input_tokens, line.cache_read_tokens) == ("claude", 100, 1000)
    # 100 x $2 + 50 x $10 + 1000 x $0.20, per million tokens.
    assert report.total_usd == pytest.approx(0.0009) and report.complete


def test_unpriced_providers_report_usage_without_inventing_dollars(monkeypatch):
    ledger = costs.Ledger()
    ledger.add("deepgram", "nova-3", calls=1, audio_seconds=90)
    report = ledger.report()
    assert report.lines[0].usd is None and report.total_usd is None and not report.complete
    monkeypatch.setenv("DEEPGRAM_PRICE_PER_MINUTE", "0.01")
    assert ledger.report().total_usd == pytest.approx(0.015)


def test_the_free_plan_runs_the_judge_on_rules(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert create_judge() is not None
    monkeypatch.setenv("PLAN", "free")
    assert create_judge() is None and config.plan() == "free"


# --------------------------------------------------------------------------- 9. voice cache

class FakeFish:
    name, model, sample_rate = "fish", "s2.1-pro", 24000

    def __init__(self):
        self.calls = 0

    async def speak(self, sentences, voice, language):
        self.calls += 1
        async for _sentence in sentences:
            for frame in frames(b"\x01\x00" * 4800):
                yield frame

    async def prewarm(self):
        return None

    async def aclose(self):
        return None


def test_a_scripted_line_is_voiced_once_then_played_from_the_cache(tmp_path):
    voice = Voice(cache=VoiceCache(tmp_path))
    fish = voice.primary = FakeFish()
    config_ = VoiceConfig(provider="fish", voice_id="v", speaking_rate=1.0, temperature=0.7,
                          latency="balanced")

    async def say(text):
        async def lines():
            yield text
        return [f async for f in voice.speak(lines(), config_, "es-AR", cache_text=text)]

    first = asyncio.run(say("¡Hola! Bienvenida."))
    second = asyncio.run(say("¡Hola! Bienvenida."))
    assert fish.calls == 1 and b"".join(first) == b"".join(second)
    asyncio.run(say("Otra línea."))
    assert fish.calls == 2


def test_a_line_cut_short_is_never_cached(tmp_path):
    voice = Voice(cache=VoiceCache(tmp_path))
    voice.primary = FakeFish()
    config_ = VoiceConfig(provider="fish", voice_id="v", speaking_rate=1.0, temperature=0.7,
                          latency="balanced")

    async def interrupted():
        async def lines():
            yield "Una línea larga."
        stream = voice.speak(lines(), config_, "es-AR", cache_text="Una línea larga.")
        await stream.__anext__()
        await stream.aclose()

    asyncio.run(interrupted())
    assert not list(tmp_path.rglob("*.pcm"))


# --------------------------------------------------------------------------- 10. pages and reports

def until(ws, kind, limit=4000):
    for _ in range(limit):
        message = ws.receive()
        if message.get("bytes") is not None:
            continue
        data = json.loads(message["text"])
        if data["type"] == kind:
            return data
    raise AssertionError(f"no {kind}")


def test_a_graded_date_gets_a_card_a_profile_and_a_cost(tmp_path):
    with TestClient(create_app(data_dir=tmp_path, runs_dir=tmp_path / "runs",
                               face_tracking=False)) as client:
        body = MatchmakerRequest(learner_name="Arth <b>", language="es-AR").model_dump()
        date = client.post("/v1/matchmaker/generate", json=body).json()
        sid = date["scenario_id"]
        assert date["cultural_moment"]["id"] == "mate"
        with client.websocket_connect("/v1/stream") as ws:
            ws.send_text(json.dumps({"type": "init", "run_id": "run_c", "scenario_id": sid}))
            until(ws, "session_ready")
            ws.send_text(json.dumps({"type": "start_date"}))
            until(ws, "audio_end")
            ws.send_text(json.dumps({"type": "user_text",
                                     "text": "Hola, me llamo Arth, güey. ¿Y vos qué hacés?"}))
            update = until(ws, "chemistry_update")
            assert "Mexico" in update["reason"]
            ws.send_text(json.dumps({"type": "end_date", "reason": "timer"}))
            until(ws, "date_ended")
        verdict = client.post("/v1/grade", json={"run_id": "run_c", "scenario_id": sid}).json()
        assert verdict["metrics"]["other_region_words"] == ["güey"]
        assert verdict["cost"]["complete"] is True

        card = client.get("/v1/date/runs/run_c/card")
        assert card.status_code == 200 and verdict["stamp"] in card.text
        assert "Parry" in card.text and "og:title" in card.text
        assert client.get("/v1/date/runs/run_c/verdict").json()["run_id"] == "run_c"
        assert client.get("/v1/date/runs/nope/card").status_code == 404

        profile = client.get("/v1/learners/Arth <b>").json()
        assert profile["dates"][0]["run_id"] == "run_c"
        report = client.get("/v1/reports/class")
        assert "Arth &lt;b&gt;" in report.text and "<b>" not in report.text.split("<tbody>")[1]
        rows = client.get("/v1/reports/class?format=json").json()["learners"]
        assert rows[0]["dates"] == 1
        assert client.get("/v1/costs").json()["plan"] == "pro"
        assert client.get("/health").json()["date"]["plan"] == "pro"
        assert "costs" in client.get("/v1/metrics").json()
        assert "cost" in client.get("/v1/date/runs/run_c").json()


def test_the_card_escapes_the_learners_words(tmp_path):
    s = scenario()
    d, _ = director(tmp_path, s)
    line = "Me llamo <script>alert(1)</script>"
    d.state.milestones["break_ice"] = line
    verdict = asyncio.run(DateGrader().grade(s, d.state, [learner(line)], "run_x"))
    html = card_html(verdict).body.decode()
    assert "<script>" not in html and "&lt;script&gt;" in html
