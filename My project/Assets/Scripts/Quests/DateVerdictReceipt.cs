using System;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.SceneManagement;

/// <summary>
/// The end of the date. When the bell rings (the clock ran out, or Q), the server grades
/// everything said under this run and the verdict card comes up: the venue and the date,
/// the stamp (a MATCH, FRIENDZONED or GHOSTED, in the dialect and in English) with the
/// chemistry curve of the whole date, four graded pillars each with the learner's own
/// words, the measured pacing, and a text from the date sliding in on a phone, with one
/// correction drawn from what the learner actually said. R tries the same date again;
/// N goes back to the matchmaker for the next table.
/// </summary>
[RequireComponent(typeof(QuestManager))]
public class DateVerdictReceipt : MonoBehaviour
{
    public static DateVerdictReceipt Instance { get; private set; }

    public Key retryKey = Key.R;
    public Key nextKey = Key.N;
    public string frontScene = "Assets/Scenes/Wish.unity";

    /// <summary>True from the bell until a new date starts.</summary>
    public bool Ended { get; private set; }
    public bool Printed => Verdict != null || !string.IsNullOrEmpty(problem);
    public DateVerdict Verdict { get; private set; }
    public event Action Finished;

    string problem = "";
    float shownAt = -10f;
    FullDuplexStreamClient client;

    void Awake()
    {
        Instance = this;
    }

    void OnDestroy()
    {
        if (client != null)
            client.Message -= OnMessage;
        if (Instance == this)
            Instance = null;
    }

    void Update()
    {
        if (client == null && FullDuplexStreamClient.Instance != null)
        {
            client = FullDuplexStreamClient.Instance;
            client.Message += OnMessage;
        }
        var kb = Keyboard.current;
        if (kb == null || !Printed)
            return;
        if (kb[retryKey].wasPressedThisFrame)
            Load(SceneManager.GetActiveScene().path);
        else if (kb[nextKey].wasPressedThisFrame)
            Load(frontScene);
    }

    void OnMessage(string type, System.Collections.Generic.Dictionary<string, object> msg)
    {
        if (type != "date_ended" || Ended)
            return;
        Ended = true;
        StartCoroutine(client.Grade(
            json =>
            {
                try { Verdict = JsonUtility.FromJson<DateVerdict>(json); }
                catch (Exception e) { problem = $"The verdict was unreadable ({e.Message})."; }
                if (Verdict == null || string.IsNullOrEmpty(Verdict.verdict))
                {
                    Verdict = null;
                    problem = string.IsNullOrEmpty(problem) ? "The verdict was empty." : problem;
                }
                Show();
            },
            error =>
            {
                problem = $"Couldn't get the verdict ({error}).";
                Show();
            }));
    }

    void Show()
    {
        shownAt = Time.unscaledTime;
        Cursor.lockState = CursorLockMode.None;
        Cursor.visible = true;
        var player = FindFirstObjectByType<FirstPersonController>();
        if (player != null)
            player.enabled = false;
        if (Verdict != null)
            Debug.Log($"DateVerdictReceipt: {Verdict.verdict} at {Verdict.final_chemistry}, overall {Verdict.overall} ({Verdict.graded_by})");
        Finished?.Invoke();
    }

    void Load(string scenePath)
    {
        Cursor.lockState = CursorLockMode.Locked;
        Cursor.visible = false;
#if UNITY_EDITOR
        if (SceneUtility.GetBuildIndexByScenePath(scenePath) < 0)
        {
            UnityEditor.SceneManagement.EditorSceneManager.LoadSceneInPlayMode(scenePath, new LoadSceneParameters(LoadSceneMode.Single));
            return;
        }
#endif
        SceneManager.LoadScene(scenePath);
    }

    // ---- drawing --------------------------------------------------------------------

