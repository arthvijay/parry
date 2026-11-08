using System;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.SceneManagement;

/// <summary>
/// The end of the date. When the bell rings (the clock ran out, or Q), the server grades
/// everything said under this run and the verdict prints as a thermal-paper receipt out of
/// a little printer: the venue, the date and the dialect; the chemistry score with a
/// dotted bar and the curve of the whole date; four numbered pillars, each graded with the
/// learner's own words; the milestones met and the overall grade. Then a rubber stamp
/// slams down across it (¡HUBO MATCH!, FRIENDZONED or GHOSTED, in the dialect and in the
/// verdict's colour), and a text from the date slides in on a phone, with one correction
/// drawn from what the learner actually said. Tab flips to the learning page; R tries the
/// same date again; N goes back to the matchmaker for the next table.
/// </summary>
[RequireComponent(typeof(QuestManager))]
public class DateVerdictReceipt : MonoBehaviour
{
    public static DateVerdictReceipt Instance { get; private set; }

    public Key retryKey = Key.R;
    public Key nextKey = Key.N;
    public Key learnKey = Key.Tab;
    public Key reportKey = Key.L;
    public string frontScene = "Assets/Scenes/Wish.unity";

    /// <summary>True from the bell until a new date starts.</summary>
    public bool Ended { get; private set; }
    public bool Printed => Verdict != null || !string.IsNullOrEmpty(problem);
    public DateVerdict Verdict { get; private set; }
    public event Action Finished;

