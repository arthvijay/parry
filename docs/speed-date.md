# The speed date: design notes

How the date stays fast, feels like a person, and stays honest about grading.

## Latency: what the learner waits for

From the learner's last word to the date's first sound:

1. **End of speech.** Deepgram endpoints at 300 ms of silence, with an utterance-end
   backstop at 1 s.
2. **First token.** Gemini Flash with thinking at `MINIMAL`. The persona prompt is
   identical across turns, so it stays warm.
3. **First sentence.** The token stream is cut at the first sentence or, if the opening
   runs long, at the first clause after ~60 characters (`SentenceChunker`). Each piece is
   flushed to Fish Audio at once.
4. **First audio.** Fish Audio streams PCM back. Its socket was opened while the learner
   was still talking (`FishVoice.prewarm`), so the turn pays no TLS handshake.
5. **Playback.** Frames go straight from the socket thread into the NPC's ring buffer.

The chemistry judge, the wingman line and the transcript store all run after the reply
has started, off the path the learner feels. `audio_start.first_audio_ms` reports the
measured gap.

## Feeling like a person

- **The persona prompt is written by code, not the model.** Every date gets the same
  rules:
  - one to three spoken sentences;
  - at most one question;
  - react, share and tease, then sometimes ask;
  - call back to what the learner said earlier;
  - never English, never correct grammar, never mention AI.
  The model only writes who the person is.
- **Silent notes each turn.** `[CHEMISTRY n/100 mood]` shapes warmth and length.
  `[NONVERBAL]` says what the face tracker and gaze saw ("they smiled while you were
  talking", "they looked puzzled"). The prompt asks for a brief reaction, only when
  natural.
- **Body language follows chemistry.**
  - At 70 or more: lean in, smile and tilt the head.
  - Below 40: lean back, glance away every few seconds, and a faint frown.
  - If the learner keeps looking elsewhere, the date starts doing the same.
- **Barge-in is local.** The client's voice detector flushes every NPC buffer within a
  frame and tells the server, which stops generating and records only what was heard.
  The date's next line knows they were cut off.
- **Echo.** While a character talks and the learner doesn't, the client sends silence
  instead of the mic, so the date's own voice from speakers isn't heard as the learner.
  Headphones still work best.

## What the face does

MediaPipe Face Landmarker reads 52 ARKit blendshapes, the head pose and a 478-point mesh
from ~8 webcam frames a second.

**The model is stock, not trained by us.** It is Google's `face_landmarker.task`
(float16, v1), run locally on the CPU in `face_tracker.py`: image mode, one face, every
confidence threshold at MediaPipe's default 0.5. The file is fetched once to
`runs/models/` and pinned by SHA-256 (`FACE_MODEL_PATH` overrides it, `FACE_TRACKING=0`
turns tracking off). Frames are analysed in memory on one worker thread, and a frame
that arrives while the last is still being read is dropped. Nothing is saved. No image
reaches Gemini or Claude: the date's brain, the judge and the grader only see the text
signals below.

The judgement lives in `nonverbal.py`, whose thresholds are set by hand. It debounces
the blendshapes, after calibration, into human signals:

- **Smile:** mean smile > 0.45, held 0.35 s.
- **Laugh:** smile > 0.5 with the jaw open > 0.3, held 0.25 s. Takes precedence over a smile.
- **Nod / head shake:** two pitch reversals of 4° or more (yaw: 6°) within 1.5 s, while
  the other axis moves less; at most one every 1.5 s.
- **Puzzled:** little smile (< 0.2), and brows down > 0.35 or a raised inner brow with
  a squint; held 0.8 s.
- **Surprised:** inner brow up > 0.5, eyes wide > 0.3, jaw open > 0.2; held 0.3 s.
- **Frown:** mouth frown > 0.35 with no smile (< 0.15); held 0.7 s.
- **Look away / look back:** from gaze telemetry, overruled by the face when the head
  turns more than 28° from centre, tilts 20° up or down (a phone in the lap), the eyes hold off to
  one side, or the face leaves the frame for a second. With no frames arriving, the game
  camera's gaze stands alone.

Everything is measured against the learner's own resting face, so a resting brow or a
webcam below the chin is not read as a frown or as looking away:

- Each expression's baseline is the 20th percentile of the last 160 frames (~20 s),
  zero for the first 12 frames. It is capped at 0.15 to 0.3, so a long real smile still
  counts, and readings above it are rescaled to 0 to 1.
- The head's centre is the median of the on-screen poses. Looking away never moves it.
- The face's verdict on looking away must hold 0.5 s, so a glance or a blink doesn't
  count.

`date_ended` carries a `face` summary: frames,
`face_visible_pct`, `attentive_pct`, and signal counts overall and while the date talked.

Each signal goes to the vision panel's feed, to the date's prompt, and to the chemistry
director (a smile while the date was joking adds +3). The same blendshapes drive the
learner's own avatar, so the cinematic camera shows them reacting.

## No quote, no tick

The live director and the final grader follow the café's rule. A milestone is met, or a
judged pillar passes, only with a quote the learner actually said, checked against the
transcript in code. A model that invents evidence is overruled:

- the milestone stays open;
- the pillar is capped at D+.

The verdict (MATCH / FRIENDZONED / GHOSTED) is never asked of a model. It is the final
chemistry reading against fixed thresholds.

## Fallbacks

Every provider has a local stand-in, so a missing key or an outage degrades the date
instead of ending it.

| Missing | Stand-in |
| --- | --- |
| Anthropic | Templates build the date, a rules judge moves chemistry, a rules grader writes the receipt |
| Gemini | Claude speaks; without Claude, a scripted date in the dialect |
| Deepgram | Voice detection still drives barge-in and the wingman's silence timer; the learner types with Enter |
| Fish Audio | The bundled sample voice, paced like speech so the lip-sync and barge-in still work |
| MediaPipe (not installed, model missing, or `FACE_TRACKING=0`) | No face signals; gaze still comes from where the camera looks |

A turn whose provider fails before its first audio frame is replayed through the
fallback. A failure after audio has started ends that line where it is.
