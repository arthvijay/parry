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

`GET /health` reports which of these are live (`"date": {...}`). To check the webcam
tracker on its own, `GET /v1/face/status` should return `"available": true`. If it says
`ModuleNotFoundError`, run `uv sync --group face`.

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
     called out in character. Looking away counts when the game camera is off the date
     or when your real face says so (see *What the webcam reads* below).
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

## What the webcam reads

`face_tracker.py` runs MediaPipe Face Landmarker on ~8 frames a second (320 px JPEGs).
It reads 52 ARKit blendshapes, the head's pitch, yaw and roll, and the face mesh.
`nonverbal.py` turns those into the signals a person across the table would notice.

**The model.** Google's stock [MediaPipe Face Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker)
(`face_landmarker.task`, float16, version 1). We have not trained or fine-tuned it.

| | |
| --- | --- |
| Where it runs | Locally, on the CPU, inside the orchestrator. Unity only captures the webcam and sends JPEGs. |
| File | Downloaded once from Google's model bucket to `runs/models/face_landmarker.task` (3.6 MB). Checked against a pinned SHA-256, so a modified file is refused. `FACE_MODEL_PATH` points at another copy. |
| Settings | Image mode, one face, detection/presence/tracking confidence 0.5 (MediaPipe's defaults). Blendshapes and the head's transform matrix turned on. |
| Throughput | One worker thread. A frame that arrives while the last is still being read is dropped, so the panel shows the newest face rather than a backlog. Each `face_analysis` reports `analysis_ms`. |
| Turning it off | `FACE_TRACKING=0`, or skip `uv sync --group face`. The date carries on with gaze from the game camera alone. |
| Privacy | Frames are analysed in memory and never written to disk. No image is sent to Gemini, Claude or any other cloud model. The language models only get the text notes below ("they smiled while you were talking"). The selfie is used for skin and hair colour, nothing else. |

All the tuning is in `nonverbal.py`, which sits on top of the model. Its thresholds are
hand-set and have been checked by hand, not measured against a labelled dataset:

| Signal | Fires when (blendshape weights 0 to 1, above your resting face) | Held for |
| --- | --- | --- |
| Smile | mean of `mouthSmileLeft/Right` > 0.45 | 0.35 s |
| Laugh | smile > 0.5 and `jawOpen` > 0.3 (wins over smile) | 0.25 s |
| Puzzled | smile < 0.2, and brows down > 0.35 or (inner brow up > 0.35 and squint > 0.3) | 0.8 s |
| Surprised | inner brow up > 0.5, eyes wide > 0.3, jaw open > 0.2 | 0.3 s |
| Frown | mouth frown > 0.35 and smile < 0.15 | 0.7 s |
| Nod / head shake | two pitch reversals of 4° or more (yaw: 6°) within 1.5 s, while the other axis stays steadier | at most one per 1.5 s |
| Looking away (face) | head turned > 28° or tilted > 20° from centre, eyes aside > 0.65 (not blinking), or no face for 1 s | 0.5 s |
| Look-away callout | looking away for 4.5 s while the date is talking (`LOOK_AWAY_CALLOUT_SECONDS`) | once per episode |

Each signal fires once per occurrence and must lapse (0.4 to 0.8 s) before it can fire
again, so a flicker doesn't count.

- **Calibrated to you:** every expression is measured against your own resting face: the
  20th percentile of the last 160 frames (~20 s), used once 12 frames (~1.5 s) have
  arrived. It is capped (0.15 to 0.3 depending on the shape) so a long real smile still
  counts, and readings are rescaled so the full 0 to 1 range is still reachable. A resting
  furrowed brow isn't read as "puzzled".
- **Camera position doesn't matter:** the head's centre is learned from where you
  normally face the screen, so a webcam off to the side or below your chin isn't read
  as looking away. Looking away never moves that centre.
- **The face can overrule the game camera:** any of these is looking away, even if the
  in-game view is on the date:
  - head turned more than 28° from centre;
  - head tilted 20° up or down (a phone in your lap);
  - eyes held off to one side;
  - face out of frame for a second.

  Blinks and quick glances are ignored. If no frames arrive, the game camera's gaze
  stands alone. Eye contact % on the receipt uses this combined answer.
- **Where it goes:** the vision panel's feed, the date's prompt (`[NONVERBAL]` notes),
  and the chemistry meter. Each `face_analysis` message also carries `calibrated`,
  `attentive` and `away_reason` (`head_turned`, `head_tilted`, `eyes_aside`,
  `out_of_frame`).
- **After the date:** `date_ended` carries a `face` summary: frames analysed,
  `face_visible_pct`, `attentive_pct`, and signal counts overall and while the date
  was talking.

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
  - The original café modules (`/v1/speech`, `/v1/scenarios`, `director.py`, `grading.py`) are kept and still pass their tests.
- `scenarios/speed_dating/dialects/*.json`: authored lines per dialect (host, openers per personality, look-away callouts, wingman fallbacks, closings, verdict stamps, follow-up texts).
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
uv run pytest                                  # 198 tests, no network
uvx ruff check orchestrator tools eval
uv run python tools/test_e2e_pipeline.py --offline   # starts a server, plays a whole date
uv run python tools/test_e2e_pipeline.py             # same, with your keys
```

Fish Audio and Deepgram are tested against local servers speaking their real protocols.
The Claude request shape is tested against a mock transport.

## Limits worth knowing

- **Face signals.** The model is stock and the thresholds above were set by hand, not
  measured on labelled footage. Expect misses in low light, with glasses that hide the
  brows, or with the face side-on to the camera. Only one face is tracked; anyone else
  in the frame is ignored or may take over.
- **Avatars.** Two Rocketbox bodies, tinted. Ready Player Me shut down on 31 January 2026,
  so a selfie colours an avatar rather than reshaping its face.
- **Worlds.** The scene prompt chooses between the scanned worlds and re-lights them; it
  doesn't generate new 3D geometry live.
- **Voices.** Configure Fish Audio voice models per dialect and gender with
  `FISH_VOICE_<DIALECT>_<GENDER>`; otherwise Fish's default voice speaks every dialect.
- **Echo.** Use headphones. The client gates echo while the date talks, but speakers next
  to the mic still make barge-in less reliable.
