using UnityEngine;
using UnityEngine.InputSystem;

/// <summary>
/// The computer vision, on screen: the webcam image (mirrored, like a selfie) with the
/// face mesh MediaPipe found drawn over it, the expression levels the date is reading,
/// the head pose, eye contact during the date, and a live feed of the signals that went
/// to the date with what each one did. Lives in a corner of every scene; H collapses it.
/// </summary>
public class VisionPanel : MonoBehaviour
{
    public enum Corner { BottomRight, BottomLeft, TopRight, Right }

    public Corner corner = Corner.BottomRight;
    [Tooltip("Width of the panel in design pixels (1280×720 canvas).")]
    public float width = 280f;
    public Key toggleKey = Key.H;
    public bool collapsed;

    static readonly (string label, string[] shapes)[] Bars =
    {
        ("Smile", new[] { "mouthSmileLeft", "mouthSmileRight" }),
        ("Jaw open", new[] { "jawOpen" }),
        ("Brows up", new[] { "browInnerUp" }),
        ("Brows down", new[] { "browDownLeft", "browDownRight" }),
        ("Frown", new[] { "mouthFrownLeft", "mouthFrownRight" }),
        ("Blink", new[] { "eyeBlinkLeft", "eyeBlinkRight" }),
    };
    static readonly string[] Outlines = { "oval", "lips", "inner_lips", "left_eye", "right_eye", "left_brow", "right_brow", "nose" };

    readonly float[] shown = new float[Bars.Length];

    void Update()
    {
        var kb = Keyboard.current;
        if (kb != null && kb[toggleKey].wasPressedThisFrame)
            collapsed = !collapsed;
    }

    void OnGUI()
    {
        var feed = VisionFeed.Instance;
        if (feed == null || (DateVerdictReceipt.Instance != null && DateVerdictReceipt.Instance.Printed))
            return;
        GUI.depth = -150;
        var m = GlassUI.Begin();
        float W = GlassUI.Width, H = GlassUI.Height;
        float camH = width * 0.75f;
        float h = collapsed ? 36f : 40f + camH + 12f + Bars.Length * 17f + 44f + 112f;
        float x = corner == Corner.BottomLeft ? 20f : W - width - 20f;
        float y = corner switch
        {
            Corner.TopRight => 130f,
            Corner.Right => (H - h) / 2f,
            _ => H - h - 20f,
        };
        var panel = new Rect(x, y, width, h);
        GlassUI.Panel(panel, 0.95f);

        // Header: what is running, and how fast.
        bool live = feed.Running && feed.TrackerAvailable && Time.unscaledTime - feed.LastReadingAt < 1.5f;
        GlassUI.Dot(new Vector2(x + 18f, y + 18f), 9f, live ? Brand.Good : feed.Running ? Brand.Warn : Brand.Bad);
        GlassUI.Label(new Rect(x + 30f, y + 6f, width - 40f, 24f), "<b>VISION</b>  MediaPipe Face Landmarker", 12, Color.white);
        string speed = live ? $"{feed.ReadingsPerSecond:0} fps · {feed.AnalysisMs:0} ms" : feed.Running ? "waiting…" : "camera off";
        GlassUI.Label(new Rect(x + 12f, y + 6f, width - 24f, 24f), speed, 11, new Color(1f, 1f, 1f, 0.55f), FontStyle.Normal, TextAnchor.MiddleRight);
        if (collapsed)
        {
            GlassUI.End(m);
            return;
        }

        // The camera, mirrored, with the mesh over it.
        var cam = new Rect(x + 12f, y + 36f, width - 24f, camH);
        GlassUI.Rounded(cam, new Color(0f, 0f, 0f, 0.6f), 10);
        if (feed.Running)
        {
            GUI.DrawTextureWithTexCoords(cam, feed.Camera, feed.Camera.videoVerticallyMirrored
                ? new Rect(1f, 1f, -1f, -1f) : new Rect(1f, 0f, -1f, 1f));
            if (live && feed.HasFace)
                DrawMesh(cam, feed);
            else if (live)
                GlassUI.Label(cam, "No face in view", 14, new Color(1f, 1f, 1f, 0.8f), FontStyle.Bold, TextAnchor.MiddleCenter);
        }
        else
        {
            string why = string.IsNullOrEmpty(feed.Error) ? "Starting camera…" : feed.Error;
            GlassUI.Label(cam, why, 13, new Color(1f, 1f, 1f, 0.7f), FontStyle.Normal, TextAnchor.MiddleCenter, true);
        }
        if (!feed.TrackerAvailable)
            GlassUI.Pill(new Rect(cam.x + 8f, cam.yMax - 26f, cam.width - 16f, 20f), new Color(0.6f, 0.2f, 0.2f, 0.85f), "tracker offline · uv sync --group face", Color.white, 11);

        // Expression levels.
        float by = cam.yMax + 12f;
        for (int i = 0; i < Bars.Length; i++)
        {
            float v = 0f;
            foreach (var s in Bars[i].shapes)
                v += feed.Shape(s);
            v /= Bars[i].shapes.Length;
            shown[i] = GlassUI.Ease(shown[i], live ? v : 0f, 14f);
            GlassUI.Label(new Rect(x + 14f, by, 80f, 14f), Bars[i].label, 11, new Color(1f, 1f, 1f, 0.75f));
            GlassUI.Bar(new Rect(x + 92f, by + 3f, width - 150f, 8f), shown[i], i == 0 ? Brand.Accent : Brand.AccentSoft);
            GlassUI.Label(new Rect(x + width - 52f, by, 40f, 14f), $"{shown[i] * 100f:0}", 11, new Color(1f, 1f, 1f, 0.6f), FontStyle.Normal, TextAnchor.MiddleRight);
            by += 17f;
        }

        // Head pose and eye contact.
        by += 4f;
        HeadGauge(new Rect(x + 14f, by, 36f, 36f), feed.HeadYaw, feed.HeadPitch, live && feed.HasFace);
        GlassUI.Label(new Rect(x + 58f, by, width - 70f, 18f),
                      $"Yaw {feed.HeadYaw:+0;-0}°  Pitch {feed.HeadPitch:+0;-0}°  Roll {feed.HeadRoll:+0;-0}°", 11, Color.white);
        var spatial = SpatialTelemetryBroadcaster.Instance;
        string contact = spatial == null ? (feed.Smiling ? "Smiling 😊" : "Neutral")
            : spatial.LookingAtDate ? "Eye contact ✓" : $"Looking away {spatial.LookAwaySeconds:0.0}s";
        Color contactColor = spatial == null || spatial.LookingAtDate ? Brand.Good : spatial.LookAwaySeconds > 3f ? Brand.Bad : Brand.Warn;
        GlassUI.Label(new Rect(x + 58f, by + 18f, width - 70f, 18f), contact, 12, contactColor, FontStyle.Bold);
        by += 44f;

        // What went to the date.
        GlassUI.Label(new Rect(x + 14f, by, width - 28f, 16f), "→ YOUR DATE SEES", 10, new Color(1f, 1f, 1f, 0.5f), FontStyle.Bold);
        by += 18f;
        int shownSignals = 0;
        foreach (var s in feed.Signals)
        {
            float age = Time.unscaledTime - s.time;
            if (age > 12f || shownSignals >= 4)
                break;
            float a = Mathf.Clamp01(1.4f - age / 10f);
            GlassUI.Label(new Rect(x + 14f, by, width - 28f, 16f), s.label, 12, new Color(1f, 1f, 1f, a), FontStyle.Bold);
            if (!string.IsNullOrEmpty(s.effect))
                GlassUI.Label(new Rect(x + 14f, by + 13f, width - 28f, 14f), s.effect, 10, new Color(Brand.AccentSoft.r, Brand.AccentSoft.g, Brand.AccentSoft.b, a * 0.9f));
            by += 23f;
            shownSignals++;
        }
        if (shownSignals == 0)
            GlassUI.Label(new Rect(x + 14f, by, width - 28f, 16f), live ? "Smile, nod, look puzzled…" : "—", 11, new Color(1f, 1f, 1f, 0.4f));

        GlassUI.End(m);
    }

