# Orchestrator API

> **New in v1:** streaming replies, session pre-warm, mouth shapes, soundscape, hints, the
> written report and measured latency. The full contract, with examples and the order to adopt
> them in, is `docs/v1_modifications.md`. Everything below still works unchanged.

Python 3.11+, managed with [uv](https://docs.astral.sh/uv/). Run from the repository root:

```sh
uv sync                      # creates .venv and installs the locked dependencies
cp orchestrator/.env.example orchestrator/.env   # then fill in the values
uv run python -m orchestrator
```

`uv sync` reads `pyproject.toml` and `uv.lock`, so everyone gets the same versions.
`uv run` re-syncs automatically before executing, and needs no activated virtualenv.

Without uv, the generated exports still work:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r orchestrator/requirements-dev.txt
.venv/bin/python -m orchestrator
```

Configuration comes from `orchestrator/.env` (or, as a fallback, the repo-root `.env`), or
from the environment, which takes precedence:

```sh
export OPENAI_API_KEY='your-key'
export SCENARIO_MODEL='your-structured-output-capable-model'
export ELEVENLABS_API_KEY='your-key'
export AGENT_ID_MARIA='...'   # see tools/provision_agents.py
export AGENT_ID_LUIS='...'
```

The server listens on `127.0.0.1:8765`. Interactive documentation: `/docs`;
OpenAPI schema: `/openapi.json`; readiness flags: `/health`. Running `python -m orchestrator` loads `orchestrator/.env`, then the repo-root `.env`; exported environment
variables take precedence. Never commit credentials. Direct Uvicorn startup requires exported variables. This is a local development API, without
public authentication or cross-origin browser access configured.

## The café scenario, and who you can talk to

The server ships with an authored scenario, `scenarios/cafe_cancun/`. You walk into
Café Nader in Cancún. **Maria**, the waitress, meets you at the door, walks you to
the window table and takes your order. **Luis** is already sitting there; he is the
person you came to meet. Order from Maria, converse with Luis.

```sh
curl http://127.0.0.1:8765/v1/npcs
```

Returns the cast so the client does not hardcode anything: for each character an
`npc_id` (send this as `npc_id`), `name`, `role`, `gender`, the `greeting` text (the
opening line the character says on `warm`, for a caption or an offline fallback), the
scene `actions` it can trigger, `aliases`, and `ready` —
false when no agent id is configured for it. An alias is an older id that still
resolves to the same character, so a client that has not been renamed keeps working;
`mariana` currently resolves to `maria`. Also returns the `menu`, the `goals` and the valid
`gestures`. 503 if no scenario pack is loaded.

Characters are created and updated from the scenario files by
`tools/provision_agents.py`; agent ids then live in `orchestrator/.env` as
`AGENT_ID_MARIA` and `AGENT_ID_LUIS`. Prices live only in `menu.json` — the server
does the arithmetic, so a character can never invent a total.

## Scene actions

A character can act on the world mid-conversation. Actions come back with the turn
that caused them, in `actions`, in order. **The conversation never waits for the
client**: the server answers the character immediately and reports the action to you
afterwards, so a slow or absent renderer can never stall speech.

| Action | Who | Payload |
| --- | --- | --- |
| `serve_order` | Maria | `items` (menu ids), `to_go`, `total_mxn`, `total_words_es` |
| `show_bill` | Maria | `total_mxn`, `total_words_es`, `items` |
| `play_gesture` | Maria, Luis | `gesture` — one of the `gestures` from `/v1/npcs`; `source: "inferred"` |

Every action also carries `action` and `npc_id`. Gestures are no longer a tool the
character calls (that cost a second model round trip on most turns); the server picks
at most one per reply from the character's words, never the same one twice running. `serve_order` declares the **whole**
order and replaces any previous one, so repeating it never double-charges.

```json
{"action": "serve_order", "npc_id": "maria", "items": ["cafe_olla", "concha"],
 "to_go": false, "total_mxn": 80, "total_words_es": "ochenta"}
```

When you request raw audio instead of JSON, the same list arrives in the
`X-Scene-Actions` response header, omitted if it would be unreasonably large.

## Prompt → structured scenario and response

```sh
curl http://127.0.0.1:8765/v1/scenarios \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Order coffee in Cancún, then chat with a friend","language":"Mexican Spanish","level":"A2"}'
```

Returns `{scenario_id, scenario, response}`. The scenario includes title, setting,
language, CEFR level, characters (id, name, role, instructions, opening_line), and
goals (id, description, evidence_required, npc_id, core). `response` introduces the
exercise to the learner; it is not generated speech. Fetch the saved result using
`GET /v1/scenarios/{scenario_id}`. Local JSON files live in `runs/scenarios` or
`SCENARIO_DIR`. IDs are UUIDs; persistence survives restarts.

Generation uses the OpenAI Responses API with Pydantic structured output, following
[official documentation](https://developers.openai.com/api/docs/guides/structured-outputs).
The server rejects invalid references, changed language/level, incomplete outputs,
and refusals rather than returning fabricated scenarios. It does not create Unity
assets or provision ElevenLabs agents.

## Speech → speech

```sh
curl -X POST 'http://127.0.0.1:8765/v1/speech?session_id=de305d54-75b4-431b-adb2-eb6b9e546014&npc_id=luis' \
  -H 'Content-Type: audio/wav' --data-binary @input.wav --output reply.audio
```

Use the returned Content-Type to decode the audio. Reuse a client-generated
`session_id` UUID for conversation continuity. Supply `scenario_id` to load a
saved scenario and validate the NPC. Add `response_format=json` to receive
`audio_base64`, `media_type`, `sample_rate`, `user_transcript`, `agent_transcript`,
`actions`, `goals_achieved` (goal ids the director had ticked *before* this turn; see
Goal tracking), `session_id`, and `npc_id`. Transcripts may be null. Also returned, and
safe to ignore: `visemes` (see Mouth shapes), `low_confidence_words` (words the
recogniser was unsure of), `timings_ms` (where the time went; also sent as a
`Server-Timing` header), `ended` (the character said goodbye and hung up; the next turn
reopens the conversation with its memory intact) and `previous_reply_heard` (see
Interruption).

Optional query parameters that make the café scenario work properly:

| Parameter | Why |
| --- | --- |
| `run_id` | Groups one visit. Send the **same** value to Maria and to Luis and he will know what you ordered from her. Each character has its own `session_id`, so without `run_id` nothing carries across. `[A-Za-z0-9_-]`, up to 64 characters. |
| `learner_name` | How the characters address the player. Defaults to `amigo`. |
| `learner_level` | `A1`, `A2`, `B1` or `B2`. Changes how simply the characters speak, never who they are. Defaults to the scenario's level (`A2`). Send it on `warm` and on every turn. |
| `interrupted_at_ms` | Set when the learner cut the previous reply short: how many ms of it had played. See Interruption. |

```sh
curl -X POST 'http://127.0.0.1:8765/v1/speech?session_id=<uuid>&npc_id=maria\
&run_id=visit-1&learner_name=Alex&response_format=json' \
  -H 'Content-Type: audio/wav' --data-binary @input.wav
```

Close a character's session when the player walks away. Agent time is billed by how
long the connection stays open, so this is worth doing promptly.

Supported media types: audio/wav, audio/x-wav, audio/mpeg, audio/webm, audio/ogg,
audio/mp4, audio/pcm. Raw PCM is signed PCM16 little-endian mono and requires the
`sample_rate` query parameter (8000–48000). Containers are decoded/validated by
the speech adapter. Each request/response is at most 10 MiB; scenario requests
are at most 32 KiB. Provider calls time out after 60 seconds. These are complete
HTTP turns. For a reply that starts playing before it is finished, see Streaming.

### Warming a session

```
POST /v1/speech/sessions/{session_id}/warm?npc_id=maria&run_id=<visit>&learner_name=<name>&learner_level=A2
→ 200 {"agent_transcript": "¡Buenas tardes! …", "audio_base64": "…", "media_type": "audio/wav",
       "sample_rate": 16000, "user_transcript": null, "actions": [], "visemes": [], …}
→ 204 when the conversation was already open
```

Opens the character's conversation (about a second) and returns their opening line,
spoken live by the agent in their own voice — the same JSON shape as
`/v1/speech?response_format=json`, with no learner side. Call it when the player walks
up and play the audio; the learner's first sentence then costs the same as every other
one instead of five seconds or more. The greeting is recorded in the run transcript as
an `npc` turn. Safe to repeat: a conversation that is already open has already said
hello, so the second call is 204 with no body. Same `session_id` as the turns that
follow. A silent or garbled clip on the first turn returns 422 and does **not** drop
the warm session. A first `/v1/speech` turn on a session that was never warmed still
works; the greeting is simply never heard.

### Streaming

```
POST /v1/speech/stream?session_id=…&npc_id=maria&run_id=…&learner_name=…&learner_level=A2
Content-Type: audio/wav          (same body and query parameters as /v1/speech)
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
  it arrives**; frames come faster than real time, so push them into a ring buffer.
- In Unity: `UnityWebRequest` with a `DownloadHandlerScript`; split `ReceiveData` on
  `\n`; parse each complete line. No new package is needed.
- `text` may arrive before or after the audio it describes; show it as the caption.
- `action` is exactly the object you already handle from `actions`.
- `flush` (rare): drop any audio you have buffered for this reply.
- `error`: `{"type":"error","detail":"…"}`, then the stream ends. Anything that can be
  rejected up front (bad audio, unknown character) is still a normal HTTP status.
- `done.ended` is true when the character said goodbye and hung up.

Measured on the live service (2026-09-20, warm session, end of upload to first audio
frame at the client): about **1.0 s** for a plain reply, **1.25 s** for one that runs
`serve_order` or `show_bill`, against 3 to 5 s before. The classic endpoint gets most
of the saving too (a reply now ends when its last word has been voiced instead of on a
1.4 s silence timer) but cannot start playing before the whole reply exists.
`GET /v1/metrics` reports p50 and p90 per stage per character, live.

### Mouth shapes

Every `audio` line has `visemes`, and `POST /v1/speech?response_format=json` returns the
whole timeline as `visemes`: `t` and `d` in milliseconds on the reply's clock (0 is the
first sample of the first frame), `v` one of `sil A E I O U PBM FV L S TD KG R CH`. They
come from the timing data ElevenLabs sends with the audio, so they are exact, not
estimated from loudness. Map them to the avatar's viseme blendshapes and blend over
about 60 ms.

