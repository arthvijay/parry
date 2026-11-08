"""Generate the scenario's soundscape with the ElevenLabs Sound Effects API.

Generated ONCE, listened to, and committed. Never at runtime: a 30-second loop costs
about 1,200 credits and takes seconds, and the demo must not depend on either.

    uv run python tools/make_ambience.py             # show what would be generated
    uv run python tools/make_ambience.py --apply     # generate whatever is missing
    uv run python tools/make_ambience.py --apply --force ocean_loop   # redo one
    uv run python tools/make_ambience.py --check     # only validate the files on disk

What to make is data: the ``ambience`` list in ``scenario.json``. Idempotent: a file
that already exists and looks like a real MP3 is left alone unless named with --force.

The agents' own built-in background sound was rejected for this: it has no ocean
preset, stops between turns, and cannot be placed in 3D by the game.

Credits come from a SPARE account, never the active one. Sound generation needs no
agents or voices on the account, so the spare keys are free to burn here while the
active account's allowance is kept for conversation minutes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from orchestrator.scene import AmbienceSpec, ScenePack, default_pack_dir  # noqa: E402

load_dotenv(ROOT / "orchestrator" / ".env")
API = "https://api.elevenlabs.io"
MODEL = "eleven_text_to_sound_v2"
OUTPUT_FORMAT = "mp3_44100_128"
# In order of preference. ELEVENLABS_API_KEY itself is deliberately absent.
SPARE_KEYS = ("ELEVENLABS_API_KEY_FOURTH", "ELEVENLABS_API_KEY_SECOND",
              "ELEVENLABS_API_KEY_THIRD")
# The documented price: 40 credits per second when a duration is given.
CREDITS_PER_SECOND = 40
# 128 kbit/s is 16 kB per second; anything under a third of that is not real audio.
MIN_BYTES_PER_SECOND = 5_000


def looks_like_mp3(data: bytes) -> bool:
    """True for an ID3 tag or a bare MPEG frame sync (11 set bits)."""
    if data[:3] == b"ID3":
        return True
    return len(data) > 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0


def problems(sound: AmbienceSpec, data: bytes) -> list[str]:
    found = []
    if not looks_like_mp3(data):
        found.append("no MP3 header")
    floor = int(sound.duration_seconds * MIN_BYTES_PER_SECOND)
    if len(data) < floor:
        found.append(f"only {len(data)} bytes, expected at least {floor}")
    return found


def spare_keys(active: str) -> list[tuple[str, str]]:
    """Spare keys that are set and are not the active account under another name."""
    return [(name, os.environ[name]) for name in SPARE_KEYS
            if os.environ.get(name) and os.environ[name] != active]


def credits_left(key: str) -> int | None:
    request = urllib.request.Request(API + "/v1/user/subscription",
                                     headers={"xi-api-key": key})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            info = json.loads(response.read())
        return int(info["character_limit"]) - int(info["character_count"])
    except (urllib.error.URLError, KeyError, ValueError):
        return None  # a restricted key cannot read its subscription; try it anyway


def generate(sound: AmbienceSpec, key: str) -> bytes:
    body = json.dumps({
        "text": sound.prompt,
        "duration_seconds": sound.duration_seconds,
        "prompt_influence": sound.prompt_influence,
        "loop": sound.loop,
        "model_id": MODEL,
    }).encode()
    request = urllib.request.Request(
        f"{API}/v1/sound-generation?output_format={OUTPUT_FORMAT}", data=body, method="POST",
        headers={"xi-api-key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=180) as response:
        return response.read()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="actually call the API")
    parser.add_argument("--force", nargs="*", metavar="ID", default=None,
                        help="regenerate even if the file exists; no ids means all")
    parser.add_argument("--check", action="store_true", help="validate files, generate nothing")
    parser.add_argument("--pack", default=str(default_pack_dir()))
    args = parser.parse_args()

    pack = ScenePack.load(args.pack)
    out = Path(args.pack) / "ambience"
    forced = None if args.force is None else set(args.force)
    unknown = (forced or set()) - {s.id for s in pack.scenario.ambience}
    if unknown:
        return print(f"unknown ambience id: {', '.join(sorted(unknown))}") or 1

    todo, bad = [], 0
    print(f"\n  scenario {pack.scenario.scenario_id}  ({len(pack.scenario.ambience)} sounds)\n")
    for sound in pack.scenario.ambience:
        target = out / sound.file
        redo = forced is not None and (not forced or sound.id in forced)
        if target.exists() and not redo:
            found = problems(sound, target.read_bytes())
            state = "ok" if not found else "BROKEN: " + "; ".join(found)
            bad += bool(found)
            print(f"  have  {sound.id:18} {target.stat().st_size:>8} bytes  {state}")
            continue
        cost = int(sound.duration_seconds * CREDITS_PER_SECOND)
        print(f"  make  {sound.id:18} {sound.duration_seconds:>5}s "
              f"{'loop' if sound.loop else 'shot'}  ~{cost} credits")
        todo.append((sound, target, cost))

    if args.check:
        missing = len(todo)
        print(f"\n  {bad} broken, {missing} missing\n")
        return 1 if bad or missing else 0
    if not todo:
        print("\n  nothing to generate\n")
        return 1 if bad else 0
    if not args.apply:
        print(f"\n  dry run — would spend ~{sum(c for *_, c in todo)} credits. "
              f"Re-run with --apply.\n")
        return 0

    keys = spare_keys(os.environ.get("ELEVENLABS_API_KEY", ""))
    if not keys:
        return print("no spare key set; refusing to spend the active account") or 1
    out.mkdir(parents=True, exist_ok=True)
    spent, failed = 0, 0
    for sound, target, cost in todo:
        for name, key in keys:
            left = credits_left(key)
            if left is not None and left < cost:
                print(f"  skip  {name}: {left} credits left, need ~{cost}")
                continue
            try:
                data = generate(sound, key)
            except urllib.error.HTTPError as error:
                print(f"  fail  {sound.id} on {name}: HTTP {error.code} "
                      f"{error.read().decode()[:200]}")
                continue
            found = problems(sound, data)
            if found:
                print(f"  fail  {sound.id} on {name}: {'; '.join(found)}")
                continue
            target.write_bytes(data)
            after = credits_left(key)
            used = left - after if left is not None and after is not None else cost
            spent += used
            print(f"  wrote {target.relative_to(Path(args.pack))}  {len(data)} bytes  "
                  f"({used} credits from {name}, {after} left)")
            break
        else:
            failed += 1
            print(f"  FAILED {sound.id}: no spare account could generate it")
    print(f"\n  spent ~{spent} credits; {failed} failed. Listen before committing.\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
