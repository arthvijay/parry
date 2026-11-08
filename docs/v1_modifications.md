# v1 modifications: what changed on the server, and what Unity does with it

Written 2026-09-20 for whoever (person or agent) is wiring the Unity client. It is the
working companion to section 18 of `docs/design.md`: that section says *why*; this
file says *what to call*. `docs/api.md` remains the endpoint reference.

**Nothing here breaks the client you already have.** `POST /v1/speech` takes the same
request and returns the same fields as before, plus new ones you may ignore. Every
item below is an upgrade you opt into.

## The idea, in one paragraph

This app is a place to make mistakes. A learner walks into a café in Cancún and gets
a real task done by speaking Spanish with people who talk at native speed, do not slow
down unless asked in Spanish, never switch to English, and never correct you. It is
the counter you freeze at, with nothing at stake. Everything that teaches happens off
to the side: a checklist that ticks quietly, a hint only when you ask, and a plain
report afterwards of what to say differently. The server work in v1 is about making
that feel like a place and a person: the reply starts in about a second, the mouth
moves, the sea is audible, the waitress notices when you are lost, and you can say
anything.

## What a visit can do now

| Moment | What the learner experiences | ElevenLabs does | OpenAI does | Unity does |
| --- | --- | --- | --- | --- |
| Walk in | Waves outside, a low murmur, a ceiling fan | Soundscape made once with the Sound Effects API | | Loop `ocean_loop` and `cafe_murmur_loop`, duck under speech |
| Approach Maria | She greets you at once, in her own voice | Greeting recorded from the agent itself | | Play `/v1/npcs/maria/greeting`; call **warm** at the same time |
| "Quiero un café de olla y una concha" | She answers in about a second: "¿Para tomar aquí o para llevar?" | Scribe hears you; the agent's reply is streamed frame by frame, each frame with mouth shapes | The director reads the turn in the background | Play frames as they arrive; drive visemes |
| "Para tomar aquí" | "Ahorita te lo traigo." A cup lands with a clink, she nods | `serve_order` tool, priced by Python; the nod is inferred from her words at no cost | Goal "order" ticks, quoting your words | Spawn the cup, play the `sfx`, play the gesture |
| You say "quiero una café" | She says "¿UN café? Claro." and carries on | The prompt makes her *recast*: use the right form, never point at the wrong one | The mistake is logged for the report, not shown | Nothing. That is the point |
| You freeze | You press the hint key: what she just said, in English, and two things you could say | | The coach writes them for your level, in under two seconds | Show the hint card; it is counted |
| You hesitate twice | Maria, unprompted, offers two options in one short sentence | A silent stage direction delivered to the live agent | The director reports `stuck` and writes the direction | Nothing |
| "Más despacio, por favor" | She repeats it, genuinely slower, then returns to normal speed | The reply is wrapped in a slow-delivery voice label | | Nothing |
| You ask something off-script: the wifi, what a concha is, to change your order | She answers in character and steers back | Free-form handling in the prompt; a changed order re-prices safely | | Apply the new `serve_order` |
| You cut her off mid-sentence | She stops, and reacts to being interrupted | Frame timing tells the server which words you had actually heard | The transcript keeps only what was heard | Stop playback; send `interrupted_at_ms` with the next turn |
| "¿Cuánto es?" | "A ver, déjame ver. Son ochenta pesos, joven." A receipt prints | `show_bill`; the total comes from Python, in Spanish words | The price goal ticks, when the scenario has one | Show the bill, play the `sfx` |
| Sit with Luis | "Ya vi que pediste café de olla, buena elección." | A second agent; `user_order` handed over through `run_id` | | Same `run_id` for both characters |
| You walk away and come back | He carries on from where you were, no second greeting | The reopened conversation is given the visit so far | | Nothing |
| Leave | The receipt grades each goal. Then a page: three things to say differently, phrases that would have helped, words to practise, how fast the café answered | ElevenLabs' own post-call analysis is configured per agent | Grader and tutor on a stronger model; pronunciation impressions from the learner's own clips | Show `/v1/feedback` |

## What Unity should do, in order of value

Each step stands alone. Step 1 and 2 are the ones a learner feels.

### 1. Warm the session when the player walks up

```
POST /v1/speech/sessions/{session_id}/warm?npc_id=maria&run_id=<visit>&learner_name=<name>&learner_level=A2
→ 204
```

