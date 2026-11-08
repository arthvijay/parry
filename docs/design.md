# End-to-End Design Doc

**The app combines photorealistic 3D environments, real-time conversational voice agents, and LLM-driven scenario generation to turn language learning into an interactive simulation of real-world conversations.**


> **Building today? Start at section 18**, then `docs/v1_modifications.md`. Section 18 records what is actually built, what this plan lacked and why each component exists; section 18.11 is the state after the build of 2026-09-20; the v1 document is the contract the Unity client codes against. Where it disagrees with sections 5, 10 or 14, section 18 wins.

## 0. How to read this doc

This is the MAIN spec. Any other guide in the repo that says "see MAIN spec" means this document. It is written for two readers: a developer with no background in 3D, Unity or voice AI, and a coding agent that needs enough context to write the code without asking.

The work splits into three areas. Each area has one section that is its home, and everyone should read sections 1 to 6 and section 10.

| Area | Home sections | Hands off |
| --- | --- | --- |
| World (Marble) | 7 | Scene files plus a `scene_manifest.json` to the Unity runtime |
| Runtime (Unity) | 8 | A running scene that speaks the bridge protocol in section 10 |
| Voice and brain (ElevenLabs, director, feedback) | 9, 10, 11, 12 | A Python orchestrator that speaks the same bridge protocol |

Claims are marked two ways. A link means the page was opened on the as-of date above and the claim was read there. The words **verify this** mean the claim could not be confirmed from a primary page and someone must check it before relying on it. Prices and credit costs change often, so re-check them on the day you spend money.

## 1. What we are building and why

The app lets a language learner walk into a photorealistic 3D copy of a real kind of place and get real tasks done by speaking with AI characters who talk at native speed. The first scenario is a café in Cancún, in Mexican Spanish.

### The problem

Many learners can pass a grammar quiz and still freeze at a counter. Classroom Spanish is slow, patient and face to face with a teacher. Real Spanish is fast, arrives before you are ready, and comes with a task attached: order, pay, reply, keep the chat going. The gap is not vocabulary. It is performance under mild social pressure, in a specific place.

### Who it is for

The first user is an adult at CEFR level A2 to B1. CEFR is the European scale for language ability; A2 to B1 means "knows present and past tenses, has a few hundred words, cannot yet hold a conversation comfortably". They have a trip, a move or a meeting coming up. They are anxious about one concrete situation, not about Spanish in general.

### What exists today and where it falls short

| Product | What it does | Where it falls short for our user |
| --- | --- | --- |
| Praktika | AI avatar tutors, role-play, corrections on pronunciation, grammar and word choice | The avatar is a tutor on a screen. It waits for you and corrects you mid-conversation. There is no place and no task pressure. |
| Speak | Guided, voice-first speaking curriculum with an AI tutor | It is a curriculum. You follow its lesson, not your own upcoming situation. |
| Duolingo Max | Video Call with a Duolingo character, plus Roleplay scenarios | It is a video call with a friendly character. Premium tier, and not in every course. |

