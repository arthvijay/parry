using System;
using UnityEngine;

/// <summary>
/// What survives the trip from the matchmaker to the venue: the generated date, the
/// player's avatar look, and where the orchestrator lives. Kept in memory and in
/// PlayerPrefs, so pressing Play directly in a venue scene (or "try again") still finds
/// the last date.
/// </summary>
public static class DateSession
{
    public const string DefaultServer = "http://127.0.0.1:8765";
    const string ServerPref = "parry.server";
    const string ScenarioPref = "parry.scenario";
    const string LookPref = "parry.look";
    const string NamePref = "parry.learnerName";

    static DateScenario scenario;
    static PlayerLook look;

    public static string ServerUrl
    {
        get => PlayerPrefs.GetString(ServerPref, DefaultServer);
        set { PlayerPrefs.SetString(ServerPref, string.IsNullOrWhiteSpace(value) ? DefaultServer : value.Trim()); PlayerPrefs.Save(); }
    }

    public static string Base => ServerUrl.TrimEnd('/');

    public static string WebSocketBase =>
        Base.StartsWith("https://") ? "wss://" + Base.Substring(8)
        : Base.StartsWith("http://") ? "ws://" + Base.Substring(7) : Base;

    public static string LearnerName
    {
        get => PlayerPrefs.GetString(NamePref, "");
        set { PlayerPrefs.SetString(NamePref, value ?? ""); PlayerPrefs.Save(); }
    }

    /// <summary>The current date, from memory or the last one saved; null if there has never been one.</summary>
    public static DateScenario Scenario
    {
        get
        {
            if (scenario == null && PlayerPrefs.HasKey(ScenarioPref))
                scenario = Parse(PlayerPrefs.GetString(ScenarioPref));
            return scenario;
        }
    }

    public static bool SetScenario(string json)
    {
        var parsed = Parse(json);
        if (parsed == null)
            return false;
        scenario = parsed;
        PlayerPrefs.SetString(ScenarioPref, json);
        PlayerPrefs.Save();
        return true;
    }

    static DateScenario Parse(string json)
    {
        try
        {
            var s = JsonUtility.FromJson<DateScenario>(json);
            return s != null && !string.IsNullOrEmpty(s.scenario_id) && s.date_character != null ? s : null;
        }
        catch (Exception e)
        {
            Debug.LogWarning($"DateSession: unreadable date ({e.Message})");
            return null;
        }
    }

    /// <summary>The player's avatar: chosen body plus colours sampled from the selfie.</summary>
    public static PlayerLook Look
    {
        get
        {
            if (look == null)
            {
                try { look = JsonUtility.FromJson<PlayerLook>(PlayerPrefs.GetString(LookPref, "")); }
                catch (Exception) { look = null; }
                look ??= new PlayerLook();
            }
            return look;
        }
        set
        {
            look = value ?? new PlayerLook();
            PlayerPrefs.SetString(LookPref, JsonUtility.ToJson(look));
            PlayerPrefs.Save();
        }
    }

    public static string NewRunId() => "run_" + Guid.NewGuid().ToString("N").Substring(0, 20);

    /// <summary>Resources path of a Rocketbox body, e.g. Female_Adult_08.</summary>
    public static string AvatarResource(string baseModel)
    {
        string b = string.IsNullOrEmpty(baseModel) ? "Female_Adult_08" : baseModel;
        return $"Avatars/{b}/Export/{b}_facial";
    }

    public static string ScenePath(string sceneName)
        => $"Assets/Scenes/{(string.IsNullOrEmpty(sceneName) ? "CancunCafe" : sceneName)}.unity";
}

// ---- the matchmaker's date (POST /v1/matchmaker/generate) ------------------------------

#pragma warning disable 0649 // DTO fields are filled by JsonUtility
[Serializable]
public class DateScenario
{
    public string scenario_id;
    public string city;
    public string language_code;
    public string dialect;
    public string dialect_label;
    public string proficiency;
    public string learner_name;
    public string venue_scene;
    public string lighting_preset;
    public VenueInfo venue;
    public string scene_description;
    public string personality_archetype;
    public DateCharacter date_character;
    public HostCharacter host_character;
    public Milestone[] milestones = Array.Empty<Milestone>();
    public int date_seconds = 180;
    public float wingman_seconds = 4f;
    public int chemistry_start = 50;
    public string generated_by;
    // Authored dates (presets) carry their café.
    public string preset_id;
    public MenuItem[] menu = Array.Empty<MenuItem>();
    public string currency;
}

[Serializable]
public class MenuItem
{
    public string id;
    public string name;
    public int price;
    public string description_en;
}

[Serializable]
public class VenueInfo
{
    public string id;
    public string label;
    public string setting;
    public string[] ambience = Array.Empty<string>();
    public string lighting_preset;
}