Send it on proximity, at the same moment you start playing the greeting audio. It opens
the character's conversation in the background (about two seconds), so the learner's
first sentence costs the same as every other one. Safe to repeat. Same `session_id`
you will use for that character's turns.

### 2. Switch to the streaming endpoint

```
POST /v1/speech/stream?session_id=…&npc_id=maria&run_id=…&learner_name=…&learner_level=A2
Content-Type: audio/wav          (same body as /v1/speech)
→ 200 application/x-ndjson       one JSON object per line, flushed as it happens
```

```json
{"type":"transcript","text":"Quiero un café de olla","low_confidence_words":["olla"],"stt_ms":402,"min_logprob":-1.9}
{"type":"audio","seq":0,"sample_rate":16000,"offset_ms":0,"pcm_base64":"…","visemes":[{"t":0,"d":46,"v":"sil"},{"t":46,"d":24,"v":"PBM"}]}
{"type":"text","text":"Claro, joven. ¿Para tomar aquí o para llevar?"}
{"type":"action","action":{"action":"play_gesture","npc_id":"maria","gesture":"nod","source":"inferred"}}
{"type":"audio","seq":1,"sample_rate":16000,"offset_ms":1180,"pcm_base64":"…","visemes":[…]}
{"type":"done","timings_ms":{"stt":402,"session_open":0,"first_audio":640,"first_sound":1050,"complete":1900,"total":2300,"reply_audio":3400},"goals_achieved":["order"],"ended":false,"previous_reply_heard":null,"session_id":"…","npc_id":"maria"}
```

- `audio.pcm_base64` is PCM16 little-endian mono at `sample_rate`. **Play each frame as
  it arrives.** Frames arrive faster than real time, so push them into the ring buffer
  the master doc's `PcmStreamPlayer` (section 8) already describes.
- In Unity: `UnityWebRequest` with a `DownloadHandlerScript`; split `ReceiveData` on
  `\n`; parse each complete line. No new package is needed.
- `text` may arrive before or after the audio it describes; show it as the caption.
- `action` is exactly the object you already handle from `actions`.
- `flush` (rare): drop any audio you have buffered for this reply.
- `error`: `{"type":"error","detail":"…"}` then the stream ends. Anything that can be
  rejected up front (bad audio, unknown character) is still a normal HTTP status.
- `done.ended` is true when the character said goodbye and hung up. The next turn
  reopens the conversation with its memory intact.

Measured on the live service, 2026-09-20, warm session, time from the end of the upload
to the first audio frame at the client:

| Turn | Before v1 | Now |
| --- | --- | --- |
| A plain reply | 3 to 5 s | **about 1.0 s** |
| A reply that runs `serve_order` or `show_bill` | 3 to 5 s | **about 1.25 s** |
| The first turn with a character | 5 s or more | **about 1.3 s**, if you called `warm` |
| Luis, who has no tools | 3 to 5 s | **about 1.0 s** |

Roughly 0.35 s of that is hearing the learner (Scribe) and 0.65 to 0.9 s is the
character starting to speak. Four things bought the rest: streaming instead of waiting
for the whole reply; ending a reply when its last character has been voiced instead of
on a 1.4 s silence timer; choosing gestures on the server instead of as a tool call,
which had been costing a second model round trip on most turns; and having Maria say
the order back *before* her tool runs, so the learner hears her at once while the order
is priced. `GET /v1/metrics` reports these live.

### 3. Soundscape

`GET /v1/ambience` lists the sounds with `url`, `loop`, `volume`, `duck_db`, `spatial`.
`GET /v1/ambience/{id}` returns the MP3. Loop `ocean_loop` and `cafe_murmur_loop` on two
AudioSources at the listed volumes, mostly non-spatial, and lower them by `duck_db`
while anyone is speaking or the learner holds the talk key. They must sit *under* a
whisper. `serve_order` and `show_bill` actions carry an `sfx` URL for a one-shot.

### 4. Mouth shapes

Every `audio` line has `visemes`: `t` and `d` in milliseconds on the reply's clock (0 is
the first sample of the first frame), `v` one of
`sil A E I O U PBM FV L S TD KG R CH`. Map them to the avatar's viseme blendshapes and
blend over about 60 ms. `POST /v1/speech?response_format=json` returns the whole
timeline as `visemes`. They come from timing data ElevenLabs sends with the audio, so
they are exact, not estimated from loudness.

### 5. Let the learner interrupt

