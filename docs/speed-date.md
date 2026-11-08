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
| Gemini | Claude speaks; without Claude, a scripted date in the dialect |
| Deepgram | Voice detection still drives barge-in and the wingman's silence timer; the learner types with Enter |
| Fish Audio | The bundled sample voice, paced like speech so the lip-sync and barge-in still work |
| MediaPipe | No face signals; gaze still comes from where the camera looks |

A turn whose provider fails before its first audio frame is replayed through the
fallback. A failure after audio has started ends that line where it is.

## Culture as data

Each dialect file carries more than lines to say. What it adds is read in code, so a
native speaker can tune a city without touching Python:

| Block | What it does |
| --- | --- |
| `nonverbal` | How long a glance away may last while the date talks, what it costs, and one line on local norms for the persona and the judge. Tokyo allows 8 s, Buenos Aires 4 s. In hi-IN the side-to-side head wobble is read as "yes, go on". |
| `cultural_moments` | The custom the date brings up about a minute in: mate in Buenos Aires, a spice dare in Mexico City, cañas in Madrid, a debate in Paris, a compliment to deflect in Shanghai, the family question in Mumbai, aizuchi in Tokyo, a tsukkomi in Osaka. It becomes that date's cultural milestone, and slang still counts too. |
| `other_region_slang` | Words a local places elsewhere ("güey" is Mexico). Hearing one gives the date a light, one-off reaction and costs a point. A word that is local slang here is never on the list. |
| `fillers` | Hesitation words: a local «este…» against an English «um». A filler counts only where a pause is: at the start of a line or before a comma or ellipsis. |
| `register` | How people address each other (vos or tú, tú or usted, 你 or 您, です/ます or casual speech) and when a mismatch is worth a remark. The remark goes in the comment and never moves a grade. |

These are tendencies, not rules about people, and they are written to be reviewed.

## Memory across dates

A learner's profile (by the name they give the matchmaker) records each graded date and a
short practice list per dialect. The list takes only corrections the learner certainly
made: quoted from their own lines and not built on a word the recogniser doubted. The
next date in that dialect carries the two most recent open items. The persona is told
to steer toward them without teaching and never to say them first. The director marks
an item fixed only when the learner's own line contains the better phrasing word for
word, and the receipt quotes that line.

## What a date costs

Every paid call reports its usage to the ledger of whatever is running, through a context
variable, so no call site carries it. That covers Claude tokens with cache reads and
writes, Gemini tokens, Deepgram seconds and Fish characters, plus characters a cached
line saved. The matchmaker's ledger is stored under the date's id, and the live date's
and the grade's under the run id. The receipt's `cost` adds the two.

Claude has list prices built in. Other providers are priced only once their prices are
configured; until then they show usage, never an invented number.

Three things keep the bill down:

- The chemistry judge's prompt is two system blocks: the instructions, then the date's
  persona, fixed for the whole date. The cache breakpoint sits on the last block, so
  every turn after the first reads that prefix from the cache.
- Scripted lines (the greeting, the opener, callouts, authored goodbyes) are voiced once
  and replayed from disk. A line cut off by a barge-in is never cached.
- `PLAN=free` runs the per-turn judge and the wingman on the rules, which removes most of
  a date's model calls.
