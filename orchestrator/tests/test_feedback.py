import asyncio
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestrator.brain_routes import build_router
from orchestrator.feedback import Draft, FeedbackService, create_feedback_service, tutor_input
from orchestrator.grading import TranscriptStore
from orchestrator.models import RubricGoal, TranscriptTurn

RUBRIC = [RubricGoal(id=i, npc_id="maria", core=core, label=i.title(), evidence_required="x")
          for i, core in (("introduce", True), ("order", True), ("price", True), ("chat", False))]
TRANSCRIPT = [
    TranscriptTurn(role="learner", npc_id="maria", text="Hola, me llamo Ana"),
    TranscriptTurn(role="npc", npc_id="maria", text="¿Qué te doy? Tengo la concha rica."),
    TranscriptTurn(role="learner", npc_id="maria", text="Yo quiero el concha y un café de olla",
                   low_confidence_words=["olla,"]),
    TranscriptTurn(role="learner", npc_id="maria", text="Una olla más",
                   low_confidence_words=["olla", "más"]),
    TranscriptTurn(role="event", npc_id="maria", text="serve_order items=concha"),
]
INSIGHTS = {"achieved": [{"id": "introduce", "evidence_quote": "me llamo Ana"}],
            "mistakes": [{"quote": "el concha", "correction": "la concha", "severity": 2,
                          "category": "gender_agreement", "explanation_en": "x",
                          "asr_suspect": False},
                         {"quote": "un café", "correction": "x", "severity": 1, "category": "other",
                          "explanation_en": "x", "asr_suspect": True}],
            "states": [{"turn": 1, "state": "fine"}], "notes": [],
            "counters": {"english_turns": 1, "repair_phrases": 0, "hints": 2}}


def fix(heard, severity, better="mejor"):
    return {"heard": heard, "better": better, "why_en": "why", "category": "other",
            "severity": severity}


def draft(**changes):
    return Draft.model_validate({
        "goals": [{"id": "introduce", "done": False, "evidence": None},
                  {"id": "order", "done": True, "evidence": "Yo quiero el concha"},
                  {"id": "price", "done": True, "evidence": "Tengo la concha rica"},
                  {"id": "chat", "done": True, "evidence": None}],
        "fixes": [fix("Hola, me", 1), fix("el concha", 2, "la concha"), fix("la concha rica", 3),
                  fix("café de olla", 3), fix("un café", 2), fix("Yo quiero", 1),
                  fix("me llamo", 1)],
        "useful_phrases": [{"es": "¿Me da…?", "en": "Can I have…?", "when": "Ordering"}],
        "went_well": {"quote": "me llamo Ana", "note": "Clear <introduction>."},
        "practice_words": ["Olla", "pizza"], "next_visit": "Ask the price.",
        "summary": "You ordered."} | changes)


class Tutor:
    def __init__(self, written=None, heard=None):
        self.written = written or draft()
        self.heard = heard
        self.listened = []

    async def write(self, rubric, transcript, insights, level):
        return self.written

    async def listen(self, wav, text):
        self.listened.append(text)
        if self.heard is None:
            raise RuntimeError("audio model down")
        return self.heard


def service(tmp_path, tutor):
    return FeedbackService(tutor, tmp_path / "feedback", tmp_path / "audio")


def test_report_keeps_only_what_the_learner_said_and_we_heard_clearly(tmp_path):
    report = asyncio.run(service(tmp_path, Tutor()).report("visit-1", RUBRIC, TRANSCRIPT, INSIGHTS))
    # Ticked live, judged with the learner's words, quoted from Maria (no), no quote (no).
    assert [(g.id, g.done) for g in report.goals] == [("introduce", True), ("order", True),
                                                      ("price", False), ("chat", False)]
    assert report.goals[0].evidence == "me llamo Ana"
    assert (report.result, report.stars) == ("partial", 2)
    # Severity order, capped at three; Maria's words, doubted words and suspect mistakes gone.
    assert [f.heard for f in report.fixes] == ["el concha", "Hola, me", "Yo quiero"]
    assert report.practice_words == ["olla"]
    assert report.counters == {"english_turns": 1, "repair_phrases": 0, "hints": 2,
                               "learner_turns": 3}
    assert report.pronunciation is None

    page = (tmp_path / "feedback" / "visit-1.html").read_text(encoding="utf-8")
    assert report.html_path.endswith("visit-1.html")
    assert "What we heard" in page and "what you said" not in page.lower()
    assert "Clear &lt;introduction&gt;." in page and "la concha" in page
    saved = json.loads((tmp_path / "feedback" / "visit-1.json").read_text(encoding="utf-8"))
    assert saved["result"] == "partial" and saved["html_path"] == report.html_path


