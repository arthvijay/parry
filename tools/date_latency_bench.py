"""Latency benchmark for the speed date, against a running server.

Measures every wait a learner can feel, per stage, over several turns of both demo
dates, and writes a JSON file and a Markdown table to runs/bench/.

    uv run python tools/date_latency_bench.py                       # server on :8765
    uv run python tools/date_latency_bench.py --url http://127.0.0.1:8790 --turns 6
    uv run python tools/date_latency_bench.py --tts-probe 3         # + ElevenLabs first audio

What is timed (all wall clock at the client unless marked "server"):

- **Turn, typed:** line sent → first sentence of the reply written (the brain) → first
  voice frame (`audio_start`; the server's own `first_audio_ms` too) → chemistry update.
- **Turn, spoken:** learner audio streamed in real time; from the end of the speech to the
  voice detector closing it, to the final transcript, to the first voice frame. This is
  the number the learner feels.
- **Barge-in:** `barge_in` sent → `clear_audio` back.
- **Wingman (W), translator (T), closing line, verdict, report, matchmaker, presets.**
- **Face tracking:** one webcam-sized JPEG → `face_analysis` (round trip and server time).
- **--tts-probe:** ElevenLabs time to first audio frame, cold and on a pre-warmed socket,
  through the same class the server uses (a few short lines, so few credits).

Learner speech is synthesised offline with espeak-ng (falls back to tools/sample_es.mp3).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import shutil
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DEMOS = {
    "cafe_cancun_ar": {
        "voice": "es-419",
        "typed": ["Hola, me llamo Arth. Soy ingeniero y me encanta bucear. ¿Vos sacás fotos bajo el agua?",
                  "¡Qué copado! Yo buceo los fines de semana. ¿Cuál es tu arrecife favorito?",
                  "Dale, pidamos unas medialunas para compartir y un cortado.",
                  "¿Extrañás Buenos Aires? Yo nunca fui, pero me encantaría.",
                  "Me caés re bien, che. ¿Me pasás tu WhatsApp?",
                  "Posta, ¿y qué música escuchás últimamente?"],
        "spoken": ["Hola, me llamo Arth y me encanta la fotografía.",
                   "Dale, pedimos un cortado y unas medialunas."],
    },
    "cafe_cancun_south": {
        "voice": "en-us",
        "typed": ["Hey Savannah, I'm Arth. I'm an engineer and I love diving. Do you shoot underwater?",
                  "That's awesome. What's the prettiest reef you've ever shot?",
                  "Let's get some medialunas to share and a couple of lattes.",
                  "Do you miss Georgia? I've never been, but I'd love to go.",
                  "I'm having a real good time. Can I get your number?",
                  "So what music have you got on repeat right now?"],
        "spoken": ["Hey, my name is Arth and I love photography.",
                   "Let's order some coffee and medialunas."],
    },
}


def stats(values: list[float]) -> dict:
    v = sorted(x for x in values if x is not None)
    if not v:
        return {"n": 0}
    p90 = v[min(len(v) - 1, round(0.9 * (len(v) - 1)))]
    return {"n": len(v), "p50": round(statistics.median(v)), "p90": round(p90),
            "min": round(v[0]), "max": round(v[-1])}


def speech_pcm(text: str, voice: str) -> bytes:
    """16 kHz PCM16 mono of `text`, with its trailing silence trimmed."""
    espeak, ffmpeg = shutil.which("espeak-ng"), shutil.which("ffmpeg")
    if espeak and ffmpeg:
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "a.wav"
            subprocess.run([espeak, "-v", voice, "-s", "150", "-w", str(wav), text], check=True,
                           capture_output=True)
            out = subprocess.run([ffmpeg, "-v", "error", "-i", str(wav), "-af",
                                  "areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse",
                                  "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                                 capture_output=True, check=True)
            return out.stdout
    out = subprocess.run([ffmpeg or "ffmpeg", "-v", "error", "-i", str(ROOT / "tools" / "sample_es.mp3"),
                          "-f", "s16le", "-ac", "1", "-ar", "16000", "-"], capture_output=True, check=True)
    return out.stdout


class Session:
    """One /v1/stream connection with a timestamped inbox."""

    def __init__(self, ws):
        self.ws = ws
        self.inbox: list[tuple[float, dict]] = []
        self.task = asyncio.create_task(self._read())

    async def _read(self):
        async for raw in self.ws:
            if isinstance(raw, str):
                self.inbox.append((time.monotonic(), json.loads(raw)))

    async def send(self, message: dict):
        await self.ws.send(json.dumps(message))

    async def wait(self, kind: str, after: float, timeout: float = 40.0, where=None) -> tuple[float, dict] | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for t, m in self.inbox:
                if t >= after and m.get("type") == kind and (where is None or where(m)):
                    return t, m
            await asyncio.sleep(0.005)
        return None

    async def idle(self, after: float):
        """Wait until the reply is fully sent and the chemistry judge has answered."""
        await self.wait("audio_end", after, 40)
        await self.wait("chemistry_update", after, 25)
        await asyncio.sleep(0.4)


def ms(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else (b - a) * 1000


async def bench_demo(url: str, preset: str, turns: int, spoken: int, barge: int) -> dict:
    from websockets.asyncio.client import connect
    demo = DEMOS[preset]
    r: dict[str, list] = {k: [] for k in (
        "typed_first_sentence", "typed_first_audio", "typed_first_audio_server", "typed_chemistry",
        "spoken_vad_close", "spoken_final_transcript", "spoken_first_audio", "barge_in_clear",
        "wingman_on_demand", "translator_card", "host_greeting_audio", "opening_line_audio",
        "session_ready", "closing_line", "preset")}
    providers = {}
    async with httpx.AsyncClient(base_url=url, timeout=120) as http:
        t = time.monotonic()
        date = (await http.post("/v1/matchmaker/preset", json={"preset": preset, "learner_name": "Arth",
                                                              "date_gender": "female"})).json()
        r["preset"].append(ms(t, time.monotonic()))
        run_id = f"bench_{preset}_{int(time.time())}"
        async with connect(url.replace("http", "ws") + "/v1/stream", max_size=2 ** 24) as ws:
            s = Session(ws)
            t = time.monotonic()
            await s.send({"type": "init", "run_id": run_id, "scenario_id": date["scenario_id"],
                          "npc_id": "host"})
            got = await s.wait("session_ready", t)
            r["session_ready"].append(ms(t, got[0]))
            providers = got[1]["providers"]
            t = time.monotonic()
            await s.send({"type": "focus", "npc_id": "host"})
            got = await s.wait("audio_start", t)
            r["host_greeting_audio"].append(ms(t, got and got[0]))
            await s.wait("audio_end", t)
            t = time.monotonic()
            await s.send({"type": "start_date"})
            got = await s.wait("audio_start", t, where=lambda m: m.get("kind") == "opening")
            r["opening_line_audio"].append(ms(t, got and got[0]))
            await s.idle(t)

            for line in (demo["typed"] * 3)[:turns]:
                t = time.monotonic()
                await s.send({"type": "user_text", "text": line})
                text = await s.wait("transcript", t, where=lambda m: m.get("speaker") not in ("user", None))
                start = await s.wait("audio_start", t, where=lambda m: m.get("kind") == "reply")
                chem = await s.wait("chemistry_update", t, 25)
                r["typed_first_sentence"].append(ms(t, text and text[0]))
                r["typed_first_audio"].append(ms(t, start and start[0]))
                r["typed_first_audio_server"].append(start and start[1].get("first_audio_ms"))
                r["typed_chemistry"].append(ms(t, chem and chem[0]))
                await s.idle(t)

            for line in demo["spoken"][:spoken]:
                pcm = speech_pcm(line, demo["voice"])
                mark = time.monotonic()
                for i in range(0, len(pcm), 640):
                    await ws.send(pcm[i:i + 640])
                    await asyncio.sleep(0.02)
                speech_end = time.monotonic()
                # An open mic keeps sending silence until the reply starts.
                start = None
                for _ in range(400):
                    await ws.send(b"\x00\x00" * 320)
                    await asyncio.sleep(0.02)
                    start = await s.wait("audio_start", speech_end, 0,
                                         where=lambda m: m.get("kind") == "reply")
                    if start:
                        break
                vad = await s.wait("user_speech", mark, 0, where=lambda m: m.get("speaking") is False)
                final = await s.wait("transcript", mark, 0,
                                     where=lambda m: m.get("speaker") == "user" and m.get("is_final"))
                r["spoken_vad_close"].append(ms(speech_end, vad and vad[0]))
                r["spoken_final_transcript"].append(ms(speech_end, final and final[0]))
                r["spoken_first_audio"].append(ms(speech_end, start and start[0]))
                if final:
                    r.setdefault("heard", []).append(final[1]["text"])
                await s.idle(speech_end)

            for _ in range(barge):
                t = time.monotonic()
                await s.send({"type": "user_text", "text": demo["typed"][1]})
                start = await s.wait("audio_start", t, where=lambda m: m.get("kind") == "reply")
                await asyncio.sleep(0.3)
                t = time.monotonic()
                await s.send({"type": "barge_in", "timestamp_ms": 1})
                got = await s.wait("clear_audio", t, 5)
                r["barge_in_clear"].append(ms(t, got and got[0]))
                await asyncio.sleep(1.0)

            for _ in range(2):
                t = time.monotonic()
                await s.send({"type": "wingman"})
                got = await s.wait("wingman_hint", t, 20)
                r["wingman_on_demand"].append(ms(t, got and got[0]))
                t = time.monotonic()
                await s.send({"type": "help"})
                got = await s.wait("help_card", t, 20)
                r["translator_card"].append(ms(t, got and got[0]))

            t = time.monotonic()
            await s.send({"type": "end_date", "reason": "quit"})
            got = await s.wait("date_ended", t, 40)
            r["closing_line"].append(ms(t, got and got[0]))
            s.task.cancel()

        t = time.monotonic()
        grade = await http.post("/v1/grade", json={"run_id": run_id, "scenario_id": date["scenario_id"]})
        r["verdict"] = [ms(t, time.monotonic())] if grade.status_code == 200 else []
        t = time.monotonic()
        report = await http.post("/v1/date/report", json={"run_id": run_id, "scenario_id": date["scenario_id"]},
                                 timeout=180)
        r["report"] = [ms(t, time.monotonic())] if report.status_code == 200 else []
    heard = r.pop("heard", [])
    return {"preset": preset, "providers": providers, "heard": heard,
            "stages": {k: stats(v) for k, v in r.items()}}


async def bench_face(url: str, image: Path, frames: int) -> dict:
    from websockets.asyncio.client import connect
    jpeg = base64.b64encode(image.read_bytes()).decode()
    rtt, server = [], []
    async with connect(url.replace("http", "ws") + "/v1/vision") as ws:
        json.loads(await ws.recv())
        for _ in range(frames):
            t = time.monotonic()
            await ws.send(json.dumps({"type": "face_frame", "jpeg_base64": jpeg}))
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), 20))
                if m.get("type") == "face_analysis":
                    break
            rtt.append(ms(t, time.monotonic()))
            if m.get("found"):
                server.append(m.get("analysis_ms"))
    return {"face_round_trip": stats(rtt), "face_server_analysis": stats(server)}


async def bench_matchmaker(url: str) -> dict:
    async with httpx.AsyncClient(base_url=url, timeout=120) as http:
        t = time.monotonic()
        res = await http.post("/v1/matchmaker/generate", json={
            "learner_name": "Arth", "language": "es-AR", "proficiency": "B1", "venue_style": "auto",
            "date_gender": "female", "date_ethnicity": "latina", "personality_archetype": "playful_sarcastic",
            "custom_notes": "loves diving", "scene_prompt": "a beachfront café at sunset"})
        return {"matchmaker_generate": stats([ms(t, time.monotonic())] if res.status_code == 200 else []),
                "generated_by": res.json().get("generated_by") if res.status_code == 200 else None}


async def bench_tts(count: int) -> dict:
    """ElevenLabs first audio frame through the server's own class: cold, then warm."""
    import os
    import sys
    sys.path.insert(0, str(ROOT))
    from dotenv import load_dotenv
    load_dotenv(ROOT / "orchestrator" / ".env")
    from orchestrator import config
    from orchestrator.date_models import VoiceConfig
    from orchestrator.tts import ElevenLabsVoice
    p = config.providers()
    if not p.elevenlabs_key:
        return {}
    tts = ElevenLabsVoice(p.elevenlabs_key, os.getenv("ELEVENLABS_TTS_MODEL") or p.elevenlabs_model)
    voice = VoiceConfig(provider="elevenlabs", voice_id=config.ELEVENLABS_DEFAULT_VOICES["female"],
                        stability=0.4, similarity_boost=0.8, speaking_rate=1.0)
    cold, warm, errors = [], [], []
    for i, text in enumerate(["Hola, che.", "¿Todo bien?", "Dale."][:count]):
        async def one(line=text):
            yield line
        if i > 0:
            await tts.prewarm(voice)
            await asyncio.sleep(1.0)  # the learner is still talking while the socket opens
        t = time.monotonic()
        try:
            async for _ in tts.speak(one(), voice, "es"):
                (warm if i else cold).append(ms(t, time.monotonic()))
                break
        except Exception as error:  # noqa: BLE001
            errors.append(f"{type(error).__name__}: {str(error)[:120]}")
    await tts.aclose()
    return {"tts_first_audio_cold": stats(cold), "tts_first_audio_warm": stats(warm), "tts_errors": errors}


