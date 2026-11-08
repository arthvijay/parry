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

/// <summary>
/// The webcam and what the orchestrator reads from it. One instance lives across scenes:
/// it opens the camera, sends small JPEG frames (~8 per second, 320 px wide) to the face
/// tracker, and keeps the latest reading: ARKit blendshapes, head pitch/yaw/roll, the face
/// mesh contours, and a feed of signals (smiling, nodding, puzzled…) with what the date
/// does with each. During the date the frames ride the date's own stream, so the date
/// sees the face; before that (the onboarding studio) they go to <c>/v1/vision</c>.
/// </summary>
public class VisionFeed : MonoBehaviour
{
    public static VisionFeed Instance { get; private set; }

    [Header("Camera")]
    public int requestWidth = 640;
    public int requestHeight = 480;
    public int requestFps = 30;

    [Header("Frames to the face tracker")]
    public float framesPerSecond = 8f;
    public int frameWidth = 320;
    [Range(30, 95)] public int jpegQuality = 70;

    public WebCamTexture Camera { get; private set; }
    public bool Running => Camera != null && Camera.isPlaying && Camera.width > 16;
    public string Error { get; private set; } = "";
    public bool TrackerAvailable { get; private set; } = true;

    // The latest reading.
    public bool HasFace { get; private set; }
    public float HeadYaw { get; private set; }
    public float HeadPitch { get; private set; }
    public float HeadRoll { get; private set; }
    public bool Smiling { get; private set; }
    public float AnalysisMs { get; private set; }
    public float LastReadingAt { get; private set; } = -10f;
    public readonly Dictionary<string, float> Blendshapes = new();
    public readonly Dictionary<string, Vector2[]> Contours = new();
    public Vector2[] Mesh { get; private set; } = Array.Empty<Vector2>();
    public float ReadingsPerSecond { get; private set; }

    public struct SignalEntry
    {
        public string kind, label, effect;
        public float time;
    }

    /// <summary>Newest first; the panel shows a few.</summary>
    public readonly List<SignalEntry> Signals = new();
    public event Action Analysed;
    public event Action<SignalEntry> SignalSeen;

    RenderTexture frameRT;
    Texture2D frameTex;
    float nextFrame;
    int readingsThisSecond;
    float secondStarted;
    FullDuplexStreamClient boundClient;

    // The onboarding socket (/v1/vision).
    ClientWebSocket socket;
    CancellationTokenSource cts;
    readonly ConcurrentQueue<string> inbox = new();
    readonly ConcurrentQueue<byte[]> outbox = new();
    readonly SemaphoreSlim outboxSignal = new(0);
    volatile bool socketOpen, socketRunning, alive = true;

    public static VisionFeed Ensure()
    {
        if (Instance != null)
            return Instance;
        var go = new GameObject("Vision Feed");
        DontDestroyOnLoad(go);
        return go.AddComponent<VisionFeed>();
    }

