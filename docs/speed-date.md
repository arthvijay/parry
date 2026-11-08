# The speed date: design notes

How the date stays fast, feels like a person, and stays honest about grading.

## Latency: what the learner waits for

From the learner's last word to the date's first sound:

1. **End of speech.** Nemotron ASR Streaming (NVIDIA Riva gRPC) closes each utterance
   with its own endpointing; a local voice detector marks speech start and end at once.
2. **First token.** Claude (`DATE_CLAUDE_MODEL`, default Sonnet) at low effort, streamed.
   `DATE_BRAIN=gemini` puts Gemini Flash (thinking `LOW`; it rejects `MINIMAL`) in front
   instead. The persona prompt is identical across turns, so it stays warm.
3. **First sentence.** The token stream is cut at the first sentence or, if the opening
   runs long, at the first clause after ~60 characters (`SentenceChunker`). Each piece is
   flushed to ElevenLabs at once.
4. **First audio.** ElevenLabs streams 24 kHz PCM back. A socket for the date's voice was
   opened while the learner was still talking (`ElevenLabsVoice.prewarm`), so the turn pays
   no TLS handshake.
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
from ~8 webcam frames a second. `nonverbal.py` debounces these into human signals:

- **Smile:** held 0.35 s.
- **Laugh:** a smile with an open jaw.
- **Nod / head shake:** two pitch or yaw reversals within 1.5 s.
- **Puzzled, surprised, frown:** brow and mouth shapes.
- **Look away / look back:** from gaze telemetry.

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
| Claude (the date's voice) | A turn Claude cannot answer gets a scripted line in the dialect |
| Gemini | Only used with `DATE_BRAIN=gemini` (Claude then takes over) and for the report's pronunciation notes |
| Nemotron ASR | Voice detection still drives barge-in and the wingman's silence timer; the learner types with Enter |
| ElevenLabs | The bundled sample voice, paced like speech so the lip-sync and barge-in still work |
| MediaPipe | No face signals; gaze still comes from where the camera looks |

A turn whose provider fails before its first audio frame is replayed through the
fallback. A failure after audio has started ends that line where it is.

## Teaching, after the date

During the date nobody corrects the learner. There are two places help lives instead:

- **The translator (T), during the date.** What the date just said, in English, and three
  replies. It's the learner's to read or ignore; the date never knows. It's counted,
  because needing help is part of the picture.
- **Your date, decoded, after the verdict.** The café's old "What we heard" page, rebuilt
  for dating: what landed, at most three fixes, phrases in the dialect for the moments
  they stalled, culture notes, words to practise, a coach's ear on their recorded voice,
  and the whole conversation with the chemistry curve.

## The demo café

Café Rayuela (`presets/cafe_cancun_ar.json`) is authored, not generated, so a demo is
the same every time. It's an Argentine café in Cancún, so the scanned Cancún world, the
ocean and café ambience, and a porteño date all fit together. Ordering is a milestone,
and it moves the scene: Don Julio walks over and serves what was ordered, by name.
