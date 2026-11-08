using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

/// <summary>
/// Places one <see cref="Seat"/> per entry of StreamingAssets/seats.json and
/// re-reads the file when it changes, like <see cref="NpcManager"/>. Seats put
/// in the scene by hand register too.
///
/// <code>
/// { "seats": [
///   { "id": "table_a", "position": {"x": 1.1, "y": -0.9, "z": 8.7}, "yaw": 90, "playerCanSit": true }
/// ] }
/// </code>
/// position = point on the cushion (world), yaw = direction the sitter faces (0 = +Z).
/// </summary>
public class SeatManager : MonoBehaviour
{
    public static SeatManager Instance { get; private set; }

    [Tooltip("JSON file under StreamingAssets.")]
    public string fileName = "seats.json";
    [Tooltip("Rebuild the seats when the file changes on disk.")]
    public bool watchFile = true;

    [Header("Speed date")]
    [Tooltip("With no seats in the file, lay out a two-top in front of the player: table_a for the date, table_b for the player.")]
    public bool autoTwoTop = true;
    [Tooltip("Metres between the two chairs of the automatic two-top.")]
    public float twoTopGap = 1.3f;
    [Tooltip("Add the V-key first-person / cinematic camera to the player.")]
    public bool dateCamera = true;

#pragma warning disable 0649 // DTO fields are filled by JsonUtility
    [Serializable]
    public class SeatDefinition
    {
        public string id;
        public Vector3 position;
        public float yaw;
        public bool playerCanSit = true;
        public float heightAboveFloor = 0.6f;
    }

    [Serializable]
    public class SeatList
    {
        public SeatDefinition[] seats = Array.Empty<SeatDefinition>();
    }
#pragma warning restore 0649

    /// <summary>Every live seat, JSON-spawned or hand-placed.</summary>
    public static IReadOnlyList<Seat> All => all;
    static readonly List<Seat> all = new();

    /// <summary>Fired after the JSON seats are (re)built.</summary>
    public event Action Changed;

    readonly List<GameObject> spawned = new();
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
        var player = FindFirstObjectByType<FirstPersonController>();
        if (dateCamera && player != null && player.GetComponent<DateCameraRig>() == null)
            player.gameObject.AddComponent<DateCameraRig>();
        if (autoTwoTop && spawned.Count == 0 && player != null)
            StartCoroutine(TwoTop(player.transform));
    }

    /// <summary>
    /// A table for two where the world has none authored: two chairs facing each other a
    /// short way in front of the player's spawn, each set on whatever floor the collider
    /// finds below (the generated world's collider loads a few frames in).
    /// </summary>
    System.Collections.IEnumerator TwoTop(Transform player)
    {
        yield return new WaitForSeconds(1.5f);
        if (Find("table_a") != null)
            yield break;
        Vector3 forward = Vector3.ProjectOnPlane(player.forward, Vector3.up).normalized;
        if (forward.sqrMagnitude < 0.01f)
            forward = Vector3.forward;
        Vector3 centre = player.position + forward * 2.2f;
        float yaw = Quaternion.LookRotation(forward).eulerAngles.y;
        MakeSeat("table_a", centre + forward * (twoTopGap / 2f), yaw + 180f, false);
        MakeSeat("table_b", centre - forward * (twoTopGap / 2f), yaw, true);
        Debug.Log("SeatManager: no authored seats; laid out a two-top in front of the player");
        Changed?.Invoke();
    }

    void MakeSeat(string id, Vector3 position, float yaw, bool playerCanSit)
    {
        Vector3 top = position + Vector3.up * 2f;
        float floor = position.y - 1f;
        if (Physics.Raycast(top, Vector3.down, out var hit, 6f, ~0, QueryTriggerInteraction.Ignore))
            floor = hit.point.y;
        var go = new GameObject($"Seat {id}");
        go.transform.SetParent(transform, worldPositionStays: false);
        go.transform.SetPositionAndRotation(new Vector3(position.x, floor + 0.47f, position.z), Quaternion.Euler(0f, yaw, 0f));
        var seat = go.AddComponent<Seat>();
        seat.id = id;
        seat.playerCanSit = playerCanSit;
        seat.heightAboveFloor = 0.47f;
        Register(seat);
        spawned.Add(go);
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
            Debug.Log($"SeatManager: {FilePath} not found; no seats.");
            return;
        }

        SeatList list;
        try
        {
            list = JsonUtility.FromJson<SeatList>(File.ReadAllText(FilePath)) ?? new SeatList();
            lastWrite = File.GetLastWriteTimeUtc(FilePath);
        }
        catch (Exception e)
        {
            Debug.LogError($"SeatManager: could not parse {FilePath}: {e.Message}");
            return;
        }

        foreach (var go in spawned)
            if (go != null)
                Destroy(go);
        spawned.Clear();
        all.RemoveAll(s => s == null);

        foreach (var def in list.seats)
        {
            if (def == null)
                continue;
            var go = new GameObject($"Seat {def.id}");
            go.transform.SetParent(transform, worldPositionStays: false);
            go.transform.SetPositionAndRotation(def.position, Quaternion.Euler(0f, def.yaw, 0f));
            var seat = go.AddComponent<Seat>();
            seat.id = def.id ?? "";
            seat.playerCanSit = def.playerCanSit;
            seat.heightAboveFloor = def.heightAboveFloor;
            Register(seat);
            spawned.Add(go);
        }
        Debug.Log($"SeatManager: {spawned.Count} seat(s) from {fileName}");
        Changed?.Invoke();
    }

    public static void Register(Seat seat)
    {
        if (seat != null && !all.Contains(seat))
            all.Add(seat);
    }

    public static void Unregister(Seat seat) => all.Remove(seat);

    /// <summary>Seat by id, or null (also finds hand-placed seats).</summary>
    public static Seat Find(string id)
    {
        if (string.IsNullOrEmpty(id))
            return null;
        all.RemoveAll(s => s == null);
        foreach (var seat in all)
            if (seat.id == id)
                return seat;
        return null;
    }

    /// <summary>Closest seat to a point within maxDistance that passes the filter, or null.</summary>
    public static Seat Nearest(Vector3 point, float maxDistance, Func<Seat, bool> filter = null)
    {
        all.RemoveAll(s => s == null);
        Seat best = null;
        float bestDist = maxDistance;
        foreach (var seat in all)
        {
            if (filter != null && !filter(seat))
                continue;
            float d = Vector3.Distance(point, seat.Position);
            if (d <= bestDist)
            {
                bestDist = d;
                best = seat;
            }
        }
        return best;
    }

    void OnDestroy()
    {
        if (Instance == this)
            Instance = null;
    }
}