### Interruption

If the talk key goes down while a character is speaking: stop that AudioSource, note
how many milliseconds of the reply had played, and send it with the next turn as
`interrupted_at_ms`. The server works out which words were actually heard, keeps only
those in the transcript, and tells the character it was cut off, so it reacts like a
person. `previous_reply_heard` echoes what it concluded.

### Built-in ElevenLabs integration

The adapter is selected automatically when `ELEVENLABS_API_KEY` is set. Configure
`AGENT_ID_MARIA`, `AGENT_ID_LUIS`, or `AGENT_ID_<NPC_ID>` for each NPC used by the
client. For beginner Luis, set `AGENT_ID_LUIS_BEGINNER` and use `npc_id=luis_beginner`.
No agent IDs are hardcoded. `SMOKE_AGENT_ID` is supported as a fallback for Luis.
A generated scenario must use character IDs that have configured agents.

The flow adapts the scripts from commit `71b8d80`: uploaded audio is transcribed
using ElevenLabs Scribe (`ELEVENLABS_STT_MODEL`, default `scribe_v2`), then the
transcript is sent as `user_message` through the signed-URL voice-agent socket.
The built-in adapter returns PCM wrapped in WAV (`audio/wav`), so save it as
`reply.wav`. This introduces a separate transcription request and is not realtime
microphone streaming. See the official [transcription API](https://elevenlabs.io/docs/api-reference/speech-to-text/convert)
and [agent WebSocket protocol](https://elevenlabs.io/docs/eleven-agents/libraries/web-sockets).

Left to pick the language itself, Scribe hears a learner's accented Spanish as
Italian, Portuguese or English and the character answers the wrong sentence. Every
clip is therefore transcribed pinned to the scenario's language (`language` in
`scenario.json`). Constructing `ElevenLabsSpeech` with several `languages` restores
detection among them, with one extra transcription (logged at INFO) when the guess
falls outside.

Agent output must be PCM; its sample rate is read from session metadata. Enable
agent_response and audio client events. The initial greeting is captured for `warm`
to return and kept out of the first reply. A reply is complete when its text has been fully voiced,
judged from the alignment data that arrives with each audio frame; a turn stays open
across a tool call so speech, tool, speech is one reply. Transcription and the socket
open run in parallel. Scene tool calls are priced and answered by the server, and
reported to the client as `actions`; see Scene actions above. Asked in Spanish to slow
down, a character wraps its next sentences in a slower voice (`<despacio>`, stripped
from transcripts).

Characters on the same `run_id` overhear each other: after a turn, every other open
session on that run whose character differs gets a `contextual_update` with what the
learner said and how the character answered, marked as not addressed to them. A session
opened later does not get earlier turns; it starts from the run state (`{{user_order}}`).
A conversation that is reopened (after `ended`, or after the idle close) is given the
visit so far, so the character carries on rather than greeting again.

### Scene notes

```sh
curl -X POST http://127.0.0.1:8765/v1/runs/visit-1/notes -H 'Content-Type: application/json' \
  -d '{"npc_id": "luis", "key": "floor", "text": "Maria is walking over to take the order."}'
```

Tells one character something about the scene without anyone taking a turn: who has just
walked up, whose turn it is to speak. The game sends these from its NPC schedule (the
`tell` list on a move in `npcs.json`) so Luis stops ending his lines on a question the
moment Maria is on her way, and picks up again when she leaves. The note goes out at once
as a `contextual_update` to that character's open session on the run, and is repeated
when their conversation (re)opens while it stands. A later note with the same `key`
replaces the earlier one; an empty `text` withdraws it. 204 on success, 422 for a bad
`run_id` or body, 503/501 without a speech adapter that supports notes. The prompts
tell both characters what to do with a "Scene note".

Connections retain conversation memory per session UUID and are closed when the
NPC/scenario changes, on error/cancellation, after 120 seconds idle, or on shutdown.
Overlapping turns for one session are rejected with 422. Up to 64 sessions are
retained. Use one server worker; session memory is process-local and is lost on
restart or expiry. Close a session immediately when the user finishes:

```sh
curl -X DELETE http://127.0.0.1:8765/v1/speech/sessions/YOUR_SESSION_UUID
```

Saved scenario content is sent as a contextual update to the configured agent;
it does not override that agent's system prompt, voice, or language configuration.
The standalone voice demo scripts remain unchanged. The beginner demo modifies the
remote agent speed when invoked; the API adapter does not modify agent settings.

### Optional custom speech adapter

Implement a zero-argument synchronous factory returning an object with:

```python
from orchestrator.speech import SpeechInput, SpeechOutput

class VoiceProvider:
    async def respond(self, request: SpeechInput) -> SpeechOutput:
        # Implement transcription/conversation/voice generation here.
        ...

    async def aclose(self):
        # Optional: clean up sessions/connections at server shutdown.
        ...

def create_provider():
    return VoiceProvider()
```

Set `SPEECH_ADAPTER=package.module:create_provider`. Input contains audio bytes,
media type, session UUID, NPC ID, optional scenario UUID and validated scenario
dictionary, and optional PCM sample rate. Return SpeechOutput containing bytes,
media type, sample rate when PCM, and optional transcripts. The provider owns
session memory, concurrency/ordering per session, expiration, decoding, provider
credentials, and cancellation cleanup. It must not block the event loop.

The API does not import the ElevenLabs SDK. Without ElevenLabs credentials or a
custom adapter, speech returns 503. Unknown/unconfigured NPC agents also return
503. `SPEECH_ADAPTER` overrides the built-in implementation when set. Tests mock
provider HTTP/WebSocket responses; they do not represent live voice validation.

## Goal tracking and grading

The characters never know they are being graded. The server records what was said; a
director ticks goals off a turn behind the conversation, and a grader judges the whole
run afterwards against the scenario's goals.

### What the server records

Every `/v1/speech` turn appends to the run it belongs to: the learner's transcript,
the character's reply, and one line per scene action the character triggered. Nothing
extra is needed from the client — send `run_id` (the same value you already send so
Luis knows what you ordered) and tracking happens on its own. Without a `run_id` the
`session_id` is used instead, which records each character separately.

```sh
curl http://127.0.0.1:8765/v1/runs/visit-1
```

```json
{"run_id": "visit-1", "turn_count": 3, "transcript": [
  {"role": "learner", "npc_id": "maria", "text": "Quisiera un café de olla, por favor."},
  {"role": "npc", "npc_id": "maria", "text": "Claro que sí, ¿algo más?"},
  {"role": "event", "npc_id": "maria", "text": "serve_order items=cafe_olla total_mxn=45"}]}
```

`event` lines are not speech: they are things that actually happened in the game, so a
goal can be checked against `serve_order` having fired rather than inferred from
wording alone. Recording is best effort and never fails a speech turn. Files are JSON
Lines under `runs/transcripts` (`RUN_DIR`), capped at 1 MiB and 400 turns read back.
404 for an unrecorded run, 422 for a `run_id` outside `[A-Za-z0-9_-]{1,64}`.

### Ticking goals during the run

```sh
curl http://127.0.0.1:8765/v1/runs/visit-1/goals
```

```json
{"run_id": "visit-1", "reviewing": false, "goals": [
  {"id": "introduce", "label": "Introduce yourself to Maria", "core": true, "npc_id": "maria",
   "achieved": true, "evidence_quote": "Hola, me llamo Alex."},
  {"id": "hometown", "label": "Tell Luis where you're from", "core": true, "npc_id": "luis",
   "achieved": false, "evidence_quote": null},
  {"id": "order", "label": "Order something in Spanish", "core": true, "npc_id": "maria",
   "achieved": false, "evidence_quote": null}]}
```

Every `/v1/speech` turn that heard the learner schedules one review of the run *after*
the reply has been sent, so the character never waits on the judge. The review covers
every goal still open, not just the latest line, which is why a slow or failed review
costs nothing: the next turn looks again. `reviewing` is true while the latest turn is
still being judged — poll a second or two after a reply and again while it stays true.
A goal is ticked only with the learner's exact words as `evidence_quote`, and once
ticked stays ticked; the grader below decides how well it was done. Goal ids are the
client's quest ids. Pass `scenario_id` to track a generated scenario's goals instead of
the pack's. State is one small JSON file per run under `runs/transcripts/goals/`
(`GOAL_DIR`). 503 when no director is configured (`OPENAI_API_KEY` plus
`DIRECTOR_MODEL`, falling back to `TUTOR_MODEL`; `director_ready` on `/health`). The
director sends `reasoning: {effort: none}`, so the model must be one that accepts a
reasoning parameter (a gpt-5.x model); a gpt-4.x model fails every review silently.

The response also carries what the director noticed: `learner_state`
(`fine`, `hesitant`, `stuck`, `distressed`), `mistake_count`, `last_note` and
`counters`. Useful as a debug overlay. `last_note` is also slipped to the character as a
scene note, at most one per three learner turns; the learner is never shown a
correction mid-run.

A quote must be a substring of something the learner actually said, checked in code,
not trusted from the model. `eval/director_cases.jsonl` holds 40 hand-labelled
transcripts, 22 of them adversarial (the order said in English, a bare "sí", Maria
giving the price unprompted, the character saying the phrase instead of the learner);
`uv run python eval/run_eval.py` fails on a single false award. See `eval/README.md`.

### Grading a finished run

```sh
curl http://127.0.0.1:8765/v1/grade \
  -H 'Content-Type: application/json' \
  -d '{"scenario_id":"<uuid>","run_id":"visit-1"}'
```

The response is the receipt the game prints at the end of a visit: one line per goal,
keyed by the goal's id (the café's goals use the same ids as the client's quests, so
each score lands on its quest line), a letter grade **A+ … F** for how well the learner
did it in the target language, and one sentence of feedback. `grade` is `null` when
the goal never came up — the learner never sat down with Luis — which is not the same
as failing it. `overall` is the weighted mean of the letters (core goals count double;
an unattempted core goal is an F, an unattempted optional one is left out), and
`summary` is two or three sentences addressed to the learner, in English.

