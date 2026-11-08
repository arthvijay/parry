using System;
using UnityEngine;

/// <summary>
/// Puts the matchmaker's characters into the venue's NPC slots. The venue's npcs json
/// says where people stand and sit and what role each slot plays ("host", "date"); the
/// date says who they are. Before <see cref="NpcManager"/> spawns a slot it asks
/// <see cref="ApplyTo"/> for the person: name, npc id, Rocketbox body, skin and hair
/// tints, resting smile. After spawn, <see cref="Bind"/> wires the live parts: the host
/// greets on approach, the date gets body language driven by chemistry. If the date
/// arrives after the NPCs have spawned, they are respawned once with it.
/// </summary>
public class CastClient : MonoBehaviour
{
    public static CastClient Instance { get; private set; }

    public const string DateRole = "date";
    public const string HostRole = "host";

    string appliedScenario = "";

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
        if (NpcManager.Instance != null)
            NpcManager.Instance.Changed += Bind;
        if (ScenarioClient.Instance != null)
            ScenarioClient.Instance.Loaded += OnDate;
        Bind();
    }

    void OnDestroy()
    {
        if (NpcManager.Instance != null)
            NpcManager.Instance.Changed -= Bind;
        if (ScenarioClient.Instance != null)
            ScenarioClient.Instance.Loaded -= OnDate;
        if (Instance == this)
            Instance = null;
    }

    void OnDate(DateScenario s)
    {
        // Spawned before the date was known: respawn with the right bodies.
        if (NpcManager.Instance != null && appliedScenario != s.scenario_id)
            NpcManager.Instance.Load();
    }

    /// <summary>Fill a slot's definition from the current date, before it spawns.</summary>
    public static void ApplyTo(NpcDefinition def)
    {
        var s = DateSession.Scenario;
        if (def == null || s == null)
            return;
        if (def.role == DateRole && s.date_character != null)
        {
            var c = s.date_character;
            def.id = "date_npc";
            def.displayName = c.display_name;
            def.greeting = c.opening_line;
            ApplyLook(def, c.avatar_config);
        }
        else if (def.role == HostRole && s.host_character != null)
        {
            var h = s.host_character;
            def.id = "host";
            def.displayName = h.display_name;
            def.greeting = h.greeting;
            ApplyLook(def, h.avatar_config);
        }
        if (Instance != null)
            Instance.appliedScenario = s.scenario_id;
    }

    static void ApplyLook(NpcDefinition def, AvatarConfig look)
    {
        if (look == null)
            return;
        if (!string.IsNullOrEmpty(look.base_model))
            def.avatar = DateSession.AvatarResource(look.base_model);
        def.skinTint = look.skin_tint;
        def.hairTint = look.hair_tint;
        def.restingSmile = look.resting_smile_weight;
        def.outfit = look.outfit_style;
    }

    /// <summary>Wire the spawned slots: the host's greeting, the date's body language.</summary>
    void Bind()
    {
        if (NpcManager.Instance == null)
            return;
        foreach (var pair in NpcManager.Instance.Spawned)
        {
            var go = pair.Value;
            if (go == null)
                continue;
            var tag = go.GetComponent<NpcIdentity>();
            var def = tag != null ? tag.definition : null;
            var talk = go.GetComponent<NpcConversation>();
            if (def == null || talk == null)
                continue;
            if (def.role == HostRole)
            {
                talk.SetId("host");
                talk.greetOnApproach = true;
            }
            else if (def.role == DateRole)
            {
                talk.SetId("date_npc");
                var body = go.GetComponent<DateBodyLanguage>();
                if (body == null)
                    body = go.AddComponent<DateBodyLanguage>();
                body.restingSmile = def.restingSmile;
                if (SpatialTelemetryBroadcaster.Instance != null)
                    SpatialTelemetryBroadcaster.Instance.SetDate(go);
            }
        }
    }

    /// <summary>The spawned date NPC, or null.</summary>
    public static GameObject Date => NpcManager.Instance != null ? NpcManager.Instance.Find("date_npc") : null;
}
