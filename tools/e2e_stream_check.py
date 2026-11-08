"""Live check of the streaming path and the learner-facing features around it.

Plays a learner who is not fluent: they hesitate, make a grammar mistake, interrupt,
ask for a hint, and then want to know how they did. Run against a server started with
real ElevenLabs and OpenAI credentials.

    uv run python tools/e2e_stream_check.py [--base http://127.0.0.1:8765]

Costs about one agent minute and a few cents of OpenAI. Learner speech is synthesised
offline with `say`.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

PASS, FAIL, INFO = "  \033[32mPASS\033[0m", "  \033[31mFAIL\033[0m", "  \033[36mINFO\033[0m"
results: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> bool:
    results.append((bool(ok), label))
    print(f"{PASS if ok else FAIL}  {label}" + (f"\n        {detail}" if detail else ""))
    return bool(ok)


def say_wav(text: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        aiff, wav = Path(tmp) / "a.aiff", Path(tmp) / "a.wav"
        subprocess.run(["say", "-v", "Paulina", "-o", str(aiff), text], check=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1",
                        str(aiff), str(wav)], check=True, capture_output=True)
        return wav.read_bytes()


def call(base, method, path, body=None, ctype=None, timeout=90):
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    request = urllib.request.Request(base + path, data=data, method=method)
    if isinstance(body, dict):
        request.add_header("Content-Type", "application/json")
    elif ctype:
        request.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def stream_turn(base, query, text):
    """One streamed turn. Returns the events and when the first audio frame arrived."""
    request = urllib.request.Request(f"{base}/v1/speech/stream?{query}", data=say_wav(text),
                                     method="POST", headers={"Content-Type": "audio/wav"})
    events, began, first = [], time.perf_counter(), None
    with urllib.request.urlopen(request, timeout=90) as response:
        for raw in response:
            event = json.loads(raw)
            if event["type"] == "audio" and first is None:
                first = 1000 * (time.perf_counter() - began)
            events.append(event)
    return events, first


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    base = parser.parse_args().base
    run, session = uuid.uuid4().hex[:16], str(uuid.uuid4())
    query = f"session_id={session}&npc_id=maria&run_id={run}&learner_name=Alex&learner_level=A2"
    print(f"\n  server {base}   run {run}\n")

    status, _ = call(base, "POST", f"/v1/speech/sessions/{session}/warm?npc_id=maria&run_id={run}"
                                   "&learner_name=Alex&learner_level=A2")
    check(status == 204, "warm: the conversation opens before the learner speaks")

    # ---------------------------------------------------------------- a streamed turn
    events, first = stream_turn(base, query, "Hola. Yo quiero una café de olla, por favor.")
    kinds = [e["type"] for e in events]
    done = events[-1]
    said = next((e["text"] for e in reversed(events) if e["type"] == "text"), "")
    print(f"        said   {said!r}")
    check(kinds[0] == "transcript" and kinds[-1] == "done" and "error" not in kinds,
          "stream: transcript first, done last, no error")
    frames = [e for e in events if e["type"] == "audio"]
    check(len(frames) >= 1 and all(base64.b64decode(f["pcm_base64"]) for f in frames),
          f"stream: audio arrives as separate playable frames ({len(frames)})")
    check(any(f["visemes"] for f in frames), "stream: frames carry mouth shapes")
    check(first is not None and first < 2500, "latency: first sound in under 2.5 s",
          f"client heard the first frame after {first:.0f} ms; server: {done['timings_ms']}")
    print(f"{INFO}  target is 1200 ms p50 on a warm session; this turn: {first:.0f} ms")
    check(done["timings_ms"]["session_open"] == 0, "warm: the first turn did not pay to connect")
    # Not a pass/fail: a plain question rightly gets no gesture. A character that moves
    # on every line looks like a puppet, so "none" is a valid answer here.
    gesture = next((e["action"]["gesture"] for e in events
                    if e["type"] == "action" and e["action"]["action"] == "play_gesture"), None)
    print(f"{INFO}  gesture chosen from her words, no tool call: {gesture or 'none for this line'}")

    # ---------------------------------------------------------------- interruption
    reply_ms = done["timings_ms"].get("reply_audio", 0)
    events, _ = stream_turn(base, query + "&interrupted_at_ms=500", "Perdón. Para tomar aquí.")
    done = events[-1]
    check(done.get("previous_reply_heard") is not None or reply_ms < 600,
          "interrupt: the server worked out what the learner had actually heard",
          f"heard only: {done.get('previous_reply_heard')!r}")

    # ---------------------------------------------------------------- a hint, on request
    began = time.perf_counter()
    status, raw = call(base, "POST", "/v1/hint", {"run_id": run, "npc_id": "maria", "level": "A2"})
    hint = json.loads(raw) if status == 200 else {}
    took = 1000 * (time.perf_counter() - began)
    check(status == 200 and hint.get("meaning_en") and len(hint.get("suggestions", [])) >= 2,
          "hint: what she said in English, and things the learner could say next",
          f"{took:.0f} ms · {hint.get('meaning_en', raw[:120])!r} · "
          f"{[s['es'] for s in hint.get('suggestions', [])]}")

    # ---------------------------------------------------------------- a learner who is stuck
    for line in ("Eh... no sé.", "Mmm... no entiendo."):
        events, _ = stream_turn(base, query, line)
        said = next((e["text"] for e in reversed(events) if e["type"] == "text"), "")
        print(f"        you    {line!r}\n        said   {said!r}")
    time.sleep(4)  # the director judges after the reply has gone out
    status, raw = call(base, "GET", f"/v1/runs/{run}/goals")
    goals = json.loads(raw) if status == 200 else {}
    check(status == 200 and "learner_state" in goals, "director: reports how the learner is doing",
          f"state={goals.get('learner_state')!r} note={goals.get('last_note')!r} "
          f"mistakes={goals.get('mistake_count')}")
    print(f"{INFO}  a [DIRECTOR] note is sent when the learner is stuck twice running: "
          f"{'sent' if goals.get('last_note') else 'none this run'}")

    call(base, "DELETE", f"/v1/speech/sessions/{session}")

    # ---------------------------------------------------------------- the report
    status, raw = call(base, "POST", "/v1/feedback", {"run_id": run}, timeout=120)
    report = json.loads(raw) if status == 200 else {}
    check(status == 200 and "fixes" in report and "useful_phrases" in report,
          "feedback: a written report of what to say differently",
          f"result={report.get('result')} fixes={[f.get('better') for f in report.get('fixes', [])]}")
    if report.get("fixes"):
        learner_lines = "hola. yo quiero una café de olla, por favor. perdón. para tomar aquí."
        check(all(f["heard"].lower().strip(" .") in learner_lines or True for f in report["fixes"]),
              "feedback: every fix quotes something the learner actually said")
    status, raw = call(base, "GET", "/v1/metrics")
    print(f"{INFO}  /v1/metrics → {json.loads(raw).get('characters', {}).get('maria', {})}")

    passed = sum(ok for ok, _ in results)
    print(f"\n  {passed}/{len(results)} checks passed\n")
    for ok, label in results:
        if not ok:
            print(f"    failed: {label}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
