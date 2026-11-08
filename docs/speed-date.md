# The speed date: design notes

How the date stays fast, feels like a person, and stays honest about grading.

## Latency: what the learner waits for

From the learner's last word to the date's first sound:

1. **End of speech.** Nemotron ASR Streaming (NVIDIA Riva gRPC) closes each utterance
   with its own endpointing; a local voice detector marks speech start and end at once,
   because Riva reports words, not the moment speech starts. Each dialect asks for its
   own locale (`asr_language` in `config.py`); `NEMOTRON_ASR_LANGUAGE` forces one.
   Hosted Nemotron is English only, so non-English locales are sent to NVIDIA's hosted
   multilingual model (Parakeet 1.1B RNNT Multilingual) on the same key and protocol
   (`stt.function_for`). Its output is tidied: the language tag is dropped, a Spanish
   ¿/¡ placed after the first word is moved back, and spaces before punctuation go.
2. **First token.** Claude (`DATE_CLAUDE_MODEL`, default Sonnet) at low effort, streamed.
   The persona prompt is identical across turns, so it stays warm.
3. **First sentence.** The token stream is cut at the first sentence or, if the opening
   runs long, at the first clause after ~60 characters (`SentenceChunker`). Each piece is
   flushed to ElevenLabs at once.
4. **First audio.** ElevenLabs Flash v2.5 (`stream-input` WebSocket, `pcm_24000`) streams
   PCM back. A socket for the date's voice was opened while the learner was still talking
   (`ElevenLabsVoice.prewarm`), so the turn pays no TLS handshake. Each personality has a
   voice stability (lower is more expressive: playful 0.40, creative 0.35), and the
   learner's level slows or speeds the voice within ElevenLabs' 0.7 to 1.2 range.
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

## Register: when polite is wrong

A textbook teaches *usted* and *vous*. On a speed date in Mexico City, Buenos Aires,
Madrid or Paris they sound like a job interview. Each dialect can name its stiff
register as a regex (`formal_marker`: *usted(es)* for the Spanish dialects, *vous* for
French, 您 for Mandarin), and the rules judge takes 3 points for it, with the reason
"too formal for a date". Japanese and Hinglish have no marker: polite です/ます at first
is normal and warm there. This replaced a blanket rule that treated those words as red
flags in every dialect.

## What the face does

MediaPipe Face Landmarker reads 52 ARKit blendshapes, the head pose and a 478-point mesh
from ~8 webcam frames a second. `nonverbal.py` debounces these into human signals:

- **Smile:** held 0.35 s.
- **Laugh:** a smile with an open jaw.
- **Nod / head shake:** two pitch or yaw reversals within 1.5 s.
- **Puzzled, surprised, frown:** brow and mouth shapes.
- **Look away / look back:** from gaze telemetry, overruled by the face when the head
  turns more than 28° from centre, tilts 20° up or down (a phone in the lap), the eyes hold off to
  one side, or the face leaves the frame for a second. With no frames arriving, the game
  camera's gaze stands alone.

Everything is measured against the learner's own resting face. Each expression's
baseline is a low quantile of the last ~20 s (capped, so a long real smile still counts),
and the head's centre is its median pose, so a resting brow or a webcam below the chin
is not read as a frown or as looking away. `date_ended` carries a `face` summary: frames,
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
| Claude (the date's voice) | A turn Claude cannot answer gets a scripted line in the dialect |
| Nemotron ASR | Voice detection still drives barge-in and the wingman's silence timer; the learner types with Enter |
| ElevenLabs | The bundled sample voice, paced like speech so the lip-sync and barge-in still work |
| MediaPipe | No face signals; gaze still comes from where the camera looks |

A turn whose provider fails before its first audio frame is replayed through the
fallback. A failure after audio has started ends that line where it is.

## Gamified, and shareable

- **The live match bar.** Chemistry runs across the top of the screen as a track in
  the three verdict zones (GHOSTED below 45, FRIENDZONED to 65, MATCH above), with a
  needle that eases to each update, a floating +/− delta, the best reading so far,
  and a banner when the date crosses into a new zone. The zone colours (rose, amber,
  ice) are the receipt's and the pitch deck's.
- **The receipt prints.** The verdict comes out of a little printer as thermal paper,
  line by line, then the stamp slams down across it.
- **The roast** is the line people screenshot. It is held to the same honesty as the
  grades: a roast that quotes the learner must quote them exactly, or it is replaced by
  one built from what was measured. It teases what happened, never who the learner is.
- **Unlocks.** A match unlocks the next dialect on a fixed trip around all nine
  (es-AR unlocks Kansai-ben in Osaka); the client remembers it (🔓 in the matchmaker)
  and N opens the matchmaker on it. Anything short of a match is a rematch.
- **Sharing.** S opens a share page with the receipt as a 9:16 card for TikTok, Reels
  and Shorts. The card is SVG drawn from the saved verdict, so the server needs no
  imaging library; the browser makes the PNG and hands it to the share sheet or the
  platform's upload page.

## Teaching, after the date

During the date nobody corrects the learner. There are two places help lives instead:

- **The translator (T), during the date.** What the date just said, in English, and three
  replies (an answer, a question back, a playful line) with a one-line tip. Claude writes
  it at effort `low` from the last twelve lines; without Claude, the wingman's lines stand
  in. It's the learner's to read or ignore; the date never knows. It's counted (0.1 off
  the pacing pillar each time, and in the report), because needing help is part of the
  picture.
- **Your date, decoded, after the verdict.** The café's old "What we heard" page, rebuilt
  for dating: what landed, at most three fixes, phrases in the dialect for the moments
  they stalled, culture notes, words to practise, pronunciation tips, and the whole
  conversation with the chemistry curve. The report keeps the grader's honesty rules: a
  learner quote not in the transcript is dropped, and nothing built on a word the
  recogniser doubted is shown as a mistake; those words go to "practise saying" instead.
  Pronunciation tips come from the words the recogniser was least sure of: Claude turns
  them into a coach's impression, never a score. Culture notes come from each dialect
  file's `culture` list when Claude is not available.

## The demo café

Café Rayuela (`presets/cafe_cancun_ar.json`) is authored, not generated, so a demo is
the same every time. It's an Argentine café in Cancún, so the scanned Cancún world, the
ocean and café ambience, and a porteño date all fit together. Ordering is a milestone,
and it moves the scene: Don Julio walks over and serves what was ordered, by name.

How an order travels:

1. The learner orders in Spanish ("pedimos unas medialunas"). `order_together` ticks only
   with that quote, like every milestone. The rules judge needs an ordering verb and a
   menu item; Claude gets the menu with the turn.
2. The server matches menu aliases in the quote and sends `scene_action` once per date.
3. Unity starts the host's `bring_order` walk from `npcs_cancun.json` (an `action`-
   triggered move). When it finishes, the client sends `scene_event: host_at_table`. If
   the walk is blocked, the HUD sends it anyway after 12 s.
4. The server waits for the date to finish their sentence (and the learner to stop
   talking), then the host says the preset's `serve_line` with the items.

The menu and prices live only in the preset; they are written into the date's prompt with
the rule never to invent items or prices.

A new authored date is one JSON file in `scenarios/speed_dating/presets/`: `dialect`,
`city`, `venue`, a `host` (greeting, chat, serve line), `variants` for `female` and `male`
(name, age, occupation, backstory, interests, flags, opening line), `menu`, `milestones`,
`closings` and `followups`. It shows up in the catalog's `presets` without code changes.