```json
{"overall": "B+", "goals_passed": 2, "goals_total": 3,
 "scenario_id": null, "run_id": "visit-1",
 "scores": [
   {"id": "introduce", "grade": "A", "evidence_quote": "Hola, me llamo Alex.",
    "comment": "You introduced yourself right at the door: «hola, me llamo Alex»."},
   {"id": "hometown", "grade": null, "evidence_quote": null,
    "comment": "You never got round to telling Luis where you're from."},
   {"id": "order", "grade": "A",
    "evidence_quote": "Quiero un café de olla y una concha, por favor.",
    "comment": "You ordered clearly: «quiero un café de olla y una concha, por favor»."}],
 "summary": "Confident from the door to the order. Next time tell Luis where you're from when he asks, and try a follow-up about his turtles."}
```

The letters sit on the scale the client averages with: F is 0, D- is 0.7, then 0.3 a
step up to A+ at 4.0. C- and up is a pass.

Both inputs have three sources, checked in order:

| Input | Order |
| --- | --- |
| The rubric | inline `goals` → the goals of a saved `scenario_id` → the loaded scenario pack |
| The conversation | inline `transcript` → whatever the server recorded for `run_id` |

So a client that already sends `run_id` needs only `{"run_id": "..."}`, one that
generated a scenario adds `scenario_id`, and one that keeps its own transcript can
post `goals` and `transcript` and let the server store nothing. Generated goals
(`description`) and authored pack goals (`label`) are normalised to one rubric shape,
so either source grades the same way.

