# Parry

*Keep up. Flirt back. Speak like a local.*

Parry is a cultural speed-dating simulator for language learners. The learner scans
their face, picks a dialect and the kind of person they want to meet, types the scene,
and lands in a 3D venue for a three-minute date with an AI character. There's no
push-to-talk: they just talk. The date answers in a streamed voice, reads their face
and gaze, warms up or cools off, and at the bell either asks for their number or ghosts
them. The receipt that follows grades how they actually spoke, quoting their own words.

Dialects: Mexican, Argentine and Castilian Spanish, Mandarin (Shanghai / Beijing),
Hinglish (Mumbai / Delhi), Japanese (Tokyo and Osaka Kansai-ben), and Parisian French.

The product name lives in one file, `My project/Assets/Resources/BrandConfig.json`,
which both the Unity client and the orchestrator read.

## Quick start

```sh
uv sync --group face            # Python deps + MediaPipe for webcam face tracking
cp orchestrator/.env.example orchestrator/.env   # add whichever keys you have
uv run python -m orchestrator   # http://127.0.0.1:8765, /docs for the API
```

Open `My project/` in Unity 6 (6000.0.x) and press Play in `Assets/Scenes/Wish.unity`.

Every key is optional. Without one, that part falls back, so the whole flow runs offline:

| Job | Provider | Key | Offline fallback |
| --- | --- | --- | --- |
| Building the date (persona, opener, flags, venue) | Claude `claude-sonnet-5-5` | `ANTHROPIC_API_KEY` | authored dialect templates |
| Live chemistry judge, wingman lines | Claude (effort `low`) | same | a rules judge, authored wingman lines |
| Final receipt and follow-up text | Claude | same | a rules grader |
| The date's live replies | Gemini `gemini-3.8-flash` | `GEMINI_API_KEY` or Vertex (`GOOGLE_CLOUD_PROJECT`) | Claude, then a scripted date |
| Hearing the learner | Deepgram live (`nova-3`; `nova-2` for Mandarin) | `DEEPGRAM_API_KEY` | voice detection only; type with Enter |
| The date's voice | Fish Audio live TTS (`s2.1-pro`) | `FISH_AUDIO_API_KEY` | a bundled sample voice |
| Face, smiles, nods, head pose | MediaPipe Face Landmarker (local) | none (`uv sync --group face`) | no face; the date carries on |

`GET /health` reports which of these are live (`"date": {...}`).

## The demo, end to end

1. **Face scan** (`Wish.unity`). A live webcam viewfinder. *Capture selfie* sends the
   photo to `POST /v1/avatar/from-selfie`, where MediaPipe finds the face and samples
   skin from the cheeks and hair from above the hairline. Those colours tint the
   learner's chosen Rocketbox body, which is rendered live beside the photo and already
   mirrors their expressions. The **vision panel** in the corner shows the camera with
   the face mesh over it, the expression levels, head pose and a feed of signals.
2. **Language.** Dialect, city and level. The low-poly globe turns and pins the city.
3. **Your date.** Gender, appearance (3D look only), personality, venue or *let my
   prompt decide*, a free-text scene ("a rooftop bar at sunset after the rain") and
   notes ("loves indie rock, hates crypto bros"). *Start Speed Date* calls
   `POST /v1/matchmaker/generate` and shows who you're meeting, then the globe flies you
   into the clouds and the venue loads.
4. **The venue.** The scene prompt picks one of the scanned worlds and re-grades it with
   a lighting preset (post-processing, so the Gaussian splat changes too), plus ambient
   sound. The host greets you in the dialect when you walk up and leads you to the table.
5. **The date.** Sit down (F) and the bell rings: 3:00 on the clock. The mic is open.
   - **Chemistry** (0–100, from 50) moves after every line you say, judged off the
     reply path, with the reason shown.
   - **Milestones** tick only with your own words as evidence.
   - **Smiling** at a joke helps. **Looking away** for 4.5 s while the date talks gets
     called out in character.
   - **Barge-in:** talk over the date and they stop mid-word.
   - **Wingman:** freeze for 4 s and the wingman whispers three options.
   - **V** toggles the cinematic two-shot, where your avatar, wearing your live face,
     sits across from them.