LABELS = [
    ("spoken_first_audio", "Spoken turn: end of your speech → first voice frame (the felt latency)"),
    ("spoken_vad_close", "Spoken turn: end of speech → voice detector closes the turn"),
    ("spoken_final_transcript", "Spoken turn: end of speech → final transcript (Nemotron/Parakeet)"),
    ("typed_first_sentence", "Typed turn: line sent → first sentence written (Claude)"),
    ("typed_first_audio", "Typed turn: line sent → first voice frame"),
    ("typed_first_audio_server", "Typed turn: first_audio_ms reported by the server"),
    ("typed_chemistry", "Chemistry meter update after a turn (Claude judge)"),
    ("barge_in_clear", "Barge-in: barge_in → clear_audio"),
    ("wingman_on_demand", "Wingman card on W"),
    ("translator_card", "Translator card on T"),
    ("host_greeting_audio", "Host greeting: focus → first voice frame"),
    ("opening_line_audio", "Date opening line: start_date → first voice frame"),
    ("closing_line", "End of date: end_date → date_ended (closing line spoken)"),
    ("verdict", "Verdict receipt (Claude grader)"),
    ("report", "Learning report (Claude + pronunciation)"),
    ("session_ready", "Stream join: init → session_ready"),
    ("preset", "Demo date built: POST /v1/matchmaker/preset"),
]


