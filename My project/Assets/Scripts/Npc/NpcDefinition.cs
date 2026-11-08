using System;
using UnityEngine;

/// <summary>
/// Schema for StreamingAssets/npcs.json. <see cref="NpcManager"/> spawns one
/// NPC per entry; <see cref="NpcSchedule"/> runs the moves. Entries with a
/// <see cref="NpcDefinition.role"/> are slots the matchmaker's date fills in
/// (<see cref="CastClient.ApplyTo"/>).
///
/// <code>
/// {
///   "npcs": [{
///     "id": "barista", "displayName": "Sofía",
///     "avatar": "Avatars/Female_Adult_08/Export/Female_Adult_08_facial",
///     "position": {"x": 0.85, "y": -1.52, "z": 2.99}, "yaw": 180, "scale": 0.7,
///     "walkSpeed": 0.8, "seat": "",
///     "moves": [{
///       "id": "greet", "trigger": "quest", "after": "order_coffee", "delay": 4,
///       "path": [{"x": 0, "y": -1.52, "z": 3}, {"x": 0, "y": -1.52, "z": -1}],
///       "endYaw": 180, "sit": "table_b"
///     }]
///   }]
/// }
/// </code>
/// </summary>
[Serializable]
public class NpcList
{
    public NpcDefinition[] npcs = Array.Empty<NpcDefinition>();
}

[Serializable]
public class NpcDefinition
{
    public string id;
    public string displayName = "NPC";

    [Tooltip("Model path under a Resources folder, without extension.")]
    public string avatar = "Avatars/Female_Adult_08/Export/Female_Adult_08_facial";

    [Tooltip("World position of the feet.")]
    public Vector3 position;
    [Tooltip("World heading in degrees (0 = +Z).")]
    public float yaw;
    public float scale = 1f;

    [Tooltip("Metres per second when walking.")]
    public float walkSpeed = 0.8f;
    [Tooltip("Degrees per second when turning.")]
    public float turnSpeed = 240f;

    [Tooltip("Idle mocap clips (Resources paths). Empty = NpcIdleAnimation defaults.")]
    public string[] idleClips = Array.Empty<string>();
    [Tooltip("Optional walk cycle clip (Resources path). Empty = procedural gait.")]
    public string walkClip = "";

    [Tooltip("Seat id (seats.json) to start the scene sitting in. Empty = standing at position.")]
    public string seat = "";

    [Header("Speed date")]
    [Tooltip("\"date\" or \"host\": the matchmaker's character for this slot replaces name, id and look. Empty = as authored.")]
    public string role = "";
    [Tooltip("Hex colour multiplied onto the skin materials, e.g. #C99A78. Empty = untinted.")]
    public string skinTint = "";
    [Tooltip("Hex colour multiplied onto the hair materials. Empty = untinted.")]
    public string hairTint = "";
    [Tooltip("Resting smile, 0-1, held on the mouthSmile blendshapes.")]
    public float restingSmile;
    [Tooltip("Outfit style (e.g. black_dress). Empty = as modelled.")]
    public string outfit = "";

    [Header("Conversation")]
    [Tooltip("Spoken (placeholder voice) the first time the player walks up. A loaded scenario's opening_line overrides it.")]
    public string greeting = "";

    public NpcMove[] moves = Array.Empty<NpcMove>();

    /// <summary>A shallow copy: slots are filled on the copy, never on the authored list.</summary>
    public NpcDefinition Clone() => (NpcDefinition)MemberwiseClone();
}

/// <summary>One scripted walk along a path, fired by a trigger.</summary>
[Serializable]
public class NpcMove
{
    public const string TriggerStart = "start";
    public const string TriggerQuest = "quest";
    public const string TriggerMove = "move";
    public const string TriggerGreet = "greet";
    public const string TriggerAction = "action";

    [Tooltip("Name other moves can chain from with trigger \"move\".")]
    public string id;

    [Tooltip("\"start\": when the scene loads. \"quest\": when quest `after` is completed. " +
             "\"move\": when this NPC finishes move `after`. " +
             "\"greet\": when this NPC has finished saying its greeting to the player. " +
             "\"action\": when the conversation server reports scene action `after` (e.g. serve_order) for this NPC.")]
    public string trigger = TriggerStart;

    [Tooltip("Quest id, move id or action name, depending on trigger (unused for start/greet).")]
    public string after = "";

    [Tooltip("Seconds to wait after the trigger before setting off.")]
    public float delay;

    [Tooltip("World-space waypoints. Y is a hint; feet are snapped to the collider below.")]
    public Vector3[] path = Array.Empty<Vector3>();

    [Tooltip("Metres per second; 0 = the NPC's walkSpeed.")]
    public float speed;

    [Tooltip("Heading to settle into on arrival (degrees, 0 = +Z). Omit to keep the walking direction.")]
    public float endYaw = float.NaN;

    [Tooltip("Keep walking the path back and forth forever.")]
    public bool loop;

    [Tooltip("Fire only the first time the trigger happens.")]
    public bool once = true;

    [Tooltip("Seat id (seats.json) to sit down in on arrival. Empty = stay standing.")]
    public string sit = "";

    [Tooltip("Scene notes for the conversation server to pass to characters when this move " +
             "sets off or arrives, e.g. tell Luis that Maria is coming to take the order.")]
    public NpcNote[] tell = Array.Empty<NpcNote>();

    public bool HasEndYaw => !float.IsNaN(endYaw);
}

/// <summary>
/// Something a character is told about the scene without anyone taking a turn
/// (<c>POST /v1/runs/{run}/notes</c>). Notes with the same <c>key</c> replace each
/// other, so "Maria is on her way" is later overwritten by "Maria has left".
/// </summary>
[Serializable]
public class NpcNote
{
    public const string WhenStart = "start";
    public const string WhenArrive = "arrive";

    [Tooltip("npc id of the character being told (e.g. luis).")]
    public string npc = "";
    [Tooltip("Subject of the note; a later note with the same key replaces this one.")]
    public string key = "floor";
    [Tooltip("What the character can see happening, in plain English. Empty withdraws the note.")]
    public string text = "";
    [Tooltip("\"start\": when the move sets off (after its delay). \"arrive\": when the NPC gets there.")]
    public string when = WhenStart;
}
