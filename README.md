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
| Hearing the learner | NVIDIA Nemotron ASR Streaming (Riva gRPC; `es-US` for Argentine Spanish) | `NVIDIA_API_KEY` (+ `NEMOTRON_ASR_FUNCTION_ID` or a self-hosted NIM for Spanish) | voice detection only; type with Enter |
| The date's voice | ElevenLabs streaming TTS (`eleven_flash_v2_5`) | `ELEVENLABS_API_KEY` | a bundled sample voice |
| Face, smiles, nods, head pose | MediaPipe Face Landmarker (local) | none (`uv sync --group face`) | no face; the date carries on |

`GET /health` reports which of these are live (`"date": {...}`).

## The demo date: Café Rayuela, Cancún

Click **▶ Demo date** in the matchmaker (or press Play straight in `CancunCafe.unity`) for
the authored date, the same every time: `scenarios/speed_dating/presets/cafe_cancun_ar.json`.

- **The place.** Café Rayuela, an Argentine-owned café two blocks from the beach in Cancún.
- **The people.** Don Julio, the porteño owner, greets you at the door and walks you to
  the window table. **Valeria** (or **Tomás** if you choose a man) is waiting there: an
  editorial photographer from Palermo who moved to Cancún to shoot the reefs.
- **How they talk.** Rioplatense voseo (*vos sos, tenés, decime*), *che*, *posta*, *re*.
- **The opener.** She complains that her last date spent ten minutes on his stock
  portfolio and recommends the medialunas.
- **The menu.** M shows the carta: cortado, medialunas, submarino, alfajores, tostado…
  Order in Spanish and Don Julio walks over and serves it.
- **Five milestones:** introduce yourself, order something to share, find common ground,
  talk like a porteño, and ask for her WhatsApp.

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
   - **T** opens the **translator**: what the date just said, in English, plus three
     replies. It's counted, gently, in the pacing grade.
6. **The verdict.** At the bell the date says goodbye in character. The receipt shows:
   - **The stamp:** MATCH (65+), FRIENDZONED (45+) or GHOSTED.
   - **Four graded pillars**, each with a verbatim quote.
   - **The measured pacing.**
   - **A text from the date**, with one correction drawn from what you said.

   **Tab** flips to the learning page. **L** opens *Your date, decoded* in the browser,
   with:
   - what landed, in your words;
   - up to three things to say differently;
   - phrases in the dialect for the moments you stalled;
   - how people really talk there;
   - words to practise;
   - a coach's ear on your recorded voice;
   - the whole conversation.

   **R** tries again with the same date; **N** goes to the next table.

## How the pieces talk

```
Unity                                      orchestrator (FastAPI, :8765)
─────                                      ─────────────────────────────
MatchmakerUI ── POST /v1/matchmaker/generate ──▶ matchmaker.py ─▶ Claude
AvatarOnboarding ── POST /v1/avatar/from-selfie ─▶ face_tracker.py (MediaPipe)
VisionFeed ── WS /v1/vision (before the date) ───▶ face_tracker + nonverbal.py

FullDuplexStreamClient ═══ WS /v1/stream ═══▶ stream_gateway.py
  mic 16 kHz PCM16 ─────────────────────────▶   stt.py (Nemotron ASR, Riva gRPC)
  telemetry 250 ms, webcam frames ──────────▶   nonverbal.py, face_tracker.py
  barge_in / start_date / end_date ─────────▶   chemistry_director.py ─▶ Claude
  ◀───────── 24 kHz PCM16 voice frames ─────    date_brain.py (Gemini) ─▶ tts.py (ElevenLabs)
  ◀── transcript, chemistry_update, wingman_hint, face_analysis, signal, clear_audio
DateVerdictReceipt ── POST /v1/grade ───────▶ date_grader.py ─▶ Claude
```

The protocol is documented in [docs/api.md](docs/api.md#speed-date) and the design
in [docs/speed-date.md](docs/speed-date.md).

## Repository

- `orchestrator/`: the Python service.
  - `config.py` holds the brand, dialects, venues, personas, models and voices.
  - The speed-date modules are `matchmaker.py`, `stream_gateway.py`, `chemistry_director.py`, `date_grader.py`, `stt.py`, `tts.py`, `date_brain.py`, `face_tracker.py`, `nonverbal.py`, `claude.py` and `date_routes.py`.
  - The original café modules (`/v1/speech`, `/v1/scenarios`, `director.py`, `grading.py`) are kept and still pass their tests.
- `scenarios/speed_dating/dialects/*.json`: authored lines per dialect (host, openers per personality, look-away callouts, wingman fallbacks, closings, verdict stamps, follow-up texts, culture notes).
- `scenarios/speed_dating/presets/cafe_cancun_ar.json`: the authored demo date.
- `orchestrator/date_report.py`: *Your date, decoded* (Claude writes it; Gemini listens to the recorded voice clips).
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
uv run pytest                                  # 205 tests, no network
uvx ruff check orchestrator tools eval
uv run python tools/test_e2e_pipeline.py --offline   # starts a server, plays a whole date
uv run python tools/test_e2e_pipeline.py             # same, with your keys
```

ElevenLabs and Nemotron ASR are tested against local servers speaking their real protocols (a Riva gRPC server for Nemotron).
The Claude request shape is tested against a mock transport.

## Limits worth knowing

- **Avatars.** Two Rocketbox bodies, tinted. Ready Player Me shut down on 31 January 2026,
  so a selfie colours an avatar rather than reshaping its face.
- **Worlds.** The scene prompt chooses between the scanned worlds and re-lights them; it
  doesn't generate new 3D geometry live.
- **Voices.** Set ElevenLabs voices per dialect and gender with
  `ELEVENLABS_VOICE_<DIALECT>_<GENDER>` (for the demo, porteño voices from the Voice Library
  added to My Voices); otherwise a premade multilingual voice speaks every dialect.
- **Echo.** Use headphones. The client gates echo while the date talks, but speakers next
  to the mic still make barge-in less reliable.