Product descriptions are from [Talkio's 2026 comparison](https://www.talkio.ai/blog/best-ai-language-speaking-practice-apps-in-2026). The "falls short" column is our argument, not theirs.

All three are "talk to an AI in Spanish". The AI is a patient tutor, the setting is a chat window, and nothing is at stake.

### Our positioning: situated rehearsal

It is not "talk to an AI in Spanish". It is: **rehearse the specific real place and the specific real task you are anxious about, with someone who does not slow down for you.**

Three things follow from that sentence, and each is a build requirement.

1. **Specific place.** The scene is generated from a description or photo of a real kind of place, so the learner can rehearse the café they will actually visit.
2. **Specific task.** Every run has explicit goals, such as "ask the price before you are told it". The run ends with a pass or fail per goal.
3. **Does not slow down.** Characters speak at natural speed and stay in character. They never switch to English and never correct grammar mid-conversation. Correction happens after the run, on a feedback screen.

### Why does this need 3D at all?

**One sentence: the anxiety lives in the approach and the place (walking up to a stranger, reading a menu on the wall, being spoken to before you are ready), and only a walkable scene lets you rehearse that, while the scene gives the conversation real things to be about.**

Pushed further, there are two supporting points. First, the scene is input to the conversation: the menu, the counter and the table are things both sides can refer to. Second, the scene is output of the conversation: when you order, a cup appears; when you ask for the bill, it arrives. A chat window can do neither.

## 2. Primer and glossary

Read this once. Every later section assumes these words.

### The 3D world

| Term | What it is |
| --- | --- |
| World model | An AI model that generates a whole 3D place you can move through, from a text prompt, photo or video. Marble, by World Labs, is one. Compare an image model, which outputs one flat picture. |
| Gaussian splat | A way to store a 3D scene as millions of small, soft, coloured blobs instead of triangles. Each blob has a position, size, colour and transparency. Drawn together they look like a photo you can walk through. Splats look real but are static: nothing in them moves, lighting is baked in, and they have no solid surface. |
| Mesh | The classic 3D format: surfaces made of triangles. Game engines collide with meshes and animate them. Characters are meshes. |
| Collider mesh | A rough, invisible triangle mesh of the same room, used only for physics. The splat is what you see. The collider is what stops you walking through the counter. Marble exports one at 100k to 200k triangles. |
| `.ply` | The plain, uncompressed splat file. Large, but every splat tool reads it. |
| `.spz` | A compressed splat file, roughly ten times smaller than `.ply`. It is Marble's native format. Fewer tools read it, and versions differ. |
| `.glb` | The standard single-file format for meshes (binary glTF). Marble's collider mesh and most avatars come as `.glb`. |
| Panorama (pano) | One 360-degree image in a 2:1 rectangle ("equirectangular"). Marble builds every world from a pano internally and lets you export it. Our last-resort fallback wraps it around the camera as a skybox. |
| Skybox | An image drawn infinitely far behind everything. You can look around it but not walk into it. |

### The engine

| Term | What it is |
| --- | --- |
| Unity | A game engine: the program that draws the scene each frame, moves the player, plays audio and runs our C# scripts. |
| GameObject, component, prefab | Everything in a Unity scene is a GameObject. Behaviour comes from components attached to it, such as an AudioSource or our own script. A prefab is a saved, reusable GameObject. |
| URP | Universal Render Pipeline, one of Unity's three renderers. Our repo already uses it. |
| Character controller | The component that moves the player with WASD and mouse and keeps them on the floor. |
| Rigged avatar | A character mesh with a skeleton inside, so animations can move it. "Humanoid" rigs let one animation play on any character. |
| Blendshape | A named facial pose stored in the mesh, such as "mouth open" or "smile", set from 0 to 100. Lip-sync works by driving blendshapes. |
| Viseme | The mouth shape that goes with a speech sound. Lip-sync software turns audio into visemes, and visemes into blendshape values. |
| Spatial audio | Sound that comes from a point in the scene, so it gets quieter and shifts left or right as you move. |

### The voice

| Term | What it is |
| --- | --- |
| Conversational agent | A hosted service that runs a full voice conversation loop: speech recognition, a language model, speech synthesis and turn-taking. We send microphone audio in and get the character's voice out. ElevenLabs calls its product ElevenAgents. |
| ASR / STT | Automatic speech recognition, or speech to text. Turns the learner's audio into words. |
| LLM | Large language model. Decides what the character says next. |
| TTS | Text to speech. Turns the character's words into a voice. |
| System prompt | The standing instructions that define the character: who they are, how they talk, what they must never do. |
| Turn-taking | Deciding when the user has finished speaking so the agent can answer. Too eager and it cuts learners off. Too patient and it feels dead. |
| Barge-in | The user starts talking while the agent is still talking. A good agent stops mid-sentence. The server tells us with an `interruption` event, and we must drop any audio still queued. |
| VAD | Voice activity detection. The signal that says "someone is speaking now". |
| Client tool | A function the agent's LLM can call that runs on our machine, not on ElevenLabs' servers. This is how the character makes things happen in the scene, such as `serve_order`. |
| Server tool (webhook) | A function the agent calls on a public web URL. We do not need these. |
| System tool | A built-in agent action such as `end_call` or `skip_turn`. |
| Dynamic variable | A `{{placeholder}}` in the prompt that we fill in when each conversation starts, such as the learner's name. |
| Override | Replacing part of the agent's configuration for one conversation, such as the voice. Off by default for security. |
| Contextual update | A silent note we send into a live conversation. The agent reads it but does not speak it. Our director uses this to steer the character. |
| WebSocket | A two-way network connection that stays open, so both sides can send messages at any time. We use two: one to ElevenLabs, one between Python and Unity. |
| PCM 16 kHz | Raw, uncompressed audio: 16,000 numbers per second, each 16 bits, one channel. The format the agent sends and expects. |

### Our own words

| Term | What it is |
| --- | --- |
| Actor | The ElevenLabs agent playing a character. Fast, in character, knows nothing about scoring. |
| Director | Our Python logic plus a small OpenAI model that watches the transcript, ticks off goals, logs mistakes and quietly steers the actor. |
| Tutor | A larger OpenAI model that writes the feedback report after the run. |
| Orchestrator | The one Python process that connects everything. |
| Bridge | The local WebSocket between the orchestrator and Unity, and the message format on it (section 10). |

## 3. The café scenario

One run is a first meeting over coffee at a small café in Cancún: the waitress walks you to the table, you order from her there, then talk with the person you came to meet. It takes 4 to 6 minutes and has four core goals and two bonus goals.

Scenario id: `cafe_cancun_v1`. Everything in this section lives in `scenarios/cafe_cancun/scenario.yaml` so the code never hard-codes it.

### Setting

Café Nader is a small independent café a few blocks from Avenida Náder in downtown Cancún, not the hotel zone. It is 5:30 pm and warm. There is a wooden counter with an espresso machine, a chalkboard menu on the wall behind it, a pastry case, and four or five tables. It is table service: the waitress seats you, takes your order at the table, and brings the bill when you ask. The café name is invented.

The player spawns just inside the door, about 4 metres from the table by the window. Maria meets them at the door and walks them over. Luis is already sitting at that table.

### Characters

Two characters, two ElevenLabs agents, two voices. Only one conversation is live at a time: whoever you are standing next to.

|  | Maria, the waitress | Luis, the person you are meeting |
| --- | --- | --- |
| `npc` id | `maria` | `luis` |
| Age and background | About 40, from Mérida, has worked at Café Nader for years | 29, marine biologist from Guadalajara, moved to Cancún 2 years ago for sea turtle conservation work |
| Manner | Warm, quick, practical. Greets you at the door, walks you to the table and takes your order there. Calls customers "joven". | Curious, playful, easy to talk to. Teases a little. Asks questions and expects some back. |
| Register | Informal "tú", Mexican idiom: "¿qué te sirvo?", "¿algo más?", "ahorita te lo traigo" | Informal "tú": "¿neta?", "qué padre", "¿y tú qué onda?" |
| What they withhold | Never states a price or the total until asked | Never carries the conversation alone. After two short answers in a row he goes quiet and waits. |
| Curveball | One fast clarifying question per order, see goal G3 | Mentions one specific detail that invites a follow-up, see goal G5 |

Luis's name, gender and voice are swappable per learner through dynamic variables and a voice override. Luis is the default.

### Assumed learner

CEFR A2 to B1. Knows present tense and some past tense, numbers to 1,000, food words and basic question words. Can build a sentence given a few seconds. Has not had a real conversation at native speed.

The characters do not simplify for this level by default. The learner can earn a slowdown by asking for it in Spanish ("¿más despacio, por favor?"). That is goal G6 and a real-world skill.

### The menu

Prices are in Mexican pesos (MXN) and are plausible, not sourced. This table is the single source of truth: it becomes `scenarios/cafe_cancun/menu.json`, the agent's knowledge base document, and the ASR keyword list.

| `item_id` | Spanish name | Price (MXN) |
| --- | --- | --- |
| `americano` | Café americano | 45 |
| `cafe_olla` | Café de olla | 50 |
| `latte` | Latte | 65 |
| `capuchino` | Capuchino | 65 |
| `horchata` | Horchata fría | 55 |
| `jamaica` | Agua de jamaica | 40 |
| `chocolate` | Chocolate caliente | 60 |
| `concha` | Concha | 30 |
| `pay_limon` | Pay de limón | 70 |
| `chilaquiles` | Chilaquiles verdes | 120 |

Today the café is out of `pay_limon`. Maria offers the concha instead. This is one of the curveballs.

### Goals

A goal is complete only when the director sees evidence in the learner's own words. The character saying it for them does not count.

| Id | Goal | With | Complete when | Does not count |
| --- | --- | --- | --- | --- |
| G1 `order` | Order at least one item in Spanish | Maria | The learner names a menu item inside a request form: "quiero", "quisiera", "me da", "me das", "me pones", "para mí", or "un X, por favor". Maria then calls `serve_order`. | Pointing, English, or only saying "sí" when Maria suggests something |
| G2 `ask_price` | Ask what something costs, or the total, before being told | Maria | The learner asks a price question: "¿cuánto cuesta...?", "¿cuánto es?", "¿cuánto le debo?", "¿qué precio tiene...?", "¿a cómo está...?" | Maria volunteering the total because the learner tried to leave |
| G4 `small_talk` | Hold a personal conversation for at least three exchanges | Luis | The learner makes at least two statements about themselves that are full clauses with a verb, across at least three back-and-forth exchanges on a personal topic | One-word answers, "sí", "no", "bien" |
| G5 `follow_up` | Ask a follow-up question about something Luis actually said | Luis | The learner's question refers to content from one of Luis's previous two turns. Example: he mentions tagging sea turtles at night, and the learner asks "¿por qué de noche?" | A bare "¿y tú?", or a new unrelated question |
| G3 `curveball` (bonus) | Handle an unexpected fast question | Maria | Maria asks one of: "¿para tomar aquí o para llevar?", "¿leche entera o deslactosada?", "se me acabó el pay, ¿te ofrezco una concha?". The learner answers appropriately within two turns, with or without asking for a repeat. | Silence, or English |
| G6 `repair` (bonus) | Recover in Spanish when lost | Either | The learner uses a Spanish repair phrase at least once: "¿cómo?", "¿mande?", "¿puedes repetir?", "más despacio, por favor", "¿qué significa...?", "no entendí" | Switching to English to ask |

### Success

| Result | Rule |
| --- | --- |
| Pass | All four core goals (G1, G2, G4, G5) complete inside the time cap |
| Partial | Two or three core goals complete |
| Retry | Fewer than two |
| Stars | One star for a pass, one for each bonus goal, so zero to three |

Two counters are shown but do not block a pass: the number of learner turns in English, and the number of hints used. A hint is holding Tab to show live subtitles.

### Timing

| Phase | Target | Hard cap |
| --- | --- | --- |
| Walk in, met at the door | 15 s | none |
| Conversation with Maria | 60 to 90 s | 180 s (`max_duration_seconds`) |
| Walk to table | 10 s | none |
| Conversation with Luis | 2 to 3 min | 300 s |
| Feedback screen | 1 min to read | none |
| Whole run | 4 to 6 min | about 9 min |

### What the feedback screen shows

1. The result and stars, and the goal checklist. Each completed goal quotes the learner's own sentence that earned it.
2. **Three things to fix**, never more. Each has what we heard you say, a better version, and one line in English on why. Ranked by how much the mistake would confuse a native speaker.
3. **Phrases that would have helped**: two or three phrases for the moments where the learner stalled or used English.
4. What went well: one specific thing, quoted.
5. Counters: English turns, hints, number of repair phrases, time taken.
6. A suggested next run, such as "same café, Maria is busier and asks two curveballs".

The screen says "what we heard", not "what you said". Speech recognition makes errors and sometimes silently fixes the learner's grammar. Section 11 covers this.

### This is a platform, not one scene

A scenario is data: a generated world, a cast of characters, a goal list, a set of scene actions. The engine, bridge, director and feedback code do not change. Three more scenarios using the same schema:

|  | Pharmacy | Ticket counter | Apartment viewing |
| --- | --- | --- | --- |
| World prompt | Small Mexican farmacia, counter, shelves behind glass | Bus station ticket window (ADO style), queue rail, departures board | Empty one-bedroom flat, kitchen, balcony |
| Character | Pharmacist, precise, asks safety questions | Clerk behind glass, bored, fast, hard to hear | Landlord, friendly but selling |
| Core goals | Describe a symptom; ask for a product; understand the dose; ask the price | State destination and time; choose between two options; confirm the platform; pay | Ask about rent and what it includes; ask about deposit; raise one problem; ask about next steps |
| What they withhold | The dose instructions, until asked | Which platform, until asked | That utilities are extra, until asked |
| Curveball | "¿Es para usted o para alguien más?" | "Ya no hay de las tres, ¿le sirve el de las cinco?" | "¿Tiene aval?" (a guarantor, a Mexico-specific concept) |
| Scene actions (client tools) | `hand_over_product`, `show_bill` | `print_ticket`, `show_departures` | `open_door`, `point_at` |

The pattern in every scenario is the same. The character withholds something the learner must ask for, and throws one curveball at native speed.

## 4. Tech stack decision

The committed stack holds up. The one structural decision is to put a single Python process, the orchestrator, between ElevenLabs and Unity. Unity never talks to the internet.

### The stack

| Layer | Choice | Why | If it fails |
| --- | --- | --- | --- |
| World generation | World Labs Marble, model `marble-1.1` | Committed. Only tool that gives a walkable photoreal room from a prompt in about 5 minutes. | Pano skybox (section 15) |
| Renderer and runtime | Unity `6000.0.68f1` with URP 17, as already in the repo | Committed. Animator, humanoid retargeting and spatial audio are built in. | Browser client with Spark (section 7) |
| Splat plugin | [winnie1994 fork](https://github.com/winnie1994/UnityGaussianSplatting) of aras-p UnityGaussianSplatting, already in `Packages/manifest.json` | It is the fork [World Labs' Unity page](https://docs.worldlabs.ai/marble/export/gaussian-splat/unity) tells you to use | [gsplat-unity](https://github.com/wuyize25/gsplat-unity), but it needs Gamma colour space |
| Voice characters | ElevenLabs ElevenAgents, one agent per character | Committed. Handles ASR, LLM, TTS, turn-taking and barge-in in one hosted loop. | None needed. It is the most mature piece. |
| Glue | Python 3.11+, [`elevenlabs` SDK 2.68.0](https://pypi.org/project/elevenlabs/), `websockets`, `openai`, `pydantic` | The Python SDK already implements the agent protocol, tools, pings and barge-in. Keys stay out of the Unity build. | Raw WebSocket in Python, same process |
| Director and tutor | OpenAI API, Responses API with structured outputs | Mature structured outputs, and keeps judgement separate from the voice vendor | Any other LLM behind the same function |

### Why a Python orchestrator in the middle

Your instinct to integrate in Python is right. Five reasons, in order of weight.

1. **The official Unity SDK does not fit.** [elevenlabs/unity](https://github.com/elevenlabs/unity) requires Unity 6.3 (`6000.3.0f1+`), is at an unreleased 0.1.0, and says its APIs may change. Our repo is on `6000.0.68f1`. Upgrading Unity mid-build puts the splat plugin at risk.
2. **The Python SDK is mature.** It handles the signed URL, ping and pong, tool calls, tool results and dropping stale audio after a barge-in. Rewriting that in C# costs hours and adds nothing to the product.
3. **The brain must see everything.** The director needs the live transcript, the tool calls and the scene events in one place. That place cannot be inside ElevenLabs, and should not be inside Unity.
4. **It decouples the work.** The voice side can be built and tested as a complete conversation with no Unity at all. The Unity side can build against a fake orchestrator.
5. **It makes the renderer replaceable.** If Unity fights us, a browser client that speaks the same bridge protocol drops in, and nothing in Python changes.

The cost is one extra hop for audio on localhost. That adds a few milliseconds, which is not audible.

### Who is the WebSocket server: recommend Python, not Unity

One alternative is Unity exposing a C# WebSocket server and Python connecting to it. It works, but the reverse is safer. **Recommendation: Python hosts the server at `ws://127.0.0.1:8765`, and Unity connects as a client.**

- Unity's Mono runtime does not implement `HttpListener` WebSockets, so a Unity server needs a third-party library. The options are [SimpleWebTransport](https://github.com/James-Frowen/SimpleWebTransport), [websocket-sharp](https://github.com/sta/websocket-sharp) (last NuGet release 2016) or [Fleck](https://github.com/statianzo/Fleck). None has a primary source confirming it as a server inside Unity on macOS. **Verify this** if you go that way.
- A Unity client is well trodden. [NativeWebSocket](https://github.com/endel/NativeWebSocket) v2.0.4 is maintained and dispatches events on Unity's main thread for you.
- Every time you press Play, Unity reloads its scripts. A server socket inside Unity dies and can leave the port busy. A client just reconnects.
- The orchestrator outlives Play sessions, so an ElevenLabs session and its logs survive a Unity restart.

The message format in section 10 is identical in both directions. If a Unity-side server already exists, keep it and have Python connect as the client. Do not spend an hour arguing about it.

### Where OpenAI fits

The two vendors do not overlap. ElevenLabs owns the voice loop. OpenAI owns the judgement.

| Use | API | Model | When it runs |
| --- | --- | --- | --- |
| Director: goal detection and mistake logging | Responses API, structured output | Small and fast, `gpt-5.6-luna` | After every learner turn, in the background, never blocking speech |
| Tutor: feedback report | Responses API, structured output | Larger, `gpt-5.6-terra` | Once, when the run ends |
| Actor's LLM (experiment) | ElevenLabs "Custom LLM" pointed at `https://api.openai.com/v1` with our key | `gpt-5.6-luna` or `gpt-5.6-terra` | Every character turn |

Model names are from [OpenAI's pricing page](https://developers.openai.com/api/docs/pricing) as read through a summarising fetcher. **Verify this**: confirm the exact model id strings on that page before hard-coding them. Keep them in `.env`.

The third row is optional. ElevenLabs [documents](https://elevenlabs.io/docs/eleven-agents/customization/llm/custom-llm) pointing Custom LLM at OpenAI with your own key stored as a workspace secret. Start with a built-in model from the agent's dropdown. Switch to Custom LLM once the demo works, measure time to first audio, and keep it only if it is within about 200 ms of the built-in.

## 5. End-to-end architecture

Two programs run on one laptop: Unity and the Python orchestrator. The orchestrator holds two WebSockets, one out to ElevenLabs and one local to Unity, and makes HTTPS calls to OpenAI.

### Components and what flows between them

```mermaid
flowchart LR
  MIC["Headset mic"] -->|"PCM16 16 kHz, PyAudio"| ORCH["Python orchestrator"]
  ORCH -->|"wss JSON, base64 PCM"| EL["ElevenLabs agent"]
  EL -->|"wss JSON: audio, text, tool calls"| ORCH
  ORCH -->|"ws JSON + binary PCM"| UNITY["Unity scene"]
  UNITY -->|"ws JSON: proximity, results"| ORCH
  ORCH -->|"HTTPS Responses API"| OAI["OpenAI director, tutor"]
  MARBLE["Marble world"] -->|".ply .glb .png + manifest"| UNITY
  UNITY -->|"spatial audio, frames"| USER["Headphones, screen"]
  ORCH -->|"feedback.json, HTML"| FB["Feedback screen"]
```

Read it left to right: the learner's voice enters at the mic, the character's voice and actions come out in Unity, and the feedback report comes out at the end.

| Arrow | Protocol or format | Detail |
| --- | --- | --- |
| Mic to orchestrator | PCM, 16-bit, mono, 16,000 Hz, 250 ms chunks | Captured by PyAudio inside the SDK's audio interface. Not captured in Unity. |
| Orchestrator to ElevenLabs | `wss://api.elevenlabs.io/v1/convai/conversation?agent_id=...` | JSON text frames. Mic audio goes as `{"user_audio_chunk": "<base64>"}`. |
| ElevenLabs to orchestrator | Same socket | JSON frames: `audio`, `user_transcript`, `agent_response`, `agent_response_correction`, `interruption`, `client_tool_call`, `ping` |
| Orchestrator to Unity | `ws://127.0.0.1:8765`, the bridge | JSON text frames for control. Binary frames for character audio: raw PCM16 mono 16 kHz. |
| Unity to orchestrator | Same socket | JSON: `hello`, `proximity.enter`, `proximity.exit`, `tool.result`, `ptt`, `hint` |
| Orchestrator to OpenAI | HTTPS, `POST /v1/responses` | Structured output parsed into Pydantic models |
| Marble to Unity | Files, by hand | `.ply` splat, `.glb` collider, `.png` pano, `scene_manifest.json` |
| Orchestrator to feedback | `runs/<run_id>/feedback.json` and `feedback.html` | Also sent to Unity as a `feedback.ready` message |

### Why the mic is in Python and the speaker is in Unity

The microphone is not spatial, so nothing is gained by capturing it in Unity. Capturing in Python avoids Unity microphone permissions, resampling and an upload hop.

The character's voice is spatial. It should come from the character's mouth, get quieter as you walk away, and drive lip-sync. So the orchestrator forwards agent audio to Unity as binary frames, and Unity plays it on the character's AudioSource.

In the first build stage the orchestrator plays audio straight to the laptop speakers and Unity is not involved. That gets a talking demo in the first hours. Section 14 has the stages.

### One conversational turn, including a tool call and a barge-in

```mermaid
sequenceDiagram
  participant L as Learner
  participant O as Orchestrator
  participant E as ElevenLabs
  participant U as Unity
  participant D as Director (OpenAI)
  L->>O: speech (mic PCM)
  O->>E: user_audio_chunk
  E-->>O: user_transcript
  O-)D: check goals, log mistakes
  E-->>O: client_tool_call serve_order
  O->>U: tool.call serve_order
  O-->>E: client_tool_result (total)
  E-->>O: agent_response + audio chunks
  O->>U: binary PCM frames
  U->>L: voice, lip-sync, cup appears
  L->>O: interrupts mid-sentence
  E-->>O: interruption
  O->>U: audio.flush
  D--)O: goal G1 done
  O->>U: goal.update G1
```

Two things in this diagram matter most. The director call is fire-and-forget, so it never delays the character's reply. And the orchestrator answers `client_tool_result` itself, at once, without waiting for Unity's animation to finish.

### States of a run

```mermaid
stateDiagram-v2
  [*] --> Exploring
  Exploring --> Connecting: proximity.enter
  Connecting --> Listening: session open
  Listening --> Thinking: learner stops
  Thinking --> Speaking: first audio
  Speaking --> Listening: audio ends
  Speaking --> Listening: barge-in
  Listening --> Exploring: exit or end_call
  Exploring --> Feedback: all NPCs done or timeout
  Feedback --> [*]
```

The orchestrator owns this state and broadcasts it to Unity as `session.state` messages. Unity uses it for the character's body language: looking at you while listening, a small "thinking" pose, talking animation while speaking.

### What runs where

| Process | Started by | Listens on | Needs internet |
| --- | --- | --- | --- |
| `python -m orchestrator` | First | `ws://127.0.0.1:8765` | Yes: ElevenLabs and OpenAI |
| Unity Editor in Play mode, or a build | Second | Nothing. Connects out to the bridge and retries every 2 s. | No |

Secrets live only in `orchestrator/.env`: `ELEVENLABS_API_KEY`, `OPENAI_API_KEY`, `AGENT_ID_MARIA`, `AGENT_ID_LUIS`, `DIRECTOR_MODEL`, `TUTOR_MODEL`. The file is git-ignored. Nothing secret is ever in the Unity project.

### Inside the orchestrator

One asyncio event loop runs four tasks.

| Module | Job |
| --- | --- |
| `bridge.py` | The WebSocket server. Parses and validates every message against Pydantic models. Holds the one Unity connection. |
| `actor.py` | Wraps the ElevenLabs conversation. Starts and ends sessions per character. Registers client tools. Implements the custom audio interface that forwards audio to the bridge. |
| `director.py` | Keeps run state: goals, mistakes, counters. Calls OpenAI after each learner turn. Sends `goal.update` to Unity and contextual updates to the actor. |
| `tutor.py` | Builds the feedback report at the end and renders `feedback.html`. |

The SDK ships a threaded `Conversation` and an `AsyncConversation` with an `AsyncAudioInterface`. Start with the threaded one: it is the documented path, and section 9 shows it. Its callbacks run on SDK threads, so hand each one to the loop with `asyncio.run_coroutine_threadsafe`. Moving to the async pair later is mechanical.

## 6. Build pipeline and the seams between components

The three areas can be built in parallel because each has a stub for the other two.

### The pipeline in dependency order

```mermaid
flowchart TD
  A["1. Generate world in Marble"] --> B["2. Export .ply, .glb, .png"]
  B --> C["3. Write scene_manifest.json"]
  C --> D["4. Import into Unity, align collider"]
  D --> E["5. Place spawn, NPCs, triggers"]
  F["A. Create ElevenLabs agents"] --> G["B. Orchestrator talks, no Unity"]
  G --> H["C. Bridge server + mock Unity"]
  E --> I["6. Unity connects to bridge"]
  H --> I
  I --> J["7. Audio, lip-sync, tools in scene"]
  J --> K["8. Director, goals HUD, feedback"]
```

Steps 1 to 5 and steps A to C are independent. They meet at step 6.

### Seam 1: world to Unity

The world step delivers one folder per world, `worlds/<scene_id>/`, holding four files and a manifest.

| File | Format | Purpose |
| --- | --- | --- |
| `cafe_cancun_v1_2m.ply` | PLY, about 2M splats | The scene you see |
| `cafe_cancun_v1_500k.ply` | PLY, about 500K splats | Low-end fallback if the frame rate is poor |
| `cafe_cancun_v1_collider.glb` | GLB, 100k to 200k triangles, typically 3 to 4 MB | Physics only, never rendered |
| `cafe_cancun_v1_pano.png` | Equirectangular PNG, 2560 x 1280 | Skybox fallback, and ambient light colour reference |
| `scene_manifest.json` | JSON, below | Everything the Unity side would otherwise have to ask |

```json
{
  "scene_id": "cafe_cancun_v1",
  "marble_world_id": "<from the Marble URL or API>",
  "source": "app",
  "model": "marble-1.1",
  "input_type": "image",
  "prompt": "<the exact text prompt used>",
  "input_image": "inputs/cafe_ref_01.png",
  "coordinate_system": "opengl",
  "metric_scale_factor": null,
  "ground_plane_offset": null,
  "files": {
    "splat": "cafe_cancun_v1_2m.ply",
    "splat_low": "cafe_cancun_v1_500k.ply",
    "collider": "cafe_cancun_v1_collider.glb",
    "pano": "cafe_cancun_v1_pano.png"
  },
  "composition": {
    "counter_visible": true,
    "table_with_two_chairs": true,
    "approx_walkable_m": [5, 4],
    "people_in_scene": false,
    "known_artifacts": "blurry corner behind the door"
  },
  "exported_at": "2026-09-19T15:00:00-04:00"
}
```

`coordinate_system`, `metric_scale_factor` and `ground_plane_offset` matter because Marble's own docs disagree about axes and scale (section 7). For API exports, copy the two numbers from the API response. For app exports, leave them `null`.

The splat files are too big for a normal git commit. GitHub rejects files over 100 MB. Put `worlds/` on a shared drive, and commit only the manifest and a `README` with the drive link. **Verify this**: check the real `.ply` size on first export. If it is under 100 MB, Git LFS is an option.

**What the world must get right in the world itself.** The scene needs a counter with standing room on both sides, one table with two chairs and clear floor next to it, at least 4 by 5 metres of walkable floor, and no people. Marble cannot generate people, and our characters are added in Unity.

**Unity stub.** Do not wait for the café. World Labs publishes [example scenes with every export format](https://docs.worldlabs.ai/marble/export/specs). Download one first and get import, alignment and walking working on it. Build the character, trigger and audio work in a grey-box room made of a plane and cubes.

**World stub.** None needed. This step has no upstream dependency. Check exports in [SuperSplat](https://superspl.at/editor) in the browser before handing over.

### Seam 2: Unity to voice

The only interface is the bridge protocol in section 10. Neither side imports the other's code.

| Stub | Who uses it | What it does |
| --- | --- | --- |
| `tools/mock_unity.py` | Voice side | Connects to the bridge as if it were Unity. Prints every message. Type `enter luis` or `exit luis` to fake proximity. Auto-replies to `tool.call`. Can write received audio to a WAV file. |
| `tools/mock_orchestrator.py` | Unity side | Hosts the bridge with no internet. On `proximity.enter` it streams `tools/sample_es.wav` as binary frames, sends a `tool.call play_gesture` every 5 s, and sends `audio.flush` when you press `f`. |

Both mocks import the same `orchestrator/protocol.py` Pydantic models as the real code. If the protocol changes, both break loudly.

**The non-negotiable rule:** the orchestrator must work with zero Unity clients connected. Every tool handler returns a result immediately whether or not Unity is there. A conversation must never stall because the renderer crashed.

### Proposed repo layout

The repo today is a fresh Unity project in a folder called `My project`. Rename it now, before people have local changes. The space in the name breaks shell commands and agent tooling.

```
repo/
  AGENTS.md                  # instructions for coding agents; points here
  docs/BUILD_DOC.md          # export of this doc
  unity/                     # renamed from "My project"
    Assets/Scenario/         # our C# scripts: BridgeClient, NpcController, ...
  orchestrator/
    __main__.py  bridge.py  actor.py  director.py  tutor.py  protocol.py
    .env.example  requirements.txt
  scenarios/cafe_cancun/
    scenario.yaml  menu.json  prompts/maria.md  prompts/luis.md
  worlds/cafe_cancun_v1/scene_manifest.json
  tools/mock_unity.py  tools/mock_orchestrator.py  tools/sample_es.wav
  eval/director_cases.jsonl  eval/run_eval.py
  runs/                      # git-ignored: transcripts, audio, feedback
```

## 7. Marble: generating the café and getting it into Unity

Generate the café from one wide reference image plus a text prompt using `marble-1.1`, export the 2M-splat PLY, the collider GLB and the pano, and budget $20 for the Standard plan. Free accounts can generate but cannot export.

### What Marble is

Marble is World Labs' world model. You give it a prompt and about 5 minutes later you get a static 3D room as Gaussian splats, plus a rough physics mesh. Internally it always builds a 360 pano first, then lifts that into 3D. It cannot generate people or anything that moves. Docs: [docs.worldlabs.ai](https://docs.worldlabs.ai).

### Input options

| Input | Limits | Good for us? |
| --- | --- | --- |
| Text | Max 2,000 characters | Fastest to try. Least control over layout. |
| Single image | PNG preferred, long side 1024 px or more, between 16:9 and 9:16, max 20 MB | **Recommended.** You control the look. Add a text prompt to describe what is out of frame. |
| Multi-image | Up to 4 with directions (front, back, left, right), or up to 8 auto-laid-out from the same space. Standard plan. | Good if someone has several photos of one real café |
| Panorama | Exactly 2:1 equirectangular, 2560 px wide suggested, one per world | Most controllable, because Marble skips its own pano step. Only if you have a real 360 photo. |
| Video | One take, max 30 s, max 100 MB, 180 to 360 degrees | Possible at a real café. Not for a quick build. |
| Chisel (3D layout) | Block out walls and boxes, or import GLB or FBX, then a text prompt sets the style | Useful if the counter and table keep landing in bad places |

Limits are from the [prompt guides](https://docs.worldlabs.ai/marble/create/prompt-guides/index.md). No Marble page ranks the input types. The recommendation above is ours.

[Image guidance](https://docs.worldlabs.ai/marble/create/prompt-guides/image-prompt.md) that matters for a café: show floor, walls and ceiling clearly; balance foreground, midground and background; avoid close-ups, people, blur, very dark or blown-out exposure, and **text or logos**. Generated text comes out as gibberish. So the chalkboard menu will be unreadable in the splat, and we overlay a real menu in Unity (section 8).

### A prompt to start from

Reference image: generate or photograph one wide, eye-level interior shot, 16:9, no people, no readable signage. If you have your own photo of a real café, use it. That is the product story: "rehearse the place you will actually go".

Text prompt to pair with it:

```
Interior of a small independent neighbourhood cafe in downtown Cancun, Mexico,
late afternoon. Warm natural light from large front windows on the left. A long
wooden service counter runs along the back wall with an espresso machine, a
glass pastry case and a blank dark chalkboard on the wall behind it. Open floor
space in front of the counter. Four small wooden tables with two chairs each;
one table sits beside the front window with clear floor around it. Polished
concrete floor, white plaster walls, exposed ceiling beams, hanging plants,
ceiling fans, pendant lamps. Colourful Mexican tile along the counter front.
No people. No text or lettering anywhere. Clean, uncluttered, realistic
photographic style, eye-level view from just inside the entrance.
```

Iterate on the prompt with `marble-1.0-draft`, which costs about a tenth as much. Then run the final with `marble-1.1`. A draft and a final from the same prompt will not match, so use drafts only to test wording. Skip `marble-1.1-plus`: it is for large or outdoor spaces, costs up to double, and cannot be expanded later.

### What to export and why

| Export | Spec | Why we want it |
| --- | --- | --- |
| PLY, 2M splats | Uncompressed, widest tool support | Primary visual. PLY avoids SPZ version problems in the Unity plugin. |
| PLY, 500K splats | Same, lower detail | Fallback for weak GPUs |
| Collider mesh GLB | 100k to 200k triangles, typically 3 to 4 MB, "not suitable for visual rendering" | Physics |
| 360 pano PNG | 2560 x 1280 equirectangular | Skybox fallback, light colour reference |
| SPZ 2M | Compressed | Only for the browser fallback. Spark reads it natively. |
| High-quality mesh GLB | About 600k textured triangles, up to 1 hour to generate, Pro plan | **Skip.** Too slow, and we render splats, not meshes. |

Specs from the [export specs](https://docs.worldlabs.ai/marble/export/specs.md) and [mesh export](https://docs.worldlabs.ai/marble/export/mesh.md) pages. One known bug: the 500K **SPZ** fails to import in the Unity plugin with "Index out of range". The 500K **PLY** is fine.

### Plans: what each tier unlocks

| Plan | Price per month | Credits per month | Worlds, roughly | Unlocks |
| --- | --- | --- | --- | --- |
| Free | $0 | 7,000 (secondary source) | 4 | Text, single image or pano input. **No export.** Non-commercial. |
| Standard | $20 | 20,000 | 12 | Multi-image, video and 3D-layout input; editing; **splat, pano and collider export** |
| Pro | $35 | 40,000 (secondary source) | 25 | Expand; high-quality mesh export; commercial rights |
| Max | $95 (secondary source) | 120,000 (secondary source) | 75 | Volume |

Features, world counts and the $20 and $35 prices are from [account and billing](https://docs.worldlabs.ai/marble/support/account-billing.md). The pricing page itself is JavaScript-rendered and could not be read, so figures marked "secondary source" come from [TechCrunch's launch coverage](https://techcrunch.com/2025/11/12/fei-fei-lis-world-labs-speeds-up-the-world-model-race-with-marble-its-first-commercial-product/). **Verify this** at marble.worldlabs.ai before paying. Subscription credits do not roll over.

Credit costs in the app: one world is 1,500 credits plus an input fee (80 for text or image, 100 for multi-image). A pano edit is 150. Expand is 2,000. The draft model is 150 plus the input fee.

### The API, and what it costs

Marble also has a public API with separate billing. App credits and API credits cannot be converted, and the API needs no subscription. Keys and billing: [platform.worldlabs.ai](https://platform.worldlabs.ai).

| Item | Value |
| --- | --- |
| Base URL | `https://api.worldlabs.ai` |
| Auth header | `WLT-Api-Key: <key>` |
| Generate | `POST /marble/v1/worlds:generate` |
| Poll (free) | `GET /marble/v1/operations/{operation_id}` |
| Fetch world | `GET /marble/v1/worlds/{world_id}` |
| Export PLY (free, synchronous) | `POST /marble/v1/worlds/{world_id}:export` with `{"asset_type":"splats","format":"ply","resolution":"full_res"}` |
| Upload an input image | `POST /marble/v1/media-assets:prepare_upload`, then PUT to the signed URL |
| Credit price | $1.00 per 1,250 credits, $5 minimum, never expire |
| Rate limit | About 3 generation starts per minute |

| Input type | `marble-1.1` | `marble-1.0-draft` |
| --- | --- | --- |
| Pano image | 1,500 credits ($1.20) | 150 ($0.12) |
| Text or single image | 1,580 ($1.26) | 230 ($0.18) |
| Multi-image or video | 1,600 ($1.28) | 250 ($0.20) |

From [API pricing](https://docs.worldlabs.ai/api/pricing.md) and the [API overview](https://docs.worldlabs.ai/api/index.md).

```bash
curl -X POST https://api.worldlabs.ai/marble/v1/worlds:generate \
  -H "WLT-Api-Key: $WORLDLABS_API_KEY" -H "Content-Type: application/json" \
  -d '{"display_name":"cafe_cancun_v1","model":"marble-1.1",
       "world_prompt":{"type":"text","text_prompt":"<prompt above>"}}'
```

Always pass `model`: the docs disagree about the default. The finished operation returns `assets.splats.spz_urls` (`100k`, `500k`, `full_res`), `assets.mesh.collider_mesh_url`, `assets.imagery.pano_url`, and `assets.splats.semantics_metadata` with `metric_scale_factor` and `ground_plane_offset`.

**Which to use.** For a first build, take the $20 Standard plan: the app has a viewer, pano editing and one-click exports. Use the API at about $1.26 per world if the plan's credits run out. The API is also the platform story: a new scenario can generate its own world from a prompt with one HTTP call. Official examples: [worldlabs-api-examples](https://github.com/worldlabsai/worldlabs-api-examples).

### Landing the export in Unity

**Which plugin.** [World Labs' Unity page](https://docs.worldlabs.ai/marble/export/gaussian-splat/unity) recommends aras-p's [UnityGaussianSplatting](https://github.com/aras-p/UnityGaussianSplatting), and specifically the [winnie1994 fork](https://github.com/winnie1994/UnityGaussianSplatting), which patches draw order for multiple splats and Marble SPZ import. Our repo already has it. The plugin is MIT, needs D3D12, Metal or Vulkan, and does not work on D3D11.

**Import steps.**

1. Copy the `.ply` somewhere outside `Assets/`, so Unity does not try to import it as a mesh.
2. Menu: Tools, Gaussian Splats, Create GaussianSplatAsset. Pick the PLY, choose quality Medium, choose an output folder under `Assets/GaussianAssets/`, and click Create Asset.
3. Create an empty GameObject called `World`. Under it create `Splat`, add a `GaussianSplatRenderer` component, and assign the new asset.
4. Because the project uses URP: select `Assets/Settings/PC_Renderer`, Add Renderer Feature, `GaussianSplatURPFeature`. Render Graph compatibility mode must be off, which is Unity 6's default. Details: [render pipeline integration](https://github.com/aras-p/UnityGaussianSplatting/blob/main/docs/render-pipeline-integration.md).
5. On Windows, open Player settings, untick Auto Graphics API and put Direct3D12 first. On a Mac, Metal is automatic.

**Coordinates and scale: expect to fix this by eye.** Marble's docs contradict each other. The [export specs](https://docs.worldlabs.ai/marble/export/specs.md) say worlds use OpenCV axes (+y down) and that you should scale Y and Z by -1. The [release notes](https://docs.worldlabs.ai/marble/release-notes.md) say exports switched to OpenGL axes in December 2025, and were roughly scaled to real-world metres in January 2026. Raw API SPZ files are still OpenCV and unscaled, per [rendering SPZ](https://docs.worldlabs.ai/api/rendering-spz.md). A [community Unity tool](https://github.com/DakkuaDev/unity-worldlabs.ai-API-client-tool) rotates the splat -180 degrees on Z.

So try, in order, on the `Splat` object: no change; rotation (0, 0, -180); scale (1, -1, -1). The right one has the floor down and the room not mirrored compared with Marble's own viewer. Then check scale: drop a 2 m tall cube next to a door. Record the winning transform in `scene_manifest.json`.

**The collider situation.** Import the GLB with glTFast: Package Manager, Add package by name, `com.unity.cloud.gltfast`. Drag the GLB under `World` as `Collider`. On each child with a MeshFilter, add a `MeshCollider` and disable the `MeshRenderer`. Align it while the renderer is still visible, because the collider may need a **different** flip from the splat. World Labs' own [web physics example](https://github.com/bmild/spark-physics) scales the two differently.

Be warned: World Labs' Unity page lists "objects falling through the GLB collider" as not fully resolved. So the default plan is simpler. **Start with hand-placed primitive colliders**: one floor plane, four invisible walls, one box for the counter, one box per table. That takes 15 minutes, and it is more reliable for a character controller than a 150k-triangle mesh. Swap in the GLB only if it aligns within 30 minutes.

**Is Blender needed?** No. Nothing on the main path uses it. Use [SuperSplat](https://superspl.at/editor) in the browser to delete floating artifacts and re-export PLY. The plugin also has cutout tools in the editor. If you ever get an SPZ you must convert, use `npm install -g @playcanvas/splat-transform` then `splat-transform in.spz out.ply` ([splat-transform](https://github.com/playcanvas/splat-transform)).

### Limits you will hit

- Quality falls off toward the edges of the generated area. No doc gives a distance. Keep the player inside the clear zone with invisible walls.
- Splats are static and their lighting is baked in. Characters added in Unity will not cast shadows on the scene or pick up its light without help (section 8).
- Expand (Pro, 2,000 credits) grows a world once per direction. We should not need it for one room.

### Unity or the browser? An honest comparison

Marble's docs steer web developers to [Spark](https://sparkjs.dev), World Labs' own three.js splat renderer. Of its web option the docs say "we highly recommend this option", and the Marble site is built on it. It deserves a fair look before we commit.

|  | Unity (our path) | Browser: Spark + three.js |
| --- | --- | --- |
| Splat loading | PLY via a community plugin whose author plans no further development. SPZ is partly broken. | SPZ and PLY load natively. Maintained by World Labs. Level-of-detail and streaming since Spark 2.0. |
| Axes and scale | Trial and error | Documented |
| Walking and collision | Built-in CharacterController and physics | Hand-rolled. World Labs lists [ready templates](https://docs.worldlabs.ai/api/interactive-world-examples.md) using Rapier physics and the collider GLB. |
| Characters and animation | Animator, humanoid retargeting, Mixamo clips: mature | three.js animation mixer: workable, more manual |
| Lip-sync from streamed audio | uLipSync, needs wiring | [TalkingHead](https://github.com/met4citizen/TalkingHead) has streamed-PCM lip-sync built in |
| Voice | Through our Python orchestrator | ElevenLabs JavaScript SDK runs in the page over WebRTC, which includes echo cancellation |
| Spatial audio | Built in | Web Audio panner: workable |
| Demo distribution | Runs on our laptop | A URL anyone can open |
| Team fit | Unity experience exists and the project is set up | No three.js experience yet |

**Verdict.** For this exact project the browser stack is arguably less total work, and it gets echo cancellation for free. We stay on Unity because it is committed, the Unity skill is there, the project is already set up, and character animation is where Unity is strongest. The decision is reversible: all voice and scoring logic is in the orchestrator. If splat import is still broken after 3 hours, the fallback is the `gaussian-splat-character-controller` web template talking to the same bridge.

## 8. Unity: the runtime

Unity has five jobs: draw the splat, move the player, place and animate two characters, play their streamed voice from their mouths with lip-sync, and tell the orchestrator when the player walks up to someone. It holds no API keys and makes no internet calls.

### Project setup

The repo is already a Unity `6000.0.68f1` URP project with the splat plugin, the new Input System (`com.unity.inputsystem` 1.18.0) and Linear colour space. Keep all of that. Do not upgrade Unity.

Add three packages through Package Manager:

| Package | How to add | For |
| --- | --- | --- |
| glTFast | Add by name: `com.unity.cloud.gltfast` | Importing the collider `.glb` |
| NativeWebSocket | Add from git URL: `https://github.com/endel/NativeWebSocket.git#upm-2` | The bridge client |
| uLipSync | Add from git URL: `https://github.com/hecomi/uLipSync.git#upm` | Lip-sync from audio |

One trap: the project's Active Input Handling is set to the new Input System only. The old `Input.GetAxis` and `Input.GetKey` calls throw errors. Every script must use `UnityEngine.InputSystem`.

### Scene hierarchy

```
CafeScene
  World                      # transform from scene_manifest.json
    Splat                    # GaussianSplatRenderer
    Colliders                # primitives first; collider GLB later
    MenuBoard                # world-space Canvas over the chalkboard
  Player                     # CharacterController + FirstPersonController + Camera + AudioListener
  NPCs
    Maria                    # NpcController, Animator, AudioSource, PcmStreamPlayer, uLipSync
      Anchors/TableTop       # where served items appear
    Luis
  Systems
    BridgeClient             # the WebSocket client and message router
    SceneActions             # executes tool calls: serve_order, show_bill
  HUD                        # goals, state ring, subtitles, push-to-talk hint
  Lighting                   # one Directional Light, tuned for the avatars only
```

### Splat rendering

Import and alignment are in section 7. Runtime notes:

- Reference numbers from the plugin README: 6.1M splats at Medium quality ran at 147 fps on an RTX 3080 Ti and 46 fps on an M1 Max. Our 2M-splat café should be comfortable on a recent MacBook Pro. If it is not, use the 500K PLY.
- Splats ignore Unity lights and cast no shadows.
- **Verify this early:** put a cube behind the counter and check that the splat counter hides the cube's lower half. Characters are ordinary opaque meshes, so they should be correctly occluded by nearer splats. If they are not, stand Maria in front of open floor instead of behind the counter.
- The chalkboard text is gibberish. `MenuBoard` is a world-space Canvas placed over it that lists the items from `menu.json`, with **no prices**. The learner has to ask.

### Player: a 40-line first-person controller

Unity's First Person Starter Assets pack has been [deprecated on the Asset Store](https://assetstore.unity.com/packages/essentials/starter-assets-firstperson-updates-in-new-charactercontroller-pa-196525). Write our own on the built-in `CharacterController`. It is short.

```csharp
using UnityEngine;
using UnityEngine.InputSystem;

[RequireComponent(typeof(CharacterController))]
public class FirstPersonController : MonoBehaviour {
  public Transform cam; public float speed = 1.6f, look = 0.12f, gravity = -9.81f;
  CharacterController cc; float pitch, vy;
  void Start() { cc = GetComponent<CharacterController>(); Cursor.lockState = CursorLockMode.Locked; }
  void Update() {
    var kb = Keyboard.current; var m = Mouse.current; if (kb == null || m == null) return;
    Vector2 d = m.delta.ReadValue() * look;
    transform.Rotate(0, d.x, 0);
    pitch = Mathf.Clamp(pitch - d.y, -80, 80); cam.localEulerAngles = new Vector3(pitch, 0, 0);
    float x = (kb.dKey.isPressed ? 1 : 0) - (kb.aKey.isPressed ? 1 : 0);
    float z = (kb.wKey.isPressed ? 1 : 0) - (kb.sKey.isPressed ? 1 : 0);
    Vector3 move = (transform.right * x + transform.forward * z).normalized * speed;
    vy = cc.isGrounded ? -1f : vy + gravity * Time.deltaTime;   // Move() does not apply gravity
    cc.Move((move + Vector3.up * vy) * Time.deltaTime);
  }
}
```

Walking speed is 1.6 m/s on purpose. A slow, human pace makes the approach feel like an approach. Set the CharacterController height to 1.7 and put the camera at 1.6.

### Where the characters come from

Ready Player Me is gone. Netflix acquired it and its avatar services [went offline on 31 January 2026](https://www.roadtovr.com/netflix-acquires-xr-avatar-startup-ready-player-me/). Any tutorial that says "grab an RPM avatar" is dead.

| Source | Licence | Face blendshapes | Verdict |
| --- | --- | --- | --- |
| [Microsoft Rocketbox](https://github.com/microsoft/Microsoft-Rocketbox) | MIT | 15 visemes, 48 FACS shapes, ARKit-compatible shapes | **Use this.** 115 rigged adults as FBX, offline, realistic enough, varied ages. Put `FixRocketboxMaxImport.cs` in `Assets/Editor` before importing. |
| [Avaturn](https://docs.avaturn.me/docs/integration/bodies/) | Free tier | T2 bodies have ARKit blendshapes and visemes | Backup. Made from a selfie in a web app, exported as GLB. |
| VRoid + [UniVRM](https://github.com/vrm-c/UniVRM) | MIT | Five vowel shapes | Only if we want an anime look. We do not. |
| Mixamo characters | Free with Adobe ID | None, as far as we know | Use Mixamo for **animations only** |

Set each character's rig to Humanoid in the import settings. Download Mixamo clips "without skin", set those to Humanoid too, and they will play on the Rocketbox bodies. Clips to find on Mixamo: a standing idle, two talking loops, waving, head nod, head shake, laughing, thinking, shrugging, pointing, and a sitting idle.

Pick a woman of about 40 for Maria and a man in his late twenties for Luis. Maria takes the order standing beside the table, and between visits she waits behind the counter, which hides her legs and forgives foot sliding. For the first build Luis stands by the window table. Seating an avatar on a chair that exists only in the splat is fiddly, so it is a stretch task.

### Making them look alive

These four things take little code and do most of the work of not looking robotic.

1. **Eye contact.** Turn on IK Pass on the Animator's base layer. In `OnAnimatorIK`, call `SetLookAtWeight(1, 0.2f, 0.8f, 1f)` and `SetLookAtPosition(playerCamera.position)` while the player is within 4 m.
2. **State-driven body language.** `session.state` from the orchestrator sets an Animator integer: listening (idle, looking at you), thinking (small head tilt), speaking (talking loop on an upper-body layer).
3. **Gestures.** `tool.call play_gesture` fires a trigger: `wave`, `nod`, `shake_head`, `laugh`, `think`, `shrug`, `point_menu`, `lean_in`.
4. **Grounding.** Splats cannot receive shadows. Put a soft, dark, transparent quad under each character's feet. Tune the one Directional Light to match the window direction, and set ambient colour from the pano's average colour.

### Proximity trigger

Use a distance check, not physics triggers. It has no dependency on the collider work.

```csharp
// NpcController.Update()
float d = Vector3.Distance(player.position, transform.position);
bool facing = Vector3.Dot(player.forward, (transform.position - player.position).normalized) > 0.3f;
if (!inside && d < 2.2f && facing)      { inside = true;  bridge.Send("proximity.enter", npcId); }
else if (inside && d > 3.5f)            { exitTimer += Time.deltaTime;
                                          if (exitTimer > 1.5f) { inside = false; bridge.Send("proximity.exit", npcId); } }
else exitTimer = 0f;
```

Enter at 2.2 m and facing the character. Exit at 3.5 m held for 1.5 s. The gap stops the conversation flickering on and off at the boundary. Only one character may be inside at a time, and the orchestrator enforces that too.

### Playing the streamed voice

Agent audio arrives as binary frames of raw PCM16 mono 16 kHz, faster than real time. Put it in a ring buffer and let a streamed AudioClip pull from it. On `audio.flush`, empty the buffer: that is what makes barge-in feel instant.

```csharp
[RequireComponent(typeof(AudioSource))]
public class PcmStreamPlayer : MonoBehaviour {
  const int Rate = 16000;
  readonly float[] ring = new float[Rate * 30];        // 30 s of audio
  int w, r; readonly object gate = new object();
  void Start() {
    var src = GetComponent<AudioSource>();
    src.clip = AudioClip.Create("npc_voice", Rate, 1, Rate, true, OnRead);   // stream = true
    src.loop = true; src.spatialBlend = 1f;
    src.rolloffMode = AudioRolloffMode.Linear; src.minDistance = 1f; src.maxDistance = 12f;
    src.Play();
  }
  public void Push(byte[] b, int offset) {              // called from the socket callback
    lock (gate) for (int i = offset; i + 1 < b.Length; i += 2) {
      ring[w] = (short)(b[i] | (b[i + 1] << 8)) / 32768f; w = (w + 1) % ring.Length; }
  }
  public void Flush() { lock (gate) r = w; }
  public bool HasAudio { get { lock (gate) return r != w; } }
  void OnRead(float[] data) {                           // audio thread: must always fill
    lock (gate) for (int i = 0; i < data.Length; i++) {
      if (r != w) { data[i] = ring[r]; r = (r + 1) % ring.Length; } else data[i] = 0f; }
  }
}
```

The clip is declared at 16,000 Hz and Unity should resample it to the output rate. The docs do not state this outright. **Verify this**: if the voice sounds sped up or slowed down, resample to `AudioSettings.outputSampleRate` inside `Push`.

`HasAudio` going from true to false is when the character has actually finished speaking. Send that to the orchestrator as `audio.drained` so the state machine knows real playback time, not just when the last chunk arrived.

### Lip-sync

| Option | Status | Verdict |
| --- | --- | --- |
| [uLipSync](https://github.com/hecomi/uLipSync) | MIT, pure C#, analyses whatever the AudioSource plays through `OnAudioFilterRead`, maps vowels A, I, U, E, O to blendshapes | **Use this.** Spanish has exactly five pure vowels, so its five-vowel model fits unusually well. |
| Oculus OVRLipSync | [End of life](https://developers.meta.com/horizon/documentation/unity/audio-ovrlipsync-unity/), last standalone build 2021 | Skip |
| SALSA | $45 asset | Skip |
| Volume-driven jaw | Ten lines | **Fallback.** Compute loudness of the last 20 ms in `Push`, smooth it, drive the "jaw open" blendshape. |

Put the `uLipSync` component on the same GameObject as the `AudioSource` and `PcmStreamPlayer`. Add `uLipSyncBlendShape`, point it at the face mesh, and map each vowel to the matching Rocketbox viseme. Start from the sample profile that ships with the package. **Verify this** early with `tools/mock_orchestrator.py`: confirm uLipSync reacts to the streamed clip. If it does not, ship the jaw fallback and move on.

### The bridge client

```csharp
public class BridgeClient : MonoBehaviour {
  WebSocket ws; public PcmStreamPlayer activeVoice;
  async void Start() { await Connect(); }
  async System.Threading.Tasks.Task Connect() {
    ws = new WebSocket("ws://127.0.0.1:8765");
    ws.OnOpen    += () => SendJson(new { v = 1, type = "hello", client = "unity", scene = "cafe_cancun_v1" });
    ws.OnMessage += bytes => {
      if (bytes.Length == 0) return;
      if (bytes[0] == 0x01) activeVoice?.Push(bytes, 1);              // audio frame
      else Route(System.Text.Encoding.UTF8.GetString(bytes));         // JSON frame starts with '{'
    };
    ws.OnClose   += _ => Invoke(nameof(Reconnect), 2f);
    await ws.Connect();
  }
  void Reconnect() { _ = Connect(); }
  void Update() { ws?.DispatchMessageQueue(); }   // required by NativeWebSocket outside WebGL; check the README for v2
}
```

NativeWebSocket hands every message over as a byte array and does not say whether it was text or binary. That is why audio frames start with the byte `0x01`, and JSON always starts with `{`. `Route` parses the JSON `type` and calls the right handler from section 10.

### Scene actions and HUD

- `serve_order`: for each `item_id`, spawn the matching prefab at `Maria/Anchors/TableTop`, slide it forward over 0.6 s, and play a cup-on-wood sound. Coloured cylinders are fine for the first build.
- `show_bill`: show a small receipt card in world space on the table with the total.
- HUD goal list: four lines, top right, that tick when `goal.update` arrives. Small and quiet, so it does not break immersion.
- State ring: a thin ring at the bottom of the screen. Green while the character is listening, pulsing while thinking, hidden while speaking. It tells the learner "it is your turn" without words.
- Subtitles: hidden by default. Holding Tab shows the latest `caption` text and sends `hint` to the orchestrator, which counts it.
- Push-to-talk: when the orchestrator runs in push-to-talk mode, show "Hold Space to talk" and send `ptt` down and up events.

## 9. ElevenLabs: the voice characters

Each character is one ElevenLabs agent with Spanish as its language, a Mexican voice, the expressive v3 voice model, patient turn-taking, and three client tools. The orchestrator connects to it with the official Python SDK.

### What the product is called now

The product is **ElevenAgents**. It was "Conversational AI", then "Agents Platform". Docs now live under [`/docs/eleven-agents/`](https://elevenlabs.io/docs/eleven-agents/overview), and old links redirect. API paths still say `/v1/convai/`, and the Python module is still `elevenlabs.conversational_ai`. All three names mean the same thing.

### What it costs, and the free-tier trap

| Item | Value |
| --- | --- |
| Voice conversation | $0.08 per minute, LLM cost passed through on top |
| Silence | Billed at 5% of the rate |
| Free plan | 15 minutes per month, 4 concurrent calls |
| Starter, $6 | 75 minutes |
| Creator, $11 | 275 minutes |

From [agents pricing](https://elevenlabs.io/pricing/agents). A second pricing page showed the minutes shifted by one plan, so **verify this** in the dashboard. Two consequences. Fifteen free minutes is about four test runs, so development needs a paid plan from day one. And [Voice Library voices cannot be used through the API on the free tier](https://elevenlabs.io/docs/eleven-creative/voices/voice-library.md), which is exactly how we pick a Mexican voice.

To save minutes while iterating on prompts, test in text-only mode. It bills per message and uses a separate concurrency pool.

### Create the agents

Do this twice, once for Maria and once for Luis. Follow the [quickstart](https://elevenlabs.io/docs/eleven-agents/quickstart.md): open the ElevenAgents dashboard, create a new agent, choose **Blank template**.

| Setting | Where | Value | Why |
| --- | --- | --- | --- |
| Language | Agent tab | Spanish (`es`). No additional languages. | Language is fixed for the call. English from the learner will transcribe badly, and the character reacts as if they did not catch it, which is what we want. |
| First message | Agent tab | See prompts below | The character speaks first, like a real waitress |
| LLM | Agent tab | A small, fast OpenAI model from the dropdown to start, such as GPT-5.4 Mini or GPT-5.6 Luna. Lowest reasoning effort. Temperature about 0.7. | Thinking time delays every turn. The [client tools page](https://elevenlabs.io/docs/eleven-agents/customization/tools/client-tools.md) recommends stronger models for reliable tool parameters, so move up one size if tool calls misfire. |
| Voice | Voice tab | A Mexican Spanish voice, see below |  |
| TTS model | Voice tab | **Flash v2.5** by default. V3 Conversational cannot be chosen when a Spanish agent is created; it is set by PATCH afterwards and is 4x slower to first audio. See section 18.3. Originally: V3 Conversational with expressive mode on | [Expressive mode](https://elevenlabs.io/docs/eleven-agents/customization/voice/expressive-mode.md) gives emotional inflection and supports tags such as `[laughs]` and `[sighs]`. Same price. About 280 ms model latency. |
| TTS fallback | Voice tab | Flash v2.5, about 75 ms | Use if time to first audio is over 1.5 s. Not Flash v2, which is English only. |
| Stability, speed | Voice tab | Stability 0.40 to 0.50. Speed 1.0 for Luis, 1.05 for Maria. | Lower stability is more emotional. [Voice design guidance](https://elevenlabs.io/docs/eleven-agents/customization/voice/best-practices/conversational-voice-design.md) puts natural speed at 0.9 to 1.1. |
| Output audio format | Voice or Advanced tab | PCM 16000 Hz | Matches what the Python SDK and our Unity player expect |
| Input audio format | Advanced tab | PCM 16000 Hz | Same |
| ASR keywords | Advanced tab | `café de olla, horchata, jamaica, concha, chilaquiles, capuchino, pay de limón, americano, deslactosada` | Biases recognition toward menu words a learner will mispronounce |
| Turn eagerness | Advanced tab | **Patient** | Learners pause mid-sentence to find words. An eager agent cuts them off, which is the single most robotic-feeling failure. |
| Turn timeout | Advanced tab | 8 s | After 8 s of silence the character prompts again, in character |
| Soft timeout | Advanced tab | 2.0 s, message "Mmm, a ver..." | A spoken filler if the LLM is slow, instead of dead air |
| Interruptions | Advanced tab | On | Barge-in is part of natural conversation |
| Ignore terms | Advanced tab | `ajá, mhm, sí, ok, claro` | Backchannel noises should not stop the character mid-sentence |
| Max duration | Advanced tab | 180 s for Maria, 300 s for Luis | Hard caps from section 3 |
| Client events | Advanced tab | Make sure `audio`, `interruption`, `user_transcript`, `agent_response`, `agent_response_correction`, `client_tool_call`, `ping` are on | The agent only sends event types that are enabled. The default list is not documented. |
| Authentication | Security tab | Enabled (private agent) | The SDK fetches a signed URL with our API key. Keeps strangers off our minutes. |
| Overrides | Security tab | Enable: first message, voice. Leave system prompt off. | Overrides are [off by default](https://elevenlabs.io/docs/eleven-agents/customization/personalization/overrides.md), and sending one that is not enabled throws an error. |
| System tools | Tools | `end_call` and `skip_turn` on. Language detection off. | `skip_turn` lets the character stay quiet when the learner says "un momento" |

Field names and ranges are from the [conversation flow docs](https://elevenlabs.io/docs/eleven-agents/customization/conversation-flow.md) and the SDK's type definitions. Exact tab locations in the dashboard move around, so search the settings if a label is not where this table says.

### Picking the voices

Open the Voice Library, filter Language to Spanish, then Accent to Mexican, then Category to Conversational. Maria needs a woman's voice and Luis a man's. Shortlist three per character and audition each with a real line, not "hola". For Maria use: "¡Buenas tardes, joven! ¿Qué te sirvo? Tenemos café de olla recién hecho." Press + to add the winner to My Voices, then select it in the agent's Voice tab. We do not name specific voice ids here because they could not be verified.

V3 Conversational does not preserve Professional Voice Clone characteristics, so pick library voices, not clones.

### The menu as a knowledge base

Create one document, `menu_cafe_nader.md`, at [Knowledge Base](https://elevenlabs.io/app/agents/knowledge-base), and attach it to Maria with usage mode **prompt**, not RAG. RAG adds about 250 ms per turn, and a menu this small belongs in the prompt. If the dashboard does not offer usage mode, paste the menu table at the bottom of the system prompt. Generate the file from `menu.json` so there is one source of truth.

```markdown
# Menú de Café Nader (precios en pesos mexicanos)
- Café americano: cuarenta y cinco pesos
- Café de olla: cincuenta pesos
- Latte: sesenta y cinco pesos
- Capuchino: sesenta y cinco pesos
- Horchata fría: cincuenta y cinco pesos
- Agua de jamaica: cuarenta pesos
- Chocolate caliente: sesenta pesos
- Concha: treinta pesos
- Pay de limón: setenta pesos (HOY NO HAY, se acabó)
- Chilaquiles verdes: ciento veinte pesos
Leche: entera, deslactosada o de avena (la de avena cuesta diez pesos más).
```

Prices are written as words so the voice model never has to guess how to read "$45".

### System prompt: Maria

The structure follows ElevenLabs' [prompting guide](https://elevenlabs.io/docs/eleven-agents/best-practices/prompting-guide): Personality, Environment, Tone, Goal, Guardrails, Tools. Instructions are in English because models follow them more reliably. The character's speech is Spanish only. Paste this verbatim.

```
# Personality
You are Maria, about forty, a waitress at Café Nader, a small neighbourhood
café in downtown Cancún, Mexico. You are from Mérida and have worked at this café
for years. You are warm, quick and practical. You like your customers, you are
proud of the café de olla, and you are usually a little busy.

# Environment
It is about 5:30 pm. A customer, {{learner_name}}, has just walked in. Their friend
is already waiting at the table by the window, so you greet them at the door, walk
them over and take their order at the table. The chalkboard by the counter lists the
items but not the prices. This is a spoken, face-to-face conversation. The customer
is a foreigner whose Spanish is intermediate. You treat them exactly like any other
customer.

# Tone
Speak only Mexican Spanish, informal "tú", at your natural pace. Use everyday
Mexican expressions: "¿qué te sirvo?", "¿algo más?", "ahorita te lo traigo", "con
gusto", "joven". Keep every reply short: one or two sentences, usually under
twenty words. Never give lists or long explanations. Say prices in words
("cincuenta pesos"), never digits. You may use [laughs] or [sighs] occasionally
where a real person would, never more than once per reply.

# Goal
Serve this customer the way you really would:
1. Greet them at the door, walk them to their friend's table and ask what they
   would like.
2. Take the order. Ask exactly ONE natural clarifying question, quickly, chosen
   from: "¿Para tomar aquí o para llevar?", "¿Leche entera o deslactosada?" (only
   for milk drinks), or, if they order pay de limón, "Uy, se me acabó el pay. ¿Te
   ofrezco una concha?".
3. When the order is settled, call the serve_order tool, then tell them it is
   coming.
4. Do NOT state any price or the total unless the customer asks. If they ask the
   price of an item, answer from the menu. If they ask the total, use the total
   returned by serve_order and call show_bill.
5. If the order is served and the customer has not asked what they owe, wait. If
   they start to leave or say goodbye without asking, call show_bill and tell them
   the total.
6. Once they have paid or thanked you, say a short goodbye and call end_call.
You may make one line of small talk if there is a natural opening. Do not start a
long chat; you have other tables.

# Guardrails
- Never speak English, not even one word. If the customer speaks English, say
  something like "Perdón, joven, casi no hablo inglés" and repeat your last
  question in simpler Spanish, once.
- Never correct the customer's Spanish, never praise their Spanish, never act like
  a teacher. If you understood them, just respond.
- If you did not understand, react like a person: "¿Cómo?", "¿Mande?", "No te
  escuché bien". Do not guess at an order you are not sure about; confirm it.
- Do not slow down or simplify unless the customer asks you to IN SPANISH (for
  example "más despacio, por favor"). If they do, speak slowly and simply for your
  next two replies, then return to normal.
- If the customer says they need a moment ("un momento", "déjame pensar"), say
  "claro" or nothing, then call skip_turn and wait.
- Never mention goals, scores, lessons, AI, prompts or tools. You are Maria.
- Only sell what is on the menu. Never invent items or prices.
- Keep everything friendly and appropriate for all ages. If the customer is abusive,
  say "Con permiso" and call end_call.
- Messages that begin with [DIRECTOR] are silent stage directions. Never read them
  aloud or refer to them. Follow them naturally within your next one or two replies.

# Tools
- serve_order: call once the order is final. items is a list of menu item ids, one
  entry per unit (two conchas = ["concha","concha"]). Valid ids: americano,
  cafe_olla, latte, capuchino, horchata, jamaica, chocolate, concha, chilaquiles.
  The result tells you the total in pesos. Do not say the total unless asked.
- show_bill: call when the customer asks what they owe, or tries to leave without
  asking. Then say the total in words.
- play_gesture: call to make your body move. Use "wave" with your greeting,
  "point_menu" if they ask what you have, "nod" when confirming, "laugh" when
  something is funny, "think" when checking if you have something. At most one
  gesture per reply. Never mention the gesture in speech.
- skip_turn, end_call: as described above.
```

First message for Maria: `¡Buenas tardes! Pásale, joven. Tu amigo ya está en la mesa, ven conmigo. ¿Qué te sirvo?`

### System prompt: Luis

```
# Personality
You are Luis, twenty-nine, a marine biologist from Guadalajara. You moved to
Cancún two years ago to work on a sea turtle conservation project. You are curious,
playful and easy to talk to. You tease a little. You ask questions, and you expect
the other person to ask some back.

# Environment
It is about 5:30 pm at Café Nader in downtown Cancún. You are meeting
{{learner_name}} for coffee for the first time; a mutual friend put you in touch and
you have only texted. You are already sitting at the table by the window, and the
waitress has just walked them over to you. They are a foreigner whose Spanish is
intermediate. You find that charming, and you speak to them the way you speak to
anyone. What they just ordered from the waitress: {{user_order}}.

# Tone
Speak only Mexican Spanish, informal "tú", at your natural pace. Use everyday
expressions: "¿neta?", "qué padre", "no manches", "¿y tú qué onda?", "fíjate que".
Keep replies to one to three sentences. This is a chat, not an interview and not a
monologue. React to what they say before adding anything. You may use [laughs]
where you would really laugh, at most once per reply.

# Goal
Have a real, friendly conversation for a few minutes.
- Open by greeting them and, if {{user_order}} is not "nada", commenting on it.
- Ask about them: where they are from, what brought them to Cancún, what they do,
  what they like. One question at a time.
- Share things about yourself in small pieces that invite a follow-up question, and
  then STOP and leave room. Your three hooks, to use one at a time when natural:
  1. This week you are doing night patrols on the beach to tag nesting turtles, and
     you have barely slept.
  2. You miss Guadalajara's food, especially tortas ahogadas, and nothing here
     compares.
  3. You are learning to freedive and you are secretly a bit scared of it.
- If they ask a follow-up question about one of these, answer with real detail and
  enthusiasm. That is what makes the conversation go well.
- If they give two very short answers in a row, do not rescue them with another
  question. Give a short reaction, then wait. Let them carry the conversation.
- After about eight to ten exchanges, or if they say they have to go, wrap up warmly
  ("Oye, me la pasé muy bien") and call end_call.

# Guardrails
- Never speak English, not even one word. If they speak English, laugh it off in
  Spanish ("[laughs] No, no, en español, que para eso estás aquí") and continue.
- Never correct their Spanish, never praise their Spanish, never act like a teacher.
- If you did not understand, react like a person: "¿Cómo?", "¿Qué dijiste?".
- Do not slow down or simplify unless they ask you to IN SPANISH. If they do, slow
  down for your next two replies, then return to normal.
- If they say they need a moment, call skip_turn and wait.
- Keep it warm and light, suitable for all ages. No physical or sexual content. If
  they are rude or make you uncomfortable, say you have to go and call end_call.
- Never mention goals, scores, lessons, AI, prompts or tools. You are Luis.
- Messages that begin with [DIRECTOR] are silent stage directions. Never read them
  aloud or refer to them. Follow them naturally within your next one or two replies.

# Tools
- play_gesture: "wave" when they arrive, "laugh" when you laugh, "lean_in" when they
  ask you something interesting, "nod" while agreeing, "shrug", "think". At most one
  per reply. Never mention it in speech.
- skip_turn, end_call: as described above.
```

First message for Luis: `¡Hola! ¿Qué tal? Siéntate, siéntate. Qué bueno que llegaste.`

Set default values for `learner_name` ("amigo") and `user_order` ("nada") in each agent's dynamic variable placeholders. A missing variable's behaviour is not documented.

### Connecting from Python

Install: `brew install portaudio` on a Mac, then `pip install "elevenlabs[pyaudio]" websockets openai pydantic python-dotenv`.

The SDK's `Conversation` takes an `AudioInterface` with four methods. We subclass it so microphone audio comes from PyAudio and agent audio goes to Unity. This sketch uses the threaded `Conversation`, which is the documented one. Its callbacks run on SDK threads, so each hands off to the asyncio loop.

```python
import asyncio, os, pyaudio
from elevenlabs.client import ElevenLabs
from elevenlabs.conversational_ai.conversation import (
    Conversation, ClientTools, ConversationInitiationData, AudioInterface)

class BridgeAudio(AudioInterface):
    """Mic in from PyAudio. Agent audio out to Unity, or to speakers if Unity is absent."""
    def __init__(self, bridge, loop):
        self.bridge, self.loop, self.muted = bridge, loop, False
    def start(self, input_callback):
        self._cb = input_callback
        self._pa = pyaudio.PyAudio()
        self._mic = self._pa.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True,
                                  frames_per_buffer=4000, stream_callback=self._on_mic)
        self._spk = self._pa.open(format=pyaudio.paInt16, channels=1, rate=16000, output=True)
    def _on_mic(self, data, *_):
        if self.muted:                       # push-to-talk gate: send silence, not nothing
            data = b"\x00" * len(data)
        self._cb(data)
        return (None, pyaudio.paContinue)
    def output(self, audio: bytes):          # must return quickly
        if self.bridge.unity_connected:
            asyncio.run_coroutine_threadsafe(self.bridge.send_audio(audio), self.loop)
        else:
            self._spk.write(audio)           # stage 1; move to a queue + thread if it stutters
    def interrupt(self):                     # barge-in: drop everything queued
        asyncio.run_coroutine_threadsafe(self.bridge.send_json({"type": "audio.flush"}), self.loop)
    def stop(self):
        self._mic.close(); self._spk.close(); self._pa.terminate()

def start_conversation(npc, bridge, director, scene, loop):
    client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
    tools = ClientTools()
    tools.register("play_gesture", lambda p: scene.play_gesture(npc, p))
    tools.register("serve_order",  lambda p: scene.serve_order(npc, p))
    tools.register("show_bill",    lambda p: scene.show_bill(npc, p))
    conv = Conversation(
        client, os.environ[f"AGENT_ID_{npc.upper()}"],
        requires_auth=True,
        audio_interface=BridgeAudio(bridge, loop),
        client_tools=tools,
        config=ConversationInitiationData(dynamic_variables={
            "learner_name": director.learner_name,
            "user_order": director.order_summary_es() or "nada"}),
        callback_user_transcript=lambda t: director.on_user_turn(npc, t),
        callback_agent_response=lambda t: director.on_agent_turn(npc, t),
        callback_agent_response_correction=lambda old, new: director.on_agent_correction(npc, old, new),
        callback_latency_measurement=lambda ms: director.metrics.ping(ms),
        callback_end_session=lambda: director.on_session_end(npc))
    conv.start_session()
    return conv     # later: conv.send_contextual_update("[DIRECTOR] ..."); conv.end_session()
```

Things the SDK does for us: fetches the signed URL when `requires_auth=True`, answers every `ping` with `{"type":"pong","event_id":N}`, sends our tool handler's return value back as `client_tool_result`, and after an `interruption` drops audio whose `event_id` is at or below the interruption's. Source: [conversation.py](https://github.com/elevenlabs/elevenlabs-python/blob/main/src/elevenlabs/conversational_ai/conversation.py).

One correction to the docs: the Python guide shows `start_session(user_id=...)`, but the source signature takes `user_id` in the constructor. Follow the source.

### Which connection path: an honest recommendation

| Path | State | Verdict |
| --- | --- | --- |
| **Python SDK in the orchestrator** | Official, v2.68.0, implements the full protocol | **Use this.** |
| Raw WebSocket in Python | The [protocol](https://elevenlabs.io/docs/eleven-agents/api-reference/eleven-agents/websocket) is small and documented | Fallback if the SDK blocks us. Also the only way to read `vad_score` and `internal_tentative_agent_response`, which the SDK does not surface. |
| [Official Unity SDK](https://github.com/elevenlabs/unity) | Exists, MIT, but needs Unity 6.3, is an unreleased 0.1.0, and "APIs subject to change". Whether it supports client tools could not be confirmed. | **Dead end for us** on Unity 6.0. Revisit later. |
| [Community Unity package](https://github.com/danieloquelis/Unity-QuestConversationalAI) | About 30 commits, built for Meta Quest and Meta SDK 77 | Not recommended. Quest-specific, small, unknown upkeep. |
| Raw WebSocket in C# inside Unity | Doable: base64 audio, ping and pong, interruption handling, tool replies, all on Unity's main thread | Not worth the time. It also puts the API key in the game and leaves the director blind. |

If a guide says "there is no Unity SDK, so use the community package", it is out of date on the first half and wrong on the second.

### After the call

`conv.wait_for_session_end()` returns the `conversation_id`. `GET https://api.elevenlabs.io/v1/convai/conversations/{conversation_id}` with the `xi-api-key` header returns the full transcript with tool calls, plus an `analysis` block. We keep our own live transcript, so this is a cross-check, not a dependency.

Optional and cheap: in each agent's **Analysis** tab, add evaluation criteria that mirror our goals, such as "The customer asked for a price or the total before being told". ElevenLabs then returns `success`, `failure` or `unknown` with a rationale for each. The tutor can show this as a second opinion next to the director's verdict.

## 10. The signal contract

> **Status, 2026-09-19.** Layer A, the client tools, is built as described. Layer B, the WebSocket bridge, was not built: Unity talks to the orchestrator over HTTP (`docs/api.md`), and scene actions return in the speech response. The streaming replacement is specified in section 18.5, C1. Keep this section for its rules, which still hold: the conversation never waits for the renderer, one live character, log everything.

There are two interfaces. Layer A is three client tools between the ElevenLabs agent and the orchestrator. Layer B is the bridge: about twenty message types between the orchestrator and Unity. The orchestrator translates between them, and it is the only code that knows both.

The source of truth for both layers is `orchestrator/protocol.py`, as Pydantic models. This section is the human-readable copy. Change the code and this section together.

### Layer A: client tools the characters can call

Tools are for things the **character decides** and the **scene must show**. Goal tracking is deliberately not a tool: the character must not know it is being scored (section 11).

| Tool | Who has it | Parameters | Blocking? | What happens |
| --- | --- | --- | --- | --- |
| `play_gesture` | Maria, Luis | `gesture`: one of `wave`, `nod`, `shake_head`, `laugh`, `think`, `shrug`, `point_menu`, `lean_in` | No. `expects_response: false` | Unity fires the matching Animator trigger on that character |
| `serve_order` | Maria | `items`: list of `item_id` strings, one per unit. `to_go`: boolean, optional. | Yes. `expects_response: true`, `response_timeout_secs: 3` | Orchestrator prices the order from `menu.json`, records it, tells Unity to put the items on the table, and returns the total to the agent |
| `show_bill` | Maria | none | Yes, 3 s | Unity shows the receipt card. Orchestrator returns the total again. |

Plus two system tools that need no code from us: `end_call` and `skip_turn`.

"Blocking" means the agent's LLM waits for our result and reads it before speaking again. We use that for `serve_order` for one reason: the orchestrator does the arithmetic, so Maria never invents a total. Our handler returns in microseconds, because it does not wait for Unity.

For all three tools set pre-tool speech to `off`, so the agent does not say filler like "one moment" before a call that returns instantly. Leave interruption mode at `allow` and execution mode at `immediate`.

**Creating the tools.** In the dashboard: Tools, Add tool, type Client, then fill in name, description and parameters, and tick "Wait for response" for the blocking two. Names are case-sensitive and must match the Python `register` names exactly. Or create them with `POST https://api.elevenlabs.io/v1/convai/tools`:

```json
{
  "tool_config": {
    "type": "client",
    "name": "serve_order",
    "description": "Place the customer's finished order on the table. Call once, when the order is final. Returns the total price in pesos.",
    "expects_response": true,
    "response_timeout_secs": 3,
    "parameters": {
      "type": "object",
      "required": ["items"],
      "properties": {
        "items": {
          "type": "array",
          "description": "Menu item ids, one entry per unit ordered. Two conchas is [\"concha\",\"concha\"].",
          "items": {
            "type": "string",
            "description": "A menu item id",
            "enum": ["americano","cafe_olla","latte","capuchino","horchata","jamaica","chocolate","concha","chilaquiles"]
          }
        },
        "to_go": { "type": "boolean", "description": "True if the customer said para llevar." }
      }
    }
  }
}
```

```json
{
  "tool_config": {
    "type": "client",
    "name": "play_gesture",
    "description": "Make your body perform a gesture while you speak. At most one per reply.",
    "expects_response": false,
    "parameters": {
      "type": "object",
      "required": ["gesture"],
      "properties": {
        "gesture": {
          "type": "string",
          "description": "Which gesture to perform",
          "enum": ["wave","nod","shake_head","laugh","think","shrug","point_menu","lean_in"]
        }
      }
    }
  }
}
```

The field names come from the SDK's [client tool config type](https://github.com/elevenlabs/elevenlabs-python/blob/main/src/elevenlabs/types/client_tool_config_input.py) and the [create tool reference](https://elevenlabs.io/docs/eleven-agents/api-reference/tools/create). **Verify this**: if the dashboard will not accept an array of enums, change `items` to one comma-separated string and split it in Python.

**What goes over the ElevenLabs socket.** The agent sends:

```json
{ "type": "client_tool_call",
  "client_tool_call": {
    "tool_name": "serve_order",
    "tool_call_id": "tool_call_8f2a",
    "parameters": { "items": ["cafe_olla", "concha"], "to_go": false } } }
```

The SDK calls our handler and sends back its return value:

```json
{ "type": "client_tool_result",
  "tool_call_id": "tool_call_8f2a",
  "result": "Served: 1 café de olla, 1 concha. Total: ochenta pesos (80 MXN). Do not say the total unless the customer asks.",
  "is_error": false }
```

If the agent sends an id that is not on the menu, the handler returns a plain-language error as the result: `Unknown item 'pay_limon'. It is sold out. Valid ids: americano, cafe_olla, ...`. The LLM reads that and recovers in character. Handlers never raise and never block.

### Layer B: the bridge between orchestrator and Unity

**Transport.** One WebSocket at `ws://127.0.0.1:8765`. The orchestrator is the server and Unity is the client. There are two kinds of frame.

| Frame | First byte | Content |
| --- | --- | --- |
| Control | `{` (0x7B) | One UTF-8 JSON object |
| Audio | `0x01` | The remaining bytes are raw PCM, 16-bit little-endian, mono, 16,000 Hz, for the currently speaking character |

**Envelope.** Every JSON message has these fields, plus its own.

```json
{ "v": 1, "type": "tool.call", "id": "o-000042", "ts": 1790000000123 }
```

`v` is the protocol version. `id` is unique per sender: prefix `o-` for the orchestrator and `u-` for Unity. `ts` is Unix milliseconds. A receiver ignores and logs any `type` it does not know, so either side can add messages without breaking the other.

**Unity to orchestrator**

| `type` | Extra fields | Sent when | Orchestrator does |
| --- | --- | --- | --- |
| `hello` | `client`, `scene`, `npcs[]` | On connect | Replies with `run.snapshot` |
| `run.start` | `learner_name`, `mic_mode`: `open``, ptt or half_duplex` | Player presses Start | Resets run state, starts the clock |
| `proximity.enter` | `npc` | Player within 2.2 m, facing | Ends any other live session, then starts this character's conversation |
| `proximity.exit` | `npc` | Player beyond 3.5 m for 1.5 s | Ends the conversation |
| `ptt` | `down`: bool | Space pressed or released, in `ptt` mode | Unmutes or mutes the mic gate |
| `hint` | `kind`: `subtitles` | Tab held | Increments the hint counter |
| `tool.result` | `call_id`, `ok`, `detail` | Unity finished or failed a `tool.call` | Logs it. Never waits for it. |
| `audio.drained` | `npc` | Playback buffer ran empty | Sets state to `listening` |
| `run.end` | `reason` | Player presses Esc or Finish | Ends sessions, runs the tutor |

**Orchestrator to Unity**

| `type` | Extra fields | Sent when | Unity does |
| --- | --- | --- | --- |
| `run.snapshot` | `goals[]`, `active_npc`, `state`, `mic_mode` | After `hello` | Rebuilds the HUD. Makes reconnects invisible. |
| `session.state` | `npc`, `state`: `connecting`, `listening`, `thinking`, `speaking`, `ended` | On every change | Sets the character's Animator state and the HUD ring |
| `audio.begin` | `npc`, `sample_rate` | Before the first audio frame of a reply | Routes the following audio frames to that character's `PcmStreamPlayer` |
| (audio frame) | binary | As chunks arrive from ElevenLabs | `Push` into the ring buffer |
| `audio.flush` | `npc` | On barge-in, and on session end | `Flush()` immediately and stop the talking animation |
| `tool.call` | `call_id`, `npc`, `name`, `params` | A character called a client tool | Runs the scene action, then sends `tool.result` |
| `caption` | `speaker`: npc id or `user`, `text`, `final` | On each transcript or agent response | Stores it. Shows it only while Tab is held. |
| `goal.update` | `goal_id`, `status`: `done`, `evidence` | Director confirmed a goal | Ticks the HUD line, plays a soft chime |
| `feedback.ready` | `report` (section 11), `html_path` | Tutor finished | Shows the end screen |
| `error` | `code`, `message`, `fatal` | Anything broke | Shows a small toast. If `fatal`, offers Restart. |

**Worked example: the learner orders.**

```json
{"v":1,"type":"session.state","id":"o-000040","ts":1790000001000,"npc":"maria","state":"thinking"}
{"v":1,"type":"tool.call","id":"o-000041","ts":1790000001450,"call_id":"tool_call_8f2a","npc":"maria",
 "name":"serve_order","params":{"items":["cafe_olla","concha"],"to_go":false,"total_mxn":80}}
{"v":1,"type":"audio.begin","id":"o-000042","ts":1790000001900,"npc":"maria","sample_rate":16000}
{"v":1,"type":"session.state","id":"o-000043","ts":1790000001901,"npc":"maria","state":"speaking"}
```

Then binary audio frames follow. Unity answers when the cup has landed:

```json
{"v":1,"type":"tool.result","id":"u-000017","ts":1790000002100,"call_id":"tool_call_8f2a","ok":true,"detail":"spawned 2 items"}
```

A moment later the director confirms the goal:

```json
{"v":1,"type":"goal.update","id":"o-000051","ts":1790000003200,"goal_id":"G1","status":"done",
 "evidence":"Quisiera un café de olla y una concha, por favor."}
```

Notice that the orchestrator adds `total_mxn` to the `tool.call` params. Unity never computes prices.

### How the orchestrator derives `session.state`

| Event from ElevenLabs or Unity | New state |
| --- | --- |
| Session opened | `listening` |
| `user_transcript` received | `thinking` |
| First `audio` chunk of a reply | `speaking` |
| `audio.drained` from Unity, or in stage 1 the local queue emptying | `listening` |
| `interruption` | `listening`, and send `audio.flush` |
| Session closed, by `end_call`, exit or timeout | `ended` |

### Rules that keep it robust

1. **The conversation never waits for the renderer.** Tool results go back to ElevenLabs at once. `tool.result` from Unity is for logs.
2. **One live character.** A second `proximity.enter` ends the first session before starting the next.
3. **Reconnect is normal.** Unity retries every 2 s. On `hello` it gets a `run.snapshot`. The ElevenLabs session is not touched by a Unity restart.
4. **Flush beats everything.** On `audio.flush` Unity drops buffered audio in the same frame. Late audio frames for an ended reply are impossible, because the SDK drops them before they reach the bridge.
5. **Validate at the door.** Both sides parse every message into a typed model and log rejects. Most integration bugs will be a misspelt field.
6. **Log everything.** The orchestrator appends every bridge message and every ElevenLabs event to `runs/<run_id>/events.jsonl`. It is the debugger, the evidence for feedback, and the replay source for the mock tools.

## 11. Director and tutor

> **Status, 2026-09-19.** Goal ticking and end-of-run grading are built (`orchestrator/director.py`, `orchestrator/grading.py`). Mistake logging, learner state, steering the actor and the written feedback report are not; see section 18.5, C5 and C10.

The character acts, a separate director judges, and a tutor explains afterwards. Keeping those three apart is the main design idea of the project, and it is where the OpenAI API does its work.

### Why the actor must not be the judge

The obvious design gives the character a `mark_goal_complete` tool. We rejected it for three reasons.

1. **It makes the character robotic.** A waitress who is also grading you talks like an examiner. The prompt fills with scoring rules and the persona thins out.
2. **It costs latency.** Every tool call is extra LLM output before the character can speak.
3. **It is unreliable.** A small, fast voice model under time pressure forgets to call bookkeeping tools.

So the actor knows nothing about goals. The director reads the same transcript a moment later, off the critical path, with a model and prompt built for judging.

### What the director does after every learner turn

`director.on_user_turn(npc, text)` fires when ElevenLabs sends a `user_transcript`. It starts a background task and returns at once. The task:

1. Builds the input: the goal rubric from `scenario.yaml` including the "does not count" column, the last six turns, the new learner turn, which goals are still open, and which character is active.
2. Calls the OpenAI Responses API with a structured output schema.
3. Merges the verdict into run state, using the evidence rules below.
4. Sends `goal.update` to Unity for any new goal.
5. Optionally sends one silent stage direction to the actor.

```python
from typing import Literal, Optional
from pydantic import BaseModel
from openai import AsyncOpenAI

class GoalHit(BaseModel):
    goal_id: Literal["G1", "G2", "G3", "G4", "G5", "G6"]
    evidence_quote: str            # the learner's exact words

class Mistake(BaseModel):
    quote: str                     # what we heard
    correction: str                # a natural Mexican Spanish version
    category: Literal["gender_agreement", "verb_conjugation", "tense", "ser_estar",
                      "por_para", "word_choice", "word_order", "register",
                      "false_friend", "english_fallback", "other"]
    explanation_en: str            # one sentence
    severity: Literal[1, 2, 3]     # 3 = a native speaker would be confused
    confidence: float              # 0 to 1
    asr_suspect: bool              # true if this looks like a transcription error

class TurnVerdict(BaseModel):
    goal_hits: list[GoalHit]
    mistakes: list[Mistake]
    used_english: bool
    used_repair_phrase: bool
    learner_state: Literal["fine", "hesitant", "stuck", "distressed"]
    director_note: Optional[str]   # a stage direction for the actor, or null

client = AsyncOpenAI()

async def judge_turn(context: str) -> TurnVerdict:
    r = await client.responses.parse(
        model=DIRECTOR_MODEL,           # loaded from orchestrator/.env
        input=[{"role": "system", "content": DIRECTOR_RUBRIC},
               {"role": "user", "content": context}],
        text_format=TurnVerdict)
    return r.output_parsed
```

`responses.parse` with a Pydantic `text_format` is the pattern in OpenAI's [structured outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs). Target latency is under 1.5 s. It never blocks speech either way.

### Hybrid evidence: model judgement plus hard events

A language model alone will sometimes award a goal wrongly. Where a hard event exists, require both.

| Goal | Model says | And the event log shows |
| --- | --- | --- |
| G1 `order` | Learner used a request form with a menu item | `serve_order` was called within the next two actor turns |
| G2 `ask_price` | Learner asked a price question | The question came before any `show_bill` that was triggered by the learner leaving |
| G3 `curveball` | Learner answered the clarifying question | One of Maria's three curveball lines appears in her previous two turns |
| G4 `small_talk` | Two or more full-clause self-statements | Three or more exchanges with Luis |
| G5 `follow_up` | Question refers to Luis's content | The director must quote **both** the learner's question and the line of Luis's it refers to. No quote, no goal. |
| G6 `repair` | Learner used a Spanish repair phrase | none needed |

A goal, once done, stays done.

### Steering the actor without breaking character

The director can whisper to the actor with `conv.send_contextual_update("[DIRECTOR] ...")`. A [contextual update](https://elevenlabs.io/docs/eleven-agents/customization/events/client-to-server-events.md) does not interrupt and is never spoken. Both prompts tell the character to follow these notes naturally. At most one note every three turns.

| Trigger | Note sent |
| --- | --- |
| `learner_state` is `stuck` for two turns with Maria | `[DIRECTOR] The customer seems stuck. Offer two options from the menu in one short sentence.` |
| `distressed`: repeated "no entiendo", long silences | `[DIRECTOR] Slow down and use simple words for your next three replies.` |
| Five exchanges with Luis and G5 still open | `[DIRECTOR] Briefly mention your night turtle patrols, then pause and let them respond.` |
| Learner is doing very well, all core goals done early | `[DIRECTOR] They are comfortable. Speak a little faster and use more slang.` |
| 40 s left before the cap | `[DIRECTOR] Wrap up naturally within your next two replies.` |

This gives us adaptive difficulty with no visible machinery. The learner only experiences a person who noticed they were struggling.

The director also carries memory between characters. When the Maria session ends, the order is stored. It is passed to Luis as the `user_order` dynamic variable, so he can say "¿Qué pediste? Ah, café de olla, buena elección."

### Capturing mistakes honestly

Mistakes come from the same per-turn verdict and accumulate in run state. Three caveats shape the design.

- **Speech recognition is not a neutral witness.** It mishears, and it often outputs grammatical Spanish even when the learner did not say it. So the schema has `confidence` and `asr_suspect`, the feedback screen shows only mistakes with confidence of 0.7 or more, and it is headed "what we heard".
- **Text cannot judge pronunciation.** We do not claim to. It is listed as future work.
- **Never interrupt to correct.** Nothing the director finds is shown during the run except goal ticks.

Stretch, if there is time: the orchestrator already has the raw mic audio. Save each learner turn as a WAV file. On the feedback screen, each fix gets two play buttons: "you" plays the learner's clip, and "Maria" plays the corrected sentence through ElevenLabs text-to-speech in the character's own voice. Hearing the difference is worth more than reading it, and it is a second, distinct use of the ElevenLabs API.

### The tutor and the feedback report

When the run ends, `tutor.py` makes one call to the larger model with the full transcript, the goal results with evidence, all logged mistakes, and the counters. Its instructions: pick at most three fixes, ranked by severity times confidence, and never pick an `asr_suspect` one. Name one specific thing that went well and quote it. Give two or three phrases that would have helped at the moments the learner stalled. Suggest the next run. Explanations are in English and examples in Spanish.

```json
{
  "run_id": "2026-09-20T09-14-03",
  "scenario": "cafe_cancun_v1",
  "result": "pass",
  "stars": 2,
  "duration_s": 312,
  "goals": [
    {"id": "G1", "label": "Order something", "done": true,
     "evidence": "Quisiera un café de olla y una concha, por favor."},
    {"id": "G2", "label": "Ask the price", "done": true, "evidence": "¿Cuánto es?"},
    {"id": "G4", "label": "Make small talk", "done": true, "evidence": "Soy de Boston y trabajo con computadoras."},
    {"id": "G5", "label": "Ask a follow-up question", "done": true,
     "evidence": "¿Por qué marcan las tortugas de noche?", "refers_to": "esta semana ando en patrullas nocturnas marcando tortugas"},
    {"id": "G3", "label": "Handle a curveball", "done": true, "evidence": "Para aquí, gracias."},
    {"id": "G6", "label": "Recover in Spanish", "done": false, "evidence": null}
  ],
  "fixes": [
    {"heard": "Estoy de Boston", "better": "Soy de Boston",
     "why": "Use ser, not estar, for where you are from.", "category": "ser_estar"}
  ],
  "went_well": {"quote": "¿Por qué marcan las tortugas de noche?",
                "note": "A real follow-up question, asked without hesitation."},
  "useful_phrases": [
    {"es": "¿Me lo puedes repetir más despacio?", "when": "When Maria asked about the milk and you switched to English."}
  ],
  "counters": {"english_turns": 1, "hints": 0, "repair_phrases": 0},
  "next_run": "Same café. Try to recover in Spanish when you miss something."
}
```

**Where it is shown.** The tutor renders `runs/<run_id>/feedback.html` from a template and opens it in the browser. Unity shows a simple end card with the result and stars. An HTML page is faster to make look good than Unity UI, and an agent can build it in one pass. Moving the full report into Unity is a stretch task.

### What it costs

One director call is roughly 1,500 input and 200 output tokens. A run has 15 to 25 learner turns, plus one tutor call of about 4,000 tokens. At the small-model prices on [OpenAI's pricing page](https://developers.openai.com/api/docs/pricing), one run costs well under one US cent for the director and a few cents for the tutor. The $50 of API credit per person is far more than we need.

## 12. Making it feel natural, not robotic

A voice character feels robotic for four reasons: it answers late, it cuts you off or talks over you, it sounds like a help desk, and its body does nothing. Each has a specific fix below, followed by the edge cases that break demos.

### Latency budget

These are estimates, not measurements. The model latencies are from [ElevenLabs' models page](https://elevenlabs.io/docs/overview/models.md).

| Stage | Estimate | Lever |
| --- | --- | --- |
| Deciding the learner has finished | 500 to 900 ms | Turn eagerness. We choose Patient on purpose: cutting a learner off is worse than a short pause. |
| Speech recognition | about 150 ms | none |
| LLM first token | 300 to 700 ms | Small model, lowest reasoning effort, short prompt, no RAG |
| Voice model first audio | about 75 ms (Flash v2.5) or about 280 ms (v3 Conversational) | The expressive model costs about 200 ms. Worth it unless the total is too high. |
| Network, both ways | 100 to 200 ms | Venue Wi-Fi. Have a phone hotspot ready. |
| Bridge and Unity audio buffer | 20 to 60 ms | none needed |
| **Total, end of speech to first sound** | **about 1.2 to 2.0 s** |  |

A pause of about a second reads as a person thinking, especially when talking with a foreigner. Two seconds starts to feel dead. **Measure, do not guess:** log the time from each `user_transcript` to the first audio chunk of the reply in `events.jsonl`, and print the median and 90th percentile at the end of every run. If the median is over 1.5 s, change one thing at a time in this order: smaller LLM, then Flash v2.5, then turn eagerness Normal.

**Cover the gap with the body.** The moment the state becomes `thinking`, the character glances away and tilts their head. When `speaking` starts, the gesture and the first word land together. A visible reaction within 200 ms makes a 1.5 s pause feel natural. If the LLM stalls past 2 s, the soft timeout makes the character say "Mmm, a ver...".

### Echo and noise: the problem that will bite in a loud room

Browser voice apps get echo cancellation free from WebRTC. Our Python path has none. If the character's voice comes out of laptop speakers, the mic hears it, and the agent interrupts itself.

| Mic mode | How it works | When to use |
| --- | --- | --- |
| `open` | Mic always live. Full barge-in. | **With headphones.** The default, and the best experience. |
| `ptt` | Mic is live only while Space is held. Silence is sent otherwise. | A loud room. Also stops nearby voices triggering the agent. |
| `half_duplex` | Mic is muted while the state is `speaking` | Last resort with speakers and no headphones. Loses barge-in. |

Use a wired headset with a boom mic for demos. Test in the actual room when it is loud, and choose the mic mode there.

### Turn-taking and barge-in

- **Patient eagerness, 8 s turn timeout.** Learners stop mid-sentence to search for a word. The agent must wait through that.
- **Backchannels do not interrupt.** "Ajá", "mhm", "sí", "ok" and "claro" are on the ignore list, so agreeing while the character talks does not cut them off.
- **Real interruptions stop the character within a frame.** ElevenLabs sends `interruption`, the SDK calls `interrupt()`, the orchestrator sends `audio.flush`, and Unity empties the ring buffer and drops the talking animation.
- **After a barge-in, trust the correction.** ElevenLabs sends `agent_response_correction` with what the character actually got out before being cut off. The director and the captions must use the corrected text. Otherwise goal G5 could credit a follow-up about something Luis never audibly said.
- **"Un momento" is respected.** The character calls `skip_turn` and stays quiet.

### Persona behaviours that read as human

- The character speaks first, and not always with the same line. The orchestrator picks one of three greetings per character and sends it as a first-message override. That is why that override is enabled.
- Replies are one or two sentences. Long replies are the clearest "I am an AI" tell in voice.
- The character reacts before asking: "¡Ah, de Boston! Qué frío, ¿no?" rather than firing the next question.
- No teacher talk, ever: no praise for their Spanish, no corrections, no "¡muy bien!".
- Each character withholds something, so the learner has to act: prices for Maria, conversational effort for Luis.
- Laughs and sighs through expressive tags, at most one per reply.
- Eye contact, a gesture on most turns, and a talking animation that stops the instant the audio does.

### Edge cases: conversation

| Situation | What happens |
| --- | --- |
| Learner says nothing after the greeting | At 8 s the character prompts again in character. After a second silence, the director sends the "offer two options" note. The session never ends abruptly on silence. |
| Learner speaks English | The character did not catch it, says so in Spanish and rephrases once. The English counter goes up. |
| Recognition garbles the order | Maria's prompt makes her confirm before serving: "¿Un café de olla y una concha, verdad?" |
| Learner orders something not on the menu | "Uy, de eso no tengo", plus one suggestion. `serve_order` rejects unknown ids anyway. |
| Learner walks away mid-conversation | `proximity.exit` after 1.5 s, then flush and end the session. The character does not shout after them. |
| Learner comes back to the same character | A new session starts with no memory of the first. Known limitation. Mitigation if time allows: pass a one-line `visit_context` dynamic variable summarising the earlier visit. |
| Learner goes to Luis first | Fine. `user_order` is "nada" and he does not mention it. Goals have no required order. |
| Learner asks "are you an AI?" | The character stays in character and is puzzled by the question |
| Learner is abusive | The character excuses themselves and calls `end_call` |
| Time cap approaching | Director sends the wrap-up note 40 s before `max_duration_seconds` |
| Internet drops mid-session | The SDK session ends. The orchestrator sends `session.state: ended` and a non-fatal `error`. Walking up again starts fresh. |
| Out of ElevenLabs minutes or over the concurrency limit | Fatal `error` with a clear message. Check the balance before a demo. |
| A tool is called with bad parameters | The handler returns an error string and the LLM recovers in speech |
| OpenAI call fails or times out | The goal tick is late or missing, and the conversation is unaffected. The tutor re-judges the whole transcript at the end, so the final report is still right. |

### Edge cases: scene

| Situation | What happens |
| --- | --- |
| Player walks into the blurry edge of the world | Invisible walls keep them inside the clean zone |
| Player falls through the floor | A kill plane at y = -5 respawns them at the door |
| Both characters in range at once | Place them more than 5 m apart. The orchestrator also enforces one live session. |
| Frame rate is poor | Switch to the 500K-splat asset and lower the render scale |
| Unity stops or crashes mid-conversation | The orchestrator keeps the session. On reconnect, `run.snapshot` restores the HUD. |
| Mouse cursor is trapped | Esc unlocks the cursor and opens a small menu: Resume, Restart, Finish |
| Character stands inside splat furniture | Placement is by hand. Check from several angles, because splats look solid from only some directions. |

## 14. Demo first, then scale up

> **Status, 2026-09-19.** Stages 0, 1, 3 (server side), 4 (ticks and grades) and 5 are done in HTTP form. The remaining work is re-planned in section 18, and section 18.8 shows the visit with the new pieces.

Build in stages where every stage ends with something you could show. After stage 1 there is always a working demo on `main`. This is an order of work with exit tests, not a timetable.

### Stages

| Stage | Name | Voice | Unity | World | Exit test |
| --- | --- | --- | --- | --- | --- |
| 0 | Set up | ElevenLabs plan. OpenAI API key. Create the Maria agent with the prompt from section 9. `.env` in place. | Rename `My project` to `unity`. Add the three packages. Confirm the splat URP feature is on the renderer. | Standard plan or API key. Download one World Labs sample scene for the Unity lane. | Everyone can run their own tool |
| 1 | Talking | Orchestrator with the SDK's default audio. Talk to Maria through headphones. `play_gesture` prints to the console. | Sample world imported, aligned, walkable with primitive colliders | First café drafts with `marble-1.0-draft` | **A full Spanish order, by voice, with barge-in working.** This alone is a demo. |
| 2 | Connected | Bridge server, `protocol.py`, `mock_unity.py`. Proximity starts and ends sessions. Audio forwarded as binary frames. | `BridgeClient`, `PcmStreamPlayer`, proximity check on a capsule stand-in for Maria, built against `mock_orchestrator.py` | Final café with `marble-1.1`. Export. Write the manifest. | Walk up to a capsule, it greets you in Spanish from its position, and interrupting it cuts the audio |
| 3 | Alive | `serve_order` and `show_bill` handlers with pricing. `session.state` broadcasts. Latency logging. | Café world in. Rocketbox Maria with idle, talk and gestures, eye contact, lip-sync. Cup appears on the table. Menu board. | Clean the splat in SuperSplat. Help place anchors. Start the pano fallback scene. | Order a coffee from a lip-synced Maria in the real café and see it arrive |
| 4 | Scored | Director with structured outputs. `goal.update`. Tutor and `feedback.html`. | HUD goal list, state ring, subtitles on Tab, end card | Second world for a second scenario, if credits allow | Finish a run and read a correct feedback report |
| 5 | Second character | Luis agent. `user_order` hand-off. Director notes. Eval harness. | Luis avatar and placement. Push-to-talk UI. | Lighting reference from the pano. Polish. | The full two-character run from section 3 |
| 6 | Polish | Greeting variants. Custom LLM experiment. Audio replay in feedback. | Thinking poses, blob shadows, sound effects, a standalone build | Backup demo video capture | A stranger can play it without help |

### If we fall behind, cut in this order

1. Audio replay on the feedback screen.
2. The Custom LLM experiment. Keep a built-in model.
3. The collider GLB. Keep primitive colliders.
4. A seated Luis. Keep him standing.
5. The feedback report inside Unity. Keep the HTML page.
6. Lip-sync by uLipSync. Keep the volume-driven jaw.
7. Luis entirely. In that case use a "slow afternoon" variant of Maria's prompt: remove "you have other tables" and give her Luis's three conversational hooks, so all four core goals still work with one character.

Never cut: barge-in, the proximity start, goal ticks, the feedback report. Those are the product.

## 15. Fallbacks

Every risky piece has a fallback that keeps the conversation system untouched. Because the voice and scoring logic live in the orchestrator, none of these fallbacks cost us the product.

| Risk | Sign it is happening | Fallback | Cost |
| --- | --- | --- | --- |
| Splat will not import or render in Unity | Black screen, pink material, "Index out of range", nothing after 2 hours | In order: use the 2M PLY, not SPZ. Check the URP renderer feature. Check the graphics API is D3D12 or Metal. Try [gsplat-unity](https://github.com/wuyize25/gsplat-unity) in a Gamma-space test project. Then the pano skybox below. | Hours, then the loss of walking |
| Splat renders but runs too slowly | Under 30 fps on the demo laptop | 500K PLY, lower render scale, smaller window | Visual detail |
| Collider GLB misaligned, or the player falls through | Walking through the counter | Primitive colliders. This is already the default. | None |
| Marble output is ugly or the layout is wrong | Melted furniture, no clear counter | Re-prompt with a better reference image. Try Chisel to block out the counter and table. Use a World Labs sample café-like scene. | Credits |
| Characters look wrong in the splat | Floating, wrongly lit, clipping | Blob shadow, one tuned light, stand them in open floor. Maria behind the counter hides most problems. | Little |
| uLipSync does not react to streamed audio | Mouth stays still | Volume-driven jaw blendshape from `PcmStreamPlayer` | 30 minutes |
| Audio through Unity stutters or plays at the wrong pitch | Chipmunk or choppy voice | Resample in `Push`. If still bad, play audio from Python (stage 1 path) and send Unity only a loudness value for the jaw. | Spatial audio |
| The Unity bridge client is flaky | Disconnects, lost messages | Swap NativeWebSocket for `System.Net.WebSockets.ClientWebSocket` on a background thread with a `ConcurrentQueue` drained in `Update` | 1 hour |
| The ElevenLabs SDK blocks us | A missing event, a bug in the audio interface | Raw WebSocket in Python, using the message shapes in the [API reference](https://elevenlabs.io/docs/eleven-agents/api-reference/eleven-agents/websocket). About 150 lines. | 2 hours |
| V3 Conversational is too slow or odd in Spanish | Over 1.5 s median latency, strange prosody | Flash v2.5 | Some expressiveness |
| The agent self-interrupts or hears the hall | Replies cut off, phantom turns | `ptt` mic mode with a headset | Open-mic barge-in |
| Client tools misfire | Wrong items, tools never called | A larger LLM for Maria. Simplify `items` to a string. As a last resort, the director infers the order from the transcript and triggers the scene action itself. | Latency or purity |
| The director is slow or wrong | Late ticks, false awards | Ticks are cosmetic during the run. The tutor re-judges everything at the end with the bigger model. Tighten the rubric using the eval set. | None for correctness |
| Venue internet fails | Everything stalls | Phone hotspot. If that fails, the backup video. | The live demo |
| Unity as a whole is the problem | Still fighting the engine at the halfway point | The browser client: World Labs' [character controller template](https://docs.worldlabs.ai/api/interactive-world-examples.md) with Spark, connected to the same bridge. Characters through [TalkingHead](https://github.com/met4citizen/TalkingHead). | A rebuild of the front end only |

### The pano skybox path, if splats fight us

This keeps the photoreal place and every part of the conversation system. It gives up walking.

1. Export the 360 pano from Marble: a 2560 by 1280 equirectangular PNG. Free-tier worlds cannot export, so this still needs the Standard plan or the API's `pano_url`.
2. In Unity, import the PNG with Texture Shape 2D, no compression, max size 4096. Create a material with the shader `Skybox/Panoramic`, set Mapping to Latitude Longitude Layout, and assign it under Lighting, Environment, Skybox Material.
3. Fix the player at the centre and allow look-around only. Moving the camera inside a skybox shows no parallax, and the illusion breaks at once.
4. Add an invisible ground plane and place Maria 2 m in front of the camera, where the counter appears in the pano. Rotate the skybox until it lines up. Add the blob shadow.
5. Replace the proximity trigger with "look at the character and press E". That sends the same `proximity.enter`. Nothing in the orchestrator changes.
6. The pano is only about 7 pixels per degree, so it looks soft full-screen. Use a narrower field of view, about 50 degrees. Optionally upscale the PNG to 8192 wide with any image upscaler.

The honest pitch in that case: "you stand in the real place and talk" instead of "you walk around it". The one-sentence answer for why 3D gets weaker, so treat this as a last resort.

### What is a genuine dead end

- **Ready Player Me avatars.** The service is shut down.
- **The official ElevenLabs Unity SDK on our Unity version.** It needs 6.3.
- **A WebSocket server inside Unity using `HttpListener`.** Not implemented in Unity's Mono runtime.
- **A WebGL build of the Unity project.** The splat plugin does not support WebGL. For the web, use Spark.
- **The high-quality mesh export as a visual fallback.** Up to an hour to generate, Pro plan only, and it looks worse than the splat.

## 16. Open questions and decisions still to make

### Things to verify

- [ ] The exact OpenAI model id strings for the director and tutor, on the pricing page
- [ ] ElevenLabs included minutes per plan, in the dashboard
- [ ] Marble plan prices and credits, on the Marble pricing page
- [ ] Real `.ply` file sizes on first export
- [ ] Which transform makes the Marble export upright in Unity, and whether the collider needs a different one
- [ ] That the splat occludes characters correctly
- [ ] That a 16 kHz streamed AudioClip plays at the right pitch
- [ ] That uLipSync reacts to a streamed clip
- [ ] That `AsyncConversation` exists in the installed SDK, if we want it
- [ ] Whether the ElevenLabs dashboard accepts an array-of-enum tool parameter
- [ ] Whether the knowledge base "prompt" usage mode is selectable in the dashboard
- [ ] What the agent does when a blocking client tool times out. It is undocumented, which is why our handlers always reply.
- [ ] Voice Library filter values for Mexican Spanish, and the chosen voice ids
- [ ] NativeWebSocket v2: whether `DispatchMessageQueue()` is still required

### Questions this doc does not answer

- How the learner picks a scenario and level. For now there is one scenario and one level.
- Pronunciation feedback. It needs audio analysis, not transcripts. Future work.
- Whether learners actually improve. It would take a study. For now, the argument is the design: task pressure, native speed, feedback after rather than during.

## 17. Sources

All pages were opened on 19 September 2026. They were read through a tool that summarises page content, so exact numbers and identifiers deserve a second look before money or code depends on them. GitHub commit dates could not be retrieved, so "maintained" claims rest on release dates and READMEs.

### World Labs Marble and Spark

- [Docs index](https://docs.worldlabs.ai) and [llms.txt](https://docs.worldlabs.ai/llms.txt)
- [Prompt guides](https://docs.worldlabs.ai/marble/create/prompt-guides/index.md): [image](https://docs.worldlabs.ai/marble/create/prompt-guides/image-prompt.md), [pano](https://docs.worldlabs.ai/marble/create/prompt-guides/pano-prompt.md), [multi-image](https://docs.worldlabs.ai/marble/create/prompt-guides/multi-image-prompt.md), [video](https://docs.worldlabs.ai/marble/create/prompt-guides/video-prompt.md), [expand](https://docs.worldlabs.ai/marble/create/prompt-guides/expand.md)
- [Export specs](https://docs.worldlabs.ai/marble/export/specs.md), [mesh export](https://docs.worldlabs.ai/marble/export/mesh.md), [Gaussian splat export](https://docs.worldlabs.ai/marble/export/gaussian-splat/index.md)
- [Unity export page](https://docs.worldlabs.ai/marble/export/gaussian-splat/unity), [Spark export page](https://docs.worldlabs.ai/marble/export/gaussian-splat/spark.md)
- [Models](https://docs.worldlabs.ai/marble/models.md), [account and billing](https://docs.worldlabs.ai/marble/support/account-billing.md), [release notes](https://docs.worldlabs.ai/marble/release-notes.md), [FAQ](https://docs.worldlabs.ai/marble/support/faq.md), [terms of service](https://docs.worldlabs.ai/terms-of-service)
- API: [overview](https://docs.worldlabs.ai/api/index.md), [pricing](https://docs.worldlabs.ai/api/pricing.md), [generate reference](https://docs.worldlabs.ai/api/reference/worlds/generate.md), [export reference](https://docs.worldlabs.ai/api/reference/worlds/export.md), [rendering SPZ](https://docs.worldlabs.ai/api/rendering-spz.md), [rate limits](https://docs.worldlabs.ai/api/rate-limits.md), [interactive world examples](https://docs.worldlabs.ai/api/interactive-world-examples.md)
- [Marble launch post](https://www.worldlabs.ai/blog/marble-world-model), [Spark 2.0 post](https://www.worldlabs.ai/blog/spark-2.0), [Spark](https://sparkjs.dev) and [its repo](https://github.com/sparkjsdev/spark)
- Secondary, for plan prices only: [TechCrunch](https://techcrunch.com/2025/11/12/fei-fei-lis-world-labs-speeds-up-the-world-model-race-with-marble-its-first-commercial-product/)

### Unity

- [aras-p/UnityGaussianSplatting](https://github.com/aras-p/UnityGaussianSplatting), its [releases](https://github.com/aras-p/UnityGaussianSplatting/releases), [render pipeline notes](https://github.com/aras-p/UnityGaussianSplatting/blob/main/docs/render-pipeline-integration.md), and the [winnie1994 fork](https://github.com/winnie1994/UnityGaussianSplatting)
- [gsplat-unity](https://github.com/wuyize25/gsplat-unity), [community Marble Unity tool](https://github.com/DakkuaDev/unity-worldlabs.ai-API-client-tool), [spark-physics example](https://github.com/bmild/spark-physics)
- [splat-transform](https://github.com/playcanvas/splat-transform), [SuperSplat editor](https://superspl.at/editor)
- [glTFast](https://github.com/atteneder/glTFast), [NativeWebSocket](https://github.com/endel/NativeWebSocket), [SimpleWebTransport](https://github.com/James-Frowen/SimpleWebTransport), [websocket-sharp](https://github.com/sta/websocket-sharp), [Fleck](https://github.com/statianzo/Fleck)
- Unity forum threads on `HttpListener` WebSockets: [one](https://discussions.unity.com/t/httplistener-and-websockets/820948), [two](https://discussions.unity.com/t/websocket-server-in-standalone-build/832108)
- Unity scripting reference: [AudioClip.Create](https://docs.unity3d.com/6000.0/Documentation/ScriptReference/AudioClip.Create.html), [OnAudioFilterRead](https://docs.unity3d.com/6000.0/Documentation/ScriptReference/MonoBehaviour.OnAudioFilterRead.html), [CharacterController.Move](https://docs.unity3d.com/6000.0/Documentation/ScriptReference/CharacterController.Move.html), [Microphone.Start](https://docs.unity3d.com/6000.0/Documentation/ScriptReference/Microphone.Start.html)
- [Starter Assets First Person, deprecated](https://assetstore.unity.com/packages/essentials/starter-assets-firstperson-updates-in-new-charactercontroller-pa-196525)
- Avatars: [Microsoft Rocketbox](https://github.com/microsoft/Microsoft-Rocketbox), [Avaturn bodies](https://docs.avaturn.me/docs/integration/bodies/), [UniVRM](https://github.com/vrm-c/UniVRM), [Ready Player Me shutdown, Road to VR](https://www.roadtovr.com/netflix-acquires-xr-avatar-startup-ready-player-me/)
- Lip-sync: [uLipSync](https://github.com/hecomi/uLipSync), [OVRLipSync end-of-life notice](https://developers.meta.com/horizon/documentation/unity/audio-ovrlipsync-unity/), [TalkingHead](https://github.com/met4citizen/TalkingHead)

### ElevenLabs

- [ElevenAgents overview](https://elevenlabs.io/docs/eleven-agents/overview), [quickstart](https://elevenlabs.io/docs/eleven-agents/quickstart.md), [docs index](https://elevenlabs.io/docs/llms.txt)
- [WebSocket API reference](https://elevenlabs.io/docs/eleven-agents/api-reference/eleven-agents/websocket), [WebSocket guide](https://elevenlabs.io/docs/eleven-agents/libraries/web-sockets.md), [client events](https://elevenlabs.io/docs/eleven-agents/customization/events/client-events.md), [client-to-server events](https://elevenlabs.io/docs/eleven-agents/customization/events/client-to-server-events.md), [signed URL](https://elevenlabs.io/docs/eleven-agents/api-reference/conversations/get-signed-url), [authentication](https://elevenlabs.io/docs/eleven-agents/customization/authentication.md)
- [Client tools](https://elevenlabs.io/docs/eleven-agents/customization/tools/client-tools.md), [create tool reference](https://elevenlabs.io/docs/eleven-agents/api-reference/tools/create), [system tools](https://elevenlabs.io/docs/eleven-agents/customization/tools/system-tools.md), [skip turn](https://elevenlabs.io/docs/eleven-agents/customization/tools/system-tools/skip-turn.md), [end call](https://elevenlabs.io/docs/eleven-agents/customization/tools/system-tools/end-call.md)
- [Overrides](https://elevenlabs.io/docs/eleven-agents/customization/personalization/overrides.md), [dynamic variables](https://elevenlabs.io/docs/eleven-agents/customization/personalization/dynamic-variables.md)
- [Language](https://elevenlabs.io/docs/eleven-agents/customization/voice/customization/language.md), [expressive mode](https://elevenlabs.io/docs/eleven-agents/customization/voice/expressive-mode.md), [voice design](https://elevenlabs.io/docs/eleven-agents/customization/voice/best-practices/conversational-voice-design.md), [models](https://elevenlabs.io/docs/overview/models.md), [Voice Library](https://elevenlabs.io/docs/eleven-creative/voices/voice-library.md)
- [Conversation flow](https://elevenlabs.io/docs/eleven-agents/customization/conversation-flow.md), [LLM choices](https://elevenlabs.io/docs/eleven-agents/customization/llm.md), [Custom LLM](https://elevenlabs.io/docs/eleven-agents/customization/llm/custom-llm.md), [cost optimisation](https://elevenlabs.io/docs/eleven-agents/customization/llm/optimizing-costs.md)
- [Knowledge base](https://elevenlabs.io/docs/eleven-agents/customization/knowledge-base.md), [RAG](https://elevenlabs.io/docs/eleven-agents/customization/knowledge-base/rag.md), [prompting guide](https://elevenlabs.io/docs/eleven-agents/best-practices/prompting-guide)
- [Get conversation](https://elevenlabs.io/docs/eleven-agents/api-reference/conversations/get), [success evaluation](https://elevenlabs.io/docs/eleven-agents/customization/agent-analysis/success-evaluation.md), [HeyGen LiveAvatar integration](https://elevenlabs.io/docs/eleven-agents/guides/integrations/live-avatar.md)
- [Python SDK guide](https://elevenlabs.io/docs/eleven-agents/libraries/python.md), [SDK source: conversation.py](https://github.com/elevenlabs/elevenlabs-python/blob/main/src/elevenlabs/conversational_ai/conversation.py), [PyPI](https://pypi.org/project/elevenlabs/)
- [Official Unity SDK](https://github.com/elevenlabs/unity), [community Quest package](https://github.com/danieloquelis/Unity-QuestConversationalAI)
- [Agents pricing](https://elevenlabs.io/pricing/agents)

### OpenAI and competitors

- [API pricing and models](https://developers.openai.com/api/docs/pricing), [structured outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs), [Codex](https://developers.openai.com/codex), [Codex CLI](https://learn.chatgpt.com/docs/codex/cli)
- [Talkio: AI speaking practice apps in 2026](https://www.talkio.ai/blog/best-ai-language-speaking-practice-apps-in-2026), for Praktika, Speak and Duolingo Max

## 18. The final build: where we are, what the plan lacked, and what to build

Written 2026-09-19. This section overrides sections 5, 10 and 14 wherever they disagree with it, because it describes the system that actually exists. Every vendor claim below was either verified against the live API today or is marked **verify this**.

### 18.1 Where we are

The build took a different shape from section 10. There is no WebSocket bridge. The orchestrator is a **FastAPI HTTP service on `127.0.0.1:8765`**, and Unity is its client. Unity records a push-to-talk clip, posts it, and plays the reply. This works end to end today.

| Piece | State | Where |
| --- | --- | --- |
| Cancún café world, walking, seating, NPC walking and look-at | Done | Unity |
| Maria (waitress) and Luis (at the table), Mexican voices, full prompts | Done, provisioned from data | `scenarios/cafe_cancun/`, `tools/provision_agents.py` |
| Speech turn: learner audio in, character audio out, transcripts | Done | `POST /v1/speech` |
| Client tools answered by Python: `serve_order`, `show_bill`, `play_gesture`; prices from `menu.json`; repeat-safe | Done | `orchestrator/scene.py` |
| Scene actions returned to Unity, and consumed by it | Done | `actions` in the speech response |
| Memory across characters: Luis knows what you ordered from Maria | Done | `run_id` |
| Cast discovery and pre-recorded greetings | Done on the server; Unity does not play the greeting audio yet | `GET /v1/npcs`, `GET /v1/npcs/{id}/greeting` |
| Director: goals ticked from speech after every turn, off the reply path | Done | `orchestrator/director.py`, `GET /v1/runs/{run_id}/goals` |
| Grader: letter grade per goal with evidence, printed as the café receipt | Done | `orchestrator/grading.py`, `POST /v1/grade` |
| Scenario generation from a prompt | Done | `POST /v1/scenarios` |
| Tests | 90 unit tests, plus a live 21-check end-to-end script | `uv run pytest`, `tools/e2e_check.py` |

Not built: streaming and low latency, barge-in, lip-sync, ambience, director steering of the actors, mistake logging and the written feedback report, pronunciation feedback, the director eval set, ElevenLabs-side agent tests, `AGENTS.md`, the standalone build.

### 18.2 What the plan lacked

Measured against the product goals and against a learner's actual experience, the original plan had these gaps. Each one maps to a component in 18.5.

**Voice and agents**

| Criterion | What the plan had | What it lacked |
| --- | --- | --- |
| Agentic depth | Two agents, tools, cross-agent memory | The director never talks back to the actors. Section 11 describes silent stage directions, but nothing sends them. The agents also know nothing about the world: where the learner is, how long they have waited, what they are looking at. No use of ElevenLabs' own analysis or agent-testing features. |
| Interaction design: low latency | A latency budget on paper | No streaming anywhere. A turn takes 3 to 5 seconds because the server waits for the whole reply, then waits 1.4 s more to be sure it ended, and on a first turn also throws away a greeting. Nothing is measured or reported. |
| Interaction design: emotional inflection | "Use V3 Conversational" | That model cannot be selected when creating a Spanish agent, so the plan's only lever for emotion silently did nothing. No plan for expressiveness on the model we can use, and no per-character choice. |
| Technical integration: voice plus video | uLipSync from audio | The agent's audio frames already carry per-character timing (verified today). The plan never used it, and lip-sync was never built. No use of the Sound Effects API at all. |
| Novelty | Situated rehearsal | Holds. Made stronger by soundscape and by generated scenarios getting live characters. |

**Judgement and feedback**

| Criterion | What the plan had | What it lacked |
| --- | --- | --- |
| How the API powers the experience | Director, tutor, scenario generator | The director runs at the model's default **medium** reasoning effort on every turn, with no timeout and a prompt layout that defeats caching. It only answers "was a goal met"; it does not log mistakes, read the learner's state, or steer anyone. There is no written feedback report, no pronunciation feedback, and no use of a second modality. |

**Against the learner's experience**

- The café is silent. A beach café with no waves and no murmur does not feel like a place.
- The character's mouth does not move.
- The learner cannot interrupt, which is how real conversation works.
- Feedback is a grade. A learner needs to know what to say differently, and to hear it.
- Nothing adapts. A learner who is drowning gets the same Maria as one who is coasting.

### 18.3 Decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Transport between Unity and Python | Keep HTTP. Add a **streaming** speech endpoint alongside the existing one. | Unity already speaks HTTP. A chunked response needs no new Unity package, and the existing endpoint keeps working for anyone who has not switched. |
| Learner audio into the agent | Keep: transcribe with Scribe, send text. | Measured today: Scribe takes about 0.4 s for a 3 s clip. ElevenLabs has no "user finished" message, so sending raw audio would hand turn-ending to a silence timer, which is slower with push-to-talk. Scribe also returns a confidence value per word, which we use. |
| Voice model | Flash v2.5 by default. V3 Conversational as a measured A/B, per character. | Measured today on the direct socket: 442 ms to first audio on Flash, 1,792 ms on V3. V3 must be set by PATCH after creation. |
| Character LLM | `gpt-5.6-luna`, to be benchmarked against two faster candidates. | The default model skipped tool calls. Any replacement must pass the end-to-end tool checks three times running. |
| Director model | `gpt-5.6-luna`, `reasoning.effort = "none"` | OpenAI's reasoning guide recommends `none` for voice and classification work. $0.20 / $1.20 per million tokens. |
| Grader, feedback and scenario model | `gpt-5.6-terra`, `reasoning.effort = "medium"` | Runs once per visit, so quality first. $2 / $12 per million tokens. About $0.07 per full visit in total. |
| Pronunciation | Scribe word confidence live, plus one `gpt-audio-1.5` pass at the end | No vendor documents pronunciation scoring, so it is presented as a coach's impression, never as a score. |
| Ambience | Generated once with the ElevenLabs Sound Effects API, committed, played by Unity | Verified today on a free account: a seamless loop in 2.4 s. The agents' built-in background sound has no ocean preset, stops between turns, and cannot be placed in 3D. |

### 18.4 Latency: budget and targets

Measured today unless marked as a target.

| Stage | Now | Target | How |
| --- | --- | --- | --- |
| Transcription (Scribe batch, 3 s clip) | 0.40 s | 0.35 s | Send `language_code=es`; send raw PCM with `file_format=pcm_s16le_16` when Unity provides it |
| Signed URL | 0.15 s | 0 on the turn | Done during pre-warm |
| Open the socket and drain the greeting | 2 to 4 s, on every first turn | 0 on the turn | Pre-warm when the player walks up (C2) |
| Agent: first audio after our text | 0.45 s direct | 0.45 to 0.8 s | Already fast; do not regress it |
| Waiting for the whole reply | 1 to 3 s | 0 | Stream chunks as they arrive (C1) |
| Deciding the reply has ended | 1.4 s fixed | about 0 | End on the frame's `is_final` flag, verified present today |
| **Learner stops talking to first sound** | **3 to 5 s** | **1.2 s p50, 1.8 s p90** | |
| Director verdict | Unmeasured; runs at medium reasoning | under 1 s p50 | C5 |

The numbers are reported by the server on every turn (C3), so the demo can show them rather than claim them.

### 18.5 Components to build

Priority P0 is the core build. P1 follows next. P2 is stretch. Every component lists the files it owns so parallel agents do not collide, and an acceptance test.

#### C1. Streaming speech endpoint (P0)

`POST /v1/speech/stream` takes exactly the same request as `POST /v1/speech`. It answers with `Content-Type: application/x-ndjson`, one JSON object per line, flushed as each becomes available:

```json
{"type":"transcript","text":"Quiero un café de olla","low_confidence_words":["olla"],"stt_ms":402}
{"type":"audio","seq":0,"sample_rate":16000,"offset_ms":0,"pcm_base64":"...","visemes":[{"t":46,"d":24,"v":"PBM"}]}
{"type":"text","text":"Claro, joven. ¿Para tomar aquí o para llevar?"}
{"type":"action","action":{"action":"play_gesture","npc_id":"maria","gesture":"nod"}}
{"type":"done","timings_ms":{"stt":402,"first_audio":910,"complete":2300},"goals_achieved":["G1"],"interrupted":false}
```

- The adapter gains `respond_stream()`, an async generator. `respond()` is rebuilt on top of it so there is one code path.
- A reply ends on `audio_event.is_final`. A 0.6 s quiet period stays only as a fallback.
- If the client disconnects mid-stream, the server stops forwarding and keeps the session.
- Errors before the first line use the normal status codes. Errors after it arrive as `{"type":"error","detail":...}` and the stream closes.
- The old endpoint gets the same `is_final` ending, which removes 1.4 s for clients that have not switched.
- Files: `orchestrator/elevenlabs_adapter.py`, `orchestrator/speech.py`, the speech routes in `orchestrator/app.py`, `orchestrator/tests/test_stream.py`.
- Accept when: a mocked socket that emits three audio frames produces three `audio` lines in order before `done`; live, `first_audio` is under 1.5 s on a warm session.

#### C2. Session pre-warm (P0)

`POST /v1/speech/sessions/{session_id}/warm?npc_id=&run_id=&learner_name=` opens the agent socket and drains the greeting, then returns 204. Unity calls it when the player comes into range, while it plays the pre-recorded greeting from `GET /v1/npcs/{id}/greeting`. The first real turn then costs the same as any other. Warming an already warm session is a no-op. Idle sessions still close after 120 s.

- Files: adapter, speech routes, tests.
- Accept when: the first turn after a warm has `first_audio` within 0.3 s of a second turn.

#### C3. Latency instrumentation (P0)

- Every speech response carries `timings_ms`: `stt`, `session_open` (0 when warm), `first_audio`, `complete`, `total`. The non-streaming endpoint also sends a `Server-Timing` header.
- `GET /v1/metrics` returns count, p50 and p90 per stage, per character, since start.
- Every turn appends one line to `runs/<run_id>/events.jsonl`.
- `tools/latency_bench.py --npc maria --turns 5 [--stream]` prints a table. It is the tool that settles every A/B in this plan.
- Files: adapter, `orchestrator/metrics.py`, routes, `tools/latency_bench.py`.

#### C4. Agent configuration pass (P0)

In `tools/provision_agents.py` and `scenario.json`:

- Add `agent_response_complete` and `agent_chat_response_part` to `client_events`.
- Add a spoken filler for slow model turns: `turn.soft_timeout_config = {"timeout_seconds": 1.5, "message": "Mmm, a ver..."}`.
- Set the character LLM's reasoning or thinking budget to its lowest value if the agent config exposes one. **Verify this** in the API schema.
- Lower Flash `stability` to 0.35 for livelier delivery, and check by ear.
- Add `--tts flash|v3`. V3 is created as Flash, then PATCHed to `eleven_v3_conversational` with `expressive_mode` and four `suggested_audio_tags` (laughs, warmly, slow, sighs). Prompts get a tone section only in the V3 variant, because **on Flash a tag such as `[laughs]` is read aloud**. The adapter strips any `[tag]` from transcripts either way.
- Benchmark three character LLMs with C3: `gpt-5.6-luna`, `gemini-2.5-flash-lite`, and one ElevenLabs-hosted Qwen model. Keep the fastest that passes `tools/e2e_check.py` three times running.
- Decision rule for voice: a character moves to V3 only if its p50 first audio stays under 1.5 s **and** it sounds clearly better. The likely outcome is Maria on Flash, because her lines are short and transactional, and Luis on V3, because his are social. Per-character choice is itself worth showing.

#### C5. Director: fast, richer, and steering (P0)

All in `orchestrator/director.py` and `orchestrator/models.py`.

- Speed: `reasoning={"effort":"none"}`, `httpx.Timeout(4.0, connect=1.5)`, one throwaway call per schema at startup because the first call with a new schema is slow, `max_output_tokens=600`. `service_tier="fast"` behind `DIRECTOR_FAST=1`.
- Caching: the full rubric and the instructions go first and never change during a run; turns follow as append-only messages; the list of still-open goal ids goes last. Drop the sliding 40-turn window, since a visit is 15 to 25 turns. Log `usage.input_tokens_details.cached_tokens`.
- A richer verdict, with `achieved` first so it is generated first:

```python
class Verdict(BaseModel):
    achieved: list[GoalTick]
    mistakes: list[Mistake]          # quote, correction, category, explanation_en, severity 1-3, asr_suspect
    used_english: bool
    used_repair_phrase: bool
    learner_state: Literal["fine", "hesitant", "stuck", "distressed"]
    director_note: str | None        # one stage direction for the character, or null
```

- Every `evidence_quote` and every mistake `quote` must be a verbatim substring of a learner line, checked in code. Anything else is dropped.
- A mistake is marked `asr_suspect` when its words overlap the turn's low-confidence words from Scribe.
- **Steering.** When `director_note` is set, the adapter sends `{"type":"contextual_update","text":"[DIRECTOR] ..."}` on that character's live socket. At most one note every three turns. The triggers are the table in section 11: stuck twice, distressed, the follow-up goal still open after five exchanges with Luis, doing very well, 40 s before the time cap. This is adaptive difficulty with no visible machinery, and it is the clearest agentic-depth story we have: one vendor's model judges, and quietly directs another vendor's actor, live.
- Mistakes, states and notes are appended to the run, so the feedback report can use them.
- `GET /v1/runs/{run_id}/goals` also returns `learner_state` and the latest note, for the demo's debug overlay.
- Free `omni-moderation-latest` check on learner text, in parallel, never on the reply path.
- Accept when: all existing director tests pass; new tests cover the substring rule, note rate-limiting, and a note reaching a mocked socket; the eval in C11 shows zero false awards.

#### C6. Soundscape from the Sound Effects API (P0)

- `tools/make_ambience.py` calls `POST /v1/sound-generation` with `model_id: eleven_text_to_sound_v2` and `loop: true`, and writes into `scenarios/cafe_cancun/ambience/`:

| File | Prompt, in short | Length | Credits |
| --- | --- | --- | --- |
| `ocean_loop.mp3` | Gentle waves on a sandy beach heard from inside an open café, distant, calm, no birds, seamless loop | 30 s | 1,200 |
| `cafe_murmur_loop.mp3` | Quiet café interior, soft indistinct Spanish murmur, occasional cup and spoon, ceiling fan, seamless loop | 30 s | 1,200 |
| `cup_on_table.mp3` | A ceramic cup and saucer set down on a wooden table | 1.5 s | 60 |
| `receipt.mp3` | A small thermal receipt printer printing and tearing | 2 s | 80 |

- Generate once, listen, commit. Never generate at runtime. Use a spare account's credits.
- `scenario.json` gains an `ambience` list (`id`, `file`, `loop`, `volume`, `duck_db`) and the two one-shots are attached to `serve_order` and `show_bill`.
- Served by `GET /v1/ambience/{name}` and listed in `GET /v1/npcs`. Each action carries an optional `sfx` URL.
- Mixing guidance for Unity: ocean at 0.12 and murmur at 0.08, mostly non-spatial, ducked by 6 dB while a character or the learner speaks, with a low-pass on the ocean so it sits behind speech. It must never be louder than a whisper under the voices.
- The scenario generator gains an `ambience_prompt` field, so a generated scenario can have its own soundscape (used by C14).
- Accept when: files exist and loop without a click; endpoint tests pass.

#### C7. Lip-sync and push-to-interrupt from alignment data (P1)

- The agent's audio frames carry `alignment: {chars, char_start_times_ms, char_durations_ms}`. Verified present today.
- `orchestrator/visemes.py` maps Spanish graphemes to a small viseme set: `A E I O U`, `PBM`, `FV`, `L`, `S` (s, z, c before e or i), `TD` (t, d, n), `KG` (c, qu, k, g, j), `R`, `CH`, `sil`. Digraphs and silent `h` are handled; timings are offset by the chunk's position.
- Streaming `audio` lines carry `visemes`. The non-streaming JSON carries one full `visemes` timeline.
- Unity drives the Rocketbox viseme blendshapes from the timeline. If that slips, the volume-driven jaw from section 8 is the fallback.
- **Push-to-interrupt.** The learner presses the talk key while a character is speaking. Unity stops playback and sends `interrupted_at_ms` with the next turn. The server uses the alignment timeline to work out which words were actually heard, records the truncated line in the transcript, and tells the agent with a contextual update: "The learner interrupted you after: '...'". The character then reacts to being cut off. This gives the demo its barge-in beat without full-duplex audio.
- Files: `orchestrator/visemes.py`, adapter, tests.
- Accept when: `"¡Buenas tardes!"` with known timings yields the expected viseme sequence; an interruption at 600 ms yields the right heard prefix.

#### C8. World-state feed (P1)

`POST /v1/speech/sessions/{session_id}/context` with `{"text": "..."}` forwards a contextual update to the live agent. Unity sends short facts: "The customer sat down at the table", "The customer has been reading the menu for 20 seconds", "The customer stood up to leave". Rate-limited to one every 5 s, 200 characters. The prompts already tell each character to treat bracketed notes as silent direction; add one line saying `[WORLD]` notes are facts about the room.

#### C9. Pronunciation and confidence (P1)

- Scribe's per-word `logprob` is already in the response we receive. Words below a threshold, tuned on real clips, become `low_confidence_words`.
- Each learner clip is saved to `runs/<run_id>/audio/turn_NN.wav`.
- At the end of a run, the two or three clips with the lowest confidence go to `gpt-audio-1.5` through Chat Completions with a forced function call, since that model does not list structured outputs. The result is shown as "coach's impressions", limited to words the transcript confirms were said.

#### C10. The written feedback report (P1)

`POST /v1/feedback` takes a `run_id` and returns, from one `gpt-5.6-terra` call over the transcript, the director's mistakes and the grades: at most three fixes ranked by severity, each with what we heard, a better version and one line of why; two or three phrases that would have helped at the moments the learner stalled; one thing that went well, quoted; counters; a suggested next visit; the pronunciation impressions; and the visit's latency figures. Never shows an `asr_suspect` mistake. Also renders `runs/<run_id>/feedback.html`.

A second opinion from ElevenLabs itself: the provisioner sets `platform_settings.evaluation.criteria` mirroring the goals and `data_collection` for items ordered and an estimated CEFR level. The adapter records each `conversation_id`; the report fetches `analysis` from `GET /v1/convai/conversations/{id}` and shows both verdicts side by side. Where they disagree, that is shown, not hidden.

#### C11. Tests that prove it (P0 for the eval, P1 for the rest)

| Test | What it proves | Cost |
| --- | --- | --- |
| `uv run pytest` | Logic, with mocked providers | Free |
| `eval/director_cases.jsonl` and `eval/run_eval.py` | 40 hand-labelled cases, half adversarial: said in English, one-word answers, the character says the phrase instead of the learner, a bare "¿y tú?". Per-goal precision and recall, p50 and p95 latency, and a hard gate: **any false award fails**. Run across `{luna, 5.4-nano} x {none, low}`. | Under $0.25 |
| `tools/agent_tests.py` | ElevenLabs' own agent-testing API: tool-call tests created with `POST /v1/convai/agent-testing/create` and run three times each with `run-tests`. Ordering leads to `serve_order`; asking the price leads to `show_bill`; pay de limón does **not** lead to `serve_order`; English gets a Spanish reply. Text only, so it costs no voice minutes. **Verify this** on the free plan. | LLM pass-through only |
| `tools/e2e_check.py`, extended | The streaming endpoint, pre-warm, timings under target, a director note arriving, ambience served, interruption handled | About 1 agent minute |
| `tools/latency_bench.py` | The latency table for the demo slide | About 1 agent minute |
| `tools/switch_account.py <name>` | Automates the account runbook: add voices, provision, write `.env`, run the end-to-end check | None |

#### C13. One conversation, two characters (P2)

ElevenLabs' `transfer_to_agent` system tool can hand a live conversation from Maria to Luis on the same socket, and the voice changes. It needs both agents in one account, and it fights Unity's one-session-per-character design. Stretch only.

#### C14. Live characters for any generated scenario (P2)

`POST /v1/scenarios/{id}/provision` creates ElevenLabs agents for a generated scenario, picking a voice by gender from the account, and generates its soundscape from `ambience_prompt`. This turns "type any situation" into a café, a pharmacy or a bus station with speaking characters. The provisioner already does the hard part.

### 18.6 What Unity needs to do

None of this is in Python, and none of it blocks the Python side. In priority order:

1. On proximity: call the pre-warm endpoint and play the greeting WAV from `GET /v1/npcs/{id}/greeting`.
2. Switch to `POST /v1/speech/stream`: read lines with a `DownloadHandlerScript`, push PCM into the streamed ring buffer that section 8 already specifies, and handle `action` lines as today.
3. Two looped AudioSources for the ambience, ducked while anyone speaks, plus the one-shot sounds that arrive with actions.
4. Drive viseme blendshapes from the `visemes` timeline.
5. Push-to-interrupt: talk key during playback stops it and sends `interrupted_at_ms`.
6. Send `[WORLD]` facts to the context endpoint: sat down, stood up, waited, looked at the menu.
7. A feedback screen after the receipt, from `POST /v1/feedback`.

If streaming cannot land in Unity in time, steps 1 and 3 alone still cut the first turn by seconds, and the old endpoint still gets the `is_final` saving.

### 18.8 The visit, after this build

| Moment | What the learner experiences | ElevenLabs | OpenAI | Time |
| --- | --- | --- | --- | --- |
| Walk in | Waves outside, a low murmur, a fan. Maria looks up. | Soundscape from the Sound Effects API | | |
| Approach Maria | She greets you at once, in her own voice, mouth moving | Pre-recorded greeting; session pre-warmed | | 0 s wait |
| "Quiero un café de olla y una concha" | She answers fast: "¿Para tomar aquí o para llevar?" | Scribe, then the agent on Flash, reply streamed chunk by chunk with visemes | Director reads the turn in the background | about 1.2 s to first sound |
| "Para tomar aquí" | "Ahorita te lo traigo." A cup lands on the table with a clink. | `serve_order` tool call, priced by Python; one-shot sound | Goal "order" ticks with your own words quoted | tick under 1 s later |
| You hesitate twice | Maria, unprompted, offers two options in one short sentence | A silent `[DIRECTOR]` note delivered as a contextual update | Director reports `stuck` and writes the note | |
| You cut her off mid-sentence | She stops, and reacts to being interrupted | Alignment data tells us which words you actually heard | The transcript keeps only what was heard | |
| "¿Cuánto es?" | "Son ochenta pesos, joven." A receipt prints. | `show_bill`; total in Spanish words from Python | Goal "ask the price" ticks | |
| Sit with Luis | "Ya vi que pediste café de olla, buena elección." He sounds warmer, laughs. | Second agent, `user_order` handed over; V3 expressive voice if it passes the A/B | | |
| He mentions night turtle patrols; you ask why at night | He lights up and tells you | | Goal "follow-up" ticks, quoting both his line and yours | |
| You sit quietly for 20 s | He fills the silence naturally | `[WORLD]` fact from Unity as a contextual update | | |
| Leave | The receipt shows a grade per goal. Then a page: three things to say differently, phrases that would have helped, which words to practise, and how fast the café answered you. | ElevenLabs' own post-call analysis as a second opinion | Grader and feedback on `gpt-5.6-terra`; pronunciation impressions from `gpt-audio-1.5` | |

### 18.10 Still to verify

- Whether the agent config exposes a reasoning-effort or thinking-budget field for the character LLM.
- Whether ElevenLabs' agent-testing endpoints run on the free plan, and what they bill.
- V3 Conversational quality in Mexican Spanish, by ear, and whether audio tags behave.
- Whether `service_tier="fast"` measurably helps `gpt-5.6-luna`.
- The Scribe confidence threshold that best separates a mispronounced word from noise.
- ElevenLabs minutes: four free accounts give about 55 minutes. Sustained use needs a paid plan on one account.

### 18.11 Built, 2026-09-20

The components of 18.5 were built on a feature branch. `docs/v1_modifications.md`
is the client-facing account of it; this is the scorecard against the plan.

| Component | State | Measured or verified |
| --- | --- | --- |
| C1 Streaming endpoint | Built | `POST /v1/speech/stream`. First sound about 1.0 s on a plain reply, about 1.25 s on a tool turn, against 3 to 5 s before |
| C2 Pre-warm | Built | First turn about 1.3 s instead of 5 s or more. Also warms transcription |
| C3 Latency instrumentation | Built | `timings_ms` on every turn, `Server-Timing`, `GET /v1/metrics`, `tools/latency_bench.py` |
| C4 Agent configuration | Built | Character model at reasoning `none`; filler only after 2.2 s; V3 path proven on a throwaway agent and left off; `gemini-2.5-flash-lite` rejected for missing tool calls |
| C5 Director | Built | Zero false awards over 480 live reviews; recall 0.91 to 0.96; median 1.3 s, above the 1 s target, and off the reply path |
| C6 Soundscape | Built | Four MP3s from the Sound Effects API, served by `/v1/ambience`; not yet checked by ear |
| C7 Visemes and interruption | Built | 14 visemes from alignment data; an interruption at 500 ms was resolved live to the words actually heard |
| C8 World-state feed | Already built on the Unity side | `POST /v1/runs/{run_id}/notes`; the director's notes use the same channel |
| C9 Pronunciation and confidence | Built | Per-word confidence live; one `gpt-audio-1.5` pass inside the report, labelled as impressions |
| C10 Feedback report | Built, minus two parts | `POST /v1/feedback`. ElevenLabs' second opinion and the latency figures are not in the report yet |
| C11 Tests | Built | 162 unit tests; the 40-case eval gate; 5 of 5 ElevenLabs agent tests, three times each; two live end-to-end scripts |
| C13, C14 | Not built | Stretch, as planned |

Three things the build found that the plan did not know:

1. **Gestures as a tool call were the largest single latency cost.** Any tool call makes the character's model
   generate twice, and a nod on most turns meant most turns paid for it. Gestures are now chosen on the server
   from the character's words, in microseconds.
2. **ElevenLabs never sets the last-frame flag**, and answering before the previous line has finished on its
   playback clock counts as interrupting that line. A reply is therefore ended by counting voiced characters
   against the reply text, and a correction that describes the previous line is ignored.
3. **Forcing a spoken line before a tool call** ("Claro, un café de olla y una concha.") lets the learner hear
   Maria at once while the order is priced. It needed the turn to stay open across the tool call; ending it at
   the first sentence lost the second, which then arrived as the answer to the next question.

Added for the learner, beyond the original component list: levels A1 to B2 that change how the characters
speak; **recasting**, where a character uses the correct form in its reply and never points at the mistake;
hints on request; a genuinely slower repeat when asked for in Spanish; free-form conversation (the wifi, what
a dish is, changing an order); memory when a conversation reopens; and a silent clip that costs nothing.

One operational fact: the first ElevenLabs account ran out of minutes during the build. The server runs on the
second, and a third is staged. `tools/switch_account.py` does the move.
