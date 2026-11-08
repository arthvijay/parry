"""Create or update the scenario's ElevenLabs agents and tools.

Idempotent: run it as often as you like. Everything is looked up by name, so the
second run updates in place instead of making duplicates, and the agent ids stay
stable. There is no local state file to drift out of date.

    uv run python tools/provision_agents.py            # show what would change
    uv run python tools/provision_agents.py --apply    # create/update for real
    uv run python tools/provision_agents.py --apply --write-env
    uv run python tools/provision_agents.py --apply --tts v3      # characters without
                                                                  # their own tts_model
    uv run python tools/provision_agents.py --selftest-v3 luis    # throwaway agent,
                                                                  # proves the V3 path
    uv run python tools/provision_agents.py --verify              # read back and check

Every --apply ends by reading each agent back and printing a table of what was asked
for against what the API stored, because several settings here are silently dropped
when misspelt rather than rejected.

Creating agents and tools costs no conversation minutes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from orchestrator.scene import ScenePack, default_pack_dir  # noqa: E402

load_dotenv(ROOT / "orchestrator" / ".env")
load_dotenv(ROOT / ".env")  # repo-root .env is the other place the key lives
API = "https://api.elevenlabs.io"
KEY = os.environ.get("ELEVENLABS_API_KEY", "")

# The agent only emits event types that are switched on, and the default set is not
# documented. client_tool_call in particular must be present or no scene action ever
# reaches us; the others are what the adapter's reader loop consumes.
CLIENT_EVENTS = [
    "conversation_initiation_metadata", "ping", "audio", "interruption",
    "user_transcript", "agent_response", "agent_response_correction", "client_tool_call",
    # agent_response_complete tells the streaming endpoint a reply is over without a
    # silence timer; agent_chat_response_part streams the text as it is written.
    "agent_response_complete", "agent_chat_response_part",
]
# Spanish agents cannot be CREATED with eleven_v3_conversational; the API rejects it
# with "Non-english Agents must use turbo or flash v2_5". Flash is also ~4x faster to
# first audio, which matters more here than expressiveness. V3 is therefore always
# reached by creating as Flash and PATCHing afterwards.
TTS_MODELS = {"flash": "eleven_flash_v2_5", "v3": "eleven_v3_conversational"}
# On Flash a tag such as [laughs] is read aloud, so these are only ever sent with V3.
V3_AUDIO_TAGS = [
    {"tag": "laughs", "description": "A short natural laugh when something is funny"},
    {"tag": "warmly", "description": "A warm, friendly tone for greetings and goodbyes"},
    {"tag": "slow", "description": "Slower, clearer delivery when asked to repeat"},
    {"tag": "sighs", "description": "A small sigh when tired or wistful"},
]
# Tool calling must be reliable: a missed serve_order means no cup and no bill.
# gemini-2.5-flash skipped the call under this prompt; this one does not.
LLM = "gpt-5.6-luna"
# Lowest first. GET /v1/convai/llm/list reports available_reasoning_efforts per model
# (gpt-5.6-luna: none…max) and the agent default is null, meaning the provider's own
# default, which thinks before speaking. A waitress does not need chain-of-thought to
# take an order, and the agent tests confirm the tools still fire at the lowest value.
REASONING_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
# Every variable the prompts mention. Agent-level values are placeholders for the
# dashboard and the agent-testing API only; production sends them per conversation.
PLACEHOLDER_VARIABLES = {"learner_name": "amigo", "user_order": "nada", "learner_level": "A2"}


def call(method: str, path: str, body: dict | None = None, raw: bool = False):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"xi-api-key": KEY}
    if data:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(API + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request) as response:
            payload = response.read()
            return payload if raw else json.loads(payload or b"{}")
    except urllib.error.HTTPError as error:
        detail = error.read().decode()[:400]
        raise SystemExit(f"\n  {method} {path} -> HTTP {error.code}\n  {detail}\n") from None


def system_tool(name: str) -> dict:
    """built_in_tools is a map of name -> full config object, not a list of names."""
    return {"type": "system", "name": name, "description": "",
            "response_timeout_secs": 20, "params": {"system_tool_type": name}}


def ensure_tools(pack: ScenePack, apply: bool) -> dict[str, str]:
    existing = {t["tool_config"]["name"]: t["id"]
                for t in call("GET", "/v1/convai/tools").get("tools", [])}
    ids: dict[str, str] = {}
    for name, spec in pack.scenario.tools.items():
        config = {
            "type": "client",
            "name": name,
            "description": spec.description,
            "expects_response": spec.expects_response,
            "parameters": spec.parameters,
            # Filler like "one moment" before a call that returns instantly sounds wrong,
            # so the default is "off"; scenario.json may opt a tool into "auto".
            "pre_tool_speech": spec.pre_tool_speech,
            "execution_mode": "immediate",
            "interruption_mode": "allow",
        }
        if spec.expects_response:
            config["response_timeout_secs"] = spec.response_timeout_secs
        if name in existing:
            print(f"  tool  {name:14} update  {existing[name]}")
            if apply:
                call("PATCH", f"/v1/convai/tools/{existing[name]}", {"tool_config": config})
            ids[name] = existing[name]
        else:
            print(f"  tool  {name:14} create")
            ids[name] = call("POST", "/v1/convai/tools",
                             {"tool_config": config})["id"] if apply else "<new>"
    return ids


@dataclass(frozen=True)
class Options:
    """What the command line chose, as opposed to what the scenario says."""

    tts: str = "flash"
    bake_level: bool = False
    llm: str = LLM
    reasoning: dict = field(default_factory=dict)


def reasoning_controls(llm: str) -> dict:
    """The least thinking this model allows, as ``prompt`` fields.

    Asked of the live API rather than hard-coded, because sending ``reasoning_effort``
    to a model that does not support it is an error, and the set differs per model.
    """
    models = {m["llm"]: m for m in call("GET", "/v1/convai/llm/list").get("llms", [])}
    if llm not in models:
        raise SystemExit(f"\n  ElevenLabs does not offer the LLM {llm!r}\n")
    efforts = models[llm].get("available_reasoning_efforts") or []
    lowest = next((e for e in REASONING_ORDER if e in efforts), None)
    if lowest is not None:
        return {"reasoning_effort": lowest}
    # Gemini 2.5 exposes a token budget instead of an effort; 0 turns thinking off.
    return {"thinking_budget": 0} if llm.startswith("gemini-2.5") else {}


def prompt_text(pack: ScenePack, npc, bake_level: bool) -> str:
    """The system prompt, optionally with the learner's level written in.

    A missing dynamic variable fails the whole conversation, it does not degrade. So
    until every caller sends ``learner_level``, --bake-level freezes it to the
    scenario's own level and the agent stops depending on the caller at all.
    """
    text = pack.prompts[npc.npc_id]
    return text.replace("{{learner_level}}", pack.scenario.level) if bake_level else text


def supported_voices(npc) -> list[dict]:
    """Multi-voice labels. ``<despacio>…</despacio>`` is the character's own voice,
    slower: the only way to slow one sentence when ``speed`` is fixed per agent."""
    return [{
        "label": voice.label,
        "voice_id": voice.voice_id or npc.voice_id,
        "language": voice.language,
        "description": voice.description,
        "speed": voice.speed,
        "stability": npc.tts.stability if voice.stability is None else voice.stability,
    } for voice in npc.supported_voices]


def analysis_settings(pack: ScenePack, npc) -> dict:
    """Post-call analysis, generated from the scenario's goals.

    ElevenLabs runs these over the transcript after the call ends, for free. They are
    a second opinion on the director, never the source of a tick: the rule "no quote,
    no tick" lives in our own grader.
    """
    criteria = [{
        "id": goal.id,
        "name": goal.label[:60],
        "type": "prompt",
        "conversation_goal_prompt": (
            f"The user is a learner of {pack.scenario.language_label}. Mark success only "
            f"if the USER (never the agent) did this, in the target language: "
            f"{goal.evidence_required}")[:2000],
        "use_knowledge_base": False,
    } for goal in pack.scenario.goals if goal.npc_id in (npc.npc_id, "any")]
    collect = {
        "grammar_errors": {
            "type": "string",
            "description": "Errors the USER made in Spanish, as a short semicolon-separated "
                           "list of 'what they said -> correct form'. Empty if none."},
        "cefr_estimate": {
            "type": "string", "enum": ["A1", "A2", "B1", "B2"],
            "description": "Best CEFR estimate of the USER's spoken Spanish in this "
                           "conversation, judged only from what they said."},
    }
    if "serve_order" in npc.tools:
        collect["items_ordered"] = {
            "type": "string",
            "description": "Comma-separated menu items the user ended up ordering, in "
                           "Spanish as named on the menu. Empty if they ordered nothing."}
    return {"evaluation": {"criteria": criteria}, "data_collection": collect}


def agent_body(pack: ScenePack, npc, tool_ids: dict[str, str], opts: Options,
               name_suffix: str = "") -> dict:
    """The full agent as Flash. V3 is layered on afterwards by :func:`v3_patch`."""
    turn = {
        "turn_eagerness": npc.turn.eagerness,
        "turn_timeout": npc.turn.timeout,
    }
    if pack.scenario.soft_timeout is not None:
        turn["soft_timeout_config"] = pack.scenario.soft_timeout.model_dump()
    return {
        "name": f"{pack.scenario.scenario_id} · {npc.npc_id}{name_suffix}",
        "tags": [pack.scenario.scenario_id],
        "platform_settings": analysis_settings(pack, npc),
        "conversation_config": {
            "agent": {
                "language": pack.scenario.language,
                "first_message": npc.first_message,
                "prompt": {
                    "prompt": prompt_text(pack, npc, opts.bake_level),
                    "llm": opts.llm,
                    # Both sent every time so that changing model clears the other.
                    "reasoning_effort": None, "thinking_budget": None,
                    **opts.reasoning,
                    "temperature": 0.7,
                    "tool_ids": [tool_ids[t] for t in npc.tools if t in tool_ids],
                    "built_in_tools": {name: system_tool(name)
                                       for name in ("end_call", "skip_turn")},
                },
                "dynamic_variables": {
                    "dynamic_variable_placeholders": dict(PLACEHOLDER_VARIABLES)},
            },
            "tts": {
                "voice_id": npc.voice_id,
                "model_id": TTS_MODELS["flash"],
                # Sent explicitly so a character moved back from V3 really is reset.
                "expressive_mode": False,
                "suggested_audio_tags": [],
                "supported_voices": supported_voices(npc),
                "agent_output_audio_format": "pcm_16000",
                "speed": npc.tts.speed,
                "stability": npc.tts.stability,
                "similarity_boost": npc.tts.similarity_boost,
            },
            "asr": {
                "user_input_audio_format": "pcm_16000",
                "keywords": pack.scenario.asr_keywords[:50],
            },
            "turn": turn,
            "conversation": {
                "text_only": False,
                "max_duration_seconds": npc.max_duration_seconds,
                "client_events": CLIENT_EVENTS,
            },
        },
    }


def v3_patch() -> dict:
    return {"conversation_config": {"tts": {
        "model_id": TTS_MODELS["v3"], "expressive_mode": True,
        "suggested_audio_tags": V3_AUDIO_TAGS}}}


def tts_choice(npc, default: str) -> str:
    """The scenario's per-character ``tts_model`` wins over the --tts flag."""
    return npc.tts_model or default


