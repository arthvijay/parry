"""Headless end-to-end check of the speed date against a real running server.

Starts the orchestrator on a free port (or uses --url), then:

1. POST /v1/matchmaker/generate in every dialect, and checks each date is complete.
2. Opens /v1/stream for one date: host greeting, start_date, streams the sample voice
   as microphone audio (so live recognition is exercised when DEEPGRAM_API_KEY is set),
   sends telemetry every 250 ms, waits for the wingman after a silence, answers by
   text, barges in on the reply, looks away mid-line, and ends the date.
3. POST /v1/grade for the run and checks the verdict receipt.

Prints one line per check with timings and exits non-zero on any failure.

    uv run python tools/test_e2e_pipeline.py              # with whatever keys .env has
    uv run python tools/test_e2e_pipeline.py --offline    # no provider keys at all
    uv run python tools/test_e2e_pipeline.py --url http://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
PROVIDER_KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY",
                 "GOOGLE_CLOUD_PROJECT", "DEEPGRAM_API_KEY", "FISH_AUDIO_API_KEY",
                 "OPENAI_API_KEY", "ELEVENLABS_API_KEY")
DIALECTS = ("es-MX", "es-AR", "es-ES", "zh-CN", "hi-IN", "ja-JP", "ja-JP-kansai", "fr-FR")
ANSWERS = {
    "es-AR": "Hola, me llamo Arth, che. Soy fotógrafo y me encanta el rock indie. ¿Y vos qué hacés?",
}

results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = ""):
    results.append((ok, name, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(offline: bool, runs: Path) -> tuple[subprocess.Popen, str]:
    port = free_port()
    env = dict(os.environ)
    if not offline:
        from dotenv import dotenv_values
        for path in (ROOT / "orchestrator" / ".env", ROOT / ".env"):
            for key, value in dotenv_values(path).items():
                env.setdefault(key, value or "")
    else:
        for key in PROVIDER_KEYS:
            env.pop(key, None)
    env.update(RUN_DIR=str(runs / "transcripts"), DATE_DIR=str(runs / "dates"),
               CHEMISTRY_DIR=str(runs / "chemistry"), SCENARIO_DIR=str(runs / "scenarios"))
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "orchestrator.app:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"], cwd=ROOT, env=env)
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{url}/health", timeout=1).status_code == 200:
                return process, url
        except httpx.HTTPError:
            time.sleep(0.3)
    process.terminate()
    raise SystemExit("server did not start")


def mic_audio() -> bytes:
    """The sample voice as 16 kHz PCM16 mono, via ffmpeg; silence-padded speech."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        out = subprocess.run([ffmpeg, "-v", "error", "-i", str(ROOT / "tools" / "sample_es.mp3"),
                              "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                             capture_output=True, check=False)
        if out.returncode == 0 and out.stdout:
            return out.stdout
    import math
    import struct
    samples = [int(9000 * math.sin(2 * math.pi * 180 * i / 16000) * (1 if (i // 3200) % 2 else 0.2))
               for i in range(16000 * 2)]
    return struct.pack(f"<{len(samples)}h", *samples)


def generate_all(client: httpx.Client) -> dict:
    dates = {}
    for code in DIALECTS:
        started = time.monotonic()
        response = client.post("/v1/matchmaker/generate", json={
            "learner_name": "Arth", "language": code, "proficiency": "B2", "venue_style": "auto",
            "date_gender": "female" if code != "fr-FR" else "male", "date_ethnicity": "mixed",
            "personality_archetype": "playful_sarcastic",
            "custom_notes": "Loves indie rock and photography, hates crypto bros",
            "scene_prompt": "a rooftop bar at sunset after the rain"}, timeout=90)
        ms = int((time.monotonic() - started) * 1000)
        ok = response.status_code == 200
        body = response.json() if ok else {}
        character = body.get("date_character", {})
        complete = ok and character.get("opening_line") and character.get("system_prompt") \
            and len(body.get("milestones", [])) == 4
        check(bool(complete), f"matchmaker {code}",
              f"{ms} ms, {body.get('generated_by')}, {character.get('display_name')}, "
              f"venue {body.get('venue', {}).get('id')}" if ok else response.text[:120])
        if complete:
            dates[code] = body
    return dates


async def live_date(url: str, date: dict, wingman_wait: float) -> str | None:
    from websockets.asyncio.client import connect

    run_id = f"e2e_{int(time.time())}"
    ws_url = url.replace("http://", "ws://") + "/v1/stream"
    seen: dict[str, list] = {}
    audio_bytes = {"total": 0}
    first_audio: list[float] = []

    async with connect(ws_url, max_size=16 * 1024 * 1024) as ws:
        async def reader():
            async for raw in ws:
                if isinstance(raw, bytes):
                    audio_bytes["total"] += len(raw)
                    continue
                msg = json.loads(raw)
                seen.setdefault(msg["type"], []).append((time.monotonic(), msg))

        task = asyncio.create_task(reader())

        async def wait(kind: str, after: float = 0.0, timeout: float = 20.0) -> dict | None:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                for t, msg in seen.get(kind, []):
                    if t >= after:
                        return msg
                await asyncio.sleep(0.05)
            return None

        await ws.send(json.dumps({"type": "init", "run_id": run_id,
                                  "scenario_id": date["scenario_id"], "npc_id": "host"}))
        ready = await wait("session_ready")
        check(ready is not None, "stream session_ready",
              json.dumps(ready.get("providers")) if ready else "no reply")
        if ready is None:
            task.cancel()
            return None

        mark = time.monotonic()
        await ws.send(json.dumps({"type": "focus", "npc_id": "host"}))
        greet = await wait("audio_end", mark)
        check(greet is not None and greet.get("npc_id") == "host", "host greeting spoken",
              f"{greet.get('duration_ms')} ms of audio" if greet else "")

        mark = time.monotonic()
        await ws.send(json.dumps({"type": "start_date"}))
        opening = await wait("audio_end", mark, 30)
        line = await wait("transcript", mark)
        check(opening is not None, "date opening line",
              f"{opening.get('duration_ms')} ms, “{(line or {}).get('text', '')[:60]}”" if opening else "")

        # Stream the sample voice as the microphone, at real time, with telemetry.
        pcm = mic_audio()
        frame = 640  # 20 ms
        mark = time.monotonic()
        for i in range(0, len(pcm), frame):
            await ws.send(pcm[i:i + frame])
            if (i // frame) % 12 == 0:
                await ws.send(json.dumps({"type": "telemetry", "is_looking_at_date": True,
                                          "gaze_target": "date_npc_eyes",
                                          "look_away_duration_sec": 0.0, "player_smiling": False,
                                          "distance_m": 1.15, "is_seated": True}))
            await asyncio.sleep(0.02)
        await ws.send(b"\x00\x00" * 16000)
        silence_from = time.monotonic()
        heard = await wait("user_speech", mark, 5)
        check(heard is not None, "microphone speech detected", "voice activity from streamed audio")
        if ready["providers"]["stt"] == "deepgram":
            await asyncio.sleep(3)
            user = [m for t, m in seen.get("transcript", []) if t >= mark and m["speaker"] == "user"
                    and m["is_final"]]
            check(bool(user), "deepgram transcribed the microphone",
                  f"“{user[-1]['text'][:60]}”" if user else "nothing heard")
            # A recognised line gets a reply; wait for it before the silence test.
            if user:
                await wait("audio_end", mark, 30)
            silence_from = time.monotonic()

        hint = await wait("wingman_hint", silence_from, wingman_wait)
        check(hint is not None and len(hint.get("options", [])) == 3,
              "wingman whispers after silence",
              " | ".join(o["tone"] for o in hint["options"]) if hint else "no hint")

        mark = time.monotonic()
        answer = ANSWERS.get(date["dialect"]) or (hint["options"][1]["target"] if hint else "Hola")
        await ws.send(json.dumps({"type": "user_text", "text": answer}))
        start = await wait("audio_start", mark, 30)
        update = await wait("chemistry_update", mark, 20)
        if start:
            first_audio.append(start.get("first_audio_ms") or 0)
        check(start is not None, "date replies with streamed voice",
              f"first audio {start.get('first_audio_ms')} ms after the answer" if start else "")
        check(update is not None, "chemistry_update after the turn",
              f"{update['chemistry_score']} ({update['delta']:+d}) {update['mood_label']}: "
              f"{update['reason']}" if update else "")

        mark = time.monotonic()
        await ws.send(json.dumps({"type": "barge_in", "timestamp_ms": 1}))
        cleared = await wait("clear_audio", mark, 5)
        check(cleared is not None, "barge-in clears the date's audio")

        mark = time.monotonic()
        await ws.send(json.dumps({"type": "user_text",
                                  "text": "Perdón, te interrumpí. ¿Me contás más?"}))
        await wait("audio_start", mark, 30)
        for away in (1.0, 5.0):
            await ws.send(json.dumps({"type": "telemetry", "is_looking_at_date": False,
                                      "look_away_duration_sec": away, "player_smiling": False,
                                      "distance_m": 1.15, "is_seated": True}))
        look = await wait("signal", mark, 5)
        check(look is not None and look.get("kind") == "look_away", "look-away noticed",
              look.get("effect", "") if look else "only fires while the date is still talking")

        mark = time.monotonic()
        await ws.send(json.dumps({"type": "end_date", "reason": "timer"}))
        ended = await wait("date_ended", mark, 40)
        check(ended is not None, "date ends with a closing line",
              f"{ended['verdict']} at {ended['chemistry_score']}" if ended else "")
        check(audio_bytes["total"] > 48000, "binary 24 kHz voice frames received",
              f"{audio_bytes['total'] / 48000:.1f} s of audio")
        task.cancel()
    return run_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="use a running server instead of starting one")
    parser.add_argument("--offline", action="store_true", help="start the server with no keys")
    parser.add_argument("--dialect", default="es-AR")
    args = parser.parse_args()

    runs = Path(tempfile.mkdtemp(prefix="parry-e2e-"))
    process = None
    url = args.url
    if url is None:
        process, url = start_server(args.offline, runs)
    print(f"server {url}")
    try:
        with httpx.Client(base_url=url) as client:
            health = client.get("/health").json()
            check(True, "health", json.dumps(health.get("date")))
            dates = generate_all(client)
            date = dates.get(args.dialect) or next(iter(dates.values()), None)
            if date is None:
                raise SystemExit("no date generated")
            run_id = asyncio.run(live_date(url, date, wingman_wait=12.0))
            if run_id:
                started = time.monotonic()
                response = client.post("/v1/grade", json={"run_id": run_id,
                                                         "scenario_id": date["scenario_id"]},
                                       timeout=120)
                ms = int((time.monotonic() - started) * 1000)
                ok = response.status_code == 200
                verdict = response.json() if ok else {}
                quoted = all(p["evidence_quote"] or p["grade"] in (None, "D+", "D", "D-", "F")
                             or p["id"] == "agility_pacing" for p in verdict.get("pillars", []))
                check(ok and quoted, "verdict receipt with verbatim quotes",
                      f"{ms} ms, {verdict.get('stamp')} / {verdict.get('overall')}, "
                      f"{verdict.get('graded_by')}" if ok else response.text[:160])
                if ok:
                    check(bool(verdict["followup"]["text"]), "follow-up text from the date",
                          f"“{verdict['followup']['text'][:70]}”")
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=10)
        shutil.rmtree(runs, ignore_errors=True)
    failed = [r for r in results if not r[0]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
