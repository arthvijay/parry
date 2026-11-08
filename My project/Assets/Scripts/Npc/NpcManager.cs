using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

/// <summary>
/// Spawns every NPC described in StreamingAssets/npcs.json (see
/// <see cref="NpcDefinition"/>) with the full component stack: avatar, idle
/// mocap, look-at, lip-synced speech, E-to-talk prompt, walking, sitting and the
/// move schedule. Like <see cref="QuestManager"/> it re-reads the file when it
/// changes on disk, so positions and paths can be tuned while playing.
/// </summary>
public class NpcManager : MonoBehaviour
{
    public static NpcManager Instance { get; private set; }

    [Tooltip("JSON file under StreamingAssets.")]
    public string fileName = "npcs.json";

    [Tooltip("Respawn the NPCs when the file changes on disk.")]
    public bool watchFile = true;

    [Tooltip("Capsule used for player collision and the E-to-talk range check.")]
    public float capsuleRadius = 0.3f;
    public float capsuleHeight = 1.8f;

    public NpcList Npcs { get; private set; } = new NpcList();

    /// <summary>Spawned NPC roots by id.</summary>
    public IReadOnlyDictionary<string, GameObject> Spawned => spawned;

    /// <summary>Fired after NPCs are (re)spawned.</summary>
    public event Action Changed;

    readonly Dictionary<string, GameObject> spawned = new();
    string FilePath => Path.Combine(Application.streamingAssetsPath, fileName);
    DateTime lastWrite;
    float nextPoll;

    void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }
        Instance = this;
    }

    void Start()
    {
        Load();
    }

    void Update()
    {
        if (!watchFile || Time.unscaledTime < nextPoll)
            return;
        nextPoll = Time.unscaledTime + 0.5f;

        if (File.Exists(FilePath) && File.GetLastWriteTimeUtc(FilePath) != lastWrite)
            Load();
    }

    public void Load()
    {
        if (!File.Exists(FilePath))
        {
            Debug.LogWarning($"NpcManager: {FilePath} not found; no NPCs spawned.");
            return;
        }

        NpcList list;
        try
        {
            list = JsonUtility.FromJson<NpcList>(File.ReadAllText(FilePath)) ?? new NpcList();
            lastWrite = File.GetLastWriteTimeUtc(FilePath);
        }
        catch (Exception e)
        {
            Debug.LogError($"NpcManager: could not parse {FilePath}: {e.Message}");
            return;
        }

        Npcs = list;
        Respawn();
    }

    void Respawn()
    {
        foreach (var go in spawned.Values)
            if (go != null)
                Destroy(go);
        spawned.Clear();

        foreach (var authored in Npcs.npcs)
        {
            if (authored == null)
                continue;
            // A copy, so filling a slot from the date never edits the authored list.
            var def = authored.Clone();
            if (!string.IsNullOrEmpty(def.role))
                CastClient.ApplyTo(def);
            string id = string.IsNullOrEmpty(def.id) ? def.displayName : def.id;
            if (spawned.ContainsKey(id))
            {
                Debug.LogWarning($"NpcManager: duplicate NPC id '{id}', skipping.");
                continue;
            }
            spawned[id] = Spawn(def, id);
        }
        Debug.Log($"NpcManager: spawned {spawned.Count} NPC(s) from {fileName}");
        Changed?.Invoke();
    }

    GameObject Spawn(NpcDefinition def, string id)
    {
        var go = new GameObject($"NPC {def.displayName}");
        go.transform.SetParent(transform, worldPositionStays: false);
        go.transform.SetPositionAndRotation(def.position, Quaternion.Euler(0f, def.yaw, 0f));
        go.transform.localScale = Vector3.one * (def.scale > 0f ? def.scale : 1f);

        var capsule = go.AddComponent<CapsuleCollider>();
        capsule.radius = capsuleRadius;
        capsule.height = capsuleHeight;
        capsule.center = Vector3.up * (capsuleHeight * 0.5f);

        // Grey stand-in until the avatar appears (or if it fails to load).
        var placeholder = GameObject.CreatePrimitive(PrimitiveType.Capsule);
        placeholder.name = "Placeholder";
        Destroy(placeholder.GetComponent<Collider>());
        placeholder.transform.SetParent(go.transform, false);
        placeholder.transform.localPosition = Vector3.up * (capsuleHeight * 0.5f);
        placeholder.transform.localScale = new Vector3(capsuleRadius * 1.5f, capsuleHeight * 0.5f, capsuleRadius * 1.5f);

        // Components subscribe to Loaded in Awake, which runs on AddComponent, so
        // they must all exist before the loader's Start fires. Adding them to an
        // inactive object defers Awake until it is activated below.
        go.SetActive(false);

        var loader = go.AddComponent<NpcAvatarLoader>();
        if (!string.IsNullOrEmpty(def.avatar))
            loader.resourcePath = def.avatar;
        loader.placeholder = placeholder;

        var idle = go.AddComponent<NpcIdleAnimation>();
        if (def.idleClips != null && def.idleClips.Length > 0)
            idle.clipResources = def.idleClips;
        idle.walkClipResource = def.walkClip ?? "";

        var look = go.AddComponent<NpcLookAt>();
        look.headBone = "Bip01 Head";
        look.spineBone = "Bip01 Spine1";
        look.breathAmplitude = 0.5f;

        go.AddComponent<StreamingAudioPlayer>();
        var speaker = go.AddComponent<NpcSpeaker>();
        speaker.mouthBone = "Bip01 Head";

        // The parametric look: skin and hair tints on the Rocketbox materials, and a
        // resting expression held on the face blendshapes.
        var tint = go.AddComponent<AvatarTinter>();
        tint.skin = def.skinTint;
        tint.hair = def.hairTint;

        var interact = go.AddComponent<NpcInteractable>();
        interact.displayName = def.displayName;

        var talk = go.AddComponent<NpcConversation>();
        talk.npcId = id; // must match the server's agent id (AGENT_ID_<ID>)
        talk.greeting = def.greeting ?? "";

        var walker = go.AddComponent<NpcWalker>();
        walker.walkSpeed = def.walkSpeed > 0f ? def.walkSpeed : 0.8f;
        walker.turnSpeed = def.turnSpeed > 0f ? def.turnSpeed : 240f;

        var schedule = go.AddComponent<NpcSchedule>();
        schedule.moves = def.moves ?? Array.Empty<NpcMove>();

        var sitter = go.AddComponent<NpcSitter>();

        var tag = go.AddComponent<NpcIdentity>();
        tag.id = id;
        tag.definition = def;

        go.SetActive(true);
        if (!string.IsNullOrEmpty(def.seat))
            sitter.Sit(def.seat); // coroutine, so only once the object is active
        return go;
    }

    /// <summary>Spawned NPC root by id, or null.</summary>
    public GameObject Find(string id) => spawned.TryGetValue(id, out var go) ? go : null;

    /// <summary>Convenience for scripts/backends: send an NPC walking somewhere now.</summary>
    public bool WalkTo(string id, Vector3 destination, float speed = 0f, float endYaw = float.NaN)
    {
        var go = Find(id);
        if (go == null)
        {
            Debug.LogWarning($"NpcManager: no NPC with id '{id}'.");
            return false;
        }
        go.GetComponent<NpcWalker>().WalkTo(destination, speed, endYaw);
        return true;
    }

    void OnDestroy()
    {
        if (Instance == this)
            Instance = null;
    }
}
