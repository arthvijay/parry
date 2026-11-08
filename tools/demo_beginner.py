"""Playable beginner-Spanish demo. Type a line, hear Luis answer.

Talks to the beginner-mode agent: very simple A1-A2 Spanish, short sentences,
patient turn-taking. Speech speed is adjustable from the command line, so you can
find the pace a real learner can actually follow.

    .venv/bin/python tools/demo_beginner.py                 # speed 0.8
    .venv/bin/python tools/demo_beginner.py --speed 0.7     # slowest allowed
    .venv/bin/python tools/demo_beginner.py --say "un cafe" # one line, then exit

Speed is 0.7 to 1.2; the API rejects anything outside that. Each reply is played
through your speakers and kept in runs/demo/ so you can compare speeds later.

Costs ElevenLabs minutes for as long as the session is open, billed by wall clock,
so the prompt shows elapsed seconds. Type 'q' to hang up.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
import wave
from pathlib import Path

import websockets
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / "orchestrator" / ".env")

API_KEY = os.environ["ELEVENLABS_API_KEY"]
AGENT_ID = os.environ["AGENT_ID_LUIS_BEGINNER"]
RATE = 16000
OUTDIR = ROOT / "runs" / "demo"

SUGGESTIONS = [
    "Hola, buenas tardes.",
    "Quiero un café, por favor.",
    "¿Cuánto cuesta?",
    "Más despacio, por favor.",
    "No entendí.",
    "Gracias, adiós.",
]


def api(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"https://api.elevenlabs.io{path}",
        data=data,
        method=method,
        headers={"xi-api-key": API_KEY, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def set_speed(speed: float) -> None:
    api("PATCH", f"/v1/convai/agents/{AGENT_ID}",
        {"conversation_config": {"tts": {"speed": speed}}})


def play(audio: bytes, tag: str) -> Path | None:
    """Write the turn to a WAV and play it. Returns the path, or None if silent."""
    if not audio:
        return None
    OUTDIR.mkdir(parents=True, exist_ok=True)
    path = OUTDIR / f"{tag}.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(audio)
    subprocess.run(["afplay", str(path)], check=False)
    return path


async def pump(ws, q: asyncio.Queue) -> None:
    """Read the socket forever, answering pings so the server keeps us alive."""
    try:
        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("type") == "ping":
                ev = msg["ping_event"]
                await asyncio.sleep((ev.get("ping_ms") or 0) / 1000)
                await ws.send(json.dumps({"type": "pong", "event_id": ev["event_id"]}))
            else:
                await q.put(msg)
    except websockets.ConnectionClosed:
        pass
    await q.put(None)


async def one_turn(q: asyncio.Queue, first_wait: float = 25.0) -> tuple[str, bytearray, float | None]:
    """Collect one agent turn: wait for its text, then drain audio until it goes quiet."""
    text, audio, ttfa = "", bytearray(), None
    started = time.perf_counter()
    quiet, deadline = 1.4, first_wait

    while True:
        try:
            msg = await asyncio.wait_for(q.get(), timeout=deadline)
        except TimeoutError:
            break
        if msg is None:
            break

        kind = msg.get("type")
        if kind == "agent_response":
            text = msg["agent_response_event"]["agent_response"].strip()
            deadline = quiet  # got the words; now just drain trailing audio
        elif kind == "audio":
            audio.extend(base64.b64decode(msg["audio_event"]["audio_base_64"]))
            if ttfa is None:
                ttfa = (time.perf_counter() - started) * 1000
            deadline = quiet
        elif kind == "interruption":
            deadline = quiet

    return text, audio, ttfa


async def main(speed: float, one_shot: str | None) -> int:
    set_speed(speed)
    url = api("GET", f"/v1/convai/conversation/get-signed-url?agent_id={AGENT_ID}")["signed_url"]

    print(f"\n  Luis, beginner mode  ·  speed {speed}  ·  simple A1-A2 Spanish")
    if not one_shot:
        print("  Type Spanish and press enter. 'q' quits. Ideas:")
        for s in SUGGESTIONS:
            print(f"      {s}")
    print()

    q: asyncio.Queue = asyncio.Queue()
    turn = 0

    async with websockets.connect(url, max_size=16 * 1024 * 1024) as ws:
        reader = asyncio.create_task(pump(ws, q))
        opened = time.perf_counter()
        await ws.send(json.dumps({
            "type": "conversation_initiation_client_data",
            # Every variable a prompt mentions must be sent, or the conversation fails.
            "dynamic_variables": {"learner_name": "amigo", "user_order": "nada",
                                  "learner_level": "A2"},
        }))

        # Luis greets first.
        text, audio, _ = await one_turn(q)
        print(f"  Luis   {text}")
        play(bytes(audio), f"turn{turn:02d}_luis")

        while True:
            if one_shot is not None:
                line, one_shot = one_shot, ""
                if not line:
                    break
                print(f"  you    {line}")
            else:
                elapsed = time.perf_counter() - opened
                try:
                    line = (await asyncio.to_thread(input, f"  you  [{elapsed:5.0f}s]  ")).strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if line.lower() in {"q", "quit", "exit"}:
                    break
                if not line:
                    continue

            turn += 1
            await ws.send(json.dumps({"type": "user_message", "text": line}))
            text, audio, ttfa = await one_turn(q)
            if not text and not audio:
                print("  (no reply — session may have ended)")
                break

            words = len(text.split())
            secs = len(audio) / 2 / RATE
            pace = f"{words / secs * 60:.0f} wpm" if secs > 0.3 else "—"
            print(f"  Luis   {text}")
            print(f"         [{ttfa:.0f} ms to first audio · {secs:.1f}s · {pace}]"
                  if ttfa else f"         [{secs:.1f}s]")
            play(bytes(audio), f"turn{turn:02d}_luis")

        total = time.perf_counter() - opened
        reader.cancel()

    print(f"\n  hung up after {total:.0f}s  ·  audio in {OUTDIR.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--speed", type=float, default=0.8, help="0.7 (slowest) to 1.2")
    p.add_argument("--say", default=None, help="say one line, then hang up")
    a = p.parse_args()
    if not 0.7 <= a.speed <= 1.2:
        sys.exit(f"speed must be 0.7 to 1.2 (the API rejects anything else); got {a.speed}")
    raise SystemExit(asyncio.run(main(a.speed, a.say)))
