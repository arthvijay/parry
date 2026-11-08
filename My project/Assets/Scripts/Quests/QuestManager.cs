using System;
using System.IO;
using UnityEngine;

/// <summary>
/// Loads the mini-quest checklist from StreamingAssets/quests.json and tracks
/// completion in memory for this run. <see cref="QuestHud"/> draws it; the
/// conversation backend marks items off with <see cref="Complete"/> (or by editing
/// the JSON file, which is watched for changes so an external process can drive it
/// too). Nothing is written back: the file is the authored list, and every load of
/// the scene starts from it.
/// </summary>
public class QuestManager : MonoBehaviour
{
    public static QuestManager Instance { get; private set; }

    [Tooltip("JSON file under StreamingAssets.")]
    public string fileName = "quests.json";

    [Tooltip("Re-read the file when it changes on disk, so statuses can be flipped from outside Unity.")]
    public bool watchFile = true;

    public QuestList Quests { get; private set; } = new QuestList();

    /// <summary>Fired after the list is (re)loaded or a status changes.</summary>
    public event Action Changed;

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
            Debug.LogWarning($"QuestManager: {FilePath} not found; no quests loaded.");
            Quests = new QuestList();
            Changed?.Invoke();
            return;
        }

        try
        {
            Quests = JsonUtility.FromJson<QuestList>(File.ReadAllText(FilePath)) ?? new QuestList();
            lastWrite = File.GetLastWriteTimeUtc(FilePath);
        }
        catch (Exception e)
        {
            Debug.LogError($"QuestManager: could not parse {FilePath}: {e.Message}");
            return;
        }
        Changed?.Invoke();
    }

    public Quest Find(string id) => Array.Find(Quests.quests, q => q.id == id);

    /// <summary>Swap in a whole new quest list (e.g. a generated scenario's goals).</summary>
    public void Replace(QuestList list)
    {
        Quests = list ?? new QuestList();
        Changed?.Invoke();
    }

    /// <summary>Mark a quest done. Returns false if the id is unknown.</summary>
    public bool Complete(string id) => SetStatus(id, Quest.Done);

    /// <summary>Put every quest back to todo (new episode).</summary>
    public void ResetAll()
    {
        bool changed = false;
        foreach (var quest in Quests.quests)
            if (quest.status != Quest.Todo)
            {
                quest.status = Quest.Todo;
                changed = true;
            }
        if (!changed)
            return;
        Changed?.Invoke();
    }

    /// <summary>Mark every quest whose <see cref="Quest.action"/> is this scene action done. Returns false if none matched.</summary>
    public bool CompleteByAction(string action)
    {
        if (string.IsNullOrEmpty(action))
            return false;
        bool any = false;
        foreach (var quest in Quests.quests)
            if (quest.action == action)
                any |= Complete(quest.id);
        return any;
    }

    public bool SetStatus(string id, string status)
    {
        var quest = Find(id);
        if (quest == null)
        {
            Debug.LogWarning($"QuestManager: no quest with id '{id}'.");
            return false;
        }
        if (quest.status == status)
            return true;

        quest.status = status;
        Changed?.Invoke();
        return true;
    }

    void OnDestroy()
    {
        if (Instance == this)
            Instance = null;
    }
}

[Serializable]
public class QuestList
{
    public string title = "";
    public Quest[] quests = Array.Empty<Quest>();
}

[Serializable]
public class Quest
{
    public const string Todo = "todo";
    public const string Done = "done";

    public string id;
    public string text;
    public string status = Todo;
    [Tooltip("Scene action from the conversation server that completes this quest (e.g. serve_order). Empty = manual.")]
    public string action = "";

    public bool IsDone => string.Equals(status, Done, StringComparison.OrdinalIgnoreCase);
}
