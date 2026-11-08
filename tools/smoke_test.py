"""Smallest end-to-end test of the ElevenLabs voice loop.

Proves: auth -> signed URL -> WebSocket -> agent replies in Spanish -> PCM16 audio
comes back, and measures time-to-first-audio. Needs no microphone, no PyAudio and
no Unity, so it is safe to run before any of that exists.

    .venv/bin/python tools/smoke_test.py "quiero un cafe de olla, por favor"

Writes the reply to runs/smoke/reply.wav so you can listen to it.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
import wave
from pathlib import Path

import websockets
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / "orchestrator" / ".env")

API_KEY = os.environ["ELEVENLABS_API_KEY"]
AGENT_ID = os.environ.get("AGENT_ID_LUIS") or os.environ["SMOKE_AGENT_ID"]
SAMPLE_RATE = 16000
OUT = ROOT / "runs" / "smoke" / "reply.wav"


async def signed_url() -> str:
    """Private agents need a short-lived signed URL; public ones accept it too."""
    import urllib.request

    req = urllib.request.Request(
        "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url"
        f"?agent_id={AGENT_ID}",
        headers={"xi-api-key": API_KEY},
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)["signed_url"]


async def main(utterance: str) -> int:
    url = await signed_url()
    audio = bytearray()
    said: list[str] = []
    heard: list[str] = []
    sent_at: float | None = None
    first_audio_ms: float | None = None

    async with websockets.connect(url, max_size=16 * 1024 * 1024) as ws:
        # A raw socket must open with this frame. Without it the server waits for a
        # user message and hangs up after 60s. The SDK sends it for you.
        await ws.send(json.dumps({
            "type": "conversation_initiation_client_data",
            # Every variable a prompt mentions must be sent, or the conversation fails.
            "dynamic_variables": {"learner_name": "amigo", "user_order": "nada",
                                  "learner_level": "A2"},
        }))

        async def say_it() -> None:
            """Speak our line, on the greeting or after a wait if none comes."""
            nonlocal sent_at
            if sent_at is not None:
                return
            print(f"\n  you            {utterance!r}")
            sent_at = time.perf_counter()
            await ws.send(json.dumps({"type": "user_message", "text": utterance}))

        async def watchdog() -> None:
            await asyncio.sleep(12)
            await say_it()

        guard = asyncio.create_task(watchdog())

        # The agent speaks first, so drain its greeting before we say anything.
        async for raw in ws:
            msg = json.loads(raw)
            kind = msg.get("type")

            if kind == "conversation_initiation_metadata":
                meta = msg["conversation_initiation_metadata_event"]
                print(f"  connected      conversation={meta.get('conversation_id')}")
                print(f"  agent audio    {meta.get('agent_output_audio_format')}")
                print(f"  user audio     {meta.get('user_input_audio_format')}")

            elif kind == "ping":
                # The server measures latency with these; the SDK answers them for us,
                # but on a raw socket we must reply or the server closes the session.
                ev = msg["ping_event"]
                await asyncio.sleep((ev.get("ping_ms") or 0) / 1000)
                await ws.send(json.dumps({"type": "pong", "event_id": ev["event_id"]}))

            elif kind == "agent_response":
                text = msg["agent_response_event"]["agent_response"].strip()
                said.append(text)
                print(f"  agent          {text!r}")
                if sent_at is None:
                    guard.cancel()
                    await say_it()  # greeting done: say our line, start the clock
                else:
                    break  # got the reply to our line

            elif kind == "user_transcript":
                heard.append(msg["user_transcription_event"]["user_transcript"])

            elif kind == "audio":
                chunk = base64.b64decode(msg["audio_event"]["audio_base_64"])
                audio.extend(chunk)
                if sent_at is not None and first_audio_ms is None:
                    first_audio_ms = (time.perf_counter() - sent_at) * 1000
                    print(f"  first audio    {first_audio_ms:.0f} ms after our turn")

            elif kind == "interruption":
                print("  interruption   (agent was cut off)")

        # Drain whatever audio is still in flight for that final reply.
        try:
            async with asyncio.timeout(3):
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("type") == "audio":
                        audio.extend(base64.b64decode(msg["audio_event"]["audio_base_64"]))
                    elif msg.get("type") == "ping":
                        ev = msg["ping_event"]
                        await ws.send(json.dumps({"type": "pong", "event_id": ev["event_id"]}))
        except (TimeoutError, websockets.ConnectionClosed):
            pass

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(bytes(audio))

    seconds = len(audio) / 2 / SAMPLE_RATE
    print(f"\n  wrote          {OUT.relative_to(ROOT)}  ({seconds:.1f}s, {len(audio)} bytes)")
    if heard:
        print(f"  transcribed    {heard}")

    ok = len(said) >= 2 and len(audio) > 0
    print(f"\n  RESULT         {'PASS' if ok else 'FAIL'}"
          f"  turns={len(said)} audio={'yes' if audio else 'no'}"
          f" ttfa={f'{first_audio_ms:.0f}ms' if first_audio_ms else 'n/a'}")
    return 0 if ok else 1


if __name__ == "__main__":
    line = sys.argv[1] if len(sys.argv) > 1 else "Quiero un café de olla, por favor."
    raise SystemExit(asyncio.run(main(line)))