def test_result_and_a_quote_the_learner_never_said(tmp_path):
    tutor = Tutor(draft(went_well={"quote": "Quisiera un café", "note": "Polite."}, fixes=[]))
    report = asyncio.run(service(tmp_path, tutor).report("visit-1", RUBRIC[:2], TRANSCRIPT, INSIGHTS))
    assert (report.result, report.stars, report.went_well, report.fixes) == ("pass", 3, None, [])
    empty = {"achieved": [], "mistakes": []}
    tutor = Tutor(draft(goals=[]))
    report = asyncio.run(service(tmp_path, tutor).report("visit-2", RUBRIC, TRANSCRIPT, empty))
    assert (report.result, report.stars) == ("retry", 0)
    assert report.counters["hints"] == 0


def clips(tmp_path, run_id="visit-1"):
    folder = tmp_path / "audio" / run_id
    folder.mkdir(parents=True)
    for turn, logprob, text in ((1, -0.1, "Hola"), (2, -2.5, "Yo quiero el concha"),
                                (3, -0.9, "Una olla más"), (4, -1.5, "Gracias"), (5, -9, "lost")):
        (folder / f"turn_{turn:03d}.json").write_text(json.dumps(
            {"text": text, "npc_id": "maria", "low_confidence_words": [], "min_logprob": logprob}))
        if turn != 5:  # a sidecar without its clip is skipped
            (folder / f"turn_{turn:03d}.wav").write_bytes(b"RIFF")
    (folder / "turn_006.json").write_text("{not json")


def test_pronunciation_listens_to_the_least_certain_clips(tmp_path, monkeypatch):
    clips(tmp_path)
    tutor = Tutor(heard={"problem_words": ["Quiero", "pizza", "quiero"], "impression": "Roll it."})
    report = asyncio.run(service(tmp_path, tutor).report("visit-1", RUBRIC, TRANSCRIPT, INSIGHTS))
    assert sorted(tutor.listened) == ["Gracias", "Una olla más", "Yo quiero el concha"]
    assert [i.turn for i in report.pronunciation.impressions] == [2, 3, 4]
    # "pizza" was never said; "quiero" only in one of the clips.
    assert [i.problem_words for i in report.pronunciation.impressions] == [["Quiero"], [], []]
    assert "not a score" in report.pronunciation.disclaimer
    assert "coach's impressions" in (tmp_path / "feedback" / "visit-1.html").read_text("utf-8")

    monkeypatch.setenv("PRONUNCIATION", "0")
    quiet = Tutor(heard={"problem_words": [], "impression": "x"})
    report = asyncio.run(service(tmp_path, quiet).report("visit-1", RUBRIC, TRANSCRIPT, INSIGHTS))
    assert report.pronunciation is None and quiet.listened == []


def test_a_failed_pronunciation_pass_never_fails_the_report(tmp_path):
    clips(tmp_path)
    report = asyncio.run(service(tmp_path, Tutor()).report("visit-1", RUBRIC, TRANSCRIPT, INSIGHTS))
    assert report.pronunciation is None and report.summary == "You ordered."


def test_tutor_never_sees_suspect_mistakes():
    body = tutor_input(RUBRIC, TRANSCRIPT, INSIGHTS, "A2")[1]["content"]
    assert '"el concha"' in body and '"un café"' not in body
    assert "(unsure: olla,)" in body and '"olla": 2' in body


def test_feedback_route(tmp_path, monkeypatch):
    from orchestrator.scene import ScenePack, default_pack_dir
    app = FastAPI()
    app.include_router(build_router())
    app.state.transcripts = TranscriptStore(tmp_path / "runs")
    app.state.director = app.state.coach = app.state.grader = None
    app.state.pack = ScenePack.load(default_pack_dir())
    app.state.feedback = service(tmp_path, Tutor())
    http = TestClient(app)
    assert http.post("/v1/feedback", json={"run_id": "nobody"}).status_code == 404
    app.state.transcripts.append("visit-1", TRANSCRIPT)
    result = http.post("/v1/feedback", json={"run_id": "visit-1", "scenario_id": None})
    assert result.status_code == 200
    body = result.json()
    assert [g["id"] for g in body["goals"]] == [g.id for g in app.state.pack.scenario.goals]
    assert body["fixes"][0]["heard"] == "el concha" and body["html_path"]
    app.state.feedback = None
    assert http.post("/v1/feedback", json={"run_id": "visit-1"}).status_code == 503
    for key in ("OPENAI_API_KEY", "TUTOR_MODEL", "SCENARIO_MODEL"):
        monkeypatch.delenv(key, raising=False)
    assert create_feedback_service() is None