    void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }
        Instance = this;
    }

    void OnDestroy()
    {
        if (Instance == this)
            Instance = null;
        alive = false;
        try { cts?.Cancel(); } catch (ObjectDisposedException) { }
        try { socket?.Abort(); } catch (Exception) { }
        if (Camera != null)
            Camera.Stop();
        if (frameRT != null)
            frameRT.Release();
    }

    // ---- camera -----------------------------------------------------------------

    public void StartCamera() => StartCoroutine(OpenCamera());

    bool opening;

    IEnumerator OpenCamera()
    {
        if (Running || opening)
            yield break;
        opening = true;
        if (!Application.HasUserAuthorization(UserAuthorization.WebCam))
            yield return Application.RequestUserAuthorization(UserAuthorization.WebCam);
        var devices = WebCamTexture.devices;
        if (devices.Length == 0)
        {
            Error = "No webcam found";
            opening = false;
            yield break;
        }
        string device = devices[0].name;
        foreach (var d in devices)
            if (d.isFrontFacing)
                device = d.name;
        Camera = new WebCamTexture(device, requestWidth, requestHeight, requestFps);
        Camera.Play();
        float giveUp = Time.unscaledTime + 5f;
        while (Camera.width <= 16 && Time.unscaledTime < giveUp)
            yield return null;
        Error = Running ? "" : "Webcam did not start (is another app using it?)";
        if (Running)
            Debug.Log($"VisionFeed: webcam '{device}' {Camera.width}×{Camera.height}");
        opening = false;
    }

    /// <summary>A JPEG of the current frame at full camera resolution, for the selfie.</summary>
    public byte[] CaptureJpeg(int width = 0, int quality = 90)
    {
        if (!Running)
            return null;
        int w = width > 0 ? width : Camera.width;
        int h = Mathf.RoundToInt(w * Camera.height / (float)Camera.width);
        var rt = RenderTexture.GetTemporary(w, h, 0);
        var tex = new Texture2D(w, h, TextureFormat.RGB24, false);
        Blit(rt);
        var previous = RenderTexture.active;
        RenderTexture.active = rt;
        tex.ReadPixels(new Rect(0, 0, w, h), 0, 0);
        tex.Apply();
        RenderTexture.active = previous;
        RenderTexture.ReleaseTemporary(rt);
        var jpeg = tex.EncodeToJPG(quality);
        Destroy(tex);
        return jpeg;
    }

    /// <summary>The camera image upright (vertically corrected), unmirrored, into <paramref name="target"/>.</summary>
    void Blit(RenderTexture target)
    {
        if (Camera.videoVerticallyMirrored)
            Graphics.Blit(Camera, target, new Vector2(1f, -1f), new Vector2(0f, 1f));
        else
            Graphics.Blit(Camera, target);
    }

    byte[] Frame()
    {
        int w = frameWidth;
        int h = Mathf.RoundToInt(w * Camera.height / (float)Camera.width);
        if (frameRT == null || frameRT.width != w || frameRT.height != h)
        {
            if (frameRT != null)
                frameRT.Release();
            frameRT = new RenderTexture(w, h, 0);
            frameTex = new Texture2D(w, h, TextureFormat.RGB24, false);
        }
        Blit(frameRT);
        var previous = RenderTexture.active;
        RenderTexture.active = frameRT;
        frameTex.ReadPixels(new Rect(0, 0, w, h), 0, 0);
        frameTex.Apply(false);
        RenderTexture.active = previous;
        return frameTex.EncodeToJPG(jpegQuality);
    }

    // ---- frames out, readings in -------------------------------------------------

    void Update()
    {
        BindClient();
        while (inbox.TryDequeue(out var text))
        {
            var msg = Json.Obj(text);
            if (msg != null)
                Handle(msg.Str("type"), msg);
        }
        if (Time.unscaledTime - secondStarted >= 1f)
        {
            ReadingsPerSecond = readingsThisSecond / (Time.unscaledTime - secondStarted);
            readingsThisSecond = 0;
            secondStarted = Time.unscaledTime;
        }
        if (!Running || Time.unscaledTime < nextFrame)
            return;
        nextFrame = Time.unscaledTime + 1f / Mathf.Max(1f, framesPerSecond);

        var client = FullDuplexStreamClient.Instance;
        if (client != null && client.Ready)
        {
            client.SendFaceFrame(Frame());
            return;
        }
        // No date yet: the studio's own socket.
        if (!socketRunning)
        {
            socketRunning = true;
            Task.Run(VisionSocket);
        }
        if (socketOpen && outbox.Count < 4)
        {
            string json = Json.Write(new Dictionary<string, object>
            {
                ["type"] = "face_frame", ["jpeg_base64"] = Convert.ToBase64String(Frame()),
            });
            outbox.Enqueue(Encoding.UTF8.GetBytes(json));
            outboxSignal.Release();
        }
    }

    void BindClient()
    {
        var client = FullDuplexStreamClient.Instance;
        if (client == boundClient)
            return;
        if (boundClient != null)
            boundClient.Message -= Handle;
        boundClient = client;
        if (client != null)
            client.Message += Handle;
    }

    void Handle(string type, Dictionary<string, object> msg)
    {
        if (type == "face_analysis")
            Read(msg);
        else if (type == "signal")
            Remember(msg.Str("kind"), msg.Str("label"), msg.Str("effect"));
        else if (type == "vision_ready")
        {
            TrackerAvailable = msg.Bool("available", true);
            if (!TrackerAvailable)
                Error = "Face tracker offline: " + msg.Str("reason");
        }
    }

    void Read(Dictionary<string, object> msg)
    {
        if (msg.Has("unavailable"))
        {
            TrackerAvailable = false;
            Error = "Face tracker offline: " + msg.Str("unavailable");
            return;
        }
        TrackerAvailable = true;
        HasFace = msg.Bool("found");
        LastReadingAt = Time.unscaledTime;
        readingsThisSecond++;
        AnalysisMs = msg.F("analysis_ms");
        var head = msg.Get("head");
        HeadPitch = head.F("pitch");
        HeadYaw = head.F("yaw");
        HeadRoll = head.F("roll");
        Smiling = msg.Get("expressions").Bool("smiling");

        Blendshapes.Clear();
        var shapes = msg.Get("blendshapes");
        if (shapes != null)
            foreach (var pair in shapes)
                if (pair.Value is double d)
                    Blendshapes[pair.Key] = (float)d;

        Contours.Clear();
        var contours = msg.Get("contours");
        if (contours != null)
            foreach (var pair in contours)
                Contours[pair.Key] = Points(pair.Value as List<object>);
        Mesh = Points(msg.List("mesh"));
        Analysed?.Invoke();
    }

    static Vector2[] Points(List<object> list)
    {
        if (list == null)
            return Array.Empty<Vector2>();
        var points = new Vector2[list.Count];
        for (int i = 0; i < list.Count; i++)
            if (list[i] is List<object> p && p.Count >= 2 && p[0] is double x && p[1] is double y)
                points[i] = new Vector2((float)x, (float)y);
        return points;
    }

    void Remember(string kind, string label, string effect)
    {
        var entry = new SignalEntry { kind = kind, label = label, effect = effect, time = Time.unscaledTime };
        Signals.Insert(0, entry);
        if (Signals.Count > 12)
            Signals.RemoveAt(Signals.Count - 1);
        SignalSeen?.Invoke(entry);
    }

    public float Shape(string name) => Blendshapes.TryGetValue(name, out var v) ? v : 0f;

    // ---- the onboarding socket ---------------------------------------------------

    async Task VisionSocket()
    {
        while (alive)
        {
            // Plain reference checks: Unity's overloaded null test is main-thread only.
            var client = FullDuplexStreamClient.Instance;
            if ((object)client != null && client.Ready)
                break;
            cts = new CancellationTokenSource();
            socket = new ClientWebSocket();
            try
            {
                await socket.ConnectAsync(new Uri(DateSession.WebSocketBase + "/v1/vision"), cts.Token);
                socketOpen = true;
                var sending = Task.Run(async () =>
                {
                    try
                    {
                        while (socket.State == WebSocketState.Open)
                        {
                            await outboxSignal.WaitAsync(cts.Token);
                            while (outbox.TryDequeue(out var data))
                                await socket.SendAsync(new ArraySegment<byte>(data), WebSocketMessageType.Text, true, cts.Token);
                        }
                    }
                    catch (Exception) { }
                });
                var buffer = new byte[64 * 1024];
                var message = new MemoryStream();
                while (socket.State == WebSocketState.Open && alive)
                {
                    var result = await socket.ReceiveAsync(new ArraySegment<byte>(buffer), cts.Token);
                    if (result.MessageType == WebSocketMessageType.Close)
                        break;
                    message.Write(buffer, 0, result.Count);
                    if (!result.EndOfMessage)
                        continue;
                    inbox.Enqueue(Encoding.UTF8.GetString(message.GetBuffer(), 0, (int)message.Length));
                    message.SetLength(0);
                    // Once the date's stream is up, frames go there; this socket can close.
                    var stream = FullDuplexStreamClient.Instance;
                    if ((object)stream != null && stream.Ready)
                        break;
                }
                cts.Cancel();
                await Task.WhenAny(sending, Task.Delay(300));
            }
            catch (Exception)
            {
                Error = "Face tracker unreachable (is the orchestrator running?)";
            }
            socketOpen = false;
            try { socket.Dispose(); } catch (Exception) { }
            await Task.Delay(2000);
        }
        socketRunning = false;
    }
}
