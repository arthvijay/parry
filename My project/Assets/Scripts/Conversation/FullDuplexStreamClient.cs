using System;
using System.Collections;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;

/// <summary>
/// The live date's connection: one persistent WebSocket to <c>/v1/stream</c>, open in
/// both directions at once. No push-to-talk.
///
/// Out: the microphone, continuously, as 16 kHz PCM16 in 20 ms frames; telemetry every
/// 250 ms (gaze, seat, smile); webcam frames for the face tracker; and control messages
/// (start_date, end_date, focus, barge_in, user_text, playback_done).
///
/// In: the speaking character's voice as 24 kHz PCM16, written straight from the socket
/// thread into that NPC's <see cref="StreamingAudioPlayer"/>; and JSON events
/// (transcripts, chemistry, wingman hints, face analysis, signals) raised on the main
/// thread for the HUDs.
///
/// Barge-in is decided here, on the client: when the learner's voice holds above the
/// threshold for <see cref="bargeInMs"/> while a character is talking, every NPC buffer is
/// flushed at once (well under 100 ms) and the server is told. While a character talks
/// and the learner does not, the mic sends silence, so speakers bleeding into the mic are
/// not heard as the learner (headphones are still best).
/// </summary>
public class FullDuplexStreamClient : MonoBehaviour
{
    public static FullDuplexStreamClient Instance { get; private set; }

    [Header("Server")]
    [Tooltip("Base URL of the orchestrator. Empty = the one chosen in the matchmaker (DateSession).")]
    public string serverUrl = "";
    [Tooltip("Date to join; set by ScenarioClient from the matchmaker's result.")]
    public string scenarioId = "";
    public int timeoutSeconds = 75;
    [Tooltip("How the characters address the player. Empty = the matchmaker's name.")]
    public string learnerName = "";

    [Header("Microphone")]
    public bool micEnabled = true;
    [Tooltip("Microphone device name; empty = system default.")]
    public string micDevice = "";

    [Header("Voice activity")]
    [Tooltip("RMS level the learner's voice must exceed (0-1).")]
    public float vadThreshold = 0.02f;
    [Tooltip("Milliseconds of voice above threshold that count as speech (and as barge-in while a character talks).")]
    public float bargeInMs = 120f;
    [Tooltip("While a character talks, the learner must be this many times louder than the threshold.")]
    public float echoGuard = 2.0f;
    [Tooltip("Send silence instead of the mic while a character talks and the learner does not.")]
    public bool echoGate = true;

    [Header("Telemetry")]
    public float telemetryInterval = 0.25f;

    public const int MicRate = 16000;
    const int FrameSamples = MicRate / 50; // 20 ms

    public string RunId { get; private set; }
    public bool Connected { get; private set; }
    public bool Ready { get; private set; }
    public string LastError { get; private set; } = "";
    public Dictionary<string, object> Providers { get; private set; }
    public bool DateRunning { get; private set; }
    public bool DateOver { get; private set; }
    public string FocusNpc { get; private set; } = "date_npc";
    public bool UserSpeaking { get; private set; }
    public float MicLevel { get; private set; }
    public bool IsOnline => !string.IsNullOrEmpty(Base);

    /// <summary>Every JSON message from the server, by type, on the main thread.</summary>
    public event Action<string, Dictionary<string, object>> Message;
    public event Action<string, int> AudioStarted;   // npc id, turn id
    public event Action<string> AudioEnded;
    public event Action<string> AudioCleared;

    /// <summary>The scene's URL when set to something other than the default, else the matchmaker's.</summary>
    public string Base => (string.IsNullOrWhiteSpace(serverUrl) || serverUrl.TrimEnd('/') == DateSession.DefaultServer
        ? DateSession.ServerUrl : serverUrl).Trim().TrimEnd('/');

    readonly ConcurrentDictionary<string, StreamingAudioPlayer> players = new();
    readonly ConcurrentQueue<string> inbox = new();
    readonly ConcurrentQueue<(WebSocketMessageType kind, byte[] data)> outbox = new();
    readonly SemaphoreSlim outboxSignal = new(0);
    volatile StreamingAudioPlayer audioTarget;
    volatile string audioTargetId = "";
    ClientWebSocket socket;
    CancellationTokenSource cts;
    int reconnects;
    volatile bool wantConnection;
    volatile bool alive = true;