If the talk key goes down while a character is speaking: stop that AudioSource, note how
many milliseconds of the reply had played, and send it with the next turn as
`&interrupted_at_ms=<ms>`. The server works out which words were actually heard, keeps
only those in the transcript, and tells the character it was cut off, so it reacts like
a person. `done.previous_reply_heard` echoes what it concluded.

### 6. Level, hints and feedback

- `learner_level=A1|A2|B1|B2` on warm and on every turn. It changes how simply and how
  fast the characters speak. Default A2.
- A hint key: `POST /v1/hint {"run_id","npc_id","level"}` →
  `{"meaning_en","suggestions":[{"es","en"}],"tip"}`. Show it as a small card. It is
  recorded, so the report can say how many were used.
- After the receipt: `POST /v1/feedback {"run_id"}` → the written report (fixes,
  useful phrases, what went well, words to practise, pronunciation impressions,
  counters) and an `html_path`. `GET /v1/runs/{run_id}/goals` now also carries
  `learner_state` and the director's latest note, useful as a debug overlay in a demo.

### 7. Things that already work and need nothing

- `run_id`: keep sending the same one to both characters.
- `POST /v1/runs/{run_id}/notes` (your scene notes) is also how the director's stage
  directions reach a character; nothing to change.
- Gestures now arrive on almost every reply, marked `"source":"inferred"`. They are
  chosen from the character's words on the server instead of being a tool call, which
  took a second off most turns.
- `GET /v1/metrics` gives median and 90th-percentile latency per stage per character,
  for a demo overlay or a slide.

## New and changed surface, at a glance

| Endpoint | New? | Purpose |
| --- | --- | --- |
| `POST /v1/speech/stream` | new | A turn, streamed as NDJSON |
| `POST /v1/speech/sessions/{id}/warm` | new | Open the conversation before the first turn |
| `GET /v1/metrics` | new | Measured latency |
| `GET /v1/ambience`, `GET /v1/ambience/{id}` | new | Soundscape and one-shot sounds |
| `POST /v1/hint` | new | What was said, and what you could say |
| `POST /v1/feedback` | new | The written report |
| `POST /v1/speech` | extended | Adds `visemes`, `low_confidence_words`, `timings_ms`, `ended`, `previous_reply_heard`; accepts `learner_level`, `interrupted_at_ms`; sends `Server-Timing` |
| `GET /v1/runs/{run_id}/goals` | extended | Adds `learner_state`, latest director note, counters |

## What the OpenAI side does now

| Piece | Model | When | What it produces |
| --- | --- | --- | --- |
| Director | `gpt-5.6-luna`, reasoning `none` | After every learner turn, never on the reply path | Goal ticks with the learner's own words as evidence; up to three mistakes with corrections; whether they used English or a repair phrase; how they are doing (`fine`, `hesitant`, `stuck`, `distressed`); and, when it helps, one silent stage direction for the character |
| Coach | `gpt-5.6-luna`, reasoning `none`, priority tier | Only when the learner asks | What was just said, in English, and two or three things they could say next at their level. About 1.4 s |
| Tutor | `gpt-5.6-terra`, reasoning `medium` | Once, after the visit | The written report |
| Pronunciation | `gpt-audio-1.5` | Inside the report | Impressions from the two or three clips the recogniser was least sure of. Labelled as impressions: nothing scores pronunciation reliably |
| Scenario generator | `gpt-5.6-terra` | On demand | A new scenario from a sentence |
| Moderation | `omni-moderation-latest` | In parallel with the director | A flag on the run, nothing more |

Rules enforced in code, not left to the model: every quote must be a substring of
something the learner said; a mistake that overlaps a word the recogniser was unsure of
is marked `asr_suspect` and never shown; a stage direction is sent at most once every
three learner turns, and the server sends one itself if the learner is stuck twice
running and the model wrote none.

The director is held to a gate: `eval/director_cases.jsonl` has 40 hand-labelled cases,
22 of them adversarial (the order said in English, a bare "sí", Maria giving the price
unprompted, the character saying the phrase instead of the learner). `eval/run_eval.py`
fails on a single false award. `gpt-5.6-luna` at `none`: **0 false awards**, precision
1.00, recall 0.96, median 1.3 s. `gpt-5.4-nano` at `none` was faster and awarded two
goals wrongly, so it is not used. The full table is in `eval/README.md`.