def ensure_agents(pack: ScenePack, tool_ids: dict[str, str], apply: bool,
                  opts: Options) -> dict[str, str]:
    existing = {a["name"]: a["agent_id"]
                for a in call("GET", "/v1/convai/agents?page_size=100").get("agents", [])}
    ids: dict[str, str] = {}
    for npc in pack.scenario.npcs:
        body = agent_body(pack, npc, tool_ids, opts)
        tools = ", ".join(npc.tools) or "none"
        tools += f" | tts {tts_choice(npc, opts.tts)} | {opts.llm}"
        if body["name"] in existing:
            agent_id = existing[body["name"]]
            print(f"  agent {npc.npc_id:14} update  {agent_id}  [{tools}]")
            if apply:
                # PATCH merge depth is undocumented, so send the whole config.
                call("PATCH", f"/v1/convai/agents/{agent_id}", body)
            ids[npc.npc_id] = agent_id
        else:
            print(f"  agent {npc.npc_id:14} create            [{tools}]")
            ids[npc.npc_id] = call("POST", "/v1/convai/agents/create",
                                   body)["agent_id"] if apply else "<new>"
        if apply and tts_choice(npc, opts.tts) == "v3":
            call("PATCH", f"/v1/convai/agents/{ids[npc.npc_id]}", v3_patch())
    return ids


