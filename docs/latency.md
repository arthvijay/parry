# Latency benchmarks

Measured on 8 November 2026 with `tools/date_latency_bench.py`, against the live stack:
Claude Sonnet 5.5 as the date's brain, chemistry judge, wingman, translator and grader;
NVIDIA Nemotron ASR (English) and Parakeet 1.1B multilingual (Spanish) over hosted Riva
gRPC; MediaPipe Face Landmarker on the server; ElevenLabs Flash v2.5 for the voice. The
server and client ran on one laptop (Fedora, Intel integrated graphics) on home Wi-Fi;
every cloud call went over the public internet.

```sh
uv run python -m orchestrator                                   # the server
uv run python tools/date_latency_bench.py --turns 6 --spoken 3  # the benchmark
uv run python tools/date_latency_bench.py --tts-probe 3         # + ElevenLabs (uses credits)
```

Each run writes JSON and a Markdown table to `runs/bench/`. Numbers below are
milliseconds: p50 / p90 (min to max), n samples.

## The headline: how long the learner waits

| What the learner does | Waits for | p50 | p90 |
| --- | --- | ---: | ---: |
| Speaks a line | the date's first word | **~2.45 s** | ~2.6 s |
| Types a line | the date's first word | **~1.2 s** | ~1.3 s |
| Interrupts the date | the date to stop | **2 ms** server + local fade | |
| Presses W (wingman) | three ways to answer | 3.7–5.1 s | 6.0 s |
| Presses T (translator) | the translation card | 3.4 s | 3.8 s |
| Ends the date | verdict receipt | 6.0 s | |

The spoken figure is the sum of measured stages: 2.30 s from the end of speech to the
first frame with the voice stage switched off, plus 0.16 s for ElevenLabs on a pre-warmed
socket. Typed is 0.99 to 1.11 s plus the same 0.16 s, which matches end-to-end checks
with ElevenLabs on (1.17 s and 1.66 s to the first voice frame).

## Where a spoken turn's time goes

| Stage | p50 | Notes |
| --- | ---: | --- |
| End of speech → speech recogniser's final transcript | 1,150–1,250 | Nemotron/Parakeet endpointing (the local voice detector closes the turn at ~700) |
| Final transcript → first sentence written | ~1,000–1,100 | Claude streaming, first sentence cut by `SentenceChunker` |
| First sentence → first voice frame | 156 (warm), 263 (cold) | ElevenLabs Flash v2.5, 24 kHz PCM |
| Network + client buffer | <20 | One WebSocket, 40 ms frames into a ring buffer |
| **Total** | **~2,450** | |

The chemistry judge (1.8 to 2.1 s) runs in parallel, after the reply has started; the
learner never waits on it.

## Full results

Run 2026-11-08 04:42 · 6 typed + 2 spoken turns and 3 barge-ins per demo. ElevenLabs was
switched off for this run (`tts: sample`) so each stage could be timed on its own; its
own numbers are under *Voice* below.

**Café Rayuela · Argentine latina (`cafe_cancun_ar`, Spanish)**

| Stage | p50 | p90 | min | max | n |
| --- | ---: | ---: | ---: | ---: | ---: |
| Spoken turn: end of speech → first voice frame | 2,321 | 2,321 | 2,321 | 2,321 | 1 |
| Spoken turn: end of speech → voice detector closes the turn | 678 | 731 | 624 | 731 | 2 |
| Spoken turn: end of speech → final transcript | 1,254 | 1,254 | 1,254 | 1,254 | 1 |
| Typed turn: line sent → first sentence written (Claude) | 995 | 1,076 | 945 | 1,251 | 6 |
| Typed turn: line sent → first voice frame | 995 | 1,076 | 945 | 1,251 | 6 |
| Chemistry meter update after a turn (Claude judge) | 1,792 | 2,101 | 1,505 | 2,335 | 6 |
| Barge-in: `barge_in` → `clear_audio` | 2 | 2 | 2 | 2 | 3 |
| Wingman card on W | 5,138 | 6,006 | 4,269 | 6,006 | 2 |
| Translator card on T | 3,429 | 3,763 | 3,095 | 3,763 | 2 |
| Host greeting / opening line → first voice frame (authored text) | 2 | 2 | 1 | 2 | 4 |
| End of date → goodbye fully spoken (`date_ended`) | 12,470 | | | | 1 |
| Verdict receipt (Claude grader) | 6,010 | | | | 1 |
| Learning report (Claude + pronunciation) | 10,502 | | | | 1 |
| Stream join: `init` → `session_ready` | 6 | | | | 2 |