**A goal is only passed with the learner's own words quoted as evidence.** A grade
that passes a goal without an `evidence_quote`, or that judges a different goal set
than it was given, is rejected as provider failure rather than returned. Bodies are capped at
256 KiB; the transcript at 400 turns and the rubric at 12 goals.

Grading uses the OpenAI Responses API with Pydantic structured output, configured by
`OPENAI_API_KEY` and `TUTOR_MODEL` (falling back to `SCENARIO_MODEL`); 503 when
neither is set, and `grader_ready` on `/health` says which. A 502 with `grader_ready`
true is usually a mistyped model name: the server log names the exception class. It
is the build doc's end-of-run tutor; the director above is its per-turn counterpart.

## Errors and checks

Errors use `{"detail": ...}`. Statuses: 404 unknown scenario or unrecorded run; 413 oversized body;
415 unsupported content type; 422 invalid inputs; 503 missing provider configuration;
502 provider failure/refusal/invalid output; 504 provider deadline exceeded.
Provider exception details are not returned to clients.

```sh
uv run pytest                        # 90 tests, no credentials needed
uv run python tools/e2e_check.py     # live end-to-end, needs a running server
```

Tests require no credentials and cover persistence, scenario-to-speech handoff,
validation, missing configuration, audio responses, timeouts, provider errors,
run recording, and grade rejection. Live provider checks require an ElevenLabs key
and configured agent IDs. The build doc's per-turn director, its live goal ticks and
actor steering, the Unity WebSocket bridge and realtime streaming voice are not
implemented; this is a complete-turn HTTP API.

