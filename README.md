# Parry

*Keep up. Flirt back. Speak like a local.*

Parry is a cultural speed-dating simulator for language learners. You scan your face, pick a dialect and the kind of person you want to meet, describe the scene, and land in a photoreal 3D venue for a three-minute date with an AI character. There is no push-to-talk: you just talk.

During the date:
- your date answers in a streamed voice, in their dialect;
- they read your face and your gaze;
- they warm up or cool off;
- at the bell they either ask for your number or ghost you.

The receipt that prints afterwards grades how you actually spoke, quoting your own words back to you, with a roast worth sharing.

---

## Quick Start

### Prerequisites

| Need | Why |
| --- | --- |
| **Git** | Cloning, and Unity fetches packages from git URLs |
| **[uv](https://docs.astral.sh/uv/)** | Installs Python 3.13 and every dependency |
| **Unity Hub + Unity 6000.0.68f1** (Unity 6, URP) | The client |
| **A webcam + mic + headphones** | Face scan, voice input, and preventing echo |

### 1. Install the Python side

```sh
git clone https://github.com/arthvijay/parry.git && cd parry
uv sync --group face    # Python 3.13, deps, MediaPipe for face tracking
```

### 2. Add your keys (optional)

```sh
cp orchestrator/.env.example orchestrator/.env
```

| Key | What you get |
| --- | --- |
| `ANTHROPIC_API_KEY` | Claude for all LLM jobs — the date's live replies, chemistry, grading, roast. **Most important key.** |
| `ELEVENLABS_API_KEY` | Real dialect voice for your date |
| `NVIDIA_API_KEY` | Speech recognition (otherwise type with Enter) |

Without any keys, the whole date runs offline with scripted dialogue, a sample voice, and typed input.

### 3. Start the orchestrator

```sh
uv run python -m orchestrator    # serves http://127.0.0.1:8765
```

### 4. Open Unity and play

1. Unity Hub → **Add project from disk** → select `My project/` → open with **6000.0.68f1**
2. First import takes a while (packages, avatars, venue splats)
3. Press **Play** in `Wish.unity`
4. Capture your selfie, pick a demo date or create your own, and talk

### Or run it as an app, without the editor

```sh
./play build      # once: builds the Linux app into Builds/Linux/ (or in the editor: Build ▸ Linux App)
./date            # starts the server and opens the game fullscreen; quitting stops the server
./play            # same, in a window   ·   ./play install adds it to your app menu
```

To start it from any folder with one word, add an alias to `~/.bashrc`:
`alias parry='/path/to/repo/date'`, then type `parry`. Don't name the alias `date`:
that hides the system `date` command, and every shell that calls it would open the game.

---

## How It Works

```
Unity 6 client (My project/)                    orchestrator (FastAPI, :8765)
────────────────────────────                    ─────────────────────────────
MatchmakerUI ─── matchmaker/catalog ───────────▶ config.py (dialects, venues, presets)
             ─── matchmaker/generate ──────────▶ matchmaker.py ─▶ Claude
AvatarOnboarding ── avatar/from-selfie ────────▶ face_tracker.py (MediaPipe)
FullDuplexStreamClient ═══ WS /v1/stream ══════▶ stream_gateway.py
  mic PCM ──────────────────────────────────────▶ stt.py (Nemotron ASR)
  webcam JPEGs ─────────────────────────────────▶ nonverbal.py + face_tracker.py
  ◀──── streamed voice, chemistry, signals ─────  date_brain.py (Claude) ─▶ tts.py (ElevenLabs)
DateVerdictReceipt ─ POST /v1/grade ───────────▶ date_grader.py ─▶ Claude
```

**Key design rule — "No quote, no tick":** A milestone, passing grade, or quote is awarded only if you actually said it, verified against the transcript in code. A model that invents evidence is overruled.

---

## Supported Dialects

| Code | Dialect | Cities |
| --- | --- | --- |
| `es-MX` | Mexican Spanish | Ciudad de México, Cancún |
| `es-AR` | Argentine Spanish | Buenos Aires (Palermo) |
| `es-ES` | Castilian Spanish | Madrid (Malasaña) |
| `zh-CN` | Mandarin Chinese | Shanghai, Beijing |
| `hi-IN` | Hinglish / Hindi | Mumbai, Delhi |
| `ja-JP` | Japanese (Tokyo) | Tokyo (Shimokitazawa) |
| `ja-JP-kansai` | Japanese (Osaka) | Osaka (Dōtonbori) |
| `fr-FR` | Parisian French | Paris (le Marais) |
| `en-US-south` | Southern American English | Cancún, Savannah, Austin |

A match unlocks the next stop on the trip.

---

## Controls

| Key | Action |
| --- | --- |
| WASD / arrows | Walk (Shift to run) |
| Mouse | Look |
| F | Sit/stand (sitting starts the date) |
| W | Wingman (3 reply suggestions) |
| T | Translator |
| M | Café menu |
| V | First person ↔ cinematic two-shot |
| S / Tab / L / R / N | Share / learning page / report / retry / next date |
| Esc | Session menu |

---

## Testing

```sh
uv run pytest                                        # all tests, no network
uv run python tools/test_e2e_pipeline.py --offline   # full end-to-end without keys
uv run python tools/test_e2e_pipeline.py             # end-to-end with keys
```

---

## Documentation

| Doc | What it covers |
| --- | --- |
| [`docs/speed-date.md`](docs/speed-date.md) | Speed-date design and architecture |
| [`docs/api.md`](docs/api.md) | HTTP/WebSocket API contract |
| [`docs/latency.md`](docs/latency.md) | Measured latency per stage |
| [`AGENTS.md`](AGENTS.md) | Repo rules for contributors and agents |
| [`demo-pitch/`](demo-pitch/) | Animated HTML pitch deck (16 slides) |

---

## Limits

- **Face signals** are stock MediaPipe with hand-tuned thresholds — expect misses in low light or with glasses
- **Avatars** are tinted Rocketbox bodies, not photorealistic
- **Venues** are scanned Gaussian splats chosen by your prompt, not generated live
- **Pronunciation tips** come from recogniser confidence, not actual audio analysis
- **Use headphones** to prevent echo and unreliable barge-in
- **Culture data** is a first draft — to be reviewed by native speakers