[Serializable]
public class AvatarConfig
{
    public string base_model = "Female_Adult_08";
    public string skin_tint = "#C99A78";
    public string hair_tint = "#2B1D16";
    public string outfit_style;
    public float resting_smile_weight;
}

[Serializable]
public class DateCharacter
{
    public string id = "date_npc";
    public string display_name;
    public string gender;
    public int age;
    public string occupation;
    public string[] interests = Array.Empty<string>();
    public string backstory;
    public AvatarConfig avatar_config;
    public string opening_line;
    public string[] green_flags = Array.Empty<string>();
    public string[] red_flags = Array.Empty<string>();
}

[Serializable]
public class HostCharacter
{
    public string id = "host";
    public string display_name;
    public string gender;
    public string greeting;
    public string[] chat_lines = Array.Empty<string>();
    public AvatarConfig avatar_config;
}

[Serializable]
public class Milestone
{
    public string id;
    public string text;
    public bool core;
}

// ---- the learning report (POST /v1/date/report) ----------------------------------------

[Serializable]
public class DateReport
{
    public string run_id;
    public string summary;
    public ReportQuote went_well;
    public ReportFix[] fixes = Array.Empty<ReportFix>();
    public ReportPhrase[] useful_phrases = Array.Empty<ReportPhrase>();
    public ReportNote[] culture_notes = Array.Empty<ReportNote>();
    public string[] practice_words = Array.Empty<string>();
    public string next_date;
    public string html_path;
}

[Serializable]
public class ReportQuote { public string quote; public string note; }

[Serializable]
public class ReportFix { public string heard; public string better; public string why_en; }

[Serializable]
public class ReportPhrase { public string target; public string gloss; public string when; }

[Serializable]
public class ReportNote { public string title; public string note; }

// ---- the matchmaker's menu (GET /v1/matchmaker/catalog) -----------------------------

[Serializable]
public class PresetInfo
{
    public string id;
    public string label;
    public string summary;
    public string dialect;
    public string city;
    public float lat;
    public float lon;
    public string default_proficiency;
}

[Serializable]
public class Catalog
{
    public PresetInfo[] presets = Array.Empty<PresetInfo>();
    public int date_seconds = 180;
    public DialectInfo[] dialects = Array.Empty<DialectInfo>();
    public Option[] venues = Array.Empty<Option>();
    public Option[] archetypes = Array.Empty<Option>();
    public Option[] appearances = Array.Empty<Option>();
    public LevelInfo[] levels = Array.Empty<LevelInfo>();
    public string[] genders = Array.Empty<string>();
}

[Serializable]
public class DialectInfo
{
    public string code;
    public string label;
    public string language;
    public CityInfo[] cities = Array.Empty<CityInfo>();
}

[Serializable]
public class CityInfo
{
    public string name;
    public float lat;
    public float lon;
}

[Serializable]
public class Option
{
    public string id;
    public string label;
    public string scene;
    public string skin;
    public string hair;
}

[Serializable]
public class LevelInfo
{
    public string cefr;
    public string band;
}

// ---- the player ---------------------------------------------------------------------

[Serializable]
public class PlayerLook
{
    public string base_model = "Male_Adult_08";
    public string skin_hex = "";
    public string hair_hex = "";
    public string selfie_path = "";
    public bool from_selfie;
}

// ---- the verdict (POST /v1/grade) -----------------------------------------------------

[Serializable]
public class DateVerdict
{
    public string scenario_id;
    public string run_id;
    public string verdict;
    public string stamp;
    public string stamp_en;
    public int final_chemistry;
    public string venue;
    public string city;
    public string date_name;
    public string persona;
    public string dialect;
    public Pillar[] pillars = Array.Empty<Pillar>();
    public MilestoneResult[] milestones = Array.Empty<MilestoneResult>();
    public DateMetrics metrics;
    public FollowUp followup;
    public string overall;
    public string summary;
    public int[] chemistry_timeline = Array.Empty<int>();
    public string graded_by;
}

[Serializable]
public class Pillar
{
    public string id;
    public string label;
    public string grade;
    public string comment;
    public string evidence_quote;
}

[Serializable]
public class MilestoneResult
{
    public string id;
    public string text;
    public bool achieved;
    public string evidence_quote;
}

[Serializable]
public class DateMetrics
{
    public int turns;
    public int learner_words;
    public int avg_response_latency_ms = -1;
    public int pronunciation_confidence_pct = -1;
    public int wingman_hints_used;
    public int wingman_lines_used;
    public int unassisted_fluency_pct;
    public int eye_contact_pct = -1;
    public int smiles;
    public int look_away_callouts;
    public int barge_ins;
    public int help_requests;
}

[Serializable]
public class FollowUp
{
    public string sender;
    public string text;
    public string translation_en;
    public Correction correction;
}

[Serializable]
public class Correction
{
    public string heard;
    public string better;
    public string why_en;
}
#pragma warning restore 0649