The pack's goals are currently three easy ones for the demo: `introduce`, `hometown`,
`order`. The eval also covers four harder ones so the judge is tested on the cases that
tempt it.

## Tests

| Command | What it proves | Cost |
| --- | --- | --- |
| `uv run pytest` | 162 tests, all providers mocked | Free |
| `uv run python eval/run_eval.py` | The director never awards a goal wrongly | Cents |
| `uv run python tools/agent_tests.py --run` | On ElevenLabs' own agent-testing API: ordering calls `serve_order`, asking the total calls `show_bill`, a sold-out item does not, English gets Spanish back, Luis never serves. 5 of 5, three times each | About 30 credits a run, no voice minutes |
| `uv run python tools/e2e_check.py` | The whole visit, live, 25 checks | About a minute of agent time |
| `uv run python tools/e2e_stream_check.py` | Streaming, warm, interruption, hint, director state, report, live | About a minute |
| `uv run python tools/latency_bench.py` | The latency table above | About a minute |

## Things worth knowing before a demo

- **ElevenLabs minutes are per account and the first account is spent.** The server now
  runs on the second account, and a third is already staged with voices, tools and
  agents. `uv run python tools/switch_account.py fourth --apply` moves to it; never just
  swap the key, because agents and voices live inside one account. If your shell ever
  exported the old key, start tools with `env -u ELEVENLABS_API_KEY -u AGENT_ID_MARIA
  -u AGENT_ID_LUIS …`: values already in the environment win over `.env`.
- The ambience MP3s were generated and checked for format and length, but nobody has
  listened to the loops for a click at the seam. Do that once.
- The service keeps its own playback clock. If the learner answers before the previous
  line would have finished playing, ElevenLabs treats that as an interruption of it.
  That is accurate, and the server handles it; it is why `warm` and the greeting should
  start together.
- A silent or garbled clip returns 422 and **does not** drop the warm session.
- Characters run on Flash v2.5. The expressive V3 model is wired behind a provisioner
  flag but measured about 1.3 s slower to first audio, so it is off.

## Everything that changed, by file

Server code (`orchestrator/`):

| File | Change |
| --- | --- |
| `elevenlabs_adapter.py` | One streaming code path (`stream`), with `respond` built on it. `warm`. A reply ends when its text has been fully voiced, judged from the frames' alignment data; a turn stays open across a tool call so speech, tool, speech is one reply. Transcription and the socket open run in parallel after a free local audio check. The transcription path is warmed with silence. Per-word confidence from Scribe. `learner_level` always sent. Delivery markup (`<despacio>`, `[laughs]`) stripped from transcripts. A reopened conversation is given the visit so far. A silent clip no longer drops a warm session. A stale correction for the *previous* line is ignored. `ended` when the character hangs up. Timings on every turn |
| `visemes.py` (new) | Spanish graphemes to 14 visemes from alignment data; the heard-so-far prefix for interruptions |
| `gestures.py` (new) | One gesture per reply chosen from the words, never repeated back to back |
| `metrics.py` (new) | p50 and p90 per stage per character |
| `app.py` | `/v1/speech/stream`, `/v1/speech/sessions/{id}/warm`, `/v1/metrics`; shared parsing and bookkeeping for both speech endpoints; learner clips saved to `runs/audio/<run>/`; the director's notes delivered through the scene-notes channel; optional lanes imported defensively so the voice path survives a broken one |
| `speech.py` | Contract extended, additively |
| `director.py`, `models.py` | Reasoning `none`, 4 s timeout, schema warm-up, cache-stable prompt order, the richer verdict, substring and rate-limit rules, persisted insights, moderation |
| `coach.py`, `feedback.py`, `brain_routes.py` (new) | `/v1/hint`, `/v1/feedback`, the HTML report, the pronunciation pass |
| `scene.py`, `ambience.py` (new) | Ambience schema and endpoints; `sfx` on actions; tool `pre_tool_speech`; slow-delivery voice; post-call analysis generated from goals |

Characters and data (`scenarios/cafe_cancun/`):

- Prompts: `{{learner_level}}` behaviour per level; **recasting** instead of correcting;
  free-form topics (recommendations, what a dish is, wifi, bathroom, changing or
  cancelling an order, allergies, small talk); `<despacio>` slow repeats when asked in
  Spanish; one simpler re-ask after a garbled clip; `[WORLD]` notes as facts about the room.