---

## Speed date

The speed date's routes sit beside the café's; the café contracts above are unchanged.

`GET /health` has a `date` object saying what each part runs on: `matchmaker`
(`claude` / `templates`), `chemistry` and `grader` (`claude` / `rules`), `brain`
(`gemini` / `claude` / `scripted`), `stt` (`nemotron` / `none`), `tts` (`elevenlabs` /
`sample`) and `face` (`ready` / `loading` / `unavailable` / `off`). `stt` is `nemotron`
when `NVIDIA_API_KEY` is set or `NEMOTRON_ASR_SERVER` points at a self-hosted NIM.

| Route | What it does |
| --- | --- |
| `GET /v1/matchmaker/catalog` | Authored `presets`, dialects (with cities), venues, personalities, appearances, levels, genders |
| `POST /v1/matchmaker/generate` | Builds one date from the learner's choices |
| `POST /v1/matchmaker/preset` | An authored date, the same every time (below) |
| `GET /v1/matchmaker/{scenario_id}` | A date built earlier |
| `POST /v1/avatar/from-selfie` | `image/jpeg` in; skin and hair colours sampled around the face landmarks out |
| `WS /v1/stream` | The live date (below) |
| `WS /v1/vision` | Face tracking alone (onboarding): `face_frame` in, `face_analysis` and `signal` out |
| `POST /v1/grade` | With a `date_…` scenario id: the verdict receipt (also `POST /v1/date/grade`) |
| `GET /v1/date/runs/{run_id}` | The recorded transcript, the chemistry state and the `cost` of a run |
| `POST /v1/date/report` | *Your date, decoded* for a run: `{"run_id","scenario_id"}` |
| `GET /v1/date/report/{run_id}.html` | The same report as a self-contained page |
| `GET /v1/date/receipt/{run_id}.svg` | The shareable receipt, 1080×1920 (9:16), from the saved verdict |
| `GET /v1/date/share/{run_id}` | The share page: download, system share sheet, TikTok / Reels / Shorts |
| `GET /v1/date/runs/{run_id}/card` | The graded verdict as a shareable HTML page |
| `GET /v1/date/runs/{run_id}/verdict` | The stored verdict as JSON, without re-grading |
| `GET /v1/learners/{name}` | One learner's profile: their dates and their practice list |
| `GET /v1/reports/class` | Every learner at a glance (HTML; `?format=json` for data, `?learners=a,b` to filter) |
| `GET /v1/costs` | Usage and dollars by provider since the server started, and the `plan` |
| `GET /v1/face/status` | Whether MediaPipe and its model are loaded |