    void OnGUI()
    {
        if (!Ended)
            return;
        GUI.depth = -300;
        var m = GlassUI.Begin();
        float W = GlassUI.Width, H = GlassUI.Height;
        GlassUI.Rounded(new Rect(-10f, -10f, W + 20f, H + 20f), new Color(0f, 0f, 0f, Printed ? 0.55f : 0.25f), 2);

        if (!Printed)
        {
            var r = new Rect((W - 340f) / 2f, H / 2f - 30f, 340f, 60f);
            GlassUI.Panel(r);
            string dots = new string('.', 1 + (int)(Time.unscaledTime * 2f) % 3);
            GlassUI.Label(r, $"The bell rang. The verdict is coming{dots}", 16, Color.white, FontStyle.Normal, TextAnchor.MiddleCenter);
            GlassUI.End(m);
            return;
        }
        if (Verdict == null)
        {
            var r = new Rect((W - 520f) / 2f, H / 2f - 60f, 520f, 120f);
            GlassUI.Panel(r);
            GlassUI.Label(new Rect(r.x + 20f, r.y + 14f, r.width - 40f, 60f), problem, 15, Color.white, FontStyle.Normal, TextAnchor.UpperLeft, true);
            GlassUI.Label(new Rect(r.x + 20f, r.y + 80f, r.width - 40f, 24f), "R  try again    ·    N  next table", 13, new Color(1f, 1f, 1f, 0.6f));
            GlassUI.End(m);
            return;
        }

        float appear = Mathf.SmoothStep(0f, 1f, Mathf.Clamp01((Time.unscaledTime - shownAt) / 0.5f));
        var card = new Rect((W - 780f) / 2f - 120f, 40f + (1f - appear) * 30f, 780f, H - 80f);
        GlassUI.Panel(card, appear);
        Header(card);
        Stamp(card);
        Pillars(card);
        Metrics(card);
        Phone(W, H);
        GlassUI.Label(new Rect(card.x + 24f, card.yMax - 36f, card.width - 48f, 24f),
                      "<b>R</b>  try again with " + Verdict.date_name + "      <b>N</b>  next table / new speed date",
                      13, new Color(1f, 1f, 1f, 0.75f));
        GlassUI.End(m);
    }

    void Header(Rect c)
    {
        var v = Verdict;
        GlassUI.Label(new Rect(c.x + 24f, c.y + 18f, c.width - 48f, 16f),
                      $"{v.venue?.ToUpperInvariant()} · {v.city?.ToUpperInvariant()}", 11, new Color(1f, 1f, 1f, 0.55f), FontStyle.Bold);
        GlassUI.Label(new Rect(c.x + 24f, c.y + 36f, c.width - 48f, 32f), $"{v.date_name}", 26, Color.white, FontStyle.Bold);
        GlassUI.Label(new Rect(c.x + 24f, c.y + 68f, c.width - 48f, 18f), $"{v.persona} · {v.dialect}", 13, Brand.AccentSoft);
    }

