using System.Collections.Generic;
using UnityEngine;
using UnityEngine.InputSystem;

/// <summary>
/// The date on screen, and its clock. Sitting down in the learner's chair rings the bell
/// and starts the date; the 3:00 countdown runs at the top; Q ends it early.
///
/// Drawn on glass: the chemistry meter (top right) easing to each update with its mood,
/// the reason it moved and a floating delta; the milestones (top left), ticked with the
/// learner's own words; live subtitles (bottom), coloured by speaker, the learner's line
/// filling in as they speak; and the wingman's earpiece card sliding in from the bottom
/// left with three ways to answer when the learner freezes. Enter opens a line to type
/// instead of speaking.
/// </summary>
public class ChemistryAndWingmanHUD : MonoBehaviour
{
    public static ChemistryAndWingmanHUD Instance { get; private set; }

    public Key endKey = Key.Q;
    public Key typeKey = Key.Enter;
    [Tooltip("Seat the learner must sit in to start the date; empty = any seat the player may take.")]
    public string playerSeat = "table_b";
    public float subtitleSeconds = 9f;

    public int Chemistry { get; private set; } = 50;
    public float SecondsLeft { get; private set; }
    public bool DateRunning => client != null && client.DateRunning;

    FullDuplexStreamClient client;
    PlayerSeating seating;
    DateScenario scenario;
    bool startRequested;
    bool endRequested;
    float dateStartedAt = -1f;
    int dateSeconds = 180;

    float shownChemistry = 50f;
    string mood = "Intriguing ✨";
    string reason = "";
    float reasonAt = -10f;
    int lastDelta;
    float deltaAt = -10f;
    readonly Dictionary<string, string> quotes = new();

    string npcLine = "", npcSpeaker = "", userLine = "";
    bool userFinal = true;
    float npcLineAt = -10f, userLineAt = -10f;

    Dictionary<string, object> hint;
    float hintAt = -10f;
    float hintSlide;

    bool typing;
    float typingSince;
    string typed = "";

