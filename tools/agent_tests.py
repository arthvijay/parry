"""Regression tests that run INSIDE ElevenLabs, against the live characters.

Our own pytest suite mocks the provider, so it cannot notice that a prompt edit made
Maria stop calling ``serve_order``. These tests can: ElevenLabs replays a scripted chat
history into the real agent (real prompt, real LLM, real tool definitions) and checks
what it does next. Text only, so they cost no voice minutes.

    uv run python tools/agent_tests.py            # show what would be created/updated
    uv run python tools/agent_tests.py --apply    # create/update the test definitions
    uv run python tools/agent_tests.py --run      # apply, run each 3 times, print a table
    uv run python tools/agent_tests.py --run --account fourth   # on a staged spare account

Each run costs about 30 credits of the account's ordinary quota (measured: an account
with none left fails every run with ``quota_exceeded``). When the active account is
spent, stage a spare with ``tools/switch_account.py NAME --stage`` and point --account
at it: the same prompts, tools and LLM are provisioned there, so the result carries.
Agents are found by name, never by the ids in ``.env``, for exactly that reason.

Idempotent: tests are found by name and updated in place. ``--run`` exits non-zero if
any repetition of any test fails, so it can gate a prompt change. An LLM is not
deterministic, which is exactly why each test runs three times: a tool call that fires
two times out of three is a broken demo one visit in three.

The older ``simulate-conversation`` endpoint is deprecated; this uses
``/v1/convai/agent-testing`` and ``/v1/convai/agents/{id}/run-tests``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from orchestrator.scene import ScenePack, default_pack_dir  # noqa: E402

load_dotenv(ROOT / "orchestrator" / ".env")
API = "https://api.elevenlabs.io"
KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ACCOUNTS = ("first", "second", "third", "fourth")
# Every variable the prompts mention; a missing one fails the conversation outright.
VARIABLES = {"learner_name": "Alex", "user_order": "nada", "learner_level": "A2"}


class ApiError(Exception):
    def __init__(self, method: str, path: str, code: int, detail: str):
        super().__init__(f"{method} {path} -> HTTP {code}\n  {detail}")
        self.code = code


def call(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"xi-api-key": KEY}
    if data:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(API + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        raise ApiError(method, path, error.code, error.read().decode()[:600]) from None


# --------------------------------------------------------------------------- the tests

def user(text: str, at: int) -> dict:
    return {"role": "user", "message": text, "time_in_call_secs": at}


def agent(text: str, at: int) -> dict:
    return {"role": "agent", "message": text, "time_in_call_secs": at}


def agent_tool(text: str, at: int, tool: str, params: dict, result: str) -> list[dict]:
    """An agent turn that called a client tool, plus the result it got back.

    Without this in the history the model has no evidence an order was ever placed,
    and a price question is answered by placing the order rather than showing the bill.
    """
    request_id = f"hist_{tool}_{at}"
    return [{
        "role": "agent", "message": text, "time_in_call_secs": at,
        "tool_calls": [{"type": "client", "request_id": request_id, "tool_name": tool,
                        "params_as_json": json.dumps(params), "tool_has_been_called": True}],
        "tool_results": [{"type": "client", "request_id": request_id, "tool_name": tool,
                          "result_value": result, "is_error": False,
                          "tool_has_been_called": True}],
    }]


def build_tests(pack: ScenePack, tool_ids: dict[str, str]) -> list[dict]:
    """One dict per test: which character it runs on, and the API body."""
    prefix = pack.scenario.scenario_id
    maria, luis = pack.npcs["maria"], pack.npcs["luis"]

    def tool_check(name: str, absent: bool = False) -> dict:
        return {"referenced_tool": {"id": tool_ids[name], "type": "client"},
                "parameters": [], "verify_absence": absent}

    def tool_test(npc: str, name: str, history: list[dict], tool: str, absent=False) -> dict:
        return {"npc": npc, "body": {
            "type": "tool", "name": f"{prefix} · {npc} · {name}",
            "dynamic_variables": dict(VARIABLES), "chat_history": history,
            "tool_call_parameters": tool_check(tool, absent),
            # Characters also gesture; a nod alongside the real call is not a failure.
            "check_any_tool_matches": True}}

    return [
        tool_test("maria", "a complete order calls serve_order", [
            agent(maria.first_message, 0),
            user("Quiero un café de olla y una concha, para tomar aquí.", 6),
        ], "serve_order"),
        tool_test("maria", "asking the total after ordering calls show_bill", [
            agent(maria.first_message, 0),
            user("Quiero un café de olla y una concha, para tomar aquí.", 6),
            *agent_tool("Claro, ahorita te lo traigo.", 9, "serve_order",
                        {"items": ["cafe_olla", "concha"], "to_go": False},
                        "Served: Café de olla, Concha. Total: ochenta pesos (80 MXN). "
                        "Do not say the total unless the customer asks."),
            user("Gracias. ¿Cuánto es todo?", 40),
        ], "show_bill"),
        tool_test("maria", "sold-out pay de limón does not call serve_order", [
            agent(maria.first_message, 0),
            user("Quiero un pay de limón.", 6),
        ], "serve_order", absent=True),
        {"npc": "maria", "body": {
            "type": "llm", "name": f"{prefix} · maria · English gets a Spanish reply",
            "dynamic_variables": dict(VARIABLES),
            "chat_history": [agent(maria.first_message, 0),
                             user("Hi, can I get a coffee please? I don't speak Spanish.", 6)],
            "success_condition": (
                "The agent's reply is written entirely in Spanish and contains no English "
                "words or sentences. Return True only if it is all Spanish."),
            "success_examples": [{"type": "success", "response":
                                  "Perdón, joven, casi no hablo inglés. ¿Qué te sirvo?"}],
            "failure_examples": [{"type": "failure", "response":
                                  "Sure! One coffee coming up. ¿Algo más?"}]}},
        tool_test("luis", "never places an order himself", [
            agent(luis.first_message, 0),
            user("Hola Luis. Oye, quiero un café de olla y una concha. ¿Me lo pides?", 6),
        ], "serve_order", absent=True),
    ]


# --------------------------------------------------------------------------- plumbing

def existing_tests() -> dict[str, str]:
    found, cursor = {}, None
    while True:
        query = "page_size=100" + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else "")
        page = call("GET", f"/v1/convai/agent-testing?{query}")
        found.update({t["name"]: t["id"] for t in page.get("tests", [])})
        cursor = page.get("next_cursor")
        if not page.get("has_more") or not cursor:
            return found


def ensure_tests(tests: list[dict], apply: bool) -> None:
    have = existing_tests()
    for test in tests:
        name = test["body"]["name"]
        if name in have:
            test["id"] = have[name]
            print(f"  test  update  {have[name]}  {name}")
            if apply:
                call("PUT", f"/v1/convai/agent-testing/{have[name]}", test["body"])
        else:
            print(f"  test  create  {'':28}  {name}")
            test["id"] = call("POST", "/v1/convai/agent-testing/create",
                              test["body"])["id"] if apply else "<new>"


def words_only_override(pack: ScenePack, agent_id: str, tool_ids: dict[str, str]) -> dict:
    """The agent's own config minus its fire-and-forget tools, for reply-text tests.

    The harness judges the FIRST thing the model generates. A gesture is generated
    before the words (measured: every run of the English test came back as a bare
    play_gesture and was failed for "no verbal response"), so a test about what the
    character SAYS has to run without gestures. Tools that expect a response stay, and
    the tool-call tests run on the untouched agent.
    """
    live = call("GET", f"/v1/convai/agents/{agent_id}")
    config = live["conversation_config"]
    silent = {tool_ids[name] for name, spec in pack.scenario.tools.items()
              if not spec.expects_response and name in tool_ids}
    prompt = config["agent"]["prompt"]
    prompt["tool_ids"] = [t for t in prompt.get("tool_ids") or [] if t not in silent]
    prompt.pop("tools", None)  # read-only echo of tool_ids; sending both is rejected
    return {"conversation_config": config, "platform_settings": {}}


def run_for_agent(agent_id: str, tests: list[dict], repeat: int, timeout: float,
                  override: dict | None = None) -> list[dict]:
    body = {"tests": [{"test_id": t["id"]} for t in tests], "repeat_count": repeat}
    if override:
        body["agent_config_override"] = override
    started = call("POST", f"/v1/convai/agents/{agent_id}/run-tests", body)
    invocation, deadline = started["id"], time.monotonic() + timeout
    while True:
        state = call("GET", f"/v1/convai/test-invocations/{invocation}")
        runs = state.get("test_runs", [])
        pending = [r for r in runs if r.get("status") == "pending"]
        if runs and not pending:
            return runs
        if time.monotonic() > deadline:
            print(f"  timed out with {len(pending)} runs still pending")
            return runs
        time.sleep(3)


def said(run: dict) -> str:
    """What the character did in this run, for the table: tools called, then words."""
    parts = []
    for turn in run.get("agent_responses") or []:
        parts += [f"[{c.get('tool_name')}]" for c in turn.get("tool_calls") or []]
        if turn.get("message"):
            parts.append(turn["message"])
    return " ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="create/update the definitions")
    parser.add_argument("--run", action="store_true", help="apply, then run and report")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=240, help="seconds to wait per agent")
    parser.add_argument("--pack", default=str(default_pack_dir()))
    parser.add_argument("--account", choices=ACCOUNTS,
                        help="run on this account instead of the active one")
    args = parser.parse_args()
    global KEY
    if args.account:
        KEY = os.environ.get(f"ELEVENLABS_API_KEY_{args.account.upper()}", "")
    if not KEY:
        return print("no API key for that account in orchestrator/.env") or 1

    pack = ScenePack.load(args.pack)
    try:
        by_name = {a["name"]: a["agent_id"]
                   for a in call("GET", "/v1/convai/agents?page_size=100").get("agents", [])}
        agents = {npc: by_name.get(f"{pack.scenario.scenario_id} · {npc}", "")
                  for npc in pack.npcs}
        tool_ids = {t["tool_config"]["name"]: t["id"]
                    for t in call("GET", "/v1/convai/tools").get("tools", [])}
        missing = set(pack.scenario.tools) - set(tool_ids)
        if missing:
            return print(f"tools not provisioned: {sorted(missing)}; run "
                         f"tools/provision_agents.py --apply first") or 1
        tests = build_tests(pack, tool_ids)
        print(f"\n  scenario {pack.scenario.scenario_id}  ({len(tests)} tests)\n")
        ensure_tests(tests, args.apply or args.run)
        if not args.run:
            print("" if args.apply else "\n  dry run — nothing was changed\n")
            return 0

        failures = 0
        print(f"\n  running each test {args.repeat} times\n")
        for npc, agent_id in agents.items():
            mine = [t for t in tests if t["npc"] == npc]
            if not mine:
                continue
            if not agent_id:
                print(f"  no agent for {npc} on this account; {len(mine)} tests not run")
                failures += len(mine)
                continue
            runs = []
            for kind in ("tool", "llm"):
                batch = [t for t in mine if t["body"]["type"] == kind]
                if batch:
                    override = words_only_override(pack, agent_id, tool_ids) \
                        if kind == "llm" else None
                    runs += run_for_agent(agent_id, batch, args.repeat, args.timeout, override)
            for test in mine:
                own = [r for r in runs if r.get("test_id") == test["id"]]
                passed = sum(r.get("status") == "passed" for r in own)
                ok = own and passed == len(own) == args.repeat
                failures += not ok
                print(f"  {'PASS' if ok else 'FAIL'}  {passed}/{len(own)}  {test['body']['name']}")
                for run in own:
                    if run.get("status") != "passed" or not ok:
                        why = ((run.get("condition_result") or {}).get("rationale") or {})
                        print(f"          {run.get('status'):7} {said(run)[:110]!r}")
                        for line in [why.get("summary"), *(why.get("messages") or [])][:2]:
                            if line:
                                print(f"                  {line[:300]}")
        print(f"\n  {len(tests) - failures}/{len(tests)} tests passed every repetition\n")
        return 1 if failures else 0
    except ApiError as error:
        # Recorded verbatim on purpose: if a plan does not include agent testing, the
        # exact refusal is the finding. Never paper over it with a fake pass.
        print(f"\n  ElevenLabs refused the request:\n  {error}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
