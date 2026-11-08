using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// What the date can see of the player, measured every frame and sent with the stream's
/// telemetry every 250 ms: whether the player's view is on the date's face (a cone around
/// the eyes, with nothing in between), whether they are looking down at the table or off
/// into the room, how long they have been looking away, how far they are, and whether
/// they are seated. When the webcam is on and shows the learner's head turned well away
/// from the screen, that counts as looking away too, whatever the camera says.
/// </summary>
public class SpatialTelemetryBroadcaster : MonoBehaviour
{
    public static SpatialTelemetryBroadcaster Instance { get; private set; }

    [Tooltip("Degrees around the date's eyes that count as eye contact.")]
    public float eyeContactAngle = 13f;
    [Tooltip("Degrees of webcam head yaw beyond which the learner is looking away from the screen.")]
    public float screenYawLimit = 32f;
    public string eyeBone = "Bip01 Head";

    public bool LookingAtDate { get; private set; } = true;
    public string GazeTarget { get; private set; } = "unknown";
    public float LookAwaySeconds { get; private set; }
    public float Distance { get; private set; }
    public bool Seated { get; private set; }

    Transform eyes;
    PlayerSeating seating;
    GameObject date;
    Transform dateEyes;

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
        if (Instance == this)
            Instance = null;
    }

    public void SetDate(GameObject npc)
    {
        date = npc;
        dateEyes = null;
    }

    void Update()
    {
        if (eyes == null)
        {
            var fpc = FindFirstObjectByType<FirstPersonController>();
            if (fpc != null)
            {
                eyes = fpc.cameraTransform != null ? fpc.cameraTransform : fpc.transform;
                seating = fpc.GetComponent<PlayerSeating>();
            }
        }
        if (date == null)
            date = CastClient.Date;
        if (date != null && dateEyes == null)
        {
            var loader = date.GetComponent<NpcAvatarLoader>();
            dateEyes = loader != null ? loader.FindBone(eyeBone) : null;
        }
        Seated = seating != null && seating.IsSeated;
        if (eyes == null || date == null)
            return;

        Vector3 target = dateEyes != null ? dateEyes.position + Vector3.up * 0.04f : date.transform.position + Vector3.up * 1.2f;
        Vector3 to = target - eyes.position;
        Distance = to.magnitude;
        float angle = Vector3.Angle(eyes.forward, to);
        bool inCone = angle < eyeContactAngle && Distance < 6f;
        if (inCone && Physics.Raycast(eyes.position, to.normalized, out var hit, Distance - 0.15f, ~0, QueryTriggerInteraction.Ignore))
            inCone = hit.transform.IsChildOf(date.transform);

        var vision = VisionFeed.Instance;
        bool facingScreen = vision == null || !vision.HasFace || Mathf.Abs(vision.HeadYaw) < screenYawLimit;
        LookingAtDate = inCone && facingScreen;

        if (LookingAtDate)
            GazeTarget = "date_npc_eyes";
        else if (!facingScreen)
            GazeTarget = "away_from_screen";
        else if (eyes.forward.y < -0.35f && angle < 50f)
            GazeTarget = "table";
        else
            GazeTarget = "room";

        LookAwaySeconds = LookingAtDate ? 0f : LookAwaySeconds + Time.deltaTime;
    }

    public Dictionary<string, object> Snapshot() => new()
    {
        ["is_looking_at_date"] = LookingAtDate,
        ["gaze_target"] = GazeTarget,
        ["look_away_duration_sec"] = Mathf.Round(LookAwaySeconds * 100f) / 100f,
        ["distance_m"] = Mathf.Round(Distance * 100f) / 100f,
        ["is_seated"] = Seated,
    };
}