6. **The verdict.** At the bell the date says goodbye in character. The receipt shows:
   - **The stamp:** MATCH (65+), FRIENDZONED (45+) or GHOSTED.
   - **Four graded pillars**, each with a verbatim quote.
   - **The measured pacing.**
   - **A text from the date**, with one correction drawn from what you said.

   **R** tries again with the same date; **N** goes to the next table.

### What makes it more than a chatbot

- **Body language is local.** Each dialect file says what eye contact and a glance away
  mean there: the date in Tokyo lets a look away go for 8 s, the one in Buenos Aires
  notices after 4. In Mumbai and Delhi the head wobble reads as "yes, go on".
- **Every city has its moment.** Mate in Buenos Aires, a spice dare in Mexico City, a
  tsukkomi in Osaka, a compliment to deflect in Shanghai. The date raises it about a
  minute in, and it becomes that date's cultural milestone.
- **Locals hear where you learned it.** Say «güey» in Buenos Aires and the date teases you
  about sounding Mexican.
- **The app remembers you.** A phrase you got wrong comes back on your next date in that
  dialect. The date steers toward it without teaching, and the receipt says when you got
  it right, quoting you.
- **Nothing is corrected that may not have been said.** A correction built on a word the
  recogniser doubted is dropped; those words become "words to practise" instead.
- **How you hesitate counts.** A local «este…» or «えーと» is noticed, and so is an English
  «um». So is how you address the date (vos or tú, tú or usted, 你 or 您).
- **Every date has a price.** Provider usage is recorded per date (tokens and cache hits,
  seconds heard, characters spoken), priced where prices are known, and shown on the
  receipt and at `GET /v1/costs`. `PLAN=free` runs the per-turn judge on the rules. The
  judge's prompt is cached, and scripted lines are voiced once, then played from disk.
- **Shareable and reportable.** `/v1/date/runs/{run_id}/card` is the receipt as a page
  to share; `/v1/reports/class` shows a whole class at a glance.

## How the pieces talk

```
Unity                                      orchestrator (FastAPI, :8765)
─────                                      ─────────────────────────────
MatchmakerUI ── POST /v1/matchmaker/generate ──▶ matchmaker.py ─▶ Claude
AvatarOnboarding ── POST /v1/avatar/from-selfie ─▶ face_tracker.py (MediaPipe)
VisionFeed ── WS /v1/vision (before the date) ───▶ face_tracker + nonverbal.py

FullDuplexStreamClient ═══ WS /v1/stream ═══▶ stream_gateway.py
  mic 16 kHz PCM16 ─────────────────────────▶   stt.py (Deepgram live)
  telemetry 250 ms, webcam frames ──────────▶   nonverbal.py, face_tracker.py
  barge_in / start_date / end_date ─────────▶   chemistry_director.py ─▶ Claude
  ◀───────── 24 kHz PCM16 voice frames ─────    date_brain.py (Gemini) ─▶ tts.py (Fish)
  ◀── transcript, chemistry_update, wingman_hint, face_analysis, signal, clear_audio
DateVerdictReceipt ── POST /v1/grade ───────▶ date_grader.py ─▶ Claude
```

