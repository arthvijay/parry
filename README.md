# Parry

*Keep up. Flirt back. Speak like a local.*

Parry is a cultural speed-dating simulator for language learners. You scan your face,
pick a dialect and the kind of person you want to meet, describe the scene, and land
in a photoreal 3D venue for a three-minute date with an AI character. There is no
push-to-talk: you just talk.

During the date:
- your date answers in a streamed voice, in their dialect;
- they read your face and your gaze;
- they warm up or cool off;
- at the bell they either ask for your number or ghost you.

The receipt that prints afterwards grades how you actually spoke, quoting your own
words back to you, with a roast worth sharing.

> The product name lives in one file, `My project/Assets/Resources/BrandConfig.json`.
> Both the Unity client and the orchestrator read it (`orchestrator/config.py`).
> Don't hardcode it anywhere else.

**Contents**

1. [The vision](#1-the-vision)
2. [What a date feels like](#2-what-a-date-feels-like)
3. [Startup guide: from a fresh clone to your first date](#3-startup-guide-from-a-fresh-clone-to-your-first-date)
4. [Configuration and providers](#4-configuration-and-providers)
5. [How it works](#5-how-it-works)
6. [Repository map](#6-repository-map)
7. [Documentation map](#7-documentation-map)
8. [Testing](#8-testing)
9. [Limits worth knowing](#9-limits-worth-knowing)
10. [Troubleshooting](#10-troubleshooting)
11. [Working in this repo](#11-working-in-this-repo)

---

## 1. The vision

> Learning a language is hard. Dating is hard. Dating in a different language is hard.
> **We make it easy.**

### The problem: a 300-day streak, and you still freeze

Language apps build vocabulary on paper. They never train the split second when a
real person is waiting for your reply. In a real conversation, learners fall into the
**mental translation trap**:

1. hear it;
2. decode it into English;
3. draft a safe textbook reply;
4. translate it back;
5. check the conjugation.

By step five, the moment is gone.

### The insight: two anxieties, one trigger

Language anxiety ("what if I conjugate it wrong?") and dating anxiety ("what if I say
something weird?") are the same fear: freezing in front of another person. Parry
doesn't remove the pressure; it **makes the pressure the practice**. Recovering from
a freeze is the skill you level up.

Parry is dating first and language learning second. The date is why you show up; the
fluency is what you leave with.

### What Parry is

A repeatable, high-retention social simulation in which:

- **The conversation is real.** Full-duplex voice. You interrupt, they stop mid-word.
  They interrupt back. Nothing is multiple-choice.
- **The partner is embodied.** A 3D character in a real place. They look at you,
  lean in when it's going well, glance away when it isn't, and notice when you look
  away from them.
- **They see you.** Your webcam reads your smiles, nods, puzzled looks and where you
  look, calibrated to your own face. Smiling at their joke counts. Staring at your
  phone while they talk gets called out, in character.
- **The dialect is local.** Not "Spanish" but porteño voseo in Palermo, Kansai-ben in
  Osaka, Hinglish in Mumbai, a Southern drawl in Savannah. Each date carries its
  city's slang, manners and culture.
- **There's a rescue when you freeze.** Stall for four seconds, or press W, and a
  wingman whispers three replies in your ear (flirty, curious, playful) with English
  glosses. A translator is one key away. Both are counted, gently, because needing
  help is part of the picture.
- **The feedback is honest.** "No quote, no tick": a milestone or a passing grade is
  awarded only when the grader can quote **your own words** that earned it. A false
  award is worse than a missed one.
- **The result is shareable.** The verdict prints as a thermal receipt: MATCH,
  FRIENDZONED or GHOSTED, four graded pillars, a roast, and a follow-up text from your
  date. Press S for a 9:16 card ready for TikTok, Reels and Shorts. A match unlocks the
  next city on the trip.

### Where it's going

Today's build plays nine dialects in authored and prompt-generated dates across
scanned 3D venues. The direction is:
- more cities and venues;
- generated portraits and venue cards (FLUX on Fal is planned, not integrated);
- dates that remember you across a trip of unlocks;
- a growth loop built on shared receipts.

The pitch deck in [`demo-pitch/`](demo-pitch/) tells the full story.

---

## 2. What a date feels like

### The demo date: Café Rayuela, Cancún

The matchmaker has two demo buttons. Both play at the same café, the same way every time:

| Button | Who you meet | Dialect | Preset |
| --- | --- | --- | --- |
| **▶ Argentine latina (Spanish)** | Valeria (or Tomás), an editorial photographer from Palermo who moved to Cancún to shoot the reefs | Rioplatense Spanish (`es-AR`): *vos sos, tenés, decime*, *che*, *posta*, *re* | `scenarios/speed_dating/presets/cafe_cancun_ar.json` (B1) |
| **▶ Southern belle (English)** | Savannah (or Beau) from Savannah, Georgia, a travel photographer | Southern American English (`en-US-south`) | `scenarios/speed_dating/presets/cafe_cancun_south.json` (B2) |

- **The place.** Café Rayuela, an Argentine-owned café two blocks from the beach.
- **The host.** Don Julio, the porteño owner, greets you at the door and walks you to
  the window table.
- **The opener.** Your date complains that their last date spent ten minutes on his
  stock portfolio, and recommends the medialunas.
- **The menu.** M shows the carta: cortado, medialunas, submarino, alfajores,
  tostado… Order in the dialect and Don Julio walks over and serves it.
- **Five milestones:**
  1. introduce yourself;
  2. order something to share;
  3. find common ground;
  4. talk like a local;
  5. ask for their number.

Pressing Play directly in `CancunCafe.unity` replays the last demo, or the Argentine
preset if there's none. Custom dates choose their venue from your prompt.

### The full flow

0. **The start screen** (`Wish.unity`), styled like the pitch deck: the neon name over
   a night sky and a lit Earth (atmosphere glow, ocean glint, city lights on the night
   side). One card per demo date (**Valeria**, Porteño Spanish; **Savannah**, Southern
   American English), a woman/man choice for who you meet, and **Create your own date**
   for the full matchmaker.
1. **Face scan**.
   - A live webcam viewfinder. *Capture selfie* sends the photo to
     `POST /v1/avatar/from-selfie`.
   - There, MediaPipe finds your face and samples skin from the cheeks and hair from
     above the hairline. Those colours tint the Rocketbox body you choose.
   - That avatar renders live beside the photo and already mirrors your expressions.
   - The **vision panel** in the corner shows the camera with the face mesh over it,
     your expression levels, head pose, eye contact and a feed of signals. H collapses
     it.
2. **Language.** Dialect, city and level (A1 to C2). The low-poly globe turns and
   pins the city. Dialects you've unlocked show 🔓.
3. **Your date.**
   - Choose gender, appearance (3D look only) and personality.
   - Choose a venue, or *let my prompt decide*.
   - Write a free-text scene ("a rooftop bar at sunset after the rain") and notes
     ("loves indie rock, hates crypto bros").
   - *Start Speed Date* calls `POST /v1/matchmaker/generate` and shows who you're
     meeting. Then the globe flies you into the clouds and the venue loads.
4. **The venue.**
   - Your scene prompt picks one of the scanned worlds and re-grades it with a
     lighting preset (post-processing, so the Gaussian splat changes too), plus ambient
     sound.
   - The host greets you in the dialect when you walk up, and leads you to the table.
5. **The date.** Sit down (F) and the bell rings: 3:00 on the clock. The mic is open.
   - **The match bar** runs across the top: chemistry (0–100, starting at 50) on a
     track split into the three verdict zones (GHOSTED below 45, FRIENDZONED to 65,
     MATCH above). It moves after every line you say, with the reason shown, and a
     banner flashes when you cross into a new zone. It's judged off the reply path, so
     your date never waits for the judge.
   - **Milestones** tick only with your own words as evidence.
   - **Smiling** at a joke helps (+3).
   - **Looking away** for 4.5 s while the date talks gets called out in character
     (−6). Looking away means your in-game view is off them, or your real head is
     turned or dropped, or you've left the camera frame.
   - **Barge-in:** talk over your date and they stop mid-word.
   - **Wingman:** freeze for about 4 s (or press W) and three options appear.
   - **Translator (T):** what your date just said, in English, plus three replies.
   - **V** toggles the cinematic two-shot: your avatar, wearing your live face, sits
     across from them.
6. **The verdict.** At the bell your date says goodbye in character, remembering
   something you talked about. Then the receipt prints out of a little thermal
   printer, line by line:
   - the venue, the date and the dialect;
   - the chemistry score and its curve over the whole date;
   - **four graded pillars**, each with a verbatim quote: icebreaker, dialect
     authenticity, active listening, and agility and pacing (measured, not judged);
   - the milestones met and an overall grade;
   - **the roast**: one affectionate line about how it went (any quote in it is yours,
     checked);
   - **the unlock**: a match unlocks the next dialect on the trip; anything less offers
     a rematch.

   Then the stamp slams down across it (MATCH, FRIENDZONED or GHOSTED, in the dialect),
   and a text from your date slides in on a phone, with one correction drawn from what
   you said.

   **S** opens the share page: the receipt as a 9:16 card, with buttons for the share
   sheet, download, and TikTok, Reels and Shorts.
   **Tab** flips to the learning page. **L** opens *Your date, decoded* in the browser:
   - what landed, in your words;
   - up to three things to say differently;
   - phrases in the dialect for the moments you stalled;
   - how people really talk there, and words to practise;
   - pronunciation tips on the words that were hardest to make out;
   - the whole conversation with the chemistry curve.

   **R** tries again with the same date. **N** goes to the next date, opening on the
   unlocked city after a match.

### Dialects

| Code | Dialect | Cities | Host |
| --- | --- | --- | --- |
| `es-MX` | Mexican Spanish | Ciudad de México, Cancún | Pau |
| `es-AR` | Argentine (Rioplatense) Spanish | Buenos Aires (Palermo) | Flor |
| `es-ES` | Castilian Spanish | Madrid (Malasaña) | Lucía |
| `zh-CN` | Mandarin Chinese | Shanghai, Beijing | 小林 |
| `hi-IN` | Hinglish / Hindi | Mumbai, Delhi | Riya |
| `ja-JP` | Japanese (Tokyo standard) | Tokyo (Shimokitazawa) | 佐藤 |
| `ja-JP-kansai` | Japanese (Osaka Kansai-ben) | Osaka (Dōtonbori) | 山本 |
| `fr-FR` | Parisian French | Paris (le Marais) | Camille |
| `en-US-south` | Southern American English | Cancún, Savannah, Austin | Darlene |

A match unlocks the next stop on a fixed trip:

es-MX → es-AR → ja-JP-kansai → fr-FR → zh-CN → es-ES → hi-IN → ja-JP → en-US-south → back to es-MX.

Labels, cities, recogniser locales and the trip are registered in
`orchestrator/config.py`. What each dialect's characters can say offline lives in
`scenarios/speed_dating/dialects/<code>.json`:
- the host's lines;
- openers per personality;
- look-away callouts;
- wingman lines;
- closings, verdict stamps and follow-up texts;
- culture notes.

### Controls

| Key | Does |
| --- | --- |
| WASD / arrows | Walk (Left Shift runs) |
| Mouse | Look (hold the right button when the cursor is free) |
| Esc | The session menu, from any screen: resume, restart this date, new session, fullscreen, quit, server status |
| Left click | Recapture the cursor |
| F11 | Fullscreen on or off |
| F | Sit or stand. Sitting at your table starts the date |
| Enter | Type a line instead of speaking; Enter again sends it |
| W (seated) | Ask the wingman for three replies |
| T | Translator card |
| M | The café menu (preset dates) |
| V | First person ↔ cinematic two-shot |
| H | Collapse / expand the vision panel |
| Q | End the date early |
| S / Tab / L / R / N | On the verdict: share / learning page / open the report / retry / next date |

---

## 3. Startup guide: from a fresh clone to your first date

This takes about 20 minutes, most of it Unity's first import. Every API key is optional:
with none at all, the whole date runs offline with a scripted date, a sample voice
and typed input. Add keys to make it real.

### Step 0: What you need

| Need | Why |
| --- | --- |
| **Git** | Cloning, and Unity fetches the Gaussian-splatting package from a git URL |
| **[uv](https://docs.astral.sh/uv/)** | Installs Python 3.13 and every dependency. Use uv only, never `pip install` |
| **Unity Hub + Unity 6000.0.68f1** (Unity 6, URP) | The client. Install the exact editor version from the Hub's archive |
| **A webcam** | Face scan, avatar tint, face signals. Optional; the date carries on without one |
| **A microphone + headphones** | You talk to your date. Headphones stop the date's voice from leaking into your mic |
| A decent GPU | The venues are Gaussian splats; integrated graphics work but run slowly |
| `ffmpeg` (optional) | Used by the end-to-end test to decode its sample audio |

### Step 1: Install the Python side

```sh
git clone https://github.com/arthvijay/parry.git && cd parry
curl -LsSf https://astral.sh/uv/install.sh | sh   # if you don't have uv yet
uv sync --group face                              # Python 3.13, deps, MediaPipe for face tracking
```

Leaving out `--group face` still works, but the date won't see your face. The other
groups (`mesh`, `media`) are only for tooling; see [§6](#pyprojecttoml-dependency-groups).

### Step 2: Add your keys (optional, recommended)

```sh
cp orchestrator/.env.example orchestrator/.env
```

Open `orchestrator/.env` and fill in whichever keys you have. This file is
git-ignored. Never commit it, paste a key into a command line, or print one.

| Add this | And you get |
| --- | --- |
| `ANTHROPIC_API_KEY` | Claude, the only LLM: the date's live replies, generated personas, the chemistry judge, the wingman and translator, the grade, the roast and the report. **The single most valuable key.** |
| `ELEVENLABS_API_KEY` | A real dialect voice for your date (otherwise a bundled sample voice speaks) |
| `NVIDIA_API_KEY` | The date hears you (NVIDIA Nemotron ASR). Without it you type with Enter. Non-English dialects automatically use NVIDIA's hosted multilingual model |

Every other setting has a working default; [§4](#4-configuration-and-providers) lists
them all.

### Step 3: Start the orchestrator

From the **repo root** (data folders are relative to it):

```sh
uv run python -m orchestrator        # serves http://127.0.0.1:8765
```

Leave it running. In another terminal, check it:

```sh
curl -s http://127.0.0.1:8765/health | python -m json.tool
curl -s http://127.0.0.1:8765/v1/face/status
```

- `/health` → `"date"` shows which provider each part is actually using: matchmaker,
  chemistry, grader, brain, stt, tts, face. `"templates"`, `"rules"`, `"scripted"`,
  `"sample"` or `"none"` means that part is on its offline fallback.
- `/v1/face/status` should say `"available": true`. On first run the server downloads
  the MediaPipe face model (about 3.7 MB, checked against its SHA-256) into
  `runs/models/`.
- The interactive API docs are at <http://127.0.0.1:8765/docs>.

### Step 4 (optional): Prove the pipeline without Unity

```sh
uv run python tools/test_e2e_pipeline.py --offline
```

This starts its own server, generates a date in every dialect, and plays whole dates
over the real WebSocket: greeting, opener, speech, wingman, barge-in, look-away,
ordering at the café, closing, verdict, roast, share card and report. It should end
with every check passing. Drop `--offline` to run the same thing with your keys.

### Step 5: Open the Unity project

1. In Unity Hub: **Add → Add project from disk** and pick the `My project/` folder.
   Open it with **6000.0.68f1**.
2. The first import takes a while. It:
   - resolves packages, including the Gaussian-splatting package from GitHub;
   - imports the Rocketbox avatars (`RocketboxImportFixer` sets them up);
   - converts the venue splats in `Assets/Worlds/` into `GaussianAssets`
     (`WorldSplatImporter`).
3. When it's done, the editor opens `Assets/Scenes/Wish.unity` on its own
   (`OpenDemoScene`). If it doesn't, open it from the Project window.

The client talks to `http://127.0.0.1:8765` by default. To point it elsewhere, set
**Server Url** on the `MatchmakerUI` component in `Wish.unity`; it's remembered in
PlayerPrefs (`parry.server`).

### Step 6: Get into a date

1. Make sure the orchestrator from Step 3 is running, then press **Play** in
   `Wish.unity`.
2. Allow the camera and microphone if your OS asks.
3. **Face:** look at the viewfinder and press *Capture selfie*. Pick a body. Your
   avatar takes on your colouring and mirrors your face.
4. **Fastest path:** on the start screen, click **Valeria** (Porteño Spanish) or
   **Savannah** (Southern American English) for the authored Café Rayuela date.
5. **Custom path:** choose a dialect, city and level, then who you want to meet, a
   personality, a venue (or let the prompt decide) and a scene. Press
   **Start Speed Date**.
6. You fly to the venue. Walk in with WASD; Don Julio (or the dialect's host) greets
   you and shows you to the window table.
7. Walk up to your seat and press **F**. The bell rings and the 3:00 clock starts.
   Your date opens.
8. **Talk.** Interrupt freely. If you freeze, wait for the wingman or press W. Press T
   for the translator, M for the menu, V for the cinematic view.
9. At the bell (or Q), watch the receipt print. Then:
   - S to share;
   - Tab for the learning page;
   - L for the full report in your browser;
   - R to retry;
   - N for the next date.

**Shortcut:** open `Assets/Scenes/CancunCafe.unity` and press Play to skip the
matchmaker. You'll get your last demo date, or the Argentine preset at B1.

### Step 7 (optional): Run it as an app, without the editor

```sh
./play build        # once: builds the Linux app into Builds/Linux/ (or in the editor: Build ▸ Linux App)
./play              # starts the server, opens the game in its own window, stops the server on quit
./play --fullscreen
./play install      # adds it to your desktop's app menu
./play server       # only the orchestrator; ./play stop stops one started in the background
```

`./play build` refuses while the project is open in the editor (Unity locks it); use
**Build ▸ Linux App** there instead, which writes the same app. Logs go to
`runs/server.log`, `runs/game.log` and `runs/build.log`.

To check how the app looks without sitting at it, the built game takes `-scene
Assets/Scenes/CancunCafe.unity` (open a scene), `-matchmaker-step Language` (open the
matchmaker on a step), `-server http://127.0.0.1:8799` (another server) and `-shot
out.png -shot-after 10` (capture the screen, then quit).

If something doesn't work, see [Troubleshooting](#10-troubleshooting).

---

## 4. Configuration and providers

All configuration is environment variables in `orchestrator/.env`, which is loaded by
`python -m orchestrator`. `orchestrator/.env.example` is the annotated template. Every
key is optional, and each part falls back on its own:

| Job | Provider | Key | Offline fallback |
| --- | --- | --- | --- |
| **The date's live replies** | Claude (`DATE_CLAUDE_MODEL`, default Sonnet 5.5), streamed | `ANTHROPIC_API_KEY` | A scripted date in the dialect |
| Building the date (persona, opener, flags, venue) | Claude `claude-sonnet-5-5` | same | Authored dialect templates |
| Live chemistry judge, wingman, translator card | Claude (effort `low`) | same | A rules judge, authored wingman lines |
| Receipt: verdict, pillars, roast, follow-up text | Claude | same | A rules grader and a roast built from what was measured |
| *Your date, decoded* report and pronunciation tips | Claude | same | A rules report, no pronunciation tips |
| Hearing the learner | NVIDIA Nemotron ASR Streaming (Riva gRPC); hosted multilingual Parakeet for non-English locales | `NVIDIA_API_KEY` (or a self-hosted NIM via `NEMOTRON_ASR_SERVER`) | Voice detection only; type with Enter |
| The date's voice | ElevenLabs streaming TTS (`eleven_flash_v2_5`, WebSocket, 24 kHz PCM) | `ELEVENLABS_API_KEY` | A bundled sample voice, paced like speech so lip-sync and barge-in still work |
| Face, smiles, nods, head pose, gaze | MediaPipe Face Landmarker, local | none (`uv sync --group face`) | No face signals; gaze comes from the in-game camera |

### All speed-date settings

| Variable | Default | Controls |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | – | Claude for every LLM job (`ANTHROPIC_AUTH_TOKEN` also works) |
| `CLAUDE_MODEL` | `claude-sonnet-5-5` | Base model for every Claude job |
| `DATE_CLAUDE_MODEL` | `CLAUDE_MODEL` | Model that speaks as the date |
| `MATCHMAKER_MODEL` / `CHEMISTRY_MODEL` / `DATE_GRADER_MODEL` | `CLAUDE_MODEL` | Per-job model overrides (the grader's also writes the report) |
| `MATCHMAKER_EFFORT` / `CHEMISTRY_EFFORT` / `DATE_GRADER_EFFORT` | `medium` / `low` / `medium` | Per-job effort |
| `CLAUDE_FALLBACKS` | `1` | Server-side refusal fallback; `0` turns it off |
| `PRONUNCIATION` | `1` | `0` turns off the report's pronunciation tips |
| `NVIDIA_API_KEY` | – | Nemotron ASR on NVIDIA's hosted endpoint |
| `NEMOTRON_ASR_SERVER` | `grpc.nvcf.nvidia.com:443` | Riva endpoint; point at a self-hosted NIM to skip the key |
| `NEMOTRON_ASR_FUNCTION_ID` | hosted English Nemotron | Function id for English |
| `NVIDIA_ASR_MULTILINGUAL_FUNCTION_ID` | hosted Parakeet multilingual | Function id for non-English locales |
| `NEMOTRON_ASR_LANGUAGE` / `NEMOTRON_ASR_SSL` | per dialect / auto | Force a locale; TLS on or off |
| `ELEVENLABS_API_KEY` | – | ElevenLabs voices |
| `ELEVENLABS_TTS_MODEL` | `eleven_flash_v2_5` | TTS model |
| `ELEVENLABS_VOICE_<DIALECT>_<GENDER>` | – | A voice per dialect and gender, e.g. `ELEVENLABS_VOICE_ES_AR_FEMALE` |
| `ELEVENLABS_VOICE_<GENDER>` | – | Fallback voice per gender (`FEMALE`, `MALE`, `NONBINARY`) |
| `FACE_TRACKING` | `1` | `0` turns webcam face tracking off |
| `FACE_MODEL_PATH` | `runs/models/face_landmarker.task` | Where the MediaPipe model lives (downloaded if missing) |
| `DATE_DIR` / `CHEMISTRY_DIR` / `RUN_DIR` | `runs/dates` / `runs/chemistry` / `runs/transcripts` | Saved dates, chemistry state, transcripts |
| `VERDICT_DIR` / `REPORT_DIR` / `RUN_AUDIO_DIR` | `runs/verdicts` / `runs/reports` / `runs/audio` | Graded receipts (for sharing later); reports; your recorded mic clips |
| `LEARNER_DIR` / `COST_DIR` / `VOICE_CACHE_DIR` | `runs/learners` / `runs/costs` / `runs/voice_cache` | Learner profiles (memory across dates); cost ledgers; scripted lines voiced once |
| `PLAN` | – | `free` runs the per-turn chemistry judge and the wingman on the rules: most of a date's model calls gone |
| `CLAUDE_PRICE_INPUT` / `_OUTPUT` / `_CACHE_READ` / `_CACHE_WRITE` | list prices | Override Claude's built-in prices for the cost report |
| `NVIDIA_ASR_PRICE_PER_MINUTE` / `ELEVENLABS_PRICE_PER_MILLION_CHARS` | – | Prices for speech and voice; unset, the cost report shows usage only |

Voices are picked in this order:
1. `ELEVENLABS_VOICE_<DIALECT>_<GENDER>`;
2. the dialect's built-in premade defaults (Jessica and Will for `en-US-south`);
3. `ELEVENLABS_VOICE_<GENDER>`;
4. a premade voice.

### Legacy café settings

These only drive the original café flow ([§5](#the-original-café-flow)); the speed date
never needs them:
- `OPENAI_API_KEY`;
- `AGENT_ID_MARIA`, `AGENT_ID_LUIS`, `AGENT_ID_LUIS_BEGINNER`;
- `DIRECTOR_MODEL`, `TUTOR_MODEL`, `SCENARIO_MODEL`, `SCENARIO_DIR`;
- `SPEECH_ADAPTER`, `ELEVENLABS_STT_MODEL`.

---

## 5. How it works

### The pieces

```
Unity 6 client (My project/)                    orchestrator (FastAPI, :8765)
────────────────────────────                    ─────────────────────────────
MatchmakerUI ─── GET  /v1/matchmaker/catalog ──▶ config.py (dialects, venues, presets)
             ─── POST /v1/matchmaker/generate ─▶ matchmaker.py ─▶ Claude
             ─── POST /v1/matchmaker/preset ───▶ matchmaker.py ◀─ scenarios/speed_dating/presets
AvatarOnboarding ── POST /v1/avatar/from-selfie ▶ face_tracker.py (MediaPipe)
VisionFeed ─── WS /v1/vision (before the date) ─▶ face_tracker.py + nonverbal.py

FullDuplexStreamClient ═══ WS /v1/stream ═══════▶ stream_gateway.py
  mic 16 kHz PCM16 (20 ms frames) ─────────────▶   stt.py (Nemotron ASR, Riva gRPC)
  telemetry every 250 ms, webcam JPEGs ~8 fps ─▶   nonverbal.py, face_tracker.py
  barge_in · start_date · end_date · help · wingman ▶ chemistry_director.py ─▶ Claude
  ◀──────────── 24 kHz PCM16 voice frames ─────    date_brain.py (Claude) ─▶ tts.py (ElevenLabs)
  ◀── transcript · chemistry_update · wingman_hint · help_card · signal · face_analysis
      clear_audio · scene_action · date_started · date_ended
VenueAmbience ─── GET /v1/ambience ─────────────▶ ambience.py
DateVerdictReceipt ─ POST /v1/grade ────────────▶ date_grader.py ─▶ Claude (pillars, roast, unlock)
                   ─ POST /v1/date/report ──────▶ date_report.py ─▶ Claude
                   ─ GET  /v1/date/report/{run}.html   (L, in the browser)
                   ─ GET  /v1/date/share/{run}         (S: share page)
                       └ GET /v1/date/receipt/{run}.svg ◀ share_card.py (9:16 card)
```

The full wire contract is in [docs/api.md](docs/api.md#speed-date), and the design
rationale is in [docs/speed-date.md](docs/speed-date.md).

### One date, end to end (server side)

1. **Building the date.**
   - `POST /v1/matchmaker/generate` sends who you want to meet. Claude drafts a
     persona: name, age, occupation, backstory, interests, an opening line, green and
     red flags, and a venue matched to your scene prompt.
   - Code then fills in everything that must be right: the id, voice, avatar, the
     four milestones and their evidence rules, the system prompt, and the host.
   - Without Claude, authored dialect templates do the drafting.
   - Presets (`POST /v1/matchmaker/preset`) are fully authored dates that add a menu,
     a serve line, closings and follow-ups.
2. **Opening the stream.** Unity opens `WS /v1/stream` and sends `init` with the run
   and scenario ids. The server builds the recogniser, the voice (pre-warmed so the
   first line is fast), the brain and the chemistry director, then replies
   `session_ready` with which provider each part is using.
3. **Before the date.** Walking up to the host makes them speak their greeting. Lines
   aimed at your date before you sit come back as "walk to the table".
4. **The bell.** Sitting sends `start_date`. The date speaks their opener and a 180 s
   clock starts (the server ends it at 188 s as a backstop).
5. **Each of your turns:**
   1. The recogniser's final transcript, or a typed line, arrives. Echoes of the
      date's own voice are filtered out, and anything still playing is interrupted.
   2. Claude streams the date's reply with silent notes appended: `[CHEMISTRY n/100
      mood]`, `[NONVERBAL]` (what the face and gaze saw) and `[SCENE]` (time left).
      Sentences are spoken as soon as they're complete, so the first word plays before
      the reply is finished. A turn Claude can't answer gets a scripted line.
   3. The chemistry judge scores your turn in the background, off the reply path. Its
      move is clamped to ±15 and scaled by the date's personality and your level.
      Milestones tick only when your quoted words are found in the transcript.
6. **Barge-in.** Unity's voice detector hears you over the date and flushes every NPC
   audio buffer within a frame (after 120 ms of speech), then tells the server. The
   server stops generating and records only what you actually heard.
7. **Rescues and nudges.**
   - After the date stops talking, a wingman hint is prepared at once. If you're
     still silent 4–5 s later (by level), it's shown, with −2 for the awkward
     silence. Pressing W shows one immediately with no penalty, and reading a hint
     aloud earns at least +2.
   - Looking away for 4.5 s while the date talks: −6 and an in-character callout.
   - Smiling at a joke: +3.
   - Ordering from the menu in a preset café sends the host over with it.
8. **The end.** `end_date` (or the clock) drains pending judgements and maps the
   score to a verdict: ≥65 match, ≥45 friendzone, otherwise ghosted. The date says a
   goodbye that mentions something you talked about, then `date_ended` is sent with
   a summary of what the camera saw.
9. **Grading.** `POST /v1/grade` returns the receipt and saves it under `runs/verdicts`.
   - Three pillars are judged by Claude (or rules): icebreaker, dialect
     authenticity, active listening. A passing grade without one of your quotes is
     capped at D+.
   - The fourth pillar, agility and pacing, is computed from your response
     latency, recogniser confidence and wingman use.
   - The roast is held to the same honesty: if it quotes you, it must quote you
     exactly, or it's replaced by one built from what was measured.
   - `next_date` says what the verdict unlocks.
10. **Sharing.** `GET /v1/date/receipt/{run}.svg` draws the saved verdict as a
    1080×1920 card (plain SVG, so the server needs no imaging library).
    `GET /v1/date/share/{run}` wraps it in a page that makes a PNG in the browser and
    hands it to the share sheet or the platform's upload page. Nothing is posted for
    you.
11. **The report.** `POST /v1/date/report` writes *Your date, decoded*.
    - Every quote is checked against the transcript, and fixes built on words the
      recogniser doubted are dropped.
    - Pronunciation tips come from the three least-confident lines: Claude may only
      name words the recogniser doubted in that line.
    - It's saved to `runs/reports/<run_id>.html`.

### What the webcam reads

`face_tracker.py` runs MediaPipe Face Landmarker on ~8 frames a second (320 px JPEGs).
It reads 52 ARKit blendshapes, the head's pitch, yaw and roll, and the face mesh.
`nonverbal.py` turns those into the signals a person across the table would notice.

- **Signals:** smile, laugh, nod, head shake, puzzled, surprised, frown, look away and
  look back. Each must hold for a moment, so a flicker doesn't count.
- **Calibrated to you:** every expression is measured against your own resting face,
  a low quantile of the last ~20 s, capped so a long real smile still counts. A
  resting furrowed brow isn't read as "puzzled".
- **Camera position doesn't matter:** the head's centre is learned from where you
  normally face the screen, so a webcam off to the side or below your chin isn't read
  as looking away. Looking away never moves that centre.
- **The face can overrule the game camera:** any of these is looking away, even if
  the in-game view is on the date:
  - head turned more than 28° from centre;
  - head tilted 20° up or down (a phone in your lap);
  - eyes held off to one side;
  - face out of frame for a second.

  Blinks and quick glances are ignored. If no frames arrive, the game camera's gaze
  stands alone. Eye contact % on the receipt uses this combined answer.
- **Where it goes:** the vision panel's feed, the date's prompt (`[NONVERBAL]` notes),
  and the chemistry meter. Each `face_analysis` message carries `calibrated`,
  `attentive` and `away_reason` (`head_turned`, `head_tilted`, `eyes_aside`,
  `out_of_frame`).
- **After the date:** `date_ended` carries a `face` summary: frames analysed,
  `face_visible_pct`, `attentive_pct`, and signal counts overall and while the date
  was talking.
- **Your avatar:** the same blendshapes drive your own avatar
  (`LocalFaceController.cs`), so the cinematic camera shows you reacting.

### Body language and voice in Unity

- **Posture:** the date's posture follows chemistry (`DateBodyLanguage.cs`). At 70+
  they lean in, smile and tilt their head. Below 40 they lean back, glance away and
  frown faintly. If you keep looking elsewhere, they start doing the same
  (`NpcLookAt.cs`).
- **Lip-sync** works in every language with no phoneme data. `NpcSpeaker.cs` drives
  the jaw from loudness and picks vowel visemes from the audio's spectrum.
- **Echo:** while a character talks and you don't, the client sends silence instead
  of the mic, so the date's voice from speakers isn't heard as you. Headphones are
  still best.

### Culture as data

Each dialect file carries more than lines to say, read in code so a native speaker can
tune a city without touching Python:

| Block | What it does |
| --- | --- |
| `nonverbal` | How long a glance away may last while the date talks and what it costs, and one line on local norms for the persona and the judge. Tokyo allows 8 s, Buenos Aires 4 s; in hi-IN the side-to-side head wobble reads as "yes, go on" |
| `cultural_moments` | The custom the date brings up about a minute in (mate in Buenos Aires, a spice dare in Mexico City, sweet tea in the South, a tsukkomi in Osaka). It becomes that date's cultural milestone; slang still counts too |
| `other_region_slang` | Words a local places elsewhere ("güey" is Mexico, "hella" is California). The date reacts once, lightly, and it costs a point |
| `fillers` | A local «este…» or «well…» against a foreign «um», counted only where a pause is |
| `register` | How people address each other (vos or tú, tú or usted, 你 or 您) and when a mismatch is worth a remark. The remark never moves a grade |
| `culture` | Notes for the report, used when Claude isn't available |

These are tendencies, not rules about people, and they're written to be reviewed.

### Memory across dates

Your profile (by the name you give the matchmaker) records each graded date and a short
practice list per dialect: only corrections you certainly made, quoted from your own
lines and not built on a word the recogniser doubted. The next date in that dialect
carries the two most recent open items; the date steers toward them without teaching
and never says them first. An item is marked fixed only when your own line contains
the better phrasing word for word, and the receipt quotes it. `GET /v1/learners/{name}`
shows a profile; `GET /v1/reports/class` shows a whole class.

### What a date costs

Every paid call reports its usage to the running job's ledger (Claude tokens with cache
reads and writes, NVIDIA speech seconds, ElevenLabs characters, and the characters a
cached line saved). The verdict's `cost` adds the matchmaker's, the live date's and the
grade's; `GET /v1/costs` totals everything since the server started. Claude has list
prices built in; the others show usage until their prices are set. Three things keep
the bill down: the chemistry judge's prompt is cached (instructions and the date's
fixed persona, menu included, as two system blocks), scripted lines are voiced once and
replayed from disk, and `PLAN=free` runs the judge and the wingman on the rules.

### No quote, no tick

The live director, the final grader, the roast and the report share one rule:

- A milestone is met, a judged pillar passes, or a quote appears only if you
  actually said it.
- This is checked against the transcript **in code**.
- A model that invents evidence is overruled: the milestone stays open, the pillar is
  capped at D+, and the quote is dropped.

Your words must also be your own: a line that only hands the date's (or the host's)
sentence back, word for word or nearly, earns no milestone and backs no grade; a line
that adds something of yours is judged on its own. In Hinglish, where English words are
welcome, a line with no Hindi in it at all still counts as English.
`eval/date_selfplay.py` plays whole dates with one-word, English and echoing learners
and fails on any award they get.

This rule is never loosened, not for a test and not for a demo.

### HTTP routes at a glance

| Route | What it does |
| --- | --- |
| `GET /v1/matchmaker/catalog` | What the matchmaker offers: presets (with date names and language), dialects and cities, venues, personalities, levels |
| `POST /v1/matchmaker/generate` · `POST /v1/matchmaker/preset` | Build a date from your choices, or an authored demo date |
| `WS /v1/stream` · `WS /v1/vision` | The live date; face tracking alone for onboarding |
| `POST /v1/avatar/from-selfie` | Skin and hair colours for the avatar |
| `POST /v1/grade` (or `/v1/date/grade`) | The verdict: stamp, pillars, roast, unlock, follow-up, progress, cost |
| `GET /v1/date/runs/{run_id}` · `…/verdict` · `…/card` | The transcript and chemistry; the stored verdict; the receipt as a readable page |
| `GET /v1/date/receipt/{run_id}.svg` · `GET /v1/date/share/{run_id}` | The 9:16 shareable receipt and its share page |
| `POST /v1/date/report` · `GET /v1/date/report/{run_id}.html` | *Your date, decoded* |
| `GET /v1/learners/{name}` · `GET /v1/reports/class` | One learner's profile; a whole class (`?format=json`) |
| `GET /v1/costs` | Usage and dollars by provider since the server started |
| `GET /v1/face/status` · `GET /health` | Readiness |

### The original café flow

Before the speed date, this codebase was a café language-practice game: Maria the
waitress and Luis the marine biologist in a Cancún café, voiced by ElevenLabs
conversational agents, with an OpenAI director, coach and tutor.

That flow still works and its tests still pass, but the Unity client no longer calls
it:
- endpoints `/v1/speech*`, `/v1/scenarios`, `/v1/runs/{id}/goals`, `/v1/hint`,
  `/v1/feedback` and `/v1/npcs`;
- characters defined as data in `scenarios/cafe_cancun/`;
- managed with `tools/provision_agents.py`.

`/v1/ambience`, which serves the café's soundscape, **is** still used by the speed
date's venues. The file map below marks every café-only file.

---

## 6. Repository map

Every file in the repo, by area. **SD** = speed date (the live product). **Café** =
the original `/v1/speech` flow, kept working. **Shared** = used by both.

### Top level

| Path | What it is |
| --- | --- |
| `README.md` | This file |
| `AGENTS.md` | Rules for coding agents (Codex, Claude Code…) working in this repo |
| `pyproject.toml` | Python project: runtime deps, dependency groups, pytest config |
| `uv.lock` | Exact resolved dependency versions |
| `.python-version` | `3.13` |
| `.gitignore` | Ignores secrets (`.env*` except `.env.example`), Python caches, `runs/`, `CLAUDE.md`, editor and OS files, Unity build output |
| `Assets/Worlds/` | Source Gaussian splats (`.spz`) and colliders for the venues, converted into the Unity project by `WorldSplatImporter` (large committed binaries; don't touch) |
| `play` | The standalone-app launcher: build, run, install, server, stop |
| `demo-pitch/` | The pitch deck ([below](#demo-pitch)) |
| `docs/` | Design and API documentation ([§7](#7-documentation-map)) |
| `eval/` | Self-play for the speed date (the zero-false-award gate) and the café director's evaluation |
| `orchestrator/` | The Python service |
| `scenarios/` | Authored content: speed-date dialects and presets, the café scenario |
| `tools/` | Test, benchmark and content scripts |
| `My project/` | The Unity 6 client |
| `runs/` (git-ignored) | Everything the server writes: dates, chemistry, transcripts, verdicts, mic clips, reports, the face model, benchmarks |

### `pyproject.toml` dependency groups

| Group | Install | Enables |
| --- | --- | --- |
| default | `uv sync` | FastAPI, uvicorn, pydantic, anthropic, nvidia-riva-client, websockets, httpx, numpy, python-dotenv, openai (café) |
| `dev` | installed by default | pytest |
| `face` | `uv sync --group face` | MediaPipe (+ OpenCV): face tracking, `/v1/vision`, selfie tinting, nonverbal signals |
| `mesh` | `uv sync --group mesh` | scipy, scikit-image, trimesh, fast-simplification, for `tools/spz_to_collider.py` only |
| `media` | `uv sync --group media` | Bundled ffmpeg, for producing audio fixtures like `tools/sample_es.mp3` |

### `orchestrator/`: the Python service

| File | Flow | What it does |
| --- | --- | --- |
| `__main__.py` | Shared | Entry point: loads `orchestrator/.env` (then a root `.env`), runs uvicorn on 127.0.0.1:8765 |
| `__init__.py` | – | Package marker |
| `app.py` | Shared | `create_app()`: wires every provider at startup; `/health`, `/v1/metrics` and the café routes; mounts the routers below. `/v1/grade` sends `date_*` scenarios to the date grader |
| `config.py` | SD | The registry: brand (from `BrandConfig.json`), 9 dialects and the unlock trip, venues, archetypes, appearances, CEFR levels, models and providers from env, voices, presets, the matchmaker catalog. Constants: 180 s dates, start 50, match 65, friendzone 45 |
| `date_routes.py` | SD | HTTP routes for the matchmaker, grading, reports, the receipt card and share page, face status, selfie; mounts `WS /v1/stream` and `WS /v1/vision` |
| `stream_gateway.py` | SD | The live date: one `StreamSession` per `/v1/stream` (recogniser → brain → voice, barge-in, wingman, callouts, clock, café order and serve, mic clips) and the onboarding `/v1/vision` socket |
| `matchmaker.py` | SD | Builds a `DateScenario` from a Claude persona draft or templates; presets; the date's system prompt; `DateStore` |
| `date_brain.py` | SD | Who speaks as the date: `ClaudeBrain`, the offline `ScriptedBrain`, and `ChainBrain`, which hands a turn Claude can't answer to the scripted lines |
| `chemistry_director.py` | SD | Per-turn chemistry judge (Claude or rules), state and store, wingman hints, translator card, mood and posture |
| `date_grader.py` | SD | The verdict: three judged pillars plus measured pacing, metrics, the roast (checked), the unlock, the follow-up text and its correction |
| `share_card.py` | SD | The shareable 9:16 receipt as SVG, and the share page around it |
| `share_routes.py` | SD | The readable receipt page and stored verdict, learner profiles, the class report, `/v1/costs` |
| `run_records.py` | SD | The stores that outlive a session: verdicts, learner profiles, costs, the voice cache |
| `learner_profile.py` | SD | Memory across dates: each learner's dates and practice list |
| `costs.py` | SD | The cost ledger: usage per provider, priced where prices are known |
| `voice_cache.py` | SD | Scripted lines voiced once, replayed from disk |
| `date_report.py` | SD | *Your date, decoded*: Claude (or rules) writes it, including pronunciation tips from the least-confident lines; renders and saves HTML and JSON |
| `date_models.py` | SD | Pydantic contracts for every speed-date message and payload |
| `claude.py` | SD | Thin Anthropic wrapper: structured output, per-job effort, server-side fallback |
| `stt.py` | SD | Nemotron/Riva streaming recogniser; energy-only `SpeechRecognizer` fallback |
| `tts.py` | SD | `SentenceChunker`, the ElevenLabs stream-input voice (kept warm), the sample voice, per-turn fallback |
| `audio.py` | SD | PCM helpers, resampling, `EnergyVad`, WAV writing, the sample voice |
| `face_tracker.py` | SD | MediaPipe Face Landmarker: model download and check, per-frame analysis, selfie colour sampling |
| `nonverbal.py` | SD | Face readings and gaze → calibrated, debounced social signals; attention; per-date face stats |
| `assets/sample_voice_24k.wav` | SD | The offline voice |
| `ambience.py` | Shared | `/v1/ambience`: the venue soundscape (served from the café pack) |
| `models.py` | Shared | Café contracts; the speed date reuses `TranscriptTurn` and `LetterGrade` |
| `grading.py` | Shared | `TranscriptStore` and letter-grade helpers (used by both); the café OpenAI grader |
| `director.py` | Shared | Quote-matching helpers used by the speed date (`said_by_learner`, `normalise`…); the café OpenAI goal director |
| `scene.py` | Café | The café scenario pack: menu pricing, tool dispatch, ambience paths |
| `metrics.py` | Café | Per-character latency for `/v1/metrics` |
| `brain_routes.py` | Café | `/v1/hint` and `/v1/feedback` (OpenAI) |
| `coach.py` | Café | OpenAI hint coach |
| `feedback.py` | Café | OpenAI tutor report and audio pronunciation |
| `scenarios.py` | Café | OpenAI scenario generation and store |
| `speech.py` | Café | Speech-provider protocol and `SPEECH_ADAPTER` loader |
| `elevenlabs_adapter.py` | Café | ElevenLabs Agents + Scribe adapter behind `/v1/speech*` |
| `gestures.py`, `visemes.py` | Café | Gesture and mouth-shape helpers for the agent adapter |
| `requirements.txt`, `requirements-dev.txt` | Shared | `uv export` pin lists for environments without uv |
| `.env.example` | Shared | Annotated template for `orchestrator/.env` |

**Tests** (`orchestrator/tests/`, all offline):

| File | Covers |
| --- | --- |
| `test_speed_date.py` | Matchmaker, chemistry, verdict, roast, unlocks, share card, report, signals, voices, ASR and TTS against local protocol servers, the live `/v1/stream` |
| `test_nonverbal.py` | Face calibration, attention, face-overrules-gaze, per-date face stats |
| `test_enhancements.py` | Culture as data, memory across dates, fillers and register, regional slang, costs, the voice cache, the readable card and class report, the echo and Hinglish honesty gates |
| `test_ambience.py` | Soundscape endpoints |
| `test_api.py`, `test_scene.py`, `test_director.py`, `test_grading.py`, `test_coach.py`, `test_feedback.py`, `test_elevenlabs.py` | The café flow |
| `test_stream.py` | The café `/v1/speech/stream` (not the speed-date stream) |

### `scenarios/`: content as data

| Path | Flow | What it is |
| --- | --- | --- |
| `speed_dating/dialects/<code>.json` | SD | One file per dialect (9): host lines, names, occupations, an opener per personality, look-away callouts, wingman lines, closings, verdict stamps, follow-up texts, culture notes, offline lines, and culture as data (`nonverbal`, `cultural_moments`, `other_region_slang`, `fillers`, `register`) |
| `speed_dating/presets/cafe_cancun_ar.json` | SD | Café Rayuela with Valeria / Tomás, Argentine Spanish, B1: venue, host Don Julio, a 10-item menu, five milestones, outfits, closings, follow-ups |
| `speed_dating/presets/cafe_cancun_south.json` | SD | The same café with Savannah / Beau, Southern American English, B2 |
| `cafe_cancun/scenario.json` | Café | Maria and Luis: voices, prompts, goals, tools, ambience generation prompts |
| `cafe_cancun/menu.json` | Café | The café menu, the single source of truth for café prices |
| `cafe_cancun/prompts/maria.md`, `luis.md` | Café | The agents' system prompts |
| `cafe_cancun/ambience/*.mp3` | Shared | Café murmur and ocean loops (used by the speed-date venue too), cup and receipt effects |

### `tools/`

| Script | Flow | What it does | Needs |
| --- | --- | --- | --- |
| `test_e2e_pipeline.py` | SD | Headless end-to-end: starts a server, generates a date in every dialect, plays a full date and the Café Rayuela preset over `/v1/stream`, grades it, checks the roast and share card, builds the report. `--offline`, `--url`, `--dialect`, `--preset` | Optional keys; ffmpeg |
| `date_latency_bench.py` | SD | Latency per stage (typed and spoken turns, barge-in, wingman, translator, verdict, report, matchmaker, face round trip) → `runs/bench/`. `--url`, `--turns`, `--spoken`, `--barge`, `--frames`, `--tts-probe` | A running server |
| `bench_face.jpg` | SD | Webcam-sized test image for the face benchmark | – |
| `sample_es.mp3` | SD | Sample learner speech for the end-to-end test | – |
| `spz_to_collider.py` | Unity | Builds a walkable collider `.glb` from a Gaussian-splat `.spz` | `uv sync --group mesh` |
| `requirements.txt` | Unity | Pin list of the `mesh` group | – |
| `provision_agents.py` | Café | Creates and updates the ElevenLabs agents from `scenarios/cafe_cancun` (dry run by default; `--apply`) | ElevenLabs key |
| `agent_tests.py` | Café | ElevenLabs-side regression tests, text only | ElevenLabs key |
| `switch_account.py` | Café | Moves the café demo to another ElevenLabs account | ElevenLabs keys |
| `make_ambience.py` | Café/Shared | Generates the café soundscape once with ElevenLabs sound effects | ElevenLabs key |
| `smoke_test.py`, `demo_beginner.py`, `e2e_check.py`, `e2e_stream_check.py`, `latency_bench.py` | Café | Smoke test, typed beginner demo, end-to-end and latency checks for `/v1/speech` | ElevenLabs/OpenAI keys; some use macOS `say` |

### `eval/`

| File | What it is |
| --- | --- |
| `date_selfplay.py` | Zero-false-award gate for the speed date: simulated learners (engaged, wrong-region, one-word, English, echo) play whole dates over `/v1/stream`; exits 1 on any false award. `--offline`, `--learner model` |
| `run_eval.py` | Zero-false-award gate for the café director: runs the real director against labelled transcripts, exits 1 on any false award (needs `OPENAI_API_KEY`) |
| `director_cases.jsonl` | 40 labelled cases (18 positive, 22 adversarial) |
| `README.md` | Method, results and prompt history |

### `My project/`: the Unity 6 client

Unity 6000.0.68f1, URP 17. Key packages:
- Gaussian Splatting (`org.nesnausk.gaussian-splatting`, from GitHub);
- Input System;
- glTFast (loads the collider `.glb`);
- AI Navigation.

**Scenes** (`Assets/Scenes/`):

| Scene | In build | What it is |
| --- | --- | --- |
| `Wish.unity` | ✅ first | The matchmaker studio over the globe. Everything is built at runtime by `MatchmakerUI` |
| `CancunCafe.unity` | ✅ | The main venue: the Cancún café splat and collider, NPCs from `npcs_cancun.json`, seats from `seats_cancun.json` |
| `SampleScene.unity` | – | A second venue on the Modern House splat, with `npcs.json` |
| `LanguageWorld.unity` | – | The original graybox café (legacy) |

**Scripts** (`Assets/Scripts/`). Systems are attached at runtime by
`Core/DateBootstrap.cs`, not by editing scenes.

| Script | What it does |
| --- | --- |
| `FirstPersonController.cs` | Walk and look, at the NPCs' measured eye height |
| `WorldColliderLoader.cs` | Loads the venue's collider `.glb`; the player stays frozen until it's in |
| **Core/** | |
| `Core/DateBootstrap.cs` | On every scene load: starts the webcam; in venues, adds the stream client, scenario, cast, HUD, telemetry, player avatar, vision panel, venue look and verdict |
| `Core/DateSession.cs` | State carried from the matchmaker to the venue (date, look, server URL and unlocked dialects in PlayerPrefs) and every DTO |
| `Core/Brand.cs` | Reads `BrandConfig.json` (name, copy, colours) |
| `Core/GlassUI.cs` | The pitch deck's look for every panel: wine glass, cream hairlines, rose glow; four typefaces bundled in `Resources/Fonts` (Fraunces, Bricolage Grotesque, JetBrains Mono, Yellowtail; open licences in `licenses/`) |
| `Core/SessionMenu.cs` | Esc: the session menu (resume, restart the date, new session, fullscreen, quit, server status); the `-scene` / `-shot` dev flags |
| `Core/Json.cs` | Small JSON reader/writer for the stream protocol |
| **Lobby/** | |
| `Lobby/MatchmakerUI.cs` | The start screen (demo cards, create your own), the three-step studio (Face, Language, Date), unlocks, matchmaking, the flight to the venue; the night sky, stars and lit Earth (shaders in `Assets/Shaders/Matchmaker/`) |
| `Lobby/AvatarOnboarding.cs` | Webcam viewfinder, selfie → `/v1/avatar/from-selfie`, tinted turntable preview with your live face |
| `Lobby/CloudCurtain.cs` | The cloud transition between scenes |
| `Lobby/LowPoly.cs` | Meshes for the globe (smooth sphere; the flat-shaded one is the fallback), clouds, pin and sky |
| **Conversation/** | |
| `Conversation/FullDuplexStreamClient.cs` | The `/v1/stream` socket: open mic, voice detection, barge-in, telemetry, webcam frames |
| `Conversation/StreamingAudioPlayer.cs` | Ring-buffer playback of streamed voice; audio analysis for lip-sync; instant flush |
| `Conversation/ChemistryAndWingmanHUD.cs` | Clock, the live match bar, milestones, subtitles, wingman, translator, menu, typed input |
| `Conversation/SpatialTelemetryBroadcaster.cs` | Eye contact with the date's face, gaze target, look-away time, seated; webcam head turn counts too |
| `Conversation/ScenarioClient.cs` | Loads the date (session, saved id, or the default preset) and applies milestones, venue look and cast |
| `Conversation/CastClient.cs` | Fills the venue's host and date slots: name, Rocketbox body, tints, outfit, behaviour |
| `Conversation/WavUtility.cs` | WAV helpers (currently unreferenced) |
| **Npc/** | |
| `Npc/DateBodyLanguage.cs` | Lean, smile, frown, blinks and laughs from chemistry |
| `Npc/NpcSpeaker.cs` | Voice at the mouth; jaw and vowel visemes from the audio |
| `Npc/NpcLookAt.cs` | Head and body tracking, boredom glances, gaze reciprocity, breathing |
| `Npc/FaceRig.cs` | ARKit blendshape names → Rocketbox `AK_` shapes |
| `Npc/AvatarTinter.cs` | Skin, hair and outfit tints, resting expression (uses `Resources/Shaders/OutfitRecolor`) |
| `Npc/NpcAvatarLoader.cs` | Instantiates an avatar from Resources |
| `Npc/NpcManager.cs` | Spawns NPCs from the StreamingAssets JSON, live-reloading it |
| `Npc/NpcConversation.cs` | Where an NPC's streamed voice lands; captions; who you're facing |
| `Npc/NpcSchedule.cs`, `NpcWalker.cs`, `NpcSitter.cs`, `NpcIdleAnimation.cs` | Scripted moves (the host walking you in, serving), walking, sitting, idle mocap |
| `Npc/NpcInteractable.cs`, `NpcIdentity.cs`, `NpcDefinition.cs` | Proximity focus, identity, the NPC JSON schema |
| **Quests/** | |
| `Quests/DateVerdictReceipt.cs` | The printed receipt, stamp, roast, unlock, phone follow-up, learning page, report link and share page; S/Tab/L/R/N |
| `Quests/QuestManager.cs` | Loads `quests.json`; the date's milestones replace it at runtime |
| `Quests/QuestHud.cs` | Legacy checklist (disabled by `DateBootstrap`) |
| **Seating/** | |
| `Seating/PlayerSeating.cs`, `Seat.cs`, `SeatManager.cs` | Sit and stand with F; seats from JSON |
| `Seating/DateCameraRig.cs` | V: first person ↔ cinematic two-shot |
| **Venue/** | |
| `Venue/VenueAmbience.cs` | Lighting grade, lights and ambient loops per venue, ducked under speech |
| `Venue/VenueLook.cs` | Runtime post-processing and a key light on the date |
| `Venue/SpeedDateChime.cs` | The bell |
| **Vision/** | |
| `Vision/VisionFeed.cs` | The webcam service: frames to the face tracker, the latest reading, the signal feed |
| `Vision/VisionPanel.cs` | The on-screen computer-vision panel |
| `Vision/LocalFaceController.cs` | Your blendshapes and head pose on an avatar |
| `Vision/PlayerAvatar.cs` | Your seated avatar for the cinematic view |

**Editor scripts** (`Assets/Editor/`):

| Script | What it does |
| --- | --- |
| `OpenDemoScene.cs` | Opens `Wish.unity` when the editor starts on an empty scene |
| `WorldSplatImporter.cs` | Converts `Assets/Worlds/*.spz` into Gaussian assets; *Tools → Worlds* menu |
| `RocketboxImportFixer.cs` | Import settings and URP material fixes for anything under `Avatars/` |
| `TrueFullScreenPreview.cs` | *Tools → Toggle True Fullscreen Game View* (Ctrl+Alt+F), for demos |
| `EditorRemote.cs` | File-driven remote control of the editor for headless testing: write commands (`play`, `stop`, `open <scene>`, `shot <png>`, `press <Key>`, `call Type.Method`, `cam`, `fps`, `splat`…) to `My project/Temp/remote_cmd.txt`; replies go to `Temp/remote_out.txt`. Always `stop` before `refresh` |

**Data and assets:**

| Path | What it is |
| --- | --- |
| `Assets/Resources/BrandConfig.json` | The product name, tagline, verdict labels and colours |
| `Assets/Resources/Avatars/` | Microsoft Rocketbox characters (`Female_Adult_08`, `Female_Party_02`, `Male_Adult_08`) and idle/seated mocap (MIT licence) |
| `Assets/Resources/Shaders/OutfitRecolor.shader` | Skin, hair and outfit tinting shader |
| `Assets/Resources/Wish/earth_map.png` | Land and sea map for the globe |
| `Assets/Resources/Audio/sample_es.mp3` | Optional placeholder clip |
| `Assets/StreamingAssets/npcs_cancun.json`, `seats_cancun.json` | The café's cast slots (host, date, four patrons, the host's moves) and seats (`table_b` is yours) |
| `Assets/StreamingAssets/npcs.json`, `seats.json` | The same for `SampleScene` |
| `Assets/StreamingAssets/quests.json` | Default milestones, flags and wingman settings |
| `Assets/StreamingAssets/Worlds/*.glb` | Walkable collider meshes for each venue |
| `Assets/GaussianAssets/` | Converted splats, generated by `WorldSplatImporter` |
| `Assets/Settings/` | URP pipeline assets and renderers |
| `Assets/Shaders/Matchmaker/` | The start screen's Earth (day/night, ocean glint, city lights), atmosphere glow and stars |
| `Assets/Editor/AppBuild.cs` | **Build ▸ Linux / Windows / macOS App**: the standalone build (all scenes, named from `BrandConfig.json`, keeps running when unfocused) |
| `Assets/Materials/` | Graybox materials (legacy) |
| `Assets/TutorialInfo/`, `Assets/Readme.asset`, `Assets/InputSystem_Actions.inputactions` | Leftovers from Unity's URP template (unused) |

### `demo-pitch/`

A self-contained animated HTML pitch deck (16 slides).
- Open `demo-pitch/index.html` in Chrome; F is fullscreen, P opens presenter notes.
- [`demo-pitch/README.md`](demo-pitch/README.md) covers the keys and where the demo
  video and photos go (`demo-pitch/assets/`).

---

## 7. Documentation map

| Doc | Audience | What it covers | Status |
| --- | --- | --- | --- |
| [`README.md`](README.md) | Everyone | Vision, startup, architecture, file map | Current |
| [`docs/speed-date.md`](docs/speed-date.md) | Developers | Speed-date design: the latency chain, personas, face signals, no quote no tick, fallbacks, the match bar, receipt, roast, unlocks and sharing, teaching, the demo café | Current |
| [`docs/api.md`](docs/api.md) | Unity developers | The HTTP/WebSocket contract. The **Speed date** section is the live one; the earlier sections are the café | Current |
| [`AGENTS.md`](AGENTS.md) | Coding agents | Repo rules | Current |
| [`demo-pitch/README.md`](demo-pitch/README.md) | Presenters | Running the pitch deck | Current |
| [`eval/README.md`](eval/README.md) | Developers | The café director evaluation | Café |
| [`docs/design.md`](docs/design.md) | Developers, agents | The original master spec (café era); section 18 tracks what was built. Not updated for the speed-date stack. Edit only when asked | Historical |
| [`docs/v1_modifications.md`](docs/v1_modifications.md) | Unity integrator | The café v1 upgrades (warm, streaming, soundscape, mouth shapes, hints) | Café |
| [`docs/api-design.md`](docs/api-design.md) | – | Early scope note for `/v1/speech` and `/v1/scenarios` | Historical |

---

## 8. Testing

```sh
uv run pytest                                        # every test, no network
uvx ruff check orchestrator tools eval               # lint
uv run python tools/test_e2e_pipeline.py --offline   # starts a server, plays whole dates
uv run python tools/test_e2e_pipeline.py             # the same, with your keys
uv run python tools/date_latency_bench.py            # latency per stage, against a running server
uv run python eval/date_selfplay.py --offline        # simulated learners on whole dates; fails on any false award
```

- ElevenLabs and Nemotron are tested against local servers speaking their real
  protocols (a Riva gRPC server stands in for Nemotron).
- Claude's request shape is tested against a mock transport.
- Face tracking tests run on synthetic readings. The two MediaPipe round-trip tests
  skip themselves if the model isn't available.

---

## 9. Limits worth knowing

- **Avatars.** Rocketbox bodies, tinted from your selfie (the date is
  `Female_Party_02`, from the [Microsoft Rocketbox](https://github.com/microsoft/Microsoft-Rocketbox)
  library, MIT licence). Ready Player Me shut down on 31 January 2026, so a selfie
  colours an avatar rather than reshaping its face.
- **Worlds.** Your scene prompt chooses between the scanned worlds and re-lights them;
  it doesn't generate new 3D geometry live.
- **Voices.** Set ElevenLabs voices per dialect and gender with
  `ELEVENLABS_VOICE_<DIALECT>_<GENDER>`. Otherwise a premade voice speaks (Jessica and
  Will for the Southern demo). Voice Library voices only work through the API on a
  paid ElevenLabs plan.
- **Pronunciation.** Claude doesn't hear audio, so pronunciation tips are drawn from
  the words the recogniser found hardest to make out, labelled as a coach's
  impression, never a score.
- **Echo.** Use headphones. The client gates echo while the date talks, but speakers
  next to the mic make barge-in less reliable.
- **Server-only extras.** The verdict's `cost`, `progress` and filler and register
  measures are in the JSON, the readable receipt page and the report; the in-game
  receipt doesn't draw them yet.
- **Culture data is a first draft.** Body-language norms, fillers, register notes and
  cultural moments are tendencies, to be reviewed and tuned by native speakers.
- **Latency.** The target is under 400 ms from the end of your turn to the date's
  first audio; measure yours with `tools/date_latency_bench.py`.

---

## 10. Troubleshooting

| Symptom | Fix |
| --- | --- |
| Unity says there's no date / can't reach the server | Start the orchestrator (`uv run python -m orchestrator`) from the repo root. Check the client's Server Url (`MatchmakerUI`, default `http://127.0.0.1:8765`) |
| Vision panel: "Face tracker offline" | Run `uv sync --group face` and restart the server; check `/v1/face/status` |
| Vision panel: "No webcam found" / "Webcam did not start" | Plug in a camera or close the app holding it; allow camera access in your OS |
| The date doesn't hear you; a notice says to type | No `NVIDIA_API_KEY` (or the recogniser failed): add it, or type with Enter |
| The date speaks in the same sample voice every time | No `ELEVENLABS_API_KEY`, or the voice failed before its first frame; check `/health` |
| The date's replies are canned | No `ANTHROPIC_API_KEY`: the scripted brain is speaking. Check `/health` → `date.brain` |
| The share page or receipt card is a 404 | The run hasn't been graded yet; the receipt must print first |
| Barge-in triggers by itself | The date's voice is reaching your mic: use headphones |
| Pink/missing venue, or no splat | Let the first import finish; run *Tools → Worlds → Use Cancun Cafe* |
| Low frame rate in the café | Gaussian splats are GPU-heavy; close other GPU apps or use a discrete GPU |

---

## 11. Working in this repo

[`AGENTS.md`](AGENTS.md) is the rulebook for agents and humans alike. In short:

- After every edit run `uv run pytest` and `uvx ruff check orchestrator tools`. Both
  must be clean. Run `tools/test_e2e_pipeline.py --offline` after changing the stream.
- uv only: never `pip install`, and never add a dependency without agreement.
- Never loosen "no quote, no tick".
- Secrets live only in `orchestrator/.env`.
- The brand name lives only in `BrandConfig.json`.
- **Dialects are data:** edit `scenarios/speed_dating/dialects/*.json`, and keep
  learner-facing lines gender-neutral about the learner.
- **Unity scripts are referenced by GUID:** rename a script's `.meta` with it. Attach
  new systems through `Core/DateBootstrap.cs`, not by editing scene YAML.
- **Café characters are data too:** edit `scenarios/cafe_cancun/`, then run
  `tools/provision_agents.py`. Never configure agents in the ElevenLabs dashboard.