### `POST /v1/matchmaker/generate`

```json
{
  "learner_name": "Arth",
  "language": "es-AR",
  "proficiency": "B2",
  "venue_style": "auto",
  "date_gender": "female",
  "date_ethnicity": "latina",
  "personality_archetype": "playful_sarcastic",
  "custom_notes": "Loves indie rock and photography, hates crypto bros",
  "scene_prompt": "a rooftop bar at sunset after the rain",
  "city": null
}
```

- `language`: one of `es-MX es-AR es-ES zh-CN hi-IN ja-JP ja-JP-kansai fr-FR`.
- `venue_style`: a venue id or `auto` (the scene prompt chooses).
- `date_ethnicity`: an appearance id. It drives the 3D model only and never reaches the persona.
- `personality_archetype`: `playful_sarcastic`, `warm_romantic`, `reserved_intellectual` or `high_energy_creative`.

The response is a `DateScenario`:

- **The date:** `scenario_id` (`date_…`), `city`, `language_code`, `dialect`, `venue`, `venue_scene` (the Unity scene), `lighting_preset`, `scene_description`.
- **`date_character`:** name, age, occupation, interests, backstory, `avatar_config` (base model, skin and hair tint, resting smile), `voice_config` (ElevenLabs voice id, stability, similarity, speed), `opening_line`, the live `system_prompt`, `green_flags`, `red_flags`.
- **`host_character`:** with a `greeting`.
- **`milestones`:** `break_ice`, `find_common_ground`, `cultural_vibe` and `close_the_date`, each with `evidence_required` and `core`. An authored date can add `order_together`.
- **Timing:** `date_seconds` (180), `wingman_seconds`, `chemistry_start` (50).
- **`generated_by`:** `model`, `template`, or `authored` for a preset.
- **The café (authored dates only):** `preset_id`, `menu`, `currency`, `serve_line`, `closings`, `followups`. Empty on a generated date.
- **`cultural_moment`:** `{id, milestone, cue, keywords}`, the local custom this date
  brings up about a minute in (mate in Buenos Aires, a tsukkomi in Osaka). Its
  `milestone` replaces the `cultural_vibe` milestone's text, whose evidence then accepts
  either the moment or local slang. Can be null.
- **`practice`:** up to two `{heard, better, why_en}`: phrasings this learner (by
  `learner_name`) got wrong on earlier dates in this dialect, which the date gives them a
  natural chance to say. Empty for a new learner.

Claude writes the creative fields; code writes the ids, voice, avatar parameters and the
system prompt, so its speaking style, chemistry protocol and safety rules are the same
for every date. Without `ANTHROPIC_API_KEY`, or when the model fails, the dialect's
authored templates build the date.

### `WS /v1/stream`

The first message must be `init`. After that the client streams the microphone as
binary frames and sends JSON control messages; the server streams the speaking
character's voice as binary frames and sends JSON events.

**Client → server**