- Agents: `play_gesture` is no longer a tool; `serve_order` and `show_bill` force one
  short spoken line first; the character model runs at reasoning `none` (it had been on
  the provider default); filler "Mmm, a ver..." only after 2.2 s; Flash stability 0.40
  for Maria and 0.35 for Luis; extra client events; ElevenLabs evaluation criteria and
  data collection (`grammar_errors`, `cefr_estimate`, `items_ordered`) per agent.
- `ambience/`: `ocean_loop.mp3`, `cafe_murmur_loop.mp3` (30 s seamless loops),
  `cup_on_table.mp3`, `receipt.mp3`, all made with the ElevenLabs Sound Effects API.

Tools (`tools/`): `provision_agents.py` (`--tts`, `--llm`, `--verify`, `--selftest-v3`),
`make_ambience.py`, `agent_tests.py`, `switch_account.py`, `latency_bench.py`,
`e2e_check.py` (25 checks), `e2e_stream_check.py`. `eval/` holds the director gate.
`AGENTS.md` is the short brief for Codex and other agents.

## Not done, or not yet seen working

Said plainly so nobody builds on sand:

- **Nothing in Unity has changed.** Streaming, warm, ambience, visemes, interruption,
  hints and the report are server features until the client calls them. The classic
  endpoint still gets most of the speed-up (no 1.4 s wait, inferred gestures, forced
  pre-tool speech) but cannot start playing before the whole reply exists.
- A director stage direction reaching a live ElevenLabs socket has been tested with a
  mock, and the channel it rides on (scene notes) is existing working code, but
  the full chain was not observed live: in the live run the learner was judged
  `hesitant`, not `stuck`, so no note was due.
- Only level A2 was exercised live. A1, B1 and B2 exist in the prompts and are untested.
- The `<despacio>` slow repeat lasted one reply in a probe, not the two the prompt asks for.
- The report does not yet include ElevenLabs' own post-call analysis or the visit's
  latency figures. The analysis is configured on the agents; nothing fetches it.
- Not built: handing one live conversation from Maria to Luis (`transfer_to_agent`), and
  live characters for a *generated* scenario. Both are in section 18 as stretch.
- The V3 expressive voice path works (proved on a throwaway agent) and is switched off:
  it measured about 1.3 s slower to first audio.
- The director's median is 1.3 s, not the 1 s hoped for. It runs after the reply has
  gone out, so the learner never waits on it; a tick lands about a second later.
- `gemini-2.5-flash-lite` was tried as the character model and rejected: it called
  `serve_order` one time in three.

## The speed date: what changed after the first Parry build

