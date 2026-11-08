using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

/// <summary>
/// Brings the matchmaker's date into the venue. On scene start it takes the date chosen
/// in the matchmaker (<see cref="DateSession"/>), or refetches it with
/// <c>GET /v1/matchmaker/{id}</c>, or, when Play was pressed directly in a venue scene,
/// plays the authored demo date (<c>POST /v1/matchmaker/preset</c>, Café Rayuela in Cancún). Then it applies it: the
/// milestones become the quest list, the venue's lighting and sound are set, the cast is
/// bound (<see cref="CastClient"/>), and the stream joins the date.
/// </summary>
public class ScenarioClient : MonoBehaviour
{
    public static ScenarioClient Instance { get; private set; }

    [Tooltip("Date to load instead of the matchmaker's (e.g. date_buenos_aires_valeria_1a2b3c). Empty = the matchmaker's.")]
    public string dateId = "";
    // Named apart from the café version's fields so their saved scene values do not apply.
    public bool joinOnStart = true;
    public int timeoutSeconds = 90;

    [Header("Default date (Play pressed in the venue)")]
    [Tooltip("Authored date to play when no date was chosen in the matchmaker.")]
    public string defaultPreset = "cafe_cancun_ar";
    [Tooltip("CEFR level for the default date: A1, A2, B1, B2, C1 or C2.")]
    public string defaultLevel = "B1";

    /// <summary>The date in play, or null until loaded.</summary>
    public DateScenario Current { get; private set; }
    public string Status { get; private set; } = "";
    public event Action<DateScenario> Loaded;

    void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(this);
            return;
        }
        Instance = this;
    }

    void Start()
    {
        if (joinOnStart)
            StartCoroutine(Load());
    }

    void OnDestroy()
    {
        if (Instance == this)
            Instance = null;
    }

    string Base => FullDuplexStreamClient.Instance != null ? FullDuplexStreamClient.Instance.Base : DateSession.Base;

    public IEnumerator Load()
    {
        var known = DateSession.Scenario;
        if (!string.IsNullOrEmpty(dateId) && (known == null || known.scenario_id != dateId))
        {
            Status = "Finding your date…";
            using var get = UnityWebRequest.Get($"{Base}/v1/matchmaker/{UnityWebRequest.EscapeURL(dateId)}");
            get.timeout = 15;
            yield return get.SendWebRequest();
            if (get.result == UnityWebRequest.Result.Success)
                DateSession.SetScenario(get.downloadHandler.text);
            else
                Debug.LogWarning($"ScenarioClient: date {dateId} not found: {FullDuplexStreamClient.Describe(get)}");
            known = DateSession.Scenario;
        }

        if (known == null)
        {
            // Play pressed straight in the venue: the authored demo date.
            Status = "Setting the table…";
            string body = Json.Write(new Dictionary<string, object>
            {
                ["preset"] = defaultPreset, ["learner_name"] = DateSession.LearnerName,
                ["proficiency"] = defaultLevel, ["date_gender"] = "female",
            });
            using var post = new UnityWebRequest($"{Base}/v1/matchmaker/preset", "POST")
            {
                uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(body)) { contentType = "application/json" },
                downloadHandler = new DownloadHandlerBuffer(),
                timeout = timeoutSeconds,
            };
            yield return post.SendWebRequest();
            if (post.result != UnityWebRequest.Result.Success || !DateSession.SetScenario(post.downloadHandler.text))
            {
                Status = "No date: is the orchestrator running? (uv run python -m orchestrator)";
                Debug.LogWarning($"ScenarioClient: demo date failed: {FullDuplexStreamClient.Describe(post)}");
                yield break;
            }
            known = DateSession.Scenario;
        }
        Apply(known);
    }

    void Apply(DateScenario s)
    {
        Current = s;
        Status = "";
        Debug.Log($"ScenarioClient: {s.date_character.display_name} ({s.personality_archetype}), " +
                  $"{s.dialect_label}, {s.venue?.label} in {s.city} [{s.generated_by}]");

        if (QuestManager.Instance != null)
        {
            var milestones = s.milestones ?? Array.Empty<Milestone>();
            var quests = new Quest[milestones.Length];
            for (int i = 0; i < milestones.Length; i++)
                quests[i] = new Quest
                {
                    id = milestones[i].id,
                    text = milestones[i].core ? milestones[i].text : milestones[i].text + " (bonus)",
                    status = Quest.Todo,
                };
            QuestManager.Instance.Replace(new QuestList { title = $"{s.date_character.display_name} · {s.city}", quests = quests });
        }

        VenueAmbience.Ensure().Apply(s);
        var client = FullDuplexStreamClient.Instance;
        if (client != null)
        {
            client.scenarioId = s.scenario_id;
            if (string.IsNullOrEmpty(client.learnerName))
                client.learnerName = s.learner_name;
            client.Connect(s.scenario_id);
        }
        Loaded?.Invoke(s);
    }

    void OnGUI()
    {
        if (string.IsNullOrEmpty(Status))
            return;
        var m = GlassUI.Begin();
        float w = Mathf.Max(260f, GlassUI.TextWidth(Status, 16) + 48f);
        var r = new Rect((GlassUI.Width - w) / 2f, 24f, w, 40f);
        GlassUI.Panel(r);
        GlassUI.Label(r, Status, 16, Color.white, FontStyle.Normal, TextAnchor.MiddleCenter);
        GlassUI.End(m);
    }
}
