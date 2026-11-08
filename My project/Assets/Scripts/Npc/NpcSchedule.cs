using System.Collections;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Runs the <see cref="NpcMove"/> list from npcs.json: fires each move when its
/// trigger happens (scene start, a quest completing, another of this NPC's
/// moves finishing, or the NPC finishing its greeting), waits the configured
/// delay, then hands the path to
/// <see cref="NpcWalker"/>. A move with <c>sit</c> ends with the NPC sitting down.
/// </summary>
[RequireComponent(typeof(NpcWalker))]
public class NpcSchedule : MonoBehaviour
{
    [Tooltip("Seconds after the avatar loads before 'start' moves may begin, so the feet " +
             "have been grounded on a still-standing pose.")]
    public float startSettle = 1.5f;

    public NpcMove[] moves = System.Array.Empty<NpcMove>();

    NpcWalker walker;
    NpcAvatarLoader loader;
    readonly HashSet<NpcMove> fired = new();
    NpcMove running;
    bool avatarReady;

    void Awake()
    {
        walker = GetComponent<NpcWalker>();
        loader = GetComponent<NpcAvatarLoader>();
        loader.Loaded += _ => StartCoroutine(AfterSettle());
        walker.Arrived += OnArrived;
        var talk = GetComponent<NpcConversation>();
        if (talk != null)
        {
            talk.Greeted += OnGreeted;
            talk.Acted += OnActed;
        }
    }

    void OnGreeted()
    {
        foreach (var move in moves)
            if (move.trigger == NpcMove.TriggerGreet)
                Fire(move);
    }

    void OnActed(string action)
    {
        foreach (var move in moves)
            if (move.trigger == NpcMove.TriggerAction && move.after == action)
                Fire(move);
    }

    void Start()
    {
        if (QuestManager.Instance != null)
            QuestManager.Instance.Changed += OnQuestsChanged;
    }

    IEnumerator AfterSettle()
    {
        yield return new WaitForSeconds(startSettle);
        avatarReady = true;
        foreach (var move in moves)
            if (move.trigger == NpcMove.TriggerStart)
                Fire(move);
        // Quests already completed before we spawned (statuses persist in quests.json).
        OnQuestsChanged();
    }

    void OnQuestsChanged()
    {
        if (!avatarReady || QuestManager.Instance == null)
            return;
        foreach (var move in moves)
        {
            if (move.trigger != NpcMove.TriggerQuest)
                continue;
            var quest = QuestManager.Instance.Find(move.after);
            if (quest != null && quest.IsDone)
                Fire(move);
        }
    }

    /// <summary>Fired when a move reaches the end of its path, with the move's id.</summary>
    public event System.Action<string> MoveFinished;

    void OnArrived()
    {
        var done = running;
        running = null;
        if (done == null)
            return;
        MoveFinished?.Invoke(done.id);
        if (!string.IsNullOrEmpty(done.sit))
            GetComponent<NpcSitter>()?.Sit(done.sit);
        Tell(done, NpcNote.WhenArrive);
        if (string.IsNullOrEmpty(done.id))
            return;
        foreach (var move in moves)
            if (move.trigger == NpcMove.TriggerMove && move.after == done.id)
                Fire(move);
    }

    /// <summary>Start a move by id regardless of its trigger (e.g. from the conversation backend).</summary>
    public bool Trigger(string moveId)
    {
        foreach (var move in moves)
            if (move.id == moveId)
            {
                Fire(move, force: true);
                return true;
            }
        Debug.LogWarning($"{name}: no move with id '{moveId}'.");
        return false;
    }

    void Fire(NpcMove move, bool force = false)
    {
        if (!force && move.once && fired.Contains(move))
            return;
        fired.Add(move);
        StartCoroutine(Run(move));
    }

    IEnumerator Run(NpcMove move)
    {
        if (move.delay > 0f)
            yield return new WaitForSeconds(move.delay);
        if (move.path == null || move.path.Length == 0)
        {
            Debug.LogWarning($"{name}: move '{move.id}' has no path.");
            yield break;
        }
        Debug.Log($"{name}: starting move '{move.id}' ({move.path.Length} waypoint(s))");
        running = move;
        Tell(move, NpcNote.WhenStart);
        walker.Walk(move.path, move.speed, move.endYaw, move.loop);
    }

    /// <summary>
    /// The move's scene notes due at this moment. The speed date's characters get their
    /// context from the stream itself, so notes are only logged for the author.
    /// </summary>
    void Tell(NpcMove move, string when)
    {
        if (move.tell == null)
            return;
        foreach (var note in move.tell)
            if (note != null && !string.IsNullOrEmpty(note.npc) && (note.when ?? NpcNote.WhenStart) == when)
                Debug.Log($"{name}: scene note for {note.npc} ({note.key}): {note.text}");
    }

    void OnDestroy()
    {
        if (QuestManager.Instance != null)
            QuestManager.Instance.Changed -= OnQuestsChanged;
    }
}