    string problem = "";
    float shownAt = -10f;
    FullDuplexStreamClient client;
    DateReport report;
    bool learning;
    bool reportRequested;
    string reportStatus = "";

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
        if (kb[learnKey].wasPressedThisFrame && Verdict != null)
            learning = !learning;
        if (kb[reportKey].wasPressedThisFrame && report != null)
            Application.OpenURL($"{client.Base}/v1/date/report/{client.RunId}.html");
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
        if (Verdict != null && !reportRequested)
        {
            reportRequested = true;
            StartCoroutine(FetchReport());
        }
        Finished?.Invoke();
    }

    /// <summary>"Your date, decoded": fetched while the learner reads the verdict.</summary>
    System.Collections.IEnumerator FetchReport()
    {
        reportStatus = "Writing your report…";
        string body = Json.Write(new System.Collections.Generic.Dictionary<string, object>
        {
            ["run_id"] = client.RunId, ["scenario_id"] = client.scenarioId,
        });
        using var req = new UnityEngine.Networking.UnityWebRequest($"{client.Base}/v1/date/report", "POST")
        {
            uploadHandler = new UnityEngine.Networking.UploadHandlerRaw(System.Text.Encoding.UTF8.GetBytes(body)) { contentType = "application/json" },
            downloadHandler = new UnityEngine.Networking.DownloadHandlerBuffer(),
            timeout = 120,
        };
        yield return req.SendWebRequest();
        if (req.result == UnityEngine.Networking.UnityWebRequest.Result.Success)
        {
            try { report = JsonUtility.FromJson<DateReport>(req.downloadHandler.text); }
            catch (Exception) { report = null; }
        }
        reportStatus = report != null ? "" : $"Report unavailable ({FullDuplexStreamClient.Describe(req)})";
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
            // The printer warms up while the server grades.
            var printer = PrinterRect(W);
            Printer(printer, true);
            string dots = new string('.', 1 + (int)(Time.unscaledTime * 2f) % 3);
            GlassUI.Label(new Rect(printer.x, printer.yMax + 16f, printer.width, 24f),
                          $"The bell rang. Printing your verdict{dots}", 16, Color.white, FontStyle.Normal, TextAnchor.MiddleCenter);
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

        string learnHint = report != null ? (learning ? "<b>Tab</b>  verdict      <b>L</b>  full report in browser      " : "<b>Tab</b>  learn from it      ")
            : string.IsNullOrEmpty(reportStatus) ? "" : reportStatus + "      ";
        string keys = learnHint + "<b>R</b>  try again with " + Verdict.date_name + "      <b>N</b>  next table";
        if (learning)
        {
            var card = new Rect((W - 780f) / 2f - 120f, 40f, 780f, H - 80f);
            GlassUI.Panel(card);
            Header(card);
            Learn(card);
            GlassUI.Label(new Rect(card.x + 24f, card.yMax - 36f, card.width - 48f, 24f), keys, 13, new Color(1f, 1f, 1f, 0.75f));
        }
        else
        {
            Receipt(W, H);
            GlassUI.Label(new Rect(0f, H - 34f, ReceiptAreaWidth(W), 24f), keys, 13, new Color(1f, 1f, 1f, 0.75f),
                          FontStyle.Normal, TextAnchor.MiddleCenter);
        }
        Phone(W, H);
        GlassUI.End(m);
    }

    // ---- the printed receipt --------------------------------------------------------

    const float PaperW = 420f, Pad = 26f;
    const float PrintStart = 0.2f, PrintSeconds = 2.4f, StampDelay = 0.4f;
    const float StampAt = PrintStart + PrintSeconds + StampDelay;
    const float PhoneAt = StampAt + 0.9f;
    bool stamped;

    static float ReceiptAreaWidth(float W) => W - 260f;   // left of the phone

    static Rect PrinterRect(float W)
    {
        float w = PaperW + 56f;
        return new Rect((ReceiptAreaWidth(W) - w) / 2f, 14f, w, 50f);
    }

    /// <summary>The little thermal printer the receipt comes out of.</summary>
    static void Printer(Rect r, bool busy)
    {
        GlassUI.Rounded(new Rect(r.x + 4f, r.y + 10f, r.width, r.height), new Color(0f, 0f, 0f, 0.4f), 16);
        GlassUI.Rounded(r, new Color(0.24f, 0.15f, 0.21f, 1f), 16);
        GlassUI.Rounded(new Rect(r.x + 2f, r.y + 2f, r.width - 4f, 14f), new Color(1f, 1f, 1f, 0.06f), 12);
        // The status light blinks while printing.
        float led = busy ? 0.35f + 0.65f * Mathf.PingPong(Time.unscaledTime * 3f, 1f) : 1f;
        var hud = new Color(0.49f, 0.96f, 0.89f);
        GlassUI.Dot(new Vector2(r.x + 26f, r.y + 20f), 16f, new Color(hud.r, hud.g, hud.b, 0.25f * led));
        GlassUI.Dot(new Vector2(r.x + 26f, r.y + 20f), 9f, new Color(hud.r, hud.g, hud.b, led));
        GlassUI.Label(new Rect(r.x + 40f, r.y + 10f, 200f, 20f), Brand.Name.ToUpperInvariant(), 10,
                      new Color(1f, 1f, 1f, 0.45f), FontStyle.Bold);
        // The slot.
        GlassUI.Rounded(new Rect(r.x + 24f, r.yMax - 16f, r.width - 48f, 9f), new Color(0.02f, 0f, 0.02f, 1f), 4);
    }

    void Receipt(float W, float H)
    {
        float t = Time.unscaledTime - shownAt;
        var printer = PrinterRect(W);
        float contentH = ReceiptBody(0f, false);
        float paperH = contentH + 8f;
        // Shrink a long receipt to fit between the printer and the key line.
        float scale = Mathf.Min(1f, (H - printer.yMax - 50f) / (paperH + 8f));
        // Printed line by line, like the deck's receipt: 48 steps.
        float p = Mathf.Floor(Mathf.Clamp01((t - PrintStart) / PrintSeconds) * 48f) / 48f;

        var m0 = GUI.matrix;
        float px = printer.center.x - PaperW * scale / 2f, py = printer.yMax - 12f;
        GUI.matrix = m0 * Matrix4x4.TRS(new Vector3(px, py, 0f), Quaternion.identity, new Vector3(scale, scale, 1f));
        float shown = paperH * p;
        float off = shown - paperH;
        GUI.BeginGroup(new Rect(0f, 0f, PaperW + 16f, shown + 20f));
        GlassUI.Rounded(new Rect(6f, off + 10f, PaperW, contentH), new Color(0f, 0f, 0f, 0.35f), 4);
        GlassUI.Rounded(new Rect(0f, off, PaperW, contentH), Brand.Paper, 2);
        // A torn, scalloped bottom edge.
        for (float x = 6f; x < PaperW; x += 12f)
            GlassUI.Dot(new Vector2(x, off + contentH), 12f, Brand.Paper);
        ReceiptBody(off, true);
        GUI.EndGroup();

        if (t >= StampAt)
        {
            if (!stamped)
            {
                stamped = true;
                SpeedDateChime.Play(0.35f);
            }
            Stamp(new Vector2(PaperW / 2f, contentH * 0.5f), t - StampAt);
        }
        GUI.matrix = m0;
        Printer(printer, p < 1f);
    }

    /// <summary>The paper's contents, top to bottom; measures (and draws when asked) at
    /// <paramref name="top"/> in paper space. Returns the height.</summary>
    float ReceiptBody(float top, bool draw)
    {
        var v = Verdict;
        Color ink = Brand.PaperInk;
        Color muted = Color.Lerp(Brand.PaperInk, Brand.Paper, 0.42f);
        Color vc = Brand.VerdictColor(v.verdict);
        float x = Pad, w = PaperW - 2f * Pad, y = top + 26f;

        void Line(string text, int size, Color c, FontStyle style = FontStyle.Normal,
                  TextAnchor anchor = TextAnchor.UpperLeft, float indent = 0f)
        {
            if (string.IsNullOrEmpty(text))
                return;
            float h = GlassUI.MonoHeight(text, size, w - indent, style);
            if (draw)
                GlassUI.MonoLabel(new Rect(x + indent, y, w - indent, h), text, size, c, style, anchor, true);
            y += h + 1f;
        }
        void Row(string left, string right, int size, int rightSize = 0)
        {
            float h = Mathf.Max(size, rightSize) + 10f;
            if (draw)
            {
                GlassUI.MonoLabel(new Rect(x, y, w - 60f, h), left, size, ink, FontStyle.Bold, TextAnchor.MiddleLeft);
                GlassUI.MonoLabel(new Rect(x, y, w, h), right, rightSize > 0 ? rightSize : size, ink, FontStyle.Bold, TextAnchor.MiddleRight);
            }
            y += h;
        }
        void Rule()
        {
            if (draw)
                for (float dx = 0f; dx < w; dx += 9f)
                    GlassUI.Rounded(new Rect(x + dx, y + 8f, 5f, 2f), new Color(muted.r, muted.g, muted.b, 0.6f), 1);
            y += 18f;
        }

        // Header.
        Line($"{Brand.Name.ToUpperInvariant()} · DATE VERDICT", 15, ink, FontStyle.Bold, TextAnchor.UpperCenter);
        y += 4f;
        Line($"{v.venue} · {v.city}", 11, muted, FontStyle.Normal, TextAnchor.UpperCenter);
        Line($"{v.dialect} · {v.date_name} ({v.persona})", 11, muted, FontStyle.Normal, TextAnchor.UpperCenter);
        string run = string.IsNullOrEmpty(v.run_id) ? "" : $" · #{v.run_id.Substring(Math.Max(0, v.run_id.Length - 6))}";
        Line($"{DateTime.Now:yyyy-MM-dd HH:mm}{run}", 10, muted, FontStyle.Normal, TextAnchor.UpperCenter);
        Rule();

        // Chemistry: the score, a dotted bar, and the curve of the whole date.
        Row("CHEMISTRY", $"{v.final_chemistry}%", 13, 30);
        if (draw)
        {
            float filled = w * Mathf.Clamp01(v.final_chemistry / 100f);
            for (float dx = 0f; dx + 6f <= filled; dx += 9f)
                GlassUI.Rounded(new Rect(x + dx, y + 2f, 6f, 10f), ink, 1);
            foreach (int mark in new[] { Brand.FriendzoneAt, Brand.MatchAt })
                GlassUI.Rounded(new Rect(x + w * mark / 100f - 1f, y - 1f, 2f, 16f), new Color(muted.r, muted.g, muted.b, 0.7f), 1);
        }
        y += 18f;
        var curve = v.chemistry_timeline;
        if (curve != null && curve.Length >= 2)
        {
            float gh = 30f;
            if (draw)
            {
                float my = y + gh * (1f - Brand.MatchAt / 100f);
                for (float dx = 0f; dx < w; dx += 7f)
                    GlassUI.Rounded(new Rect(x + dx, my, 3f, 1f), new Color(muted.r, muted.g, muted.b, 0.6f), 1);
                for (int i = 1; i < curve.Length; i++)
                {
                    Vector2 a = new(x + w * (i - 1) / (curve.Length - 1), y + gh * (1f - curve[i - 1] / 100f));
                    Vector2 b = new(x + w * i / (curve.Length - 1), y + gh * (1f - curve[i] / 100f));
                    GlassUI.Line(a, b, 2f, vc);
                }
            }
            y += gh + 6f;
        }
        Rule();

        // The four pillars, each with the learner's own words.
        var pillars = v.pillars ?? Array.Empty<Pillar>();
        for (int i = 0; i < pillars.Length; i++)
        {
            var p = pillars[i];
            Row($"{i + 1:00} {(p.label ?? p.id ?? "").ToUpperInvariant()}", string.IsNullOrEmpty(p.grade) ? "—" : p.grade, 12, 14);
            if (!string.IsNullOrEmpty(p.evidence_quote))
                Line($"“{p.evidence_quote}”", 12, ink, FontStyle.Italic, TextAnchor.UpperLeft, 28f);
            Line(p.comment, 10, muted, FontStyle.Normal, TextAnchor.UpperLeft, 28f);
            if (p.id == "agility_pacing")
                Line(PacingLine(v.metrics), 10, muted, FontStyle.Normal, TextAnchor.UpperLeft, 28f);
            y += 8f;
        }
        Rule();

        // Milestones and the overall grade.
        var ms = v.milestones ?? Array.Empty<MilestoneResult>();
        if (ms.Length > 0)
        {
            int met = 0;
            foreach (var mr in ms)
                if (mr.achieved)
                    met++;
            Row("MILESTONES", $"{met}/{ms.Length}", 12);
            foreach (var mr in ms)
                Line($"{(mr.achieved ? "[x]" : "[ ]")} {mr.text}", 10, mr.achieved ? ink : muted);
            y += 4f;
        }
        if (!string.IsNullOrEmpty(v.overall))
            Row("OVERALL", v.overall, 13, 16);
        Rule();

        // The verdict line, and a barcode for the look of it.
        Line(Brand.Verdict(v.verdict), 13, vc, FontStyle.Bold, TextAnchor.UpperCenter);
        y += 8f;
        if (draw)
        {
            int seed = (v.run_id ?? v.date_name ?? "parry").GetHashCode();
            var rng = new System.Random(seed);
            float bw = w * 0.72f, bx = x + (w - bw) / 2f, cx = 0f;
            while (cx < bw)
            {
                float thick = rng.Next(1, 4);
                GlassUI.Rounded(new Rect(bx + cx, y, thick, 30f), ink, 1);
                cx += thick + rng.Next(1, 4);
            }
        }
        y += 36f;
        Line("KEEP THIS RECEIPT · BEAT IT NEXT TIME", 9, muted, FontStyle.Normal, TextAnchor.UpperCenter);
        y += 18f;
        return y - top;
    }

    static string PacingLine(DateMetrics m)
    {
        if (m == null)
            return "";
        var parts = new System.Collections.Generic.List<string>();
        if (m.avg_response_latency_ms > 0)
            parts.Add($"{m.avg_response_latency_ms / 1000f:0.00} s avg latency");
        if (m.pronunciation_confidence_pct >= 0 && m.turns > 0)
            parts.Add($"{m.pronunciation_confidence_pct}% STT confidence");
        parts.Add(m.wingman_hints_used == 1 ? "1 wingman whisper" : $"{m.wingman_hints_used} wingman whispers");
        if (m.help_requests > 0)
            parts.Add(m.help_requests == 1 ? "1 translator peek" : $"{m.help_requests} translator peeks");
        if (m.eye_contact_pct >= 0)
            parts.Add($"{m.eye_contact_pct}% eye contact");
        return string.Join(" · ", parts);
    }

    /// <summary>The rubber stamp: slams down big, overshoots, settles at a tilt.</summary>
    void Stamp(Vector2 centre, float age)
    {
        var v = Verdict;
        Color c = Brand.VerdictColor(v.verdict);
        float scale = age < 0.35f ? Mathf.Lerp(2.6f, 0.94f, Mathf.SmoothStep(0f, 1f, age / 0.35f))
            : Mathf.Lerp(0.94f, 1f, Mathf.Clamp01((age - 0.35f) / 0.15f));
        float alpha = Mathf.Clamp01(age / 0.2f) * 0.92f;
        string big = string.IsNullOrEmpty(v.stamp) ? Brand.Verdict(v.verdict) : v.stamp;
        float w = Mathf.Max(240f, GlassUI.TextWidth(big, 38, FontStyle.Bold) + 56f), h = 92f;
        var box = new Rect(centre.x - w / 2f, centre.y - h / 2f, w, h);

        var matrix = GUI.matrix;
        Vector3 pivot = matrix.MultiplyPoint3x4(new Vector3(centre.x, centre.y, 0f));
        GUIUtility.RotateAroundPivot(-13f, new Vector2(pivot.x, pivot.y));
        GUIUtility.ScaleAroundPivot(new Vector2(scale, scale), new Vector2(pivot.x, pivot.y));
        Color ink = new(c.r, c.g, c.b, alpha);
        GlassUI.Rounded(box, new Color(c.r, c.g, c.b, 0.08f * alpha), 12);
        // A double border, like an ink stamp.
        void Frame(Rect r, float t)
        {
            GlassUI.Rounded(new Rect(r.x, r.y, r.width, t), ink, 1);
            GlassUI.Rounded(new Rect(r.x, r.yMax - t, r.width, t), ink, 1);
            GlassUI.Rounded(new Rect(r.x, r.y, t, r.height), ink, 1);
            GlassUI.Rounded(new Rect(r.xMax - t, r.y, t, r.height), ink, 1);
        }
        Frame(box, 5f);
        Frame(new Rect(box.x + 9f, box.y + 9f, box.width - 18f, box.height - 18f), 2f);
        GlassUI.Label(new Rect(box.x, box.y + 12f, box.width, 46f), big, 38, ink, FontStyle.Bold, TextAnchor.MiddleCenter);
        if (!string.IsNullOrEmpty(v.stamp_en) && v.stamp_en != big)
            GlassUI.Label(new Rect(box.x, box.y + 58f, box.width, 18f), v.stamp_en.ToUpperInvariant(), 12, ink, FontStyle.Bold, TextAnchor.MiddleCenter);
        GUI.matrix = matrix;
    }

    void Header(Rect c)
    {
        var v = Verdict;
        GlassUI.Label(new Rect(c.x + 24f, c.y + 18f, c.width - 48f, 16f),
                      $"{v.venue?.ToUpperInvariant()} · {v.city?.ToUpperInvariant()}", 11, new Color(1f, 1f, 1f, 0.55f), FontStyle.Bold);
        GlassUI.Label(new Rect(c.x + 24f, c.y + 36f, c.width - 48f, 32f), $"{v.date_name}", 26, Color.white, FontStyle.Bold);
        GlassUI.Label(new Rect(c.x + 24f, c.y + 68f, c.width - 48f, 18f), $"{v.persona} · {v.dialect}", 13, Brand.AccentSoft);
    }

    void Phone(float W, float H)
    {
        var f = Verdict.followup;
        if (f == null || string.IsNullOrEmpty(f.text))
            return;
        float t = Mathf.Clamp01((Time.unscaledTime - shownAt - (learning ? 0f : PhoneAt)) / 0.6f);
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

    /// <summary>The learning page: what landed, what to say differently, what to keep.</summary>
    void Learn(Rect c)
    {
        float x = c.x + 24f, w = c.width - 48f, y = c.y + 96f;
        float Block(string title, float at)
        {
            GlassUI.Label(new Rect(x, at, w, 16f), title, 10, new Color(1f, 1f, 1f, 0.5f), FontStyle.Bold);
            return at + 18f;
        }
        float Text(string text, float at, int size, Color color, FontStyle style = FontStyle.Normal)
        {
            float h = GlassUI.TextHeight(text ?? "", size, w, style);
            GlassUI.Label(new Rect(x, at, w, h), text, size, color, style, TextAnchor.UpperLeft, true);
            return at + h + 4f;
        }
        y = Text(report.summary, y, 13, Color.white);
        if (report.went_well != null && !string.IsNullOrEmpty(report.went_well.quote))
        {
            y = Block("THIS LANDED", y + 6f);
            y = Text($"«{report.went_well.quote}»  <color=#{ColorUtility.ToHtmlStringRGB(Brand.AccentSoft)}>{report.went_well.note}</color>", y, 12, Color.white);
        }
        if (report.fixes != null && report.fixes.Length > 0)
        {
            y = Block("NEXT TIME, SAY IT LIKE THIS", y + 6f);
            foreach (var f in report.fixes)
                y = Text($"<color=#999999><s>{f.heard}</s></color>  →  <b><color=#{ColorUtility.ToHtmlStringRGB(Brand.Good)}>{f.better}</color></b>   <size=10>{f.why_en}</size>", y, 12, Color.white);
        }
        if (report.useful_phrases != null && report.useful_phrases.Length > 0)
        {
            y = Block("PHRASES TO KEEP IN YOUR POCKET", y + 6f);
            foreach (var p in report.useful_phrases)
                y = Text($"<b>{p.target}</b>  <color=#aaaaaa>{p.gloss} · {p.when}</color>", y, 12, Color.white);
        }
        if (report.culture_notes != null && report.culture_notes.Length > 0)
        {
            y = Block("HOW THEY REALLY TALK", y + 6f);
            foreach (var n in report.culture_notes)
            {
                if (y > c.yMax - 90f)
                    break;
                y = Text($"<b>{n.title}</b>  <color=#bbbbbb>{n.note}</color>", y, 11, Color.white);
            }
        }
        if (report.practice_words != null && report.practice_words.Length > 0 && y < c.yMax - 70f)
        {
            y = Block("PRACTISE SAYING", y + 6f);
            Text(string.Join("   ·   ", report.practice_words), y, 12, Brand.AccentSoft, FontStyle.Bold);
        }
    }
}
