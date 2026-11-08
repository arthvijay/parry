"""Measure how long a learner waits to hear a character, against a running server.

    uv run python tools/latency_bench.py                     # streaming, Maria, 4 turns
    uv run python tools/latency_bench.py --classic           # the non-streaming endpoint
    uv run python tools/latency_bench.py --npc luis --no-warm --base http://127.0.0.1:8790

`heard` is the number that matters: wall-clock time from the end of the upload to the
first audio frame reaching the client. The server's own stage timings are printed next
to it, so a regression can be pinned on transcription, the agent, or the connection.
Learner speech is synthesised offline with `say`; only the agent turns are billed.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

LINES = ["Buenas tardes. Quiero un café de olla, por favor.", "Para tomar aquí.",
         "¿Qué es una concha?", "¿Cuánto es todo?", "Muchas gracias.", "¿Tienen wifi?"]


def say_wav(text: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        aiff, wav = Path(tmp) / "a.aiff", Path(tmp) / "a.wav"
        subprocess.run(["say", "-v", "Paulina", "-o", str(aiff), text], check=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1",
                        str(aiff), str(wav)], check=True, capture_output=True)
        return wav.read_bytes()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--npc", default="maria")
    ap.add_argument("--turns", type=int, default=4)
    ap.add_argument("--classic", action="store_true", help="use /v1/speech instead of /stream")
    ap.add_argument("--no-warm", action="store_true", help="skip the pre-warm call")
    args = ap.parse_args()

    session, run = uuid.uuid4(), uuid.uuid4().hex[:12]
    query = f"session_id={session}&npc_id={args.npc}&run_id={run}&learner_level=A2"
    clips = [say_wav(line) for line in LINES[:args.turns]]  # synthesise before timing anything

    if not args.no_warm:
        began = time.perf_counter()
        urllib.request.urlopen(urllib.request.Request(
            f"{args.base}/v1/speech/sessions/{session}/warm?npc_id={args.npc}&run_id={run}"
            "&learner_level=A2", method="POST"), timeout=60).read()
        print(f"\n  pre-warm            {1000 * (time.perf_counter() - began):6.0f} ms  (off the learner's clock)")

    mode = "classic /v1/speech" if args.classic else "streaming /v1/speech/stream"
    print(f"\n  {mode} · {args.npc} · {'cold first turn' if args.no_warm else 'warm'}\n")
    print(f"  {'turn':<5}{'heard':>8}{'stt':>7}{'open':>7}{'agent':>7}{'done':>8}   reply")
    heard_ms = []
    for i, clip in enumerate(clips, 1):
        path = "/v1/speech?response_format=json&" if args.classic else "/v1/speech/stream?"
        request = urllib.request.Request(f"{args.base}{path}{query}", data=clip, method="POST",
                                         headers={"Content-Type": "audio/wav"})
        began, first, text, timings = time.perf_counter(), None, "", {}
        with urllib.request.urlopen(request, timeout=90) as response:
            if args.classic:
                body = json.loads(response.read())
                first = time.perf_counter() - began   # nothing is playable until it all arrives
                text, timings = body["agent_transcript"], body.get("timings_ms") or {}
            else:
                for raw in response:
                    event = json.loads(raw)
                    if event["type"] == "audio" and first is None:
                        first = time.perf_counter() - began
                    elif event["type"] == "text":
                        text = event["text"]
                    elif event["type"] == "done":
                        timings = event["timings_ms"]
                    elif event["type"] == "error":
                        raise SystemExit(f"  server error: {event['detail']}")
        heard_ms.append(1000 * (first or 0))
        print(f"  {i:<5}{heard_ms[-1]:>8.0f}{timings.get('stt', 0):>7}{timings.get('session_open', 0):>7}"
              f"{timings.get('first_audio', 0):>7}{timings.get('total', 0):>8}   {text[:52]}")

    urllib.request.urlopen(urllib.request.Request(
        f"{args.base}/v1/speech/sessions/{session}", method="DELETE"), timeout=30).read()
    ordered = sorted(heard_ms)
    print(f"\n  heard: p50 {statistics.median(ordered):.0f} ms · worst {ordered[-1]:.0f} ms"
          f" · target p50 1200 ms\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