def markdown(result: dict) -> str:
    lines = [f"Run {result['when']} · {result['turns']} typed + {result['spoken']} spoken turns per demo · "
             f"server {result['url']}", ""]
    for demo in result["demos"]:
        p = demo["providers"]
        lines += [f"**{demo['preset']}** (brain {p.get('brain')}, stt {p.get('stt')}, tts {p.get('tts')}, "
                  f"judge {p.get('judge')}, face {p.get('face')})", "",
                  "| Stage | p50 ms | p90 ms | min | max | n |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for key, label in LABELS:
            st = demo["stages"].get(key, {"n": 0})
            if st.get("n"):
                lines.append(f"| {label} | {st['p50']} | {st['p90']} | {st['min']} | {st['max']} | {st['n']} |")
        if demo.get("heard"):
            lines.append("")
            lines.append("Heard: " + " · ".join(f"“{h}”" for h in demo["heard"]))
        lines.append("")
    other = result.get("other", {})
    lines += ["**Other**", "", "| Stage | p50 ms | p90 ms | min | max | n |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for key, label in [("matchmaker_generate", "Custom date written by the matchmaker (Claude)"),
                       ("face_round_trip", "Face tracking: JPEG → face_analysis, round trip"),
                       ("face_server_analysis", "Face tracking: MediaPipe time on the server"),
                       ("tts_first_audio_cold", "ElevenLabs first audio frame, cold socket"),
                       ("tts_first_audio_warm", "ElevenLabs first audio frame, pre-warmed socket")]:
        st = other.get(key, {"n": 0})
        if st.get("n"):
            lines.append(f"| {label} | {st['p50']} | {st['p90']} | {st['min']} | {st['max']} | {st['n']} |")
    if other.get("tts_errors"):
        lines += ["", "ElevenLabs errors: " + "; ".join(other["tts_errors"])]
    return "\n".join(lines) + "\n"


async def main_async(args) -> dict:
    result = {"when": time.strftime("%Y-%m-%d %H:%M"), "url": args.url, "turns": args.turns,
              "spoken": args.spoken, "demos": [], "other": {}}
    for preset in args.presets:
        print(f"benchmarking {preset}…", flush=True)
        result["demos"].append(await bench_demo(args.url, preset, args.turns, args.spoken, args.barge))
    print("benchmarking face tracking and the matchmaker…", flush=True)
    result["other"].update(await bench_face(args.url, Path(args.face), args.frames))
    result["other"].update(await bench_matchmaker(args.url))
    if args.tts_probe:
        print("probing ElevenLabs…", flush=True)
        result["other"].update(await bench_tts(args.tts_probe))
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--presets", nargs="+", default=list(DEMOS))
    ap.add_argument("--turns", type=int, default=6)
    ap.add_argument("--spoken", type=int, default=2)
    ap.add_argument("--barge", type=int, default=3)
    ap.add_argument("--frames", type=int, default=30)
    ap.add_argument("--face", default=str(ROOT / "tools" / "bench_face.jpg"))
    ap.add_argument("--tts-probe", type=int, default=0, help="ElevenLabs probes (each a few credits)")
    args = ap.parse_args()
    result = asyncio.run(main_async(args))
    out = ROOT / "runs" / "bench"
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    (out / f"date_latency_{stamp}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    table = markdown(result)
    (out / f"date_latency_{stamp}.md").write_text(table)
    print("\n" + table)


if __name__ == "__main__":
    main()
