"""Move the demo to another ElevenLabs account, in one command.

Four free accounts, 15 agent minutes each. Pasting a different key over
``ELEVENLABS_API_KEY`` on its own BREAKS the demo: agents, tools and voices all live
inside one account, so the agent ids in ``.env`` do not exist on anyone else's. This
script does the whole runbook from CLAUDE.md, in order:

1. add the scenario's Voice Library voices to that account's My Voices (an agent
   cannot use a library voice until it is there; it 404s otherwise),
2. recreate the tools and agents there (``provision_agents.py --apply``),
3. point ``ELEVENLABS_API_KEY`` and the ``AGENT_ID_*`` lines in ``orchestrator/.env``
   at the new account,
4. print how many agent minutes that account has left.

    uv run python tools/switch_account.py fourth            # dry run: what would happen
    uv run python tools/switch_account.py fourth --apply    # do it
    uv run python tools/switch_account.py fourth --stage    # steps 1-2 only: get the
                                                            # account ready, leave .env
                                                            # and the live demo alone

Dry run is the default because step 3 changes which account the running demo talks to.
After --apply, restart the server and run ``tools/e2e_check.py``. Greeting audio is
committed and account-agnostic, so it is not re-recorded.

Keys are never printed; accounts are referred to by name only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import dotenv_values  # noqa: E402

from orchestrator.scene import ScenePack, default_pack_dir  # noqa: E402

API = "https://api.elevenlabs.io"
ENV_PATH = ROOT / "orchestrator" / ".env"
ACCOUNTS = ("first", "second", "third", "fourth")
FREE_AGENT_SECONDS = 15 * 60


def call(key: str, method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"xi-api-key": key}
    if data:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(API + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        raise SystemExit(f"\n  {method} {path} -> HTTP {error.code}\n"
                         f"  {error.read().decode()[:400]}\n") from None


def ensure_voices(key: str, pack: ScenePack, apply: bool) -> bool:
    """Add each character's library voice to My Voices if it is not there yet."""
    mine = {v["voice_id"] for v in call(key, "GET", "/v1/voices").get("voices", [])}
    ready = True
    for npc in pack.scenario.npcs:
        if npc.voice_id in mine:
            print(f"  voice {npc.npc_id:8} present  {npc.voice_id}")
        elif not npc.voice_library_owner_id:
            ready = False
            print(f"  voice {npc.npc_id:8} MISSING and scenario.json has no "
                  f"voice_library_owner_id to add it with")
        else:
            print(f"  voice {npc.npc_id:8} add      {npc.voice_id}")
            if apply:
                call(key, "POST",
                     f"/v1/voices/add/{npc.voice_library_owner_id}/{npc.voice_id}",
                     {"new_name": npc.voice_name or npc.name})
    return ready


def minutes_left(key: str) -> str:
    listing = call(key, "GET", "/v1/convai/conversations?page_size=100")
    used = sum(c.get("call_duration_secs") or 0 for c in listing.get("conversations", []))
    more = " (at least; more than 100 conversations)" if listing.get("has_more") else ""
    return (f"{used}s of {FREE_AGENT_SECONDS}s used, "
            f"{max(FREE_AGENT_SECONDS - used, 0) / 60:.1f} min left{more}")


def credits_left(key: str) -> str:
    info = call(key, "GET", "/v1/user/subscription")
    return f"{info['character_limit'] - info['character_count']} of {info['character_limit']}"


def set_env_key(text: str, name: str, value: str) -> str:
    """Replace ``NAME=…`` in .env text, or append it. Other lines are untouched."""
    line, pattern = f"{name}={value}", rf"(?m)^{re.escape(name)}=.*$"
    if re.search(pattern, text):
        return re.sub(pattern, lambda _: line, text)
    return text.rstrip("\n") + f"\n{line}\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("account", choices=ACCOUNTS)
    parser.add_argument("--apply", action="store_true", help="really switch")
    parser.add_argument("--stage", action="store_true",
                        help="prepare the account (voices, tools, agents) but leave .env alone")
    parser.add_argument("--dry-run", action="store_true",
                        help="the default; accepted so the intent can be spelt out")
    parser.add_argument("--pack", default=str(default_pack_dir()))
    args = parser.parse_args()
    if args.dry_run and (args.apply or args.stage):
        return print("--dry-run contradicts --apply/--stage") or 2

    env = dotenv_values(ENV_PATH)
    source = f"ELEVENLABS_API_KEY_{args.account.upper()}"
    key = env.get(source) or ""
    if not key:
        return print(f"{source} is not set in {ENV_PATH.relative_to(ROOT)}") or 1
    already = env.get("ELEVENLABS_API_KEY") == key
    changing = args.apply or args.stage
    mode = "STAGE — .env untouched" if args.stage else "APPLY" if args.apply else \
        "dry run — nothing will change"
    print(f"\n  account  {args.account}" + ("  (already the active account)" if already else ""))
    print(f"  mode     {mode}\n")

    pack = ScenePack.load(args.pack)
    print(f"  credits  {credits_left(key)} left")
    print(f"  minutes  {minutes_left(key)}\n")
    if not ensure_voices(key, pack, changing):
        return 1

    # The provisioner reads the key from the environment, and python-dotenv never
    # overrides a variable that is already set, so this aims it at the new account
    # without the key ever appearing on a command line.
    command = [sys.executable, str(ROOT / "tools" / "provision_agents.py"), "--pack", args.pack]
    if changing:
        command.append("--apply")
    if args.apply:
        # Written before provisioning so that --write-env lands next to the right key,
        # and a crash half-way leaves a key whose agents can simply be re-provisioned.
        ENV_PATH.write_text(set_env_key(ENV_PATH.read_text(), "ELEVENLABS_API_KEY", key))
        print(f"\n  ELEVENLABS_API_KEY now points at {args.account}")
        command.append("--write-env")
    print(f"\n  running provision_agents.py {' '.join(command[4:]) or '(dry run)'}")
    sys.stdout.flush()  # keep our lines ahead of the child's in a piped log
    done = subprocess.run(command, env={**os.environ, "ELEVENLABS_API_KEY": key}, cwd=ROOT)
    if done.returncode:
        print("  provisioning FAILED; the account is not ready")
        return done.returncode

    if args.apply:
        print("  next: restart the server, then  uv run python tools/e2e_check.py\n")
    elif args.stage:
        print(f"  {args.account} is ready. Switch to it later with --apply.\n")
    else:
        print("  dry run — re-run with --apply to switch, or --stage to prepare only\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