def _subset_mismatch(want, got, path: str = "") -> list[str]:
    """Where ``got`` fails to contain ``want``. The API echoes many defaults we never
    sent, so equality is the wrong test; containment is the right one."""
    if isinstance(want, dict):
        if not isinstance(got, dict):
            return [path or "."]
        return [m for key, value in want.items()
                for m in _subset_mismatch(value, got.get(key), f"{path}.{key}".lstrip("."))]
    if isinstance(want, list):
        if not isinstance(got, list) or len(want) != len(got):
            return [path or "."]
        return [m for i, (w, g) in enumerate(zip(want, got, strict=True))
                for m in _subset_mismatch(w, g, f"{path}[{i}]")]
    if isinstance(want, float) and isinstance(got, (int, float)):
        return [] if abs(want - got) < 1e-6 else [path]
    return [] if want == got else [path]


def verify_agent(agent_id: str, body: dict, tts: str) -> list[tuple[str, str, bool]]:
    """GET the agent back and compare, setting by setting. Returns table rows."""
    live = call("GET", f"/v1/convai/agents/{agent_id}")
    want_cfg, got_cfg = body["conversation_config"], live["conversation_config"]
    want_tts = dict(want_cfg["tts"])
    if tts == "v3":
        want_tts.update(v3_patch()["conversation_config"]["tts"])
    want_prompt = want_cfg["agent"]["prompt"]
    checks: list[tuple[str, object, object]] = [
        ("prompt text", want_prompt["prompt"], got_cfg["agent"]["prompt"].get("prompt")),
        ("llm", want_prompt["llm"], got_cfg["agent"]["prompt"].get("llm")),
        ("reasoning_effort", want_prompt["reasoning_effort"],
         got_cfg["agent"]["prompt"].get("reasoning_effort")),
        ("thinking_budget", want_prompt["thinking_budget"],
         got_cfg["agent"]["prompt"].get("thinking_budget")),
        ("tool_ids", sorted(want_prompt["tool_ids"]),
         sorted(got_cfg["agent"]["prompt"].get("tool_ids") or [])),
        ("client_events", sorted(want_cfg["conversation"]["client_events"]),
         sorted(got_cfg["conversation"].get("client_events") or [])),
        ("turn.soft_timeout_config", want_cfg["turn"].get("soft_timeout_config", {}),
         got_cfg["turn"].get("soft_timeout_config")),
        ("tts.model_id", want_tts["model_id"], got_cfg["tts"].get("model_id")),
        ("tts.stability", want_tts["stability"], got_cfg["tts"].get("stability")),
        ("tts.speed", want_tts["speed"], got_cfg["tts"].get("speed")),
        ("tts.expressive_mode", want_tts["expressive_mode"],
         got_cfg["tts"].get("expressive_mode")),
        ("tts.suggested_audio_tags", want_tts["suggested_audio_tags"],
         got_cfg["tts"].get("suggested_audio_tags")),
        ("tts.supported_voices", want_tts["supported_voices"],
         got_cfg["tts"].get("supported_voices")),
        ("evaluation.criteria", body["platform_settings"]["evaluation"]["criteria"],
         (live["platform_settings"].get("evaluation") or {}).get("criteria")),
        ("data_collection", body["platform_settings"]["data_collection"],
         live["platform_settings"].get("data_collection")),
    ]
    rows = []
    for label, want, got in checks:
        missing = _subset_mismatch(want, got)
        shown = json.dumps(got, ensure_ascii=False)
        if label == "prompt text":
            shown = f"{len(got or '')} chars, " + (
                "uses {{learner_level}}" if "{{learner_level}}" in (got or "")
                else "level baked in")
        elif label in ("evaluation.criteria", "data_collection"):
            shown = ", ".join(c["id"] for c in got) if isinstance(got, list) else \
                ", ".join(got or {})
        elif label == "tts.supported_voices":
            shown = ", ".join(f"{v.get('label')}@{v.get('speed')}" for v in got or [])
        elif label == "tts.suggested_audio_tags":
            shown = ", ".join(t.get("tag", "?") for t in got or []) or "none"
        elif label == "client_events":
            shown = f"{len(got or [])} events"
        elif label == "tool_ids":
            shown = f"{len(got or [])} tools"
        elif label == "turn.soft_timeout_config" and isinstance(got, dict):
            shown = f"{got.get('timeout_seconds')}s {got.get('message')!r}"
        if missing:
            shown += f"   <- differs at {', '.join(missing[:3])}"
        rows.append((label, shown[:90], not missing))
    return rows