Everything above is about the café flow (`/v1/speech`). These are the later changes to
the speed date itself; the contract is in [api.md](api.md#speed-date) and the reasoning in
[speed-date.md](speed-date.md).

**Providers.** Both swaps follow the credits available, and each keeps its offline fallback.

| Job | Was | Now | Why it matters |
| --- | --- | --- | --- |
| Hearing the learner | Deepgram live (`nova-3`, `nova-2` for Mandarin), `DEEPGRAM_API_KEY` | NVIDIA Nemotron ASR Streaming over Riva gRPC (`nvidia-riva-client`), `NVIDIA_API_KEY`, `NEMOTRON_ASR_*` | Riva gives words, not speech onsets, so a local voice detector now marks speech start and end. Hosted Nemotron is English only, so non-English dates use NVIDIA's hosted Parakeet 1.1B RNNT Multilingual by default (`NVIDIA_ASR_MULTILINGUAL_FUNCTION_ID` overrides; a self-hosted multilingual Nemotron NIM also works). `Dialect.stt_language` / `stt_model` became `asr_language` |
| The date's voice | Fish Audio (`s2.1-pro`, msgpack socket), `FISH_AUDIO_API_KEY`, `FISH_VOICE_*` | ElevenLabs Flash v2.5 over the `stream-input` WebSocket, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_<DIALECT>_<GENDER>` | `VoiceConfig` is now `{provider: elevenlabs\|sample, voice_id, stability, similarity_boost, speaking_rate 0.7–1.2}`; archetypes carry `voice_stability` instead of `voice_temperature`. Without a voice set, a premade multilingual voice speaks. `ormsgpack` is no longer a dependency |

`/health` and `session_ready` now report `stt: nemotron` and `tts: elevenlabs`.

**Features.**

- **The demo date.** `POST /v1/matchmaker/preset` and `scenarios/speed_dating/presets/`:
  Café Rayuela, an Argentine café in Cancún, written by hand so a demo is the same every
  time. `DateScenario` gained `preset_id`, `menu`, `currency`, `serve_line`, `closings`,
  `followups` and `generated_by: "authored"`; the catalog gained `presets`. Unity: a
  **▶ Demo date** button, and Play pressed straight in a venue plays it.
- **Ordering moves the scene.** A fifth milestone, `order_together`, still needs a quote.
  When it ticks, the server sends `scene_action`, the host walks over (`bring_order` in
  `npcs_cancun.json`, `NpcSchedule.MoveFinished`), the client answers
  `scene_event: host_at_table`, and the host serves the order by name.
- **The translator.** `{"type":"help"}` → `help_card` (meaning in English, three replies, a
  tip). Counted in `help_requests`, which costs a little on the pacing pillar. Key T.
- **Your date, decoded.** `POST /v1/date/report` and `GET /v1/date/report/{run_id}.html`
  (`date_report.py`): what landed, up to three fixes, phrases, culture notes, practice
  words, pronunciation impressions from saved clips, the full conversation. The stream
  now saves each recognised learner line as a WAV under `runs/audio/{run_id}/`. Keys Tab
  (learning page) and L (open in the browser) on the receipt.
- **Register.** `Dialect.formal_marker` (*usted*, *vous*, 您) costs chemistry as "too
  formal for a date". It replaces matching `usted`, `vous`, 您 and あなた様 as red flags in
  every dialect.
- **Dialect files** gained a `culture` list (used by the offline report). They were also
  reformatted, one item per line.
- **Grading.** An authored date's own `followups` (and `<kind>_en` translations) replace
  the dialect's; its `closings` replace the dialect's goodbyes.
- **Gamified and shareable.** A full-width live match bar replaces the chemistry
  meter. The verdict prints as a thermal receipt with a stamp. `DateVerdict` gained
  `roast` (quotes checked), `next_date` (a match unlocks the next dialect,
  `config.NEXT_DIALECT`; `Dialect.nickname` names it) and `share_path`. Verdicts are
  saved under `VERDICT_DIR`; `share_card.py` serves the 9:16 card
  (`/v1/date/receipt/{run_id}.svg`) and the share page (`/v1/date/share/{run_id}`).
  Unity: S shares, N opens the matchmaker on the unlocked dialect.
- **Webcam.** `VisionFeed` tries colour cameras before infrared (face-login) ones, moves
  on if one won't start, and frees the device properly; the camera survives scene loads.
- **Editor helpers.** `Editor/OpenDemoScene.cs` opens the matchmaker scene on an empty
  editor; `Editor/EditorRemote.cs` lets a script drive the editor for headless testing.
  The client's `MenuItem` became `CafeMenuItem`, so it no longer clashes with Unity's
  `[MenuItem]` in editor scripts.
- **Recognition timing.** The start of an utterance now survives the voice detector's
  "speech ended" arriving before the final words, so measured latency and clip cuts are
  right.

**Merged from `features/10-fea-enhance`.** Culture as data (`nonverbal`, `fillers`,
`register`, `other_region_slang`, `cultural_moments` in every dialect file), memory
across dates (`learner_profile.py`, `practice` on the scenario, `progress` on the
verdict), filler and register measures, the cost ledger (`costs.py`, `cost` on the
verdict, `GET /v1/costs`, `PLAN=free`, Claude prompt caching for the judge), the voice
cache for scripted lines, the readable receipt page, learner profiles and the class
report (`share_routes.py`), one verdict store (`run_records.py`, shared with the 9:16
share page) and `eval/date_selfplay.py`. The branch predated the provider switch, so
its cost and cache hooks were ported to Nemotron and ElevenLabs
(`NVIDIA_ASR_PRICE_PER_MINUTE`, `ELEVENLABS_PRICE_PER_MILLION_CHARS`). Its self-play
gate failed on the branch (15 false awards: echoing learners, and plain English in
Hinglish); both holes are closed (`echoes_the_date`, the Hinglish English check) and
the gate now passes.

**Tests.** 245 (`uv run pytest`), with the Nemotron path tested against a local Riva gRPC
server and ElevenLabs against a local WebSocket server. `tools/test_e2e_pipeline.py` now
plays the demo date: it orders, waits for the host to serve, asks the translator, then
checks the verdict (with its roast, unlock and shareable card) and the report.