    /// <summary>The mesh scatter, the feature outlines and the irises, mirrored like the image.</summary>
    static void DrawMesh(Rect cam, VisionFeed feed)
    {
        Vector2 P(Vector2 p) => new(cam.x + (1f - p.x) * cam.width, cam.y + p.y * cam.height);
        var dotColor = new Color(Brand.Accent.r, Brand.Accent.g, Brand.Accent.b, 0.55f);
        foreach (var p in feed.Mesh)
            GlassUI.Dot(P(p), 2.2f, dotColor);
        var lineColor = new Color(1f, 1f, 1f, 0.75f);
        foreach (var name in Outlines)
        {
            if (!feed.Contours.TryGetValue(name, out var pts))
                continue;
            for (int i = 1; i < pts.Length; i++)
                GlassUI.Line(P(pts[i - 1]), P(pts[i]), 1.2f, lineColor);
        }
        foreach (var iris in new[] { "left_iris", "right_iris" })
            if (feed.Contours.TryGetValue(iris, out var pts) && pts.Length > 0)
            {
                Vector2 c = Vector2.zero;
                foreach (var p in pts)
                    c += P(p);
                GlassUI.Dot(c / pts.Length, 5f, Brand.Good);
            }
    }

    static void HeadGauge(Rect r, float yaw, float pitch, bool live)
    {
        GlassUI.Rounded(r, new Color(1f, 1f, 1f, 0.1f), Mathf.RoundToInt(r.width / 2f));
        var centre = r.center;
        var dot = centre + new Vector2(Mathf.Clamp(-yaw / 45f, -1f, 1f), Mathf.Clamp(-pitch / 35f, -1f, 1f)) * (r.width * 0.4f);
        GlassUI.Line(centre, dot, 1.5f, new Color(1f, 1f, 1f, 0.5f));
        GlassUI.Dot(dot, 8f, live ? Brand.Accent : new Color(1f, 1f, 1f, 0.3f));
    }
}
