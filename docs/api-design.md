# API implementation scope

The current task delivers two HTTP endpoints. Unity implementation and ElevenLabs
provider implementation are out of scope here. The earlier end-to-end plan
is context, not a requirement to implement the full game or scoring director here.

## Speech turn

`POST /v1/speech` accepts raw audio bytes, a Content-Type, and query parameters
`session_id`, `npc_id`, and optional `scenario_id`. It returns raw response audio
with the provider's Content-Type. The caller generates and reuses a session UUID.
This is a complete-turn HTTP interface; it is not a realtime streaming or barge-in
protocol. The built-in adapter integrates the signed-URL voice-agent flow with
Scribe transcription, conversation memory, and provider session cleanup.

The API owns input limits, metadata validation, deadlines, error mapping, and
adapter loading. Missing adapters must return an explicit unavailable response,
never fake voice output. Transcripts, if the adapter supplies them, can be returned
using `response_format=json`, alongside base64 audio and format metadata.

## Scenario generation

`POST /v1/scenarios` accepts a prompt, target language, and learner level. It returns
a structured scenario and a learner-facing response. A scenario contains a setting,
characters with actor instructions and opening lines, and observable learning goals.
The model produces a schema-validated object; it cannot provision ElevenLabs agents
or create Unity assets. The API assigns the scenario ID and stores the validated
result locally so the speech adapter can load it through its provided context.

OpenAI credentials and model selection are server configuration. Refusals,
incomplete output, malformed results, timeouts, and provider failures produce
explicit errors. Tests inject provider doubles and require no paid API requests.