def verify_agents(pack: ScenePack, tool_ids: dict[str, str], agent_ids: dict[str, str],
                  opts: Options) -> bool:
    ok = True
    live_tools = {t["tool_config"]["name"]: t["tool_config"]
                  for t in call("GET", "/v1/convai/tools").get("tools", [])}
    print("\n  verify tools")
    for name, spec in pack.scenario.tools.items():
        got = live_tools.get(name, {})
        good = (got.get("pre_tool_speech") == spec.pre_tool_speech
                and got.get("description") == spec.description
                and bool(got.get("expects_response")) == spec.expects_response)
        print(f"    {'ok  ' if good else 'DIFF'}  {name:26} "
              f"pre_tool_speech={got.get('pre_tool_speech')} "
              f"expects_response={got.get('expects_response')}")
        ok = ok and good
    for npc in pack.scenario.npcs:
        agent_id = agent_ids.get(npc.npc_id, "<new>")
        print(f"\n  verify {npc.npc_id}  {agent_id}")
        if agent_id == "<new>":
            print("    agent does not exist yet")
            ok = False
            continue
        body = agent_body(pack, npc, tool_ids, opts)
        for label, shown, good in verify_agent(agent_id, body, tts_choice(npc, opts.tts)):
            print(f"    {'ok  ' if good else 'DIFF'}  {label:26} {shown}")
            ok = ok and good
    return ok