| Message | When |
| --- | --- |
| binary | Microphone: 16 kHz PCM16 LE mono, 20–40 ms per frame, continuously |
| `{"type":"init","run_id","scenario_id","npc_id":"host"\|"date_npc"}` | First |
| `{"type":"focus","npc_id":"host"}` | Walked up to the host: the host greets |
| `{"type":"start_date"}` | Seated at the table: opening line, clock starts |
| `{"type":"telemetry","is_looking_at_date","gaze_target","look_away_duration_sec","player_smiling","distance_m","is_seated"}` | Every 250 ms |
| `{"type":"face_frame","jpeg_base64"}` | ~8 per second, ~320 px wide |
| `{"type":"barge_in","timestamp_ms"}` | The client's voice detector heard the learner over the date |
| `{"type":"user_text","text"}` | Typed instead of spoken |
| `{"type":"playback_done","npc_id"}` | The last frame of a line has played (starts the wingman's 4 s) |
| `{"type":"help"}` | The translator: answered with a `help_card` |
| `{"type":"scene_event","event":"host_at_table"}` | The host reached the table with the order |
| `{"type":"end_date","reason":"timer"\|"quit"}` | The bell |

**Server → client**

| Message | Meaning |
| --- | --- |
| binary | The voice: 24 kHz PCM16 LE mono, for the NPC named by the last `audio_start` |
| `session_ready` | Joined; `providers` says which are live: `stt` (`nemotron` / `none`), `tts` (`elevenlabs` / `sample`), `brain` (`gemini` / `claude` / `scripted`), `judge` (`claude` / `rules`), `face` (`mediapipe` / `off`) |
| `audio_start` `{npc_id, turn_id, kind, first_audio_ms}` | Voice frames for this NPC follow (`kind`: greeting, opening, reply, callout, closing, serve) |
| `audio_end` `{npc_id, turn_id, duration_ms}` | Last frame of the line sent |
| `transcript` `{speaker, text, is_final, confidence}` | Subtitles: the learner's line filling in, the date's line sentence by sentence |
| `chemistry_update` `{chemistry_score, delta, mood_label, reason, npc_posture, completed_milestones, evidence_quotes, green_flags_hit, red_flags_hit, source}` | After every learner turn, and on non-verbal events |
| `wingman_hint` `{whisper_context, options:[{tone, target, gloss}×3]}` | 4 s of silence after the date finished |
| `clear_audio` `{npc_id}` | Acknowledges a barge-in: drop everything buffered |
| `face_analysis` `{found, blendshapes, head:{pitch,yaw,roll}, contours, mesh, frame, analysis_ms, expressions}` | One per analysed webcam frame |
| `signal` `{kind, label, effect, during_npc}` | A smile, laugh, nod, head shake, head wobble (only where it means yes: hi-IN), puzzled or surprised look, look-away, look-back |
| `user_speech` `{speaking}` | The recogniser heard speech start or end |
| `help_card` `{said, meaning_en, suggestions:[{target, gloss}]×1–3, tip}` | The translator's answer. Without Claude, `meaning_en` says translation needs the key and the suggestions are the wingman's lines |
| `scene_action` `{action:"order_placed", npc_id:"host", items}` | An order was placed (once per date): send the host to the table |
| `date_started` `{seconds}` / `date_ended` `{verdict, chemistry_score, run_id, scenario_id}` | The clock |
| `notice`, `error` `{detail, fatal}` | Human-readable problems |

**Barge-in.** Voice is sent at most ~0.8 s ahead of playback, so on `barge_in` the server
knows roughly what was heard. It stops generating, sends `clear_audio`, and records the date's line cut to
that point, plus an `event` line saying the learner interrupted.

**What the date notices.** `[CHEMISTRY]`, `[NONVERBAL]` and `[SCENE]` notes are added to
the date's prompt each turn:

- the chemistry score and mood;
- what the face tracker and gaze saw since their last line;
- the time left when under 45 s.

Looking away too long while the date talks costs chemistry and triggers an in-character
callout after the line ends. How long is too long, and what it costs, is the dialect's
norm (`nonverbal` in its data file): 4 s in Buenos Aires, 8 s in Tokyo.

Slang from another region ("güey" in Buenos Aires) gets a light in-character reaction
and a small chemistry note naming the region.

**The translator.** `help` is answered with a `help_card` for the learner's eyes only:
nothing is said to the date. It adds an `event` line to the transcript and counts in
`metrics.help_requests`.

**Too formal.** Each dialect can name what stiff, textbook address sounds like
(`formal_marker` in `config.py`: *usted* in the Spanish dialects, *vous* in French, 您 in
Mandarin). The rules judge takes a little chemistry for it ("too formal for a date").
Japanese and Hinglish have no marker, because polite speech there is normal and warm.

**The learner's voice.** The server keeps the last 30 s of microphone audio and, at each
final recognised line, saves that line as `runs/audio/{run_id}/turn_NNN.wav` with a
`.json` of what was heard (up to 60 per run). The report's pronunciation pass reads them.

### `POST /v1/grade` (speed date)

```json
{"run_id": "run_…", "scenario_id": "date_…"}
```

The response is a `DateVerdict`:

- **`verdict`:** `match` at 65+, `friendzone` at 45–64, `ghosted` below. This comes from the final chemistry, in code.
- **The stamp:** `stamp` in the dialect, with `stamp_en`.
- **`pillars`:** each with `grade` A+…F, `comment` and `evidence_quote`.
  - `icebreaker`, `dialect_authenticity` and `active_listening` are judged.
  - `agility_pacing` is measured: latency, recogniser confidence, wingman use, and a small cost per translator use.
- **`milestones`:** each with its quote.
- **`metrics`:** turns, words, average response latency, pronunciation confidence, wingman hints and lines used, unassisted fluency, eye contact, smiles, look-away callouts, barge-ins, `help_requests`; and, measured from the learner's lines, `local_fillers` and `foreign_fillers` (a local «este…» versus an English «um»), `register_used` (`casual`, `formal`, `mixed` or null), `words_to_practise` (words the recogniser doubted) and `other_region_words`.
- **`followup`:** a text from the date in the dialect, its translation, and one `correction` drawn from the learner's words. An authored date's own `followups` replace the dialect's.
- **`progress`:** `[{better, quote}]`, earlier dates' phrasings said right on this one, quoted.
- **`cost`:** `{lines: [{provider, model, calls, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, audio_seconds, characters, characters_cached, usd}], total_usd, complete}` for the whole date (matchmaker, live date, grade). `usd` is null for a provider with no configured price; `complete` says whether every line was priced.
- **Also:** `overall`, `summary`, `chemistry_timeline` and `graded_by` (`model` or `rules`).
- **`roast`:** one short, affectionate English line about how the date went (at most
  160 characters). Claude writes it; any quote in it (in «», “” or "") must be the
  learner's own words, checked against the transcript, or the line is replaced by an
  offline one built from the metrics (wingman lines, translator peeks, English turns,
  look-away callouts, the verdict).
- **`next_date`:** `{kind, dialect, label, city, headline}`. A match is `unlocked`: the
  next dialect on a fixed trip (`config.NEXT_DIALECT`: es-MX → es-AR → ja-JP-kansai →
  fr-FR → zh-CN → es-ES → hi-IN → ja-JP → es-MX), e.g. *NEXT DATE UNLOCKED · KANSAI-BEN,
  OSAKA*. Friendzone and ghosted are a `rematch` in the same dialect and city (*REMATCH ·
  …*, *TRY AGAIN · …*).
- **`share_path`:** `/v1/date/share/{run_id}`.

Every graded verdict is saved as `VERDICT_DIR/{run_id}.json` (default `runs/verdicts`),
so the receipt can be shared after the fact.

A judged pillar graded C- or better must quote the learner's own words, checked against
the transcript, and must not be the date's own line repeated back (an echo);
otherwise it is capped at D+. The `correction` must also be the learner's
own words, and is never one built on a word the recogniser was unsure of. A register
remark (tú or usted) is added to the dialect pillar's comment only; it never moves a grade.

Grading also stores the verdict (for the card), adds the date to the learner's profile
when the date had a `learner_name`, and records its cost.


### `POST /v1/matchmaker/preset`: authored dates and the café

```json
{"preset": "cafe_cancun_ar", "learner_name": "Arth", "proficiency": "B1", "date_gender": "female"}
```

- `preset`: a file in `scenarios/speed_dating/presets/` (default `cafe_cancun_ar`). The
  catalog's `presets` lists them with `label`, `summary`, `dialect`, `city`, `lat`, `lon`
  and `default_proficiency`. An unknown id is a 404.
- `proficiency`: optional; the preset's `default_proficiency` otherwise.
- `date_gender`: `female` or `male`; each preset authors both variants (Café Rayuela:
  Valeria or Tomás).

The response is a `DateScenario` with `generated_by: "authored"`. Only who the learner is
can change; the person, place and lines are fixed, so a demo is the same every time. It
goes through the same code as a generated date (voice, avatar, persona rules), plus the
café, which is also written into the date's prompt so it can recommend things and never
invents items or prices:

- `menu` (items with prices and the aliases a learner might say), `currency`, and
  the host's `serve_line`;
- its own `closings` and `followups`.

Ordering works like this:

1. The `order_together` milestone ticks (quoted, as always).
2. The server matches the menu items in the quote (longest alias first, accents
   ignored) and sends `scene_action`. If the quote names no item, it uses what the
   learner said this date; failing that, the first menu item.
3. The client walks the host over (the `bring_order` move in `npcs_cancun.json`) and
   reports `scene_event: host_at_table`.
4. The host serves with the serve line, after the date finishes their sentence.

### Sharing the receipt

`GET /v1/date/receipt/{run_id}.svg` draws the saved verdict as a 1080×1920 card: the
receipt paper (chemistry, the four pillars with the learner's quotes, the unlock
headline), the stamp across it, the roast, and the date's follow-up text when it fits.
It is plain SVG (no external resources), so a browser can turn it into a PNG.

`GET /v1/date/share/{run_id}` is the page around it:

- **Share…** turns the card into a PNG and opens the system share sheet
  (`navigator.share` with a file; on a phone, that is where TikTok, Instagram and
  YouTube are). Without one, it saves the image and copies the caption.
- **Download image** saves the PNG.
- **TikTok / Reels / Shorts** save the image, copy the caption, and open
  `tiktok.com/upload`, `instagram.com` or `youtube.com/upload`. Nothing is posted for
  the learner; there are no platform accounts or API keys involved.
- **Copy caption**: the verdict, the date's name and city, the chemistry, the roast and
  hashtags.

Both return 404 until the run has been graded and 422 for a malformed `run_id`.

### `POST /v1/date/report`

```json
{"run_id": "run_…", "scenario_id": "date_…"}
```

*Your date, decoded*: the learning page for a finished date. A 404 if the date or run was
never recorded. It can take tens of seconds with Claude, so the client fetches it while
the learner reads the verdict. The `DateReport` contains:

- `run_id`, `scenario_id`, `date_name`, `dialect`, `verdict`, `final_chemistry`;
- `summary`;
- `went_well` (a learner quote);
- up to three `fixes` (`heard` → `better`, `why_en`);
- three `useful_phrases` in the dialect;
- `culture_notes`;
- `practice_words` (words the recogniser doubted);
- `pronunciation` (Gemini's impressions of up to three recorded clips, only naming words
  that were said) and its `pronunciation_disclaimer`;
- the `chemistry_timeline`, the full `transcript` (`learner`, `date`, `host`, `event`
  turns) and `counters` (lines, wingman hints and lines used, help requests, English and
  local-slang turns, smiles, look-away callouts);
- `next_date`, `written_by` (`model` or `rules`) and `html_path`.

The report is saved as JSON and HTML under `REPORT_DIR` (default `runs/reports`).
`GET /v1/date/report/{run_id}.html` serves the page, with a 404 until the report has been
written.

Every learner quote is checked against the transcript, and nothing built on a doubted word
is shown as a mistake. Without Claude the dialect's authored lines write a plainer
report. The pronunciation pass needs Gemini (`PRONUNCIATION_MODEL`, default the date's
model) and is skipped with `PRONUNCIATION=0`; if it fails, the page goes out without it.