    // Microphone.
    AudioClip micClip;
    int micPosition;
    int micRate;
    float[] micChunk = new float[0];
    readonly List<float> micPending = new();
    float noiseFloor = 0.005f;
    float voicedMs, silentMs;
    bool bargedThisTurn;
    float nextTelemetry;

    void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(this);
            return;
        }
        Instance = this;
        RunId = DateSession.NewRunId();
        if (string.IsNullOrEmpty(learnerName))
            learnerName = DateSession.LearnerName;
    }

    void OnDestroy()
    {
        if (Instance == this)
            Instance = null;
        alive = false;
        wantConnection = false;
        Disconnect();
        if (micClip != null && Microphone.IsRecording(Device))
            Microphone.End(Device);
    }

    string Device => string.IsNullOrEmpty(micDevice) ? null : micDevice;

    // ---- NPC voices -----------------------------------------------------------------

    /// <summary>NPCs register the player their voice should stream into.</summary>
    public void Register(string npcId, StreamingAudioPlayer player)
    {
        if (string.IsNullOrEmpty(npcId) || player == null)
            return;
        players[npcId] = player;
        player.Drained += () => OnDrained(npcId);
    }

    public void Unregister(string npcId, StreamingAudioPlayer player)
    {
        if (players.TryGetValue(npcId, out var current) && current == player)
            players.TryRemove(npcId, out _);
    }

    /// <summary>A character's voice is still playing on this machine.</summary>
    public bool NpcSpeaking
    {
        get
        {
            foreach (var p in players.Values)
                if (p != null && p.IsPlaying)
                    return true;
            return false;
        }
    }

    public float NpcLevel
    {
        get
        {
            float max = 0f;
            foreach (var p in players.Values)
                if (p != null)
                    max = Mathf.Max(max, p.Level);
            return max;
        }
    }

    void FlushAll()
    {
        foreach (var p in players.Values)
            p?.Flush();
    }

    void OnDrained(string npcId)
    {
        AudioEnded?.Invoke(npcId);
        Send(new Dictionary<string, object> { ["type"] = "playback_done", ["npc_id"] = npcId });
    }

    // ---- connection -----------------------------------------------------------------

    /// <summary>Join the date: open the socket and send init. Safe to call again.</summary>
    public void Connect(string scenario)
    {
        scenarioId = scenario;
        wantConnection = true;
        // Resolved here, on the main thread: PlayerPrefs cannot be read from the socket thread.
        streamUrl = WsBase + "/v1/stream";
        if (socket == null && !running)
        {
            running = true;
            // The socket loops run on a worker thread: voice frames never wait for a frame.
            Task.Run(Run);
        }
    }

    volatile bool running;
    string streamUrl = "";
    volatile float dateStartedAt = -1f;
    volatile float lastFrameTime;

    async Task Run()
    {
        while (wantConnection && alive)
        {
            cts = new CancellationTokenSource();
            socket = new ClientWebSocket();
            socket.Options.KeepAliveInterval = TimeSpan.FromSeconds(15);
            try
            {
                await socket.ConnectAsync(new Uri(streamUrl), cts.Token);
                Connected = true;
                LastError = "";
                reconnects = 0;
                var init = new Dictionary<string, object>
                {
                    ["type"] = "init", ["run_id"] = RunId, ["scenario_id"] = scenarioId,
                    ["npc_id"] = FocusNpc,
                };
                if (DateRunning && dateStartedAt >= 0f)
                {
                    // Rejoining mid-date: carry on with the clock where it was, no second opener.
                    init["resume"] = true;
                    init["elapsed_sec"] = lastFrameTime - dateStartedAt;
                }
                Send(init);
                var sending = SendLoop(socket, cts.Token);
                await ReceiveLoop(socket, cts.Token);
                cts.Cancel();
                await Task.WhenAny(sending, Task.Delay(500));
            }
            catch (Exception e)
            {
                LastError = e is WebSocketException || e is OperationCanceledException
                    ? "server unreachable" : e.Message;
            }
            Connected = false;
            Ready = false;
            socket?.Dispose();
            socket = null;
            if (!wantConnection || DateOver || ++reconnects > 4)
                break;
            // The server keeps the run's chemistry; rejoining with the same run_id resumes it.
            await Task.Delay(TimeSpan.FromSeconds(Math.Min(8, 1 << reconnects)));
        }
        socket = null;
        running = false;
    }

    string WsBase => Base.StartsWith("https://") ? "wss://" + Base.Substring(8)
        : Base.StartsWith("http://") ? "ws://" + Base.Substring(7) : Base;

    void Disconnect()
    {
        try { cts?.Cancel(); } catch (ObjectDisposedException) { }
        try { socket?.Abort(); } catch (Exception) { }
    }

    async Task ReceiveLoop(ClientWebSocket ws, CancellationToken token)
    {
        var buffer = new byte[64 * 1024];
        var message = new MemoryStream();
        while (ws.State == WebSocketState.Open && !token.IsCancellationRequested)
        {
            var result = await ws.ReceiveAsync(new ArraySegment<byte>(buffer), token);
            if (result.MessageType == WebSocketMessageType.Close)
                return;
            if (result.MessageType == WebSocketMessageType.Binary)
            {
                // Voice: straight into the speaking character's ring buffer, off the main thread.
                if (result.EndOfMessage && message.Length == 0)
                    audioTarget?.Enqueue(buffer, 0, result.Count);
                else
                {
                    message.Write(buffer, 0, result.Count);
                    if (result.EndOfMessage)
                    {
                        audioTarget?.Enqueue(message.GetBuffer(), 0, (int)message.Length);
                        message.SetLength(0);
                    }
                }
                continue;
            }
            message.Write(buffer, 0, result.Count);
            if (!result.EndOfMessage)
                continue;
            string text = Encoding.UTF8.GetString(message.GetBuffer(), 0, (int)message.Length);
            message.SetLength(0);
            RouteAudio(text);
            inbox.Enqueue(text);
        }
    }

    /// <summary>
    /// Audio routing must happen on the socket thread, in order with the frames: an
    /// audio_start names who the next frames belong to, clear_audio silences them now.
    /// </summary>
    void RouteAudio(string text)
    {
        if (text.Contains("\"audio_start\""))
        {
            var msg = Json.Obj(text);
            string npc = msg.Str("npc_id");
            players.TryGetValue(npc, out var player);
            audioTargetId = npc;
            audioTarget = player;
            player?.BeginTurn();
        }
        else if (text.Contains("\"clear_audio\""))
        {
            var msg = Json.Obj(text);
            if (players.TryGetValue(msg.Str("npc_id"), out var player))
                player.Flush();
            audioTarget = null;
        }
        else if (text.Contains("\"audio_end\""))
        {
            var msg = Json.Obj(text);
            if (players.TryGetValue(msg.Str("npc_id"), out var player))
                player.EndTurn();
        }
    }

    async Task SendLoop(ClientWebSocket ws, CancellationToken token)
    {
        try
        {
            while (!token.IsCancellationRequested && ws.State == WebSocketState.Open)
            {
                await outboxSignal.WaitAsync(token);
                while (outbox.TryDequeue(out var item))
                    await ws.SendAsync(new ArraySegment<byte>(item.data), item.kind, true, token);
            }
        }
        catch (OperationCanceledException) { }
        catch (WebSocketException) { }
    }

    public void Send(Dictionary<string, object> message)
    {
        if (!Connected && (message.Str("type") != "init"))
            return;
        outbox.Enqueue((WebSocketMessageType.Text, Encoding.UTF8.GetBytes(Json.Write(message))));
        outboxSignal.Release();
    }

    void SendBinary(byte[] data)
    {
        if (!Ready)
            return;
        // Never let a stalled socket grow the queue without bound.
        if (outbox.Count > 400)
            return;
        outbox.Enqueue((WebSocketMessageType.Binary, data));
        outboxSignal.Release();
    }

    // ---- control --------------------------------------------------------------------

    public void StartDate()
    {
        if (DateRunning || DateOver)
            return;
        FocusNpc = "date_npc";
        Send(new Dictionary<string, object> { ["type"] = "start_date" });
    }

    public void EndDate(string reason)
    {
        if (!DateRunning)
            return;
        Send(new Dictionary<string, object> { ["type"] = "end_date", ["reason"] = reason });
    }

    public void Focus(string npcId)
    {
        if (string.IsNullOrEmpty(npcId) || DateRunning && npcId != "date_npc")
            return;
        FocusNpc = npcId;
        Send(new Dictionary<string, object> { ["type"] = "focus", ["npc_id"] = npcId });
    }

    public void SendUserText(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return;
        Send(new Dictionary<string, object> { ["type"] = "user_text", ["text"] = text.Trim() });
    }

    public void SendFaceFrame(byte[] jpeg)
    {
        if (!Ready || jpeg == null)
            return;
        Send(new Dictionary<string, object> { ["type"] = "face_frame", ["jpeg_base64"] = Convert.ToBase64String(jpeg) });
    }

    public void BargeIn()
    {
        FlushAll();
        audioTarget = null;
        Send(new Dictionary<string, object>
        {
            ["type"] = "barge_in", ["timestamp_ms"] = (long)(Time.realtimeSinceStartup * 1000f),
        });
        AudioCleared?.Invoke(audioTargetId);
    }

    /// <summary>POST /v1/grade for this run; exactly one callback is called.</summary>
    public IEnumerator Grade(Action<string> onJson, Action<string> onError)
    {
        string body = Json.Write(new Dictionary<string, object> { ["run_id"] = RunId, ["scenario_id"] = scenarioId });
        using var req = new UnityWebRequest($"{Base}/v1/grade", "POST")
        {
            uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(body)) { contentType = "application/json" },
            downloadHandler = new DownloadHandlerBuffer(),
            timeout = timeoutSeconds,
        };
        yield return req.SendWebRequest();
        if (req.result != UnityWebRequest.Result.Success)
            onError?.Invoke(Describe(req));
        else
            onJson?.Invoke(req.downloadHandler.text);
    }

    // ---- main thread ----------------------------------------------------------------

    void Update()
    {
        lastFrameTime = Time.unscaledTime;
        int handled = 0;
        while (handled++ < 64 && inbox.TryDequeue(out var text))
            Dispatch(text);
        if (Ready && micEnabled)
            PumpMicrophone();
        if (Ready && Time.unscaledTime >= nextTelemetry)
        {
            nextTelemetry = Time.unscaledTime + telemetryInterval;
            SendTelemetry();
        }
    }

    void Dispatch(string text)
    {
        var msg = Json.Obj(text);
        if (msg == null)
            return;
        string type = msg.Str("type");
        switch (type)
        {
            case "session_ready":
                Ready = true;
                Providers = msg.Get("providers");
                StartMicrophone();
                Debug.Log($"Stream: joined date {msg.Str("scenario_id")} as {RunId} ({Json.Write(Providers)})");
                break;
            case "date_started":
                DateRunning = true;
                dateStartedAt = Time.unscaledTime;
                break;
            case "date_ended":
                DateRunning = false;
                DateOver = true;
                break;
            case "audio_start":
                bargedThisTurn = false;
                AudioStarted?.Invoke(msg.Str("npc_id"), msg.Int("turn_id"));
                break;
            case "clear_audio":
                AudioCleared?.Invoke(msg.Str("npc_id"));
                break;
            case "error":
                LastError = msg.Str("detail");
                Debug.LogWarning($"Stream: {LastError}");
                if (msg.Bool("fatal"))
                    wantConnection = false;
                break;
            case "notice":
                Debug.Log($"Stream: {msg.Str("text")}");
                break;
        }
        Message?.Invoke(type, msg);
    }

    // ---- microphone, voice activity and barge-in ------------------------------------

    void StartMicrophone()
    {
        if (!micEnabled || micClip != null)
            return;
        if (Microphone.devices.Length == 0)
        {
            LastError = "no microphone; type to talk (Enter)";
            return;
        }
        Microphone.GetDeviceCaps(Device, out int minRate, out int maxRate);
        micRate = minRate == 0 && maxRate == 0 ? MicRate : Mathf.Clamp(MicRate, minRate, maxRate);
        micClip = Microphone.Start(Device, true, 10, micRate);
        micPosition = 0;
        Debug.Log($"Stream: microphone at {micRate} Hz");
    }

    void PumpMicrophone()
    {
        if (micClip == null)
            return;
        int position = Microphone.GetPosition(Device);
        if (position < 0 || position == micPosition)
            return;
        int available = position > micPosition ? position - micPosition : micClip.samples - micPosition + position;
        if (micChunk.Length < available)
            micChunk = new float[available];
        if (position > micPosition)
            ReadMic(micPosition, available, 0);
        else
        {
            int tail = micClip.samples - micPosition;
            ReadMic(micPosition, tail, 0);
            ReadMic(0, position, tail);
        }
        micPosition = position;

        // To 16 kHz, then 20 ms frames.
        if (micRate == MicRate)
            for (int i = 0; i < available; i++)
                micPending.Add(micChunk[i]);
        else
        {
            float step = micRate / (float)MicRate;
            int outCount = Mathf.FloorToInt(available / step);
            for (int i = 0; i < outCount; i++)
            {
                float src = i * step;
                int a = Mathf.Min((int)src, available - 1), b = Mathf.Min(a + 1, available - 1);
                micPending.Add(Mathf.Lerp(micChunk[a], micChunk[b], src - a));
            }
        }
        while (micPending.Count >= FrameSamples)
        {
            Frame(micPending, FrameSamples);
            micPending.RemoveRange(0, FrameSamples);
        }
    }

    void ReadMic(int offset, int count, int into)
    {
        if (count <= 0)
            return;
        var temp = new float[count];
        micClip.GetData(temp, offset);
        Array.Copy(temp, 0, micChunk, into, count);
    }

    void Frame(List<float> samples, int count)
    {
        float sum = 0f;
        for (int i = 0; i < count; i++)
            sum += samples[i] * samples[i];
        float rms = Mathf.Sqrt(sum / count);
        MicLevel = rms;

        bool npcTalking = NpcSpeaking;
        float threshold = Mathf.Max(vadThreshold, noiseFloor * 3f);
        if (npcTalking)
            threshold = Mathf.Max(threshold * echoGuard, NpcLevel * 0.6f);
        bool voiced = rms > threshold;
        if (!voiced && !UserSpeaking)
            noiseFloor = Mathf.Lerp(noiseFloor, rms, 0.02f);

        if (voiced)
        {
            voicedMs += 20f;
            silentMs = 0f;
            if (!UserSpeaking && voicedMs >= bargeInMs)
            {
                UserSpeaking = true;
                if (npcTalking && !bargedThisTurn && DateRunning)
                {
                    bargedThisTurn = true;
                    BargeIn();
                }
            }
        }
        else
        {
            silentMs += 20f;
            if (silentMs > 600f)
            {
                UserSpeaking = false;
                voicedMs = 0f;
            }
        }

        // The echo gate: while a character talks and the learner is not, send silence.
        bool gate = echoGate && npcTalking && !UserSpeaking && voicedMs < bargeInMs;
        var pcm = new byte[count * 2];
        if (!gate)
            for (int i = 0; i < count; i++)
            {
                short v = (short)Mathf.Clamp(samples[i] * 32767f, -32768f, 32767f);
                pcm[i * 2] = (byte)(v & 0xff);
                pcm[i * 2 + 1] = (byte)((v >> 8) & 0xff);
            }
        SendBinary(pcm);
    }

    void SendTelemetry()
    {
        var spatial = SpatialTelemetryBroadcaster.Instance;
        var message = spatial != null ? spatial.Snapshot() : new Dictionary<string, object>
        {
            ["is_looking_at_date"] = true, ["gaze_target"] = "unknown", ["look_away_duration_sec"] = 0f,
            ["distance_m"] = 0f, ["is_seated"] = false,
        };
        message["type"] = "telemetry";
        message["player_smiling"] = VisionFeed.Instance != null && VisionFeed.Instance.Smiling;
        Send(message);
    }

    /// <summary>Human-readable failure, unwrapping FastAPI's {"detail": ...}.</summary>
    public static string Describe(UnityWebRequest req)
    {
        string body = req.downloadHandler?.text;
        var parsed = Json.Obj(body ?? "");
        if (parsed != null && parsed.Has("detail"))
            body = parsed["detail"] as string ?? Json.Write(parsed["detail"]);
        if (string.IsNullOrEmpty(body))
            body = req.error ?? "unknown error";
        return req.responseCode == 0 ? $"server unreachable ({req.error})"
            : $"server {req.responseCode}: {(body.Length > 200 ? body.Substring(0, 200) + "…" : body)}";
    }
}