    void Stamp(Rect c)
    {
        var v = Verdict;
        Color ink = v.verdict == "match" ? Brand.Accent : v.verdict == "friendzone" ? Brand.Warn : Brand.Bad;
        var box = new Rect(c.xMax - 310f, c.y + 18f, 280f, 86f);
        var matrix = GUI.matrix;
        Vector3 pivot = matrix.MultiplyPoint3x4(new Vector3(box.center.x, box.center.y, 0f));
        GUIUtility.RotateAroundPivot(-7f, new Vector2(pivot.x, pivot.y));
        GlassUI.Rounded(new Rect(box.x - 3f, box.y - 3f, box.width + 6f, box.height + 6f), new Color(ink.r, ink.g, ink.b, 0.9f), 10);
        GlassUI.Rounded(box, new Color(0.06f, 0.06f, 0.09f, 0.95f), 8);
        GlassUI.Label(new Rect(box.x, box.y + 8f, box.width, 36f), v.stamp, 24, ink, FontStyle.Bold, TextAnchor.MiddleCenter);
        string icon = v.verdict == "match" ? " 💚" : v.verdict == "friendzone" ? " 🤝" : " 💔";
        GlassUI.Label(new Rect(box.x, box.y + 44f, box.width, 20f), v.stamp_en + icon, 13, Color.white, FontStyle.Bold, TextAnchor.MiddleCenter);
        GlassUI.Label(new Rect(box.x, box.y + 64f, box.width, 16f), $"chemistry {v.final_chemistry}% · overall {v.overall}", 11, new Color(1f, 1f, 1f, 0.6f), FontStyle.Normal, TextAnchor.MiddleCenter);
        GUI.matrix = matrix;

        // The chemistry curve of the whole date.
        var t = v.chemistry_timeline;
        if (t == null || t.Length < 2)
            return;
        var graph = new Rect(c.x + 24f, c.y + 98f, c.width - 360f, 34f);
        GlassUI.Rounded(new Rect(graph.x, graph.y + graph.height * (1f - 0.65f), graph.width, 1f), new Color(1f, 1f, 1f, 0.25f), 1);
        for (int i = 1; i < t.Length; i++)
        {
            Vector2 a = new(graph.x + graph.width * (i - 1) / (t.Length - 1), graph.yMax - graph.height * t[i - 1] / 100f);
            Vector2 b = new(graph.x + graph.width * i / (t.Length - 1), graph.yMax - graph.height * t[i] / 100f);
            GlassUI.Line(a, b, 2f, ink);
        }
    }

    void Pillars(Rect c)
    {
        float y = c.y + 146f;
        float w = c.width - 48f;
        foreach (var p in Verdict.pillars ?? Array.Empty<Pillar>())
        {
            string grade = string.IsNullOrEmpty(p.grade) ? "—" : p.grade;
            Color g = GradeColor(p.grade);
            GlassUI.Pill(new Rect(c.x + 24f, y + 2f, 46f, 26f), new Color(g.r, g.g, g.b, 0.85f), grade, Brand.Ink, 15);
            GlassUI.Label(new Rect(c.x + 82f, y, w - 70f, 18f), p.label, 14, Color.white, FontStyle.Bold);
            float ch = GlassUI.TextHeight(p.comment ?? "", 12, w - 70f);
            GlassUI.Label(new Rect(c.x + 82f, y + 18f, w - 70f, ch), p.comment, 12, new Color(1f, 1f, 1f, 0.8f), FontStyle.Normal, TextAnchor.UpperLeft, true);
            y += 20f + ch;
            if (!string.IsNullOrEmpty(p.evidence_quote))
            {
                GlassUI.Label(new Rect(c.x + 82f, y, w - 70f, 16f), $"<i>«{p.evidence_quote}»</i>", 12, Brand.AccentSoft);
                y += 18f;
            }
            y += 10f;
        }
    }

    void Metrics(Rect c)
    {
        var m = Verdict.metrics;
        if (m == null)
            return;
        string Latency() => m.avg_response_latency_ms > 0 ? $"{m.avg_response_latency_ms / 1000f:0.0} s" : "—";
        string Pct(int v) => v >= 0 && m.turns > 0 ? $"{v}%" : "—";
        var items = new (string label, string value)[]
        {
            ("Response time", Latency()),
            ("Pronunciation", Pct(m.pronunciation_confidence_pct)),
            ("Wingman hints", $"{m.wingman_hints_used}"),
            ("Unassisted", Pct(m.unassisted_fluency_pct)),
            ("Eye contact", Pct(m.eye_contact_pct)),
        };
        float y = c.yMax - 104f;
        float w = (c.width - 48f) / items.Length;
        for (int i = 0; i < items.Length; i++)
        {
            var r = new Rect(c.x + 24f + i * w, y, w - 8f, 56f);
            GlassUI.Rounded(r, new Color(1f, 1f, 1f, 0.07f), 10);
            GlassUI.Label(new Rect(r.x, r.y + 6f, r.width, 24f), items[i].value, 18, Color.white, FontStyle.Bold, TextAnchor.MiddleCenter);
            GlassUI.Label(new Rect(r.x, r.y + 32f, r.width, 16f), items[i].label, 10, new Color(1f, 1f, 1f, 0.55f), FontStyle.Normal, TextAnchor.MiddleCenter);
        }
    }