def selftest_v3(pack: ScenePack, tool_ids: dict[str, str], npc_id: str,
                opts: Options) -> bool:
    """Prove the Flash -> V3 PATCH path on a throwaway agent, then delete it.

    The live characters stay on Flash because latency is not negotiable, so without
    this the V3 branch would be code nobody has ever run.
    """
    npc = pack.npcs[npc_id]
    body = agent_body(pack, npc, tool_ids, opts, name_suffix=" · v3-selftest")
    agent_id = call("POST", "/v1/convai/agents/create", body)["agent_id"]
    print(f"  created throwaway {agent_id} as Flash")
    try:
        call("PATCH", f"/v1/convai/agents/{agent_id}", v3_patch())
        print("  patched to V3; reading back")
        rows = verify_agent(agent_id, body, "v3")
        for label, shown, good in rows:
            print(f"    {'ok  ' if good else 'DIFF'}  {label:26} {shown}")
        return all(good for _, _, good in rows)
    finally:
        call("DELETE", f"/v1/convai/agents/{agent_id}", raw=True)
        print(f"  deleted throwaway {agent_id}")


def write_env(ids: dict[str, str]) -> None:
    path = ROOT / "orchestrator" / ".env"
    text = path.read_text() if path.exists() else ""
    for npc_id, agent_id in ids.items():
        line = f"AGENT_ID_{npc_id.upper()}={agent_id}"
        pattern = rf"(?m)^AGENT_ID_{re.escape(npc_id.upper())}=.*$"
        text = re.sub(pattern, line, text) if re.search(pattern, text) else \
            text.rstrip("\n") + f"\n{line}\n"
    path.write_text(text)
    print(f"  wrote agent ids into {path.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="actually create/update")
    parser.add_argument("--write-env", action="store_true", help="save ids to orchestrator/.env")
    parser.add_argument("--pack", default=str(default_pack_dir()))
    parser.add_argument("--tts", choices=sorted(TTS_MODELS), default="flash",
                        help="voice model for characters with no tts_model of their own")
    parser.add_argument("--llm", default=LLM,
                        help="character LLM, for A/B runs; must still pass agent_tests.py")
    parser.add_argument("--bake-level", action="store_true",
                        help="write the scenario's level into the prompts instead of "
                             "{{learner_level}}; use until every caller sends that variable")
    parser.add_argument("--verify", action="store_true",
                        help="read the agents back and compare, without changing them")
    parser.add_argument("--selftest-v3", metavar="NPC",
                        help="create a throwaway copy of NPC, PATCH it to V3, verify, delete")
    args = parser.parse_args()

    if not KEY:
        return print("ELEVENLABS_API_KEY is not set (orchestrator/.env)") or 1

    pack = ScenePack.load(args.pack)
    print(f"\n  scenario {pack.scenario.scenario_id}  ({len(pack.npcs)} characters)")
    mode = ("V3 self-test — one throwaway agent is created and deleted" if args.selftest_v3
            else "APPLY" if args.apply else "dry run — nothing will change")
    print(f"  mode     {mode}\n")

    opts = Options(args.tts, args.bake_level, args.llm, reasoning_controls(args.llm))
    if args.selftest_v3:
        if args.selftest_v3 not in pack.npcs:
            return print(f"unknown npc {args.selftest_v3!r}") or 1
        tool_ids = ensure_tools(pack, apply=False)
        return 0 if selftest_v3(pack, tool_ids, args.selftest_v3, opts) else 1

    tool_ids = ensure_tools(pack, args.apply)
    agent_ids = ensure_agents(pack, tool_ids, args.apply, opts)
    verified = True
    if args.apply or args.verify:
        verified = verify_agents(pack, tool_ids, agent_ids, opts)
        print(f"\n  verification {'passed' if verified else 'FAILED — see DIFF rows above'}")

    if args.apply and args.write_env:
        write_env(agent_ids)
    elif args.apply:
        print("\n  add these to orchestrator/.env:")
        for npc_id, agent_id in agent_ids.items():
            print(f"    AGENT_ID_{npc_id.upper()}={agent_id}")
    print()
    return 0 if verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
