using System.Collections.Generic;
using UnityEngine;
using UnityEngine.InputSystem;

/// <summary>
/// The date on screen, and its clock. Sitting down in the learner's chair rings the bell
/// and starts the date; the 3:00 countdown runs at the top; Q ends it early.
///
/// Drawn on glass: the live match bar across the top (the clock, then a GHOSTED /
/// FRIENDZONED / MATCH track whose needle eases to each chemistry update, the score in the
/// zone's colour, the mood, the reason it moved, a floating +/- delta, the best reading so
/// far, and a banner when the date crosses into a new zone); the milestones (top left), ticked with the
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
    public Key helpKey = Key.T;
    [Tooltip("Asks the wingman for three ways to answer (seated, during the date: W does not walk then).")]
    public Key wingmanKey = Key.W;
    public Key menuKey = Key.M;
    [Tooltip("Seat the learner must sit in to start the date; empty = any seat the player may take.")]
    public string playerSeat = "table_b";
    public float subtitleSeconds = 9f;
    [Tooltip("Seconds the translator and wingman cards stay up, even while the learner talks.")]
    public float cardSeconds = 12f;

    public int Chemistry { get; private set; } = 50;
    public float SecondsLeft { get; private set; }
    public bool DateRunning => client != null && client.DateRunning;

    /// <summary>True when game keys may act: no line is being typed. (The Input System itself
    /// only delivers the keyboard while the game window has focus.)</summary>
    public static bool KeysFree => Instance == null || !Instance.typing;

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
    int peak = 50;
    string zone = "friendzone";
    string zoneToast;
    bool zoneRising;
    float zoneAt = -10f;
    readonly Dictionary<string, string> quotes = new();

    string npcLine = "", npcSpeaker = "", userLine = "";
    bool userFinal = true;
    float npcLineAt = -10f, userLineAt = -10f;

    Dictionary<string, object> hint;
    float hintAt = -10f;
    float wingmanAskedAt = -10f;
    float hintSlide;

    bool typing;
    float typingSince;
    string typed = "";

    Dictionary<string, object> helpCard;
    float helpAt = -10f, helpSlide;
    bool helpPending;
    bool menuOpen;
    float menuSlide;
    List<string> served;
    float servedAt = -10f;
    NpcSchedule hostSchedule;
    float orderSentAt = -1f;
    bool hostArrived;

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
        if (!typing && client.DateRunning && kb[endKey].wasPressedThisFrame)
            End("quit");
        if (!typing && kb[helpKey].wasPressedThisFrame && client.DateRunning && !helpPending)
        {
            helpPending = true;
            helpAt = Time.time;
            client.Send(new Dictionary<string, object> { ["type"] = "help" });
        }
        if (!typing && kb[wingmanKey].wasPressedThisFrame && client.DateRunning && SeatedAtTable()
            && Time.time - wingmanAskedAt > 2f)
        {
            wingmanAskedAt = Time.time;
            client.Send(new Dictionary<string, object> { ["type"] = "wingman" });
        }
        if (!typing && kb[menuKey].wasPressedThisFrame && (scenario?.menu?.Length ?? 0) > 0)
            menuOpen = !menuOpen;
        // The cards stay up while the learner reads them out; they go after cardSeconds.
        if (helpCard != null && !helpPending && Time.time - helpAt > cardSeconds && !client.UserSpeaking)
            helpCard = null;
        // The host was sent with the order; if the walk is blocked, serve anyway.
        if (orderSentAt > 0f && !hostArrived && Time.time - orderSentAt > 12f)
            HostAtTable();
        if (!typing && kb[typeKey].wasPressedThisFrame && client.Ready && !client.DateOver)
        {
            typing = true;
            typingSince = Time.unscaledTime;
            typed = "";
        }

        // A spoken answer clears the wingman card.
        if (hint != null && Time.time - hintAt > cardSeconds && !client.UserSpeaking)
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
                peak = Mathf.Max(peak, score);
                string now = Brand.Zone(score);
                if (now != zone)
                {
                    zoneRising = ZoneRank(now) > ZoneRank(zone);
                    zone = now;
                    zoneToast = now;
                    zoneAt = Time.time;
                }
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
            case "help_card":
                helpCard = msg;
                helpAt = Time.time;
                helpPending = false;
                break;
            case "scene_action":
                if (msg.Str("action") == "order_placed")
                    SendHost(msg);
                break;
            case "date_ended":
                hint = null;
                break;
        }
    }

    // ---- the café ---------------------------------------------------------------------

    /// <summary>The order is in: the host walks over (NpcSchedule "action" move) and serves on arrival.</summary>
    void SendHost(Dictionary<string, object> msg)
    {
        served = new List<string>();
        foreach (var item in msg.List("items") ?? new List<object>())
            if (item is string s)
                served.Add(s);
        servedAt = Time.time;
        orderSentAt = Time.time;
        hostArrived = false;
        var host = NpcManager.Instance != null ? NpcManager.Instance.Find("host") : null;
        if (host == null)
            return;
        hostSchedule = host.GetComponent<NpcSchedule>();
        if (hostSchedule != null)
        {
            hostSchedule.MoveFinished -= OnHostMoved;
            hostSchedule.MoveFinished += OnHostMoved;
        }
        var talk = host.GetComponent<NpcConversation>();
        if (talk != null)
            talk.RaiseAction("order_placed");
    }

    void OnHostMoved(string move)
    {
        if (move == "bring_order")
            HostAtTable();
    }

    void HostAtTable()
    {
        if (hostArrived)
            return;
        hostArrived = true;
        client.Send(new Dictionary<string, object> { ["type"] = "scene_event", ["event"] = "host_at_table" });
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
        else if (!client.DateRunning && !client.DateOver)
            Waiting(W);

        if (client.DateRunning || client.DateOver)
        {
            MatchBar(W);
            ZoneBanner(W);
            Milestones();
        }
        Subtitles(W, H);
        Wingman(H);
        Help(W, H);
        Menu(H);
        Legend(W);
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

    // ---- the live match bar --------------------------------------------------------

    const float BarTop = 16f, BarHeight = 80f;

    static int ZoneRank(string z) => z == "match" ? 2 : z == "friendzone" ? 1 : 0;

    static string ZoneTitle(string z) => z == "match" ? "MATCH ZONE" : z == "friendzone" ? "FRIEND ZONE" : "GHOST ZONE";

    static Color Alpha(Color c, float a) => new(c.r, c.g, c.b, a);

    /// <summary>
    /// The match bar across the top of the screen: the clock, then the chemistry track in
    /// its three verdict zones with a glowing needle, the score in the zone's colour, the
    /// mood and the reason it last moved. Every update pulses the bar and floats the delta.
    /// </summary>
    void MatchBar(float W)
    {
        shownChemistry = GlassUI.Ease(shownChemistry, Chemistry, 3f);
        // Right of the milestones panel, to the right edge.
        var bar = new Rect(340f, BarTop, W - 360f, BarHeight);
        string z = Brand.Zone(shownChemistry);
        Color zc = Brand.VerdictColor(z);

        float pulse = Mathf.Clamp01(1f - (Time.time - deltaAt) / 1.2f);
        if (pulse > 0f && lastDelta != 0)
        {
            Color pc = lastDelta > 0 ? Brand.Match : Brand.Ghosted;
            GlassUI.Rounded(new Rect(bar.x - 5f, bar.y - 5f, bar.width + 10f, bar.height + 10f), Alpha(pc, 0.4f * pulse), 21);
        }
        GlassUI.Panel(bar, 0.95f);

        // The clock.
        var clock = new Rect(bar.x + 10f, bar.y + 10f, 104f, bar.height - 20f);
        GlassUI.Rounded(clock, new Color(1f, 1f, 1f, 0.06f), 12);
        int s = Mathf.CeilToInt(SecondsLeft);
        string time = client.DateOver ? "TIME" : $"{s / 60}:{s % 60:00}";
        Color ink = SecondsLeft < 10f && !client.DateOver ? Color.Lerp(Brand.Bad, Color.white, Mathf.PingPong(Time.time * 2f, 1f))
            : SecondsLeft < 30f && !client.DateOver ? Brand.Warn : Color.white;
        GlassUI.Label(new Rect(clock.x, clock.y + 4f, clock.width, 36f), time, 30, ink, FontStyle.Bold, TextAnchor.MiddleCenter);
        GlassUI.Label(new Rect(clock.x, clock.y + 40f, clock.width, 14f), "SPEED DATE", 9, new Color(1f, 1f, 1f, 0.5f), FontStyle.Bold, TextAnchor.MiddleCenter);

        // The label and the mood.
        float lx = clock.xMax + 16f;
        GlassUI.Label(new Rect(lx, bar.y + 12f, 130f, 16f), "CHEMISTRY", 11, new Color(1f, 1f, 1f, 0.55f), FontStyle.Bold);
        float mw = Mathf.Min(130f, GlassUI.TextWidth(mood, 11, FontStyle.Bold) + 18f);
        GlassUI.Pill(new Rect(lx, bar.y + 32f, mw, 20f), Alpha(zc, 0.3f), mood, Color.white, 11);

        // The score, in the zone's colour.
        var value = new Rect(bar.xMax - 136f, bar.y + 8f, 122f, 44f);
        GlassUI.Label(value, $"{shownChemistry:0}%", 36, zc, FontStyle.Bold, TextAnchor.MiddleRight);
        GlassUI.Label(new Rect(value.x, value.yMax, value.width, 14f), ZoneTitle(z), 9, Alpha(zc, 0.85f), FontStyle.Bold, TextAnchor.MiddleRight);

        // The track: GHOSTED below 45, FRIENDZONED to 65, MATCH above.
        float tx = lx + 146f, tw = Mathf.Max(80f, value.x - 18f - tx);
        var track = new Rect(tx, bar.y + 20f, tw, 12f);
        var zones = new (string id, int from, int to, string label, TextAnchor anchor)[]
        {
            ("ghosted", 0, Brand.FriendzoneAt, "GHOSTED", TextAnchor.MiddleLeft),
            ("friendzone", Brand.FriendzoneAt, Brand.MatchAt, "FRIENDZONED", TextAnchor.MiddleCenter),
            ("match", Brand.MatchAt, 100, "MATCH", TextAnchor.MiddleRight),
        };
        foreach (var zn in zones)
        {
            float a = track.x + tw * zn.from / 100f + (zn.from > 0 ? 1.5f : 0f);
            float b = track.x + tw * zn.to / 100f - (zn.to < 100 ? 1.5f : 0f);
            bool here = zn.id == z;
            Color c = Brand.VerdictColor(zn.id);
            GlassUI.Rounded(new Rect(a, track.y, b - a, track.height), Alpha(c, here ? 0.9f : 0.32f), 6);
            GlassUI.Label(new Rect(a, track.yMax + 4f, b - a, 14f), zn.label, 9,
                          here ? c : new Color(1f, 1f, 1f, 0.4f), FontStyle.Bold, zn.anchor);
        }
        // The best reading so far.
        if (peak > Chemistry + 2)
        {
            float px = track.x + tw * peak / 100f;
            GlassUI.Rounded(new Rect(px - 1f, track.y - 5f, 2f, track.height + 10f), new Color(1f, 1f, 1f, 0.45f), 1);
            GlassUI.Label(new Rect(px - 20f, track.y - 17f, 40f, 12f), "BEST", 8, new Color(1f, 1f, 1f, 0.45f), FontStyle.Bold, TextAnchor.MiddleCenter);
        }
        // The needle, glowing in the zone's colour.
        float nx = track.x + tw * Mathf.Clamp01(shownChemistry / 100f);
        float glow = 0.35f + 0.25f * pulse;
        GlassUI.Rounded(new Rect(nx - 7f, track.y - 9f, 14f, track.height + 18f), Alpha(zc, glow), 7);
        GlassUI.Rounded(new Rect(nx - 2f, track.y - 7f, 4f, track.height + 14f), Color.white, 2);

        // Why it last moved, fading.
        float ra = Mathf.Clamp01(1.5f - (Time.time - reasonAt) / 6f);
        if (ra > 0f && !string.IsNullOrEmpty(reason))
            GlassUI.Label(new Rect(track.x, bar.y + 56f, tw, 16f), reason, 11, new Color(1f, 1f, 1f, 0.75f * ra), FontStyle.Italic, TextAnchor.MiddleCenter);

        // The delta, floating up beside the score.
        float da = Time.time - deltaAt;
        if (da < 1.6f && lastDelta != 0)
        {
            string d = lastDelta > 0 ? $"+{lastDelta}" : lastDelta.ToString();
            Color dc = lastDelta > 0 ? Brand.Match : Brand.Ghosted;
            GlassUI.Label(new Rect(value.x - 64f, value.y + 12f - da * 18f, 56f, 26f), d, 20,
                          Alpha(dc, 1f - da / 1.6f), FontStyle.Bold, TextAnchor.MiddleRight);
        }
    }

    /// <summary>A banner when the date crosses into a new verdict zone.</summary>
    void ZoneBanner(float W)
    {
        float t = Time.time - zoneAt;
        if (zoneToast == null || t > 2.6f || !client.DateRunning)
            return;
        string text = zoneToast switch
        {
            "match" => "💘  MATCH ZONE · they're into you",
            "friendzone" => zoneRising ? "🤝  FRIEND ZONE · warming up" : "🤝  FRIEND ZONE · win them back",
            _ => "👻  GHOST ZONE · ask them something",
        };
        Color c = Brand.VerdictColor(zoneToast);
        float pop = t < 0.25f ? Mathf.Lerp(1.25f, 1f, t / 0.25f) : 1f;
        float alpha = Mathf.Clamp01((2.6f - t) / 0.5f);
        float w = (GlassUI.TextWidth(text, 15, FontStyle.Bold) + 40f) * pop, h = 36f * pop;
        var r = new Rect((W - w) / 2f, BarTop + BarHeight + 58f, w, h);
        GlassUI.Rounded(new Rect(r.x - 2f, r.y - 2f, r.width + 4f, r.height + 4f), Alpha(c, 0.9f * alpha), Mathf.RoundToInt(h / 2f) + 2);
        GlassUI.Rounded(r, new Color(0.07f, 0.03f, 0.06f, 0.92f * alpha), Mathf.RoundToInt(h / 2f));
        GlassUI.Label(r, text, Mathf.RoundToInt(15 * pop), Alpha(c, alpha), FontStyle.Bold, TextAnchor.MiddleCenter);
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

    void Legend(float W)
    {
        if (!client.DateRunning)
            return;
        bool hasMenu = (scenario?.menu?.Length ?? 0) > 0;
        string keys = (hasMenu ? "M  carta     " : "") + "W  wingman     T  translate     Enter  type     V  camera     Q  end";
        GlassUI.Label(new Rect((W - 520f) / 2f, BarTop + BarHeight + 4f, 520f, 16f), keys, 10, new Color(1f, 1f, 1f, 0.55f), FontStyle.Normal, TextAnchor.MiddleCenter);
        if (served != null && Time.time - servedAt < 8f)
        {
            string order = "🧾 Ordered: " + string.Join(", ", served);
            float w = GlassUI.TextWidth(order, 13) + 32f;
            var r = new Rect((W - w) / 2f, BarTop + BarHeight + 24f, w, 28f);
            GlassUI.Panel(r, Mathf.Clamp01(8f - (Time.time - servedAt)));
            GlassUI.Label(r, order, 13, Color.white, FontStyle.Normal, TextAnchor.MiddleCenter);
        }
    }

    /// <summary>The translator: what the date just said, what it means, and three replies.</summary>
    void Help(float W, float H)
    {
        bool show = (helpCard != null && Time.time - helpAt < 20f) || helpPending;
        helpSlide = GlassUI.Ease(helpSlide, show ? 1f : 0f, 9f);
        if (helpSlide < 0.01f)
            return;
        float w = 360f;
        var options = helpCard?.List("suggestions");
        float h = helpCard == null ? 70f : 120f + (options?.Count ?? 0) * 50f;
        // Left of the vision panel, below the match bar and its zone banner.
        float x = Mathf.Lerp(W + 20f, W - w - 320f, Mathf.SmoothStep(0f, 1f, helpSlide));
        var r = new Rect(x, 196f, w, h);
        GlassUI.Panel(r, 0.95f, 16, new Color(0.07f, 0.1f, 0.16f));
        GlassUI.Label(new Rect(r.x + 16f, r.y + 10f, w - 32f, 18f), "🌐 TRANSLATOR", 11, new Color(0.55f, 0.8f, 1f), FontStyle.Bold);
        if (helpCard == null)
        {
            GlassUI.Label(new Rect(r.x + 16f, r.y + 32f, w - 32f, 24f), "Listening back…", 13, Color.white);
            return;
        }
        float y = r.y + 30f;
        string said = helpCard.Str("said");
        if (!string.IsNullOrEmpty(said))
        {
            float sh = Mathf.Min(48f, GlassUI.TextHeight($"«{said}»", 12, w - 32f));
            GlassUI.Label(new Rect(r.x + 16f, y, w - 32f, sh), $"«{said}»", 12, new Color(1f, 1f, 1f, 0.6f), FontStyle.Italic, TextAnchor.UpperLeft, true);
            y += sh + 2f;
        }
        float mh = Mathf.Min(54f, GlassUI.TextHeight(helpCard.Str("meaning_en"), 13, w - 32f));
        GlassUI.Label(new Rect(r.x + 16f, y, w - 32f, mh), helpCard.Str("meaning_en"), 13, Color.white, FontStyle.Normal, TextAnchor.UpperLeft, true);
        y += mh + 8f;
        foreach (var o in options ?? new List<object>())
        {
            if (!(o is Dictionary<string, object> s))
                continue;
            GlassUI.Label(new Rect(r.x + 16f, y, w - 32f, 20f), s.Str("target"), 13, Color.white, FontStyle.Bold);
            GlassUI.Label(new Rect(r.x + 16f, y + 19f, w - 32f, 16f), s.Str("gloss"), 10, new Color(1f, 1f, 1f, 0.55f));
            y += 46f;
        }
        GlassUI.Label(new Rect(r.x + 16f, r.yMax - 26f, w - 32f, 18f), "💡 " + helpCard.Str("tip"), 11, new Color(0.55f, 0.8f, 1f));
    }

    /// <summary>The café's carta: what can be ordered, in Spanish, with prices.</summary>
    void Menu(float H)
    {
        var menu = scenario?.menu;
        menuSlide = GlassUI.Ease(menuSlide, menuOpen ? 1f : 0f, 10f);
        if (menuSlide < 0.01f || menu == null || menu.Length == 0)
            return;
        float w = 300f, h = 56f + menu.Length * 34f;
        float x = Mathf.Lerp(-w - 20f, 20f, Mathf.SmoothStep(0f, 1f, menuSlide));
        var r = new Rect(x, Mathf.Max(270f, (H - h) / 2f), w, h); // below the milestones
        GlassUI.Panel(r, 0.96f, 16, new Color(0.13f, 0.1f, 0.08f));
        GlassUI.Label(new Rect(r.x + 16f, r.y + 10f, w - 32f, 22f), $"☕ {scenario.venue?.label ?? "Carta"}", 16, Brand.AccentSoft, FontStyle.Bold);
        GlassUI.Label(new Rect(r.x + 16f, r.y + 32f, w - 32f, 14f), "CARTA · ask for it in Spanish", 9, new Color(1f, 1f, 1f, 0.5f), FontStyle.Bold);
        float y = r.y + 52f;
        foreach (var item in menu)
        {
            GlassUI.Label(new Rect(r.x + 16f, y, w - 90f, 18f), item.name, 13, Color.white, FontStyle.Bold);
            GlassUI.Label(new Rect(r.x + 16f, y, w - 32f, 18f), $"${item.price} {scenario.currency}", 12, Brand.AccentSoft, FontStyle.Normal, TextAnchor.MiddleRight);
            GlassUI.Label(new Rect(r.x + 16f, y + 16f, w - 32f, 14f), item.description_en, 10, new Color(1f, 1f, 1f, 0.5f));
            y += 34f;
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