    void Phone(float W, float H)
    {
        var f = Verdict.followup;
        if (f == null || string.IsNullOrEmpty(f.text))
            return;
        float t = Mathf.Clamp01((Time.unscaledTime - shownAt - 1.4f) / 0.6f);
        if (t <= 0f)
            return;
        float slide = Mathf.SmoothStep(0f, 1f, t);
        var phone = new Rect(W - 250f + (1f - slide) * 280f, 60f, 230f, 440f);
        GlassUI.Rounded(phone, new Color(0.02f, 0.02f, 0.03f, 0.95f), 28);
        var screen = new Rect(phone.x + 8f, phone.y + 8f, phone.width - 16f, phone.height - 16f);
        GlassUI.Rounded(screen, new Color(0.11f, 0.12f, 0.16f, 1f), 22);
        GlassUI.Rounded(new Rect(phone.center.x - 30f, phone.y + 14f, 60f, 8f), new Color(0f, 0f, 0f, 0.9f), 4);
        GlassUI.Label(new Rect(screen.x, screen.y + 20f, screen.width, 16f), DateTime.Now.ToString("HH:mm"), 11, new Color(1f, 1f, 1f, 0.6f), FontStyle.Bold, TextAnchor.MiddleCenter);

        float bw = screen.width - 20f;
        GlassUI.Label(new Rect(screen.x + 10f, screen.y + 48f, bw, 16f), f.sender, 12, Color.white, FontStyle.Bold);
        float th = GlassUI.TextHeight(f.text, 13, bw - 20f);
        var bubble = new Rect(screen.x + 10f, screen.y + 68f, bw, th + 16f);
        GlassUI.Rounded(bubble, new Color(0.19f, 0.6f, 0.36f, 1f), 14);
        GlassUI.Label(new Rect(bubble.x + 10f, bubble.y + 8f, bw - 20f, th), f.text, 13, Color.white, FontStyle.Normal, TextAnchor.UpperLeft, true);
        float y = bubble.yMax + 6f;
        float trh = GlassUI.TextHeight(f.translation_en ?? "", 10, bw);
        GlassUI.Label(new Rect(screen.x + 10f, y, bw, trh), f.translation_en, 10, new Color(1f, 1f, 1f, 0.5f), FontStyle.Italic, TextAnchor.UpperLeft, true);
        y += trh + 14f;

        var fix = f.correction;
        if (fix != null && !string.IsNullOrEmpty(fix.heard))
        {
            string body = $"<b>You said</b> «{fix.heard}»\n<b>Try</b> «{fix.better}»\n{fix.why_en}";
            float ch = GlassUI.TextHeight(body, 11, bw - 20f);
            var tip = new Rect(screen.x + 10f, y, bw, ch + 30f);
            GlassUI.Rounded(tip, new Color(1f, 1f, 1f, 0.08f), 12);
            GlassUI.Label(new Rect(tip.x + 10f, tip.y + 6f, bw - 20f, 14f), "💡 ONE THING TO FIX", 9, Brand.Warn, FontStyle.Bold);
            GlassUI.Label(new Rect(tip.x + 10f, tip.y + 22f, bw - 20f, ch), body, 11, Color.white, FontStyle.Normal, TextAnchor.UpperLeft, true);
        }
    }

    static Color GradeColor(string grade)
    {
        if (string.IsNullOrEmpty(grade))
            return new Color(1f, 1f, 1f, 0.4f);
        return grade[0] switch
        {
            'A' => Brand.Good,
            'B' => Color.Lerp(Brand.Good, Brand.Warn, 0.4f),
            'C' => Brand.Warn,
            _ => Brand.Bad,
        };
    }
}