**Café Rayuela · Southern belle (`cafe_cancun_south`, English)**

| Stage | p50 | p90 | min | max | n |
| --- | ---: | ---: | ---: | ---: | ---: |
| Spoken turn: end of speech → first voice frame | 2,304 | 2,446 | 2,162 | 2,446 | 2 |
| Spoken turn: end of speech → voice detector closes the turn | 709 | 730 | 688 | 730 | 2 |
| Spoken turn: end of speech → final transcript | 1,156 | 1,173 | 1,139 | 1,173 | 2 |
| Typed turn: line sent → first sentence written (Claude) | 1,105 | 1,165 | 816 | 1,232 | 6 |
| Typed turn: line sent → first voice frame | 1,105 | 1,165 | 816 | 1,232 | 6 |
| Chemistry meter update after a turn (Claude judge) | 2,051 | 2,400 | 1,673 | 2,862 | 6 |
| Barge-in: `barge_in` → `clear_audio` | 2 | 2 | 2 | 2 | 3 |
| Wingman card on W | 3,700 | 4,016 | 3,384 | 4,016 | 2 |
| Translator card on T | 3,456 | 3,735 | 3,176 | 3,735 | 2 |
| End of date → goodbye fully spoken (`date_ended`) | 11,814 | | | | 1 |
| Verdict receipt (Claude grader) | 5,946 | | | | 1 |
| Learning report (Claude + pronunciation) | 6,795 | | | | 1 |

**Voice (ElevenLabs Flash v2.5, through the server's own `ElevenLabsVoice`)**

| Stage | p50 | p90 | n |
| --- | ---: | ---: | ---: |
| First audio frame, cold socket | 263 | 263 | 1 |
| First audio frame, pre-warmed socket | 156 | 165 | 2 |

**Everything else**

| Stage | p50 | p90 | min | max | n |
| --- | ---: | ---: | ---: | ---: | ---: |
| Face tracking: webcam JPEG → `face_analysis`, round trip | 24 | 30 | 18 | 35 | 30 |
| Face tracking: MediaPipe time on the server | 20 | 26 | 15 | 32 | 30 |
| Custom date written by the matchmaker (Claude) | 5,438 | | | | 1 |
| Demo date built (`POST /v1/matchmaker/preset`, authored) | 5–34 | | | | 4 |

**Client (Unity 6 editor, same laptop)**

| Measure | Value |
| --- | --- |
| Café scene, seated at the table (1.92 M Gaussian splats, full SH, sort every frame) | 25–33 FPS, ~29–39 ms GPU per frame |
| Gaze telemetry to the server | every 250 ms |
| Webcam frames to the face tracker | 8 per second (the server analyses one in ~20 ms, so it keeps up with headroom) |
| Client voice detector frame | 20 ms; barge-in fades the ring buffer locally before the server's 2 ms `clear_audio` |

## Reading the numbers

- **The biggest stage is the speech recogniser's endpointing** (~1.2 s after the last
  word). The hosted Nemotron/Parakeet stream decides when an utterance has ended; the
  local voice detector already knows at ~0.7 s. Finalising on the local detector, or
  tuning Riva's endpointing, is the clearest win left (about 0.5 s).
- **Claude's first sentence takes about 1 s** at low effort with a streamed reply. The
  persona prompt is identical every turn, so it stays cached.
- **The voice adds about 0.16 s** because its socket is opened while the learner is still
  talking.
- **Authored lines** (the host's greeting, the opening line) start in 1 to 3 ms: their
  text is known, so only the voice is waited on.
- **Barge-in is local first.** The client stops playback on its own voice detector; the
  server's 2 ms `clear_audio` only confirms and drops anything still buffered.
- **The slow calls are off the conversation path:** the chemistry judge runs while the
  date talks; the verdict and report are written while the bell rings and the receipt
  prints.
- `date_ended` arrives once the goodbye has been spoken in full (judges drained, the
  goodbye written by Claude, then voiced), so its 12 s is mostly the date talking.

## Caveats

- Small samples (n = 1 to 6 per stage, one run); treat them as typical, not guaranteed.
- Learner speech was synthesised with espeak-ng; a robotic voice is harder to recognise
  (one Spanish line in two was not transcribed), and a real voice is usually easier.
- Cloud latency varies with the network and provider load; the earlier Gemini Flash
  brain was faster to start (~0.4 s first audio) but failed on the free tier, so Claude
  is the default (see `DATE_BRAIN` in `orchestrator/.env.example`).
- The FPS was measured in the Unity editor; a standalone build runs faster.
