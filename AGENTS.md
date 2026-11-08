# AGENTS.md

Rules for Codex and any other coding agent working in this repo. Short on purpose.

## Read first

0. The product is **Parry**, a cultural speed-dating simulator. `README.md`,
   `docs/speed-date.md` (design) and `docs/api.md#speed-date` (the contract Unity reads)
   describe it. The sections below about the café (Maria, Luis, the menu) cover the
   original `/v1/speech` flow, which is kept working.
1. `docs/design.md`, **section 18**: what is built,
   the components still to build (C1 to C14) with the files each one owns, the latency
   targets and the cut order. It is the master spec. Never edit it unless asked.
2. `docs/v1_modifications.md`: what changed from the original plan and why.
   `docs/api.md` is the contract the Unity client reads.

## Rules

- Run `uv run pytest` after every edit, and `uvx ruff check orchestrator tools`. Both
  must be clean before you stop. Use `uv` only: never `pip install`, never add a
  dependency without being asked.
- **Never loosen "no quote, no tick".** A goal is awarded only when the grader can
  quote the learner's own words that earned it. Do not relax that to make a test or a
  demo pass; a false award is worse than a missed one.
- The product name lives only in `My project/Assets/Resources/BrandConfig.json`; Python
  reads it through `orchestrator/config.py`. Never hardcode it anywhere else.
- Unity scenes reference scripts by GUID. Renaming a script means renaming its `.meta`
  with it; new systems are attached at runtime by `Core/DateBootstrap.cs` rather than by
  editing scene YAML. Never touch `Assets/` (large committed binaries).
- **Dialects are data.** What each dialect's characters can say offline (host, openers,
  callouts, wingman lines, closings, stamps, follow-ups) is in
  `scenarios/speed_dating/dialects/*.json`; registries are in `orchestrator/config.py`.
  Keep learner-facing lines gender-neutral about the learner.
- Run `uv run python tools/test_e2e_pipeline.py --offline` after changing the stream.
- Secrets live only in `orchestrator/.env`, which is git-ignored. Never print, log,
  commit or paste a key, and never put one on a command line.
- **Characters are data.** Maria and Luis are defined in `scenarios/` (`scenario.json`,
  `menu.json`, `prompts/*.md`). To change how a character talks or what it can do, edit
  those files, then run the provisioner. Never configure an agent by hand in the
  ElevenLabs dashboard; the next run would overwrite it.

```sh
uv run python tools/provision_agents.py            # dry run: what would change
uv run python tools/provision_agents.py --apply    # update the agents, then verify
uv run python tools/agent_tests.py --run           # ElevenLabs-side regression tests
```

- Prices come only from `menu.json` and Python does the arithmetic. A character never
  invents a price or a menu item.
- A prompt may only use the dynamic variables the adapter always sends
  (`learner_name`, `user_order`, `learner_level`). A missing one fails the whole
  conversation.
- Live agent minutes are scarce (15 per free account). Prefer `agent_tests.py`, which
  is text-only, over opening voice conversations. Move accounts only with
  `tools/switch_account.py`.