The protocol is documented in [docs/api.md](docs/api.md#speed-date) and the design
in [docs/speed-date.md](docs/speed-date.md).

## Repository

- `orchestrator/`: the Python service.
  - `config.py` holds the brand, dialects, venues, personas, models and voices.
  - The speed-date modules are `matchmaker.py`, `stream_gateway.py`, `chemistry_director.py`, `date_grader.py`, `stt.py`, `tts.py`, `date_brain.py`, `face_tracker.py`, `nonverbal.py`, `claude.py` and `date_routes.py`.
  - What outlives a date: `learner_profile.py` (memory across dates), `costs.py` (the cost ledger), `voice_cache.py`, `run_records.py` (the stores) and `share_routes.py` (the share page, class report and costs).
  - The original café modules (`/v1/speech`, `/v1/scenarios`, `director.py`, `grading.py`) are kept and still pass their tests.
- `scenarios/speed_dating/dialects/*.json`: authored lines per dialect (host, openers per personality, look-away callouts, wingman fallbacks, closings, verdict stamps, follow-up texts), plus its culture as data: body-language norms (`nonverbal`), hesitation words (`fillers`), how people address each other (`register`), other regions' slang a local would notice (`other_region_slang`) and the local moment the date brings up (`cultural_moments`). The norms are tendencies, written to be checked and tuned by native speakers.
- `My project/`: the Unity 6 (URP) client. Scenes: `Wish.unity` (matchmaker), `CancunCafe.unity` (primary venue), `SampleScene.unity` (fallback venue).
- `tools/test_e2e_pipeline.py`: headless end-to-end check against a running server.
- `tools/spz_to_collider.py`: builds a walkable collider `.glb` from a Gaussian splat.

### Unity scripts

| Script | Job |
| --- | --- |
| `Lobby/MatchmakerUI.cs` | The three-step studio over the globe; matchmaking; the flight to the venue |
| `Lobby/AvatarOnboarding.cs` | Webcam viewfinder, selfie, avatar built from it, live preview |
| `Vision/VisionFeed.cs` | Webcam service: frames to the face tracker, latest reading, signal feed |
| `Vision/VisionPanel.cs` | The on-screen computer vision panel |
| `Vision/LocalFaceController.cs` | The learner's blendshapes and head pose on an avatar |
| `Vision/PlayerAvatar.cs` | The learner's seated avatar for the cinematic view |
| `Conversation/FullDuplexStreamClient.cs` | The `/v1/stream` socket, open mic, voice activity, barge-in, telemetry |
| `Conversation/StreamingAudioPlayer.cs` | Ring-buffer playback of streamed voice; audio analysis for lip-sync |
| `Conversation/ChemistryAndWingmanHUD.cs` | Timer, chemistry meter, milestones, subtitles, wingman card, type-to-talk |
| `Conversation/SpatialTelemetryBroadcaster.cs` | Eye contact, gaze target, look-away time, seat |
| `Conversation/ScenarioClient.cs`, `CastClient.cs` | The date into the venue: milestones, lighting, cast |
| `Npc/DateBodyLanguage.cs` | Lean, smile, frown, blinks from chemistry |
| `Npc/NpcSpeaker.cs` | Streamed voice at the mouth; jaw and vowel visemes from the audio |
| `Npc/NpcLookAt.cs` | Eye contact, boredom glances, gaze reciprocity |
| `Seating/DateCameraRig.cs` | V: first person ↔ cinematic two-shot |
| `Quests/DateVerdictReceipt.cs` | The verdict card and the phone follow-up |
| `Venue/VenueAmbience.cs` | Post-processing grade, lights and ambient loops per venue |
| `Core/DateBootstrap.cs` | Adds the speed-date systems to any venue scene at load |

## Tests

```sh
uv run pytest                                  # 227 tests, no network
uvx ruff check orchestrator tools eval
uv run python tools/test_e2e_pipeline.py --offline   # starts a server, plays a whole date
uv run python tools/test_e2e_pipeline.py             # same, with your keys
uv run python eval/date_selfplay.py --offline        # simulated learners; fails on any false award
```

Fish Audio and Deepgram are tested against local servers speaking their real protocols.
The Claude request shape is tested against a mock transport.

## Limits worth knowing

- **Avatars.** Two Rocketbox bodies, tinted. Ready Player Me shut down on 31 January 2026,
  so a selfie colours an avatar rather than reshaping its face.
- **Worlds.** The scene prompt chooses between the scanned worlds and re-lights them; it
  doesn't generate new 3D geometry live.
- **Voices.** Configure Fish Audio voice models per dialect and gender with
  `FISH_VOICE_<DIALECT>_<GENDER>`; otherwise Fish's default voice speaks every dialect.
- **Echo.** Use headphones. The client gates echo while the date talks, but speakers next
  to the mic still make barge-in less reliable.