    void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(this);
            return;
        }
        Instance = this;
    }

    void OnDestroy()
    {
        if (client != null)
            client.Message -= OnMessage;
        if (Instance == this)
            Instance = null;
    }

    void Start()
    {
        var fpc = FindFirstObjectByType<FirstPersonController>();
        seating = fpc != null ? fpc.GetComponent<PlayerSeating>() : null;
        if (ScenarioClient.Instance != null)
            ScenarioClient.Instance.Loaded += s => scenario = s;
        scenario = DateSession.Scenario;
    }

    void Bind()
    {
        if (client != null || FullDuplexStreamClient.Instance == null)
            return;
        client = FullDuplexStreamClient.Instance;
        client.Message += OnMessage;
    }

    void Update()
    {
        Bind();
        if (client == null)
            return;

        // Sit down in the learner's chair: the bell rings and the date begins.
        if (!startRequested && client.Ready && !client.DateRunning && !client.DateOver && SeatedAtTable())
        {
            startRequested = true;
            SpeedDateChime.Play(0.6f);
            client.StartDate();
        }

        if (client.DateRunning && dateStartedAt >= 0f)
        {
            SecondsLeft = Mathf.Max(0f, dateSeconds - (Time.time - dateStartedAt));
            if (SecondsLeft <= 0f && !endRequested)
                End("timer");
        }

        var kb = Keyboard.current;
        if (kb == null)
            return;
        if (!typing && client.DateRunning && kb[endKey].wasPressedThisFrame && Cursor.lockState == CursorLockMode.Locked)
            End("quit");
        if (!typing && kb[typeKey].wasPressedThisFrame && client.Ready && !client.DateOver)
        {
            typing = true;
            typingSince = Time.unscaledTime;
            typed = "";
        }

        // A spoken answer clears the wingman card.
        if (hint != null && client.UserSpeaking && Time.time - hintAt > 0.8f)
            hint = null;
    }

    bool SeatedAtTable()
    {
        if (seating == null || !seating.IsSeated)
            return false;
        return string.IsNullOrEmpty(playerSeat) || seating.Seat.id == playerSeat || seating.Seat.playerCanSit;
    }

    void End(string why)
    {
        if (endRequested)
            return;
        endRequested = true;
        SpeedDateChime.Play(0.9f);
        client.EndDate(why);
    }

    void OnMessage(string type, Dictionary<string, object> msg)
    {
        switch (type)
        {
            case "date_started":
                dateStartedAt = Time.time;
                dateSeconds = msg.Int("seconds", 180);
                SecondsLeft = dateSeconds;
                break;
            case "chemistry_update":
                int score = msg.Int("chemistry_score", Chemistry);
                lastDelta = msg.Int("delta");
                if (lastDelta != 0)
                    deltaAt = Time.time;
                Chemistry = score;
                mood = msg.Str("mood_label", mood);
                string why = msg.Str("reason");
                if (!string.IsNullOrEmpty(why) && why != "First impressions")
                {
                    reason = why;
                    reasonAt = Time.time;
                }
                var done = msg.List("completed_milestones");
                var evidence = msg.Get("evidence_quotes");
                if (done != null)
                    foreach (var id in done)
                        if (id is string s && !quotes.ContainsKey(s))
                        {
                            quotes[s] = evidence.Str(s);
                            QuestManager.Instance?.Complete(s);
                        }
                break;
            case "transcript":
                if (msg.Str("speaker") == "npc")
                {
                    npcLine = msg.Str("text");
                    npcSpeaker = msg.Str("npc_id") == "host"
                        ? (scenario?.host_character?.display_name ?? "Host")
                        : (scenario?.date_character?.display_name ?? "Your date");
                    npcLineAt = Time.time;
                }
                else
                {
                    userLine = msg.Str("text");
                    userFinal = msg.Bool("is_final");
                    userLineAt = Time.time;
                }
                break;
            case "wingman_hint":
                hint = msg;
                hintAt = Time.time;
                break;
            case "date_ended":
                hint = null;
                break;
        }
    }

    // ---- drawing --------------------------------------------------------------------

    void OnGUI()
    {
        if (client == null)
            return;
        GUI.depth = -100;
        var m = GlassUI.Begin();
        float W = GlassUI.Width, H = GlassUI.Height;

        if (!client.Connected || !client.Ready)
        {
            string text = !string.IsNullOrEmpty(client.LastError) ? client.LastError : "Joining your date…";
            float w = GlassUI.TextWidth(text, 14) + 40f;
            var r = new Rect((W - w) / 2f, 20f, w, 34f);
            GlassUI.Panel(r);
            GlassUI.Label(r, text, 14, Color.white, FontStyle.Normal, TextAnchor.MiddleCenter);
        }
        else if (client.DateRunning || client.DateOver)
            Timer(W);
        else
            Waiting(W);

        if (client.DateRunning || client.DateOver)
        {
            Meter(W);
            Milestones();
        }
        Subtitles(W, H);
        Wingman(H);
        TypeBox(W, H);
        GlassUI.End(m);
    }

    void Waiting(float W)
    {
        string name = scenario?.date_character?.display_name ?? "Your date";
        string text = SeatedAtTable() ? "Ringing the bell…" : $"{name} is waiting at the table · sit down (F) to start";
        float w = GlassUI.TextWidth(text, 15) + 48f;
        var r = new Rect((W - w) / 2f, 20f, w, 38f);
        GlassUI.Panel(r);
        GlassUI.Label(r, text, 15, Color.white, FontStyle.Normal, TextAnchor.MiddleCenter);
    }

    void Timer(float W)
    {
        int s = Mathf.CeilToInt(SecondsLeft);
        string text = client.DateOver ? "TIME" : $"{s / 60}:{s % 60:00}";
        Color ink = SecondsLeft < 10f && !client.DateOver ? Color.Lerp(Brand.Bad, Color.white, Mathf.PingPong(Time.time * 2f, 1f))
            : SecondsLeft < 30f ? Brand.Warn : Color.white;
        var r = new Rect((W - 150f) / 2f, 16f, 150f, 52f);
        GlassUI.Panel(r);
        GlassUI.Label(new Rect(r.x, r.y + 2f, r.width, 34f), text, 30, ink, FontStyle.Bold, TextAnchor.MiddleCenter);
        GlassUI.Label(new Rect(r.x, r.y + 33f, r.width, 16f), "SPEED DATE", 9, new Color(1f, 1f, 1f, 0.5f), FontStyle.Bold, TextAnchor.MiddleCenter);
    }

    void Meter(float W)
    {
        shownChemistry = GlassUI.Ease(shownChemistry, Chemistry, 4f);
        var r = new Rect(W - 320f, 16f, 300f, 104f);
        GlassUI.Panel(r);
        GlassUI.Label(new Rect(r.x + 16f, r.y + 10f, 150f, 18f), "CHEMISTRY", 11, new Color(1f, 1f, 1f, 0.6f), FontStyle.Bold);
        GlassUI.Label(new Rect(r.x + 16f, r.y + 6f, r.width - 32f, 28f), $"{shownChemistry:0}%", 22, Color.white, FontStyle.Bold, TextAnchor.MiddleRight);
        float v = shownChemistry / 100f;
        Color fill = v < 0.4f ? Color.Lerp(Brand.Bad, Brand.Warn, v / 0.4f)
            : v < 0.7f ? Color.Lerp(Brand.Warn, Brand.Good, (v - 0.4f) / 0.3f)
            : Color.Lerp(Brand.Good, Brand.Accent, (v - 0.7f) / 0.3f);
        GlassUI.Bar(new Rect(r.x + 16f, r.y + 38f, r.width - 32f, 12f), v, fill);
        // Ticks at the verdict lines: friendzone and match.
        foreach (float mark in new[] { 0.45f, 0.65f })
            GlassUI.Rounded(new Rect(r.x + 16f + (r.width - 32f) * mark - 1f, r.y + 35f, 2f, 18f), new Color(1f, 1f, 1f, 0.35f), 1);
        float mw = GlassUI.TextWidth(mood, 12, FontStyle.Bold) + 20f;
        GlassUI.Pill(new Rect(r.x + 16f, r.y + 58f, mw, 20f), new Color(fill.r, fill.g, fill.b, 0.35f), mood, Color.white, 12);
        float ra = Mathf.Clamp01(1.5f - (Time.time - reasonAt) / 6f);
        if (ra > 0f)
            GlassUI.Label(new Rect(r.x + 16f, r.y + 80f, r.width - 32f, 18f), reason, 11, new Color(1f, 1f, 1f, 0.75f * ra));
        float da = Time.time - deltaAt;
        if (da < 1.6f && lastDelta != 0)
        {
            string d = lastDelta > 0 ? $"+{lastDelta}" : lastDelta.ToString();
            GlassUI.Label(new Rect(r.x - 70f, r.y + 30f - da * 18f, 60f, 26f), d, 20,
                          new Color(lastDelta > 0 ? Brand.Good.r : Brand.Bad.r, lastDelta > 0 ? Brand.Good.g : Brand.Bad.g,
                                    lastDelta > 0 ? Brand.Good.b : Brand.Bad.b, 1f - da / 1.6f), FontStyle.Bold, TextAnchor.MiddleRight);
        }
    }

    void Milestones()
    {
        var list = QuestManager.Instance?.Quests?.quests;
        if (list == null || list.Length == 0)
            return;
        float h = 40f;
        foreach (var q in list)
            h += quotes.ContainsKey(q.id) && !string.IsNullOrEmpty(quotes[q.id]) ? 40f : 24f;
        var r = new Rect(20f, 16f, 300f, h);
        GlassUI.Panel(r, 0.9f);
        GlassUI.Label(new Rect(r.x + 16f, r.y + 10f, r.width, 18f), "MILESTONES", 11, new Color(1f, 1f, 1f, 0.6f), FontStyle.Bold);
        float y = r.y + 34f;
        foreach (var q in list)
        {
            bool done = q.IsDone;
            GlassUI.Rounded(new Rect(r.x + 16f, y + 4f, 14f, 14f), done ? Brand.Good : new Color(1f, 1f, 1f, 0.15f), 7);
            if (done)
                GlassUI.Label(new Rect(r.x + 16f, y + 3f, 14f, 16f), "✓", 11, Brand.Ink, FontStyle.Bold, TextAnchor.MiddleCenter);
            GlassUI.Label(new Rect(r.x + 38f, y, r.width - 50f, 22f), q.text, 12, done ? Brand.Good : Color.white);
            y += 22f;
            if (quotes.TryGetValue(q.id, out var quote) && !string.IsNullOrEmpty(quote))
            {
                GlassUI.Label(new Rect(r.x + 38f, y - 2f, r.width - 50f, 16f), $"<i>«{quote}»</i>", 10, new Color(1f, 1f, 1f, 0.6f));
                y += 18f;
            }
            else
                y += 2f;
        }
    }

    void Subtitles(float W, float H)
    {
        bool npcRecent = Time.time - npcLineAt < subtitleSeconds && !string.IsNullOrEmpty(npcLine);
        bool userRecent = Time.time - userLineAt < subtitleSeconds && !string.IsNullOrEmpty(userLine);
        if (!npcRecent && !userRecent)
            return;
        float w = Mathf.Min(560f, W - 700f + 260f);
        float textW = w - 32f;
        float h = 20f;
        string npc = npcRecent ? $"<b><color=#{ColorUtility.ToHtmlStringRGB(Brand.AccentSoft)}>{npcSpeaker}</color></b>  {npcLine}" : null;
        string you = userRecent ? $"<b><color=#{ColorUtility.ToHtmlStringRGB(Brand.Good)}>You</color></b>  {userLine}{(userFinal ? "" : " …")}" : null;
        if (npc != null) h += GlassUI.TextHeight(npc, 16, textW) + 4f;
        if (you != null) h += GlassUI.TextHeight(you, 14, textW) + 4f;
        var r = new Rect((W - w) / 2f, H - h - 24f, w, h);
        GlassUI.Panel(r, 0.9f);
        float y = r.y + 10f;
        if (npc != null)
        {
            float lh = GlassUI.TextHeight(npc, 16, textW);
            GlassUI.Label(new Rect(r.x + 16f, y, textW, lh), npc, 16, Color.white, FontStyle.Normal, TextAnchor.UpperLeft, true);
            y += lh + 4f;
        }
        if (you != null)
            GlassUI.Label(new Rect(r.x + 16f, y, textW, GlassUI.TextHeight(you, 14, textW)), you, 14,
                          new Color(1f, 1f, 1f, userFinal ? 0.9f : 0.65f), FontStyle.Normal, TextAnchor.UpperLeft, true);
    }

    void Wingman(float H)
    {
        bool show = hint != null && Time.time - hintAt < 18f;
        hintSlide = GlassUI.Ease(hintSlide, show ? 1f : 0f, 9f);
        if (hintSlide < 0.01f || hint == null)
            return;
        var options = hint.List("options");
        if (options == null)
            return;
        float w = 340f;
        float h = 64f + options.Count * 62f;
        float x = Mathf.Lerp(-w - 20f, 20f, Mathf.SmoothStep(0f, 1f, hintSlide));
        var r = new Rect(x, H - h - 24f, w, h);
        GlassUI.Panel(r, 0.95f, 16, new Color(0.08f, 0.09f, 0.14f));
        GlassUI.Label(new Rect(r.x + 16f, r.y + 10f, w - 32f, 18f), "🎧 WINGMAN", 11, Brand.AccentSoft, FontStyle.Bold);
        GlassUI.Label(new Rect(r.x + 16f, r.y + 28f, w - 32f, 30f), hint.Str("whisper_context"), 12, new Color(1f, 1f, 1f, 0.8f), FontStyle.Italic, TextAnchor.UpperLeft, true);
        float y = r.y + 62f;
        foreach (var o in options)
        {
            if (!(o is Dictionary<string, object> option))
                continue;
            var card = new Rect(r.x + 12f, y, w - 24f, 56f);
            GlassUI.Rounded(card, new Color(1f, 1f, 1f, 0.07f), 10);
            GlassUI.Label(new Rect(card.x + 10f, card.y + 4f, card.width - 20f, 14f), option.Str("tone"), 10, Brand.AccentSoft, FontStyle.Bold);
            GlassUI.Label(new Rect(card.x + 10f, card.y + 17f, card.width - 20f, 20f), option.Str("target"), 13, Color.white, FontStyle.Bold);
            GlassUI.Label(new Rect(card.x + 10f, card.y + 36f, card.width - 20f, 16f), option.Str("gloss"), 10, new Color(1f, 1f, 1f, 0.55f));
            y += 62f;
        }
    }

    void TypeBox(float W, float H)
    {
        if (!typing)
            return;
        var e = Event.current;
        // The Enter that opened the box must not also send it.
        if (e.type == EventType.KeyDown && (e.keyCode == KeyCode.Return || e.keyCode == KeyCode.KeypadEnter)
            && Time.unscaledTime - typingSince > 0.2f)
        {
            client.SendUserText(typed);
            typing = false;
            e.Use();
            return;
        }
        if (e.type == EventType.KeyDown && e.keyCode == KeyCode.Escape)
        {
            typing = false;
            e.Use();
            return;
        }
        var r = new Rect((W - 560f) / 2f, H - 210f, 560f, 52f);
        GlassUI.Panel(r);
        typed = GlassUI.Field(new Rect(r.x + 10f, r.y + 8f, r.width - 20f, 36f), typed, "Type what you'd say · Enter to send · Esc to cancel", 300, 15, "parry-type");
        GUI.FocusControl("parry-type");
    }
}
