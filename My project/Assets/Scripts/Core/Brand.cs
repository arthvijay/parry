using System;
using UnityEngine;

/// <summary>
/// The product's name, copy and colours, read once from Resources/BrandConfig.json, the
/// same file the orchestrator reads. Nothing else in the client spells the name.
/// </summary>
public static class Brand
{
    [Serializable]
    class Verdicts
    {
        public string match = "SECOND DATE UNLOCKED";
        public string friendzone = "FRIENDZONED";
        public string ghosted = "GHOSTED";
    }

    [Serializable]
    class Colors
    {
        public string accent = "#FF5A7A";
        public string accentSoft = "#FFB3C1";
        public string ink = "#14151C";
        public string glass = "#1A1C26";
        public string good = "#4CD787";
        public string warn = "#FFC24B";
        public string bad = "#FF5A5A";
        // The three verdict zones, on the live match bar and the receipt.
        public string match = "#FF3D6E";
        public string friendzone = "#FFB454";
        public string ghosted = "#7FA6FF";
        public string paper = "#F7ECDF";
        public string paperInk = "#2A1820";
        // The pitch deck's type colours: primary, secondary and tertiary text.
        public string cream = "#F7ECDF";
        public string muted = "#C9B1BD";
        public string dim = "#8D7381";
    }

    [Serializable]
    class Data
    {
        public string name = "Parry";
        public string tagline = "Keep up. Flirt back. Speak like a local.";
        public string description = "";
        public Verdicts verdicts = new();
        public Colors colors = new();
    }

    static Data data;

    static Data D
    {
        get
        {
            if (data != null)
                return data;
            var asset = Resources.Load<TextAsset>("BrandConfig");
            try { data = asset != null ? JsonUtility.FromJson<Data>(asset.text) : null; }
            catch (Exception e) { Debug.LogWarning($"Brand: BrandConfig.json unreadable ({e.Message})"); }
            data ??= new Data();
            data.verdicts ??= new Verdicts();
            data.colors ??= new Colors();
            return data;
        }
    }

    public static string Name => D.name;
    public static string Tagline => D.tagline;

    public static string Verdict(string kind) => kind switch
    {
        "match" => D.verdicts.match,
        "friendzone" => D.verdicts.friendzone,
        _ => D.verdicts.ghosted,
    };

    public static Color Accent => Hex(D.colors.accent, new Color(1f, 0.35f, 0.48f));
    public static Color AccentSoft => Hex(D.colors.accentSoft, new Color(1f, 0.7f, 0.76f));
    public static Color Ink => Hex(D.colors.ink, new Color(0.08f, 0.08f, 0.11f));
    public static Color Glass => Hex(D.colors.glass, new Color(0.1f, 0.11f, 0.15f));
    public static Color Good => Hex(D.colors.good, new Color(0.3f, 0.84f, 0.53f));
    public static Color Warn => Hex(D.colors.warn, new Color(1f, 0.76f, 0.29f));
    public static Color Bad => Hex(D.colors.bad, new Color(1f, 0.35f, 0.35f));

    public static Color Match => Hex(D.colors.match, new Color(1f, 0.24f, 0.43f));
    public static Color Friendzone => Hex(D.colors.friendzone, new Color(1f, 0.71f, 0.33f));
    public static Color Ghosted => Hex(D.colors.ghosted, new Color(0.5f, 0.65f, 1f));
    public static Color Paper => Hex(D.colors.paper, new Color(0.97f, 0.93f, 0.87f));
    public static Color PaperInk => Hex(D.colors.paperInk, new Color(0.16f, 0.09f, 0.13f));
    public static Color Cream => Hex(D.colors.cream, new Color(0.97f, 0.93f, 0.87f));
    public static Color Muted => Hex(D.colors.muted, new Color(0.79f, 0.69f, 0.74f));
    public static Color Dim => Hex(D.colors.dim, new Color(0.55f, 0.45f, 0.51f));

    /// <summary>Chemistry at which a date ends in each verdict (the server's thresholds).</summary>
    public const int FriendzoneAt = 45, MatchAt = 65;

    public static string Zone(float chemistry) =>
        chemistry >= MatchAt ? "match" : chemistry >= FriendzoneAt ? "friendzone" : "ghosted";

    public static Color VerdictColor(string kind) => kind switch
    {
        "match" => Match,
        "friendzone" => Friendzone,
        _ => Ghosted,
    };

    public static Color Hex(string hex, Color fallback)
        => !string.IsNullOrEmpty(hex) && ColorUtility.TryParseHtmlString(hex, out var c) ? c : fallback;
}
