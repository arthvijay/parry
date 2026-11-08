using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Moves the NPC along a list of world-space waypoints, keeping her feet on
/// whatever collider is below, and animates the walk. If
/// <see cref="NpcIdleAnimation"/> has a walk clip it is blended in; otherwise a
/// procedural gait (thigh/knee/arm swing plus a pelvis bob) is layered on top of
/// the idle mocap in LateUpdate, the same way <see cref="NpcLookAt"/> layers the
/// head. Call <see cref="Walk"/> or <see cref="WalkTo"/>; <see cref="NpcSchedule"/>
/// drives it from JSON.
/// </summary>
[RequireComponent(typeof(NpcAvatarLoader))]
public class NpcWalker : MonoBehaviour
{
    [Header("Movement")]
    public float walkSpeed = 0.8f;
    public float turnSpeed = 240f;
    [Tooltip("Waypoint counts as reached within this distance (m).")]
    public float arriveDistance = 0.05f;
    [Tooltip("Raycast from this high above the feet to find the floor each step.")]
    public float groundProbeHeight = 0.6f;
    public float groundProbeDepth = 2f;

    [Header("Procedural gait (used when no walk clip is set)")]
    [Tooltip("Metres the feet travel per full gait cycle, at avatar scale 1.")]
    public float strideLength = 1.3f;
    public float thighSwing = 28f;
    public float kneeBend = 45f;
    public float armSwing = 18f;
    public float elbowBend = 12f;
    [Tooltip("Vertical pelvis bob amplitude in metres, at avatar scale 1.")]
    public float bob = 0.02f;
    public float blendTime = 0.3f;

    [Header("Bones")]
    public string leftThigh = "Bip01 L Thigh";
    public string leftCalf = "Bip01 L Calf";
    public string rightThigh = "Bip01 R Thigh";
    public string rightCalf = "Bip01 R Calf";
    public string leftUpperArm = "Bip01 L UpperArm";
    public string leftForearm = "Bip01 L Forearm";
    public string rightUpperArm = "Bip01 R UpperArm";
    public string rightForearm = "Bip01 R Forearm";
    public string pelvis = "Bip01";

    public bool IsWalking => path.Count > 0;

    /// <summary>Walking, or arrived and still turning to the requested heading.</summary>
    public bool OwnsHeading => path.Count > 0 || settling;

    /// <summary>Fired when the last waypoint is reached (not for looping paths).</summary>
    public event Action Arrived;

    NpcAvatarLoader loader;
    NpcIdleAnimation anim;
    readonly List<Vector3> path = new();
    int target;
    int direction = 1;   // for ping-pong loops
    bool loop;
    float endYaw = float.NaN;
    bool settling;       // arrived, still turning to endYaw

    float phase;         // gait cycle, radians
    float weight;        // 0 = idle, 1 = walking
    Transform lThigh, lCalf, rThigh, rCalf, lArm, lFore, rArm, rFore, root;

    void Awake()
    {
        loader = GetComponent<NpcAvatarLoader>();
        anim = GetComponent<NpcIdleAnimation>();
        loader.Loaded += OnAvatarLoaded;
    }

    void OnAvatarLoaded(Transform avatar)
    {
        lThigh = loader.FindBone(leftThigh);
        lCalf = loader.FindBone(leftCalf);
        rThigh = loader.FindBone(rightThigh);
        rCalf = loader.FindBone(rightCalf);
        lArm = loader.FindBone(leftUpperArm);
        lFore = loader.FindBone(leftForearm);
        rArm = loader.FindBone(rightUpperArm);
        rFore = loader.FindBone(rightForearm);
        root = loader.FindBone(pelvis);
        if (lThigh == null || rThigh == null)
            Debug.LogWarning($"{name}: leg bones not found; walk will slide without animating.");
    }

    /// <summary>Walk through the given world-space waypoints in order.</summary>
    public void Walk(IList<Vector3> waypoints, float speed = 0f, float finalYaw = float.NaN, bool pingPong = false)
    {
        path.Clear();
        if (waypoints != null)
            path.AddRange(waypoints);
        if (path.Count == 0)
            return;

        // Walking starts from standing.
        var sitter = GetComponent<NpcSitter>();
        if (sitter != null && sitter.IsSeated)
            sitter.Stand();

        if (speed > 0f)
            walkSpeed = speed;
        endYaw = finalYaw;
        loop = pingPong && path.Count > 1;
        target = 0;
        direction = 1;
        settling = false;
    }

    public void WalkTo(Vector3 destination, float speed = 0f, float finalYaw = float.NaN)
        => Walk(new[] { destination }, speed, finalYaw);

    /// <summary>Stop where she stands and fade back to idle.</summary>
    public void Stop()
    {
        path.Clear();
        settling = false;
    }

    void Update()
    {
        if (settling)
        {
            settling = TurnTowards(Quaternion.Euler(0f, endYaw, 0f));
            return;
        }
        if (path.Count == 0)
            return;

        Vector3 pos = transform.position;
        Vector3 goal = path[target];
        Vector3 to = goal - pos;
        to.y = 0f;
        float dist = to.magnitude;

        float step = walkSpeed * Time.deltaTime;
        if (dist > 0.001f)
        {
            TurnTowards(Quaternion.LookRotation(to));
            pos += to / dist * Mathf.Min(step, dist);
        }
        // Foot travel drives the gait so the stride never slides, whatever the speed.
        phase += Mathf.Min(step, dist) / Mathf.Max(0.1f, strideLength * transform.lossyScale.y) * 2f * Mathf.PI;

        transform.position = Ground(pos);

        if (dist <= Mathf.Max(arriveDistance, step))
            NextWaypoint();
    }

    void NextWaypoint()
    {
        if (loop)
        {
            if (target + direction < 0 || target + direction >= path.Count)
                direction = -direction;
            target += direction;
            return;
        }
        if (++target < path.Count)
            return;

        path.Clear();
        settling = !float.IsNaN(endYaw);
        Arrived?.Invoke();
    }

    /// <summary>Returns true while still turning.</summary>
    bool TurnTowards(Quaternion rotation)
    {
        transform.rotation = Quaternion.RotateTowards(transform.rotation, rotation, turnSpeed * Time.deltaTime);
        return Quaternion.Angle(transform.rotation, rotation) > 0.5f;
    }

    Vector3 Ground(Vector3 pos)
    {
        Vector3 from = pos + Vector3.up * groundProbeHeight;
        float best = float.MaxValue;
        foreach (var hit in Physics.RaycastAll(from, Vector3.down, groundProbeHeight + groundProbeDepth, ~0, QueryTriggerInteraction.Ignore))
            if (!hit.transform.IsChildOf(transform) && hit.distance < best) // skip our own interaction capsule
                best = hit.distance;
        if (best < float.MaxValue)
            pos.y = from.y - best;
        return pos;
    }

    void LateUpdate()
    {
        bool walking = path.Count > 0;
        weight = Mathf.MoveTowards(weight, walking ? 1f : 0f, Time.deltaTime / Mathf.Max(0.01f, blendTime));

        if (anim != null && anim.HasWalkClip)
        {
            anim.WalkWeight = weight;
            return;
        }
        if (weight <= 0f || lThigh == null)
            return;

        // Rotate about the character's lateral axis in world space so the result
        // doesn't depend on the Biped bones' local axes. In Unity a positive
        // rotation about +right swings a hanging limb backwards, so forward = -angle.
        Vector3 right = transform.right;
        float s = Mathf.Sin(phase);
        float legL = thighSwing * s;                 // left leg forward at phase = pi/2
        float legR = -legL;
        float kneeL = kneeBend * Mathf.Max(0f, Mathf.Cos(phase));      // bent mid-swing (moving forward)
        float kneeR = kneeBend * Mathf.Max(0f, -Mathf.Cos(phase));

        Swing(lThigh, -legL, right);
        Swing(lCalf, kneeL, right);
        Swing(rThigh, -legR, right);
        Swing(rCalf, kneeR, right);

        // Arms counter-swing the legs; elbows stay slightly bent.
        Swing(lArm, armSwing * s, right);
        Swing(lFore, -elbowBend * (1f + 0.5f * s), right);
        Swing(rArm, -armSwing * s, right);
        Swing(rFore, -elbowBend * (1f - 0.5f * s), right);

        // The idle clip rewrites the root position every frame, so this offset
        // doesn't accumulate; without a clip it would, so skip it.
        if (root != null && anim != null && anim.IsPlaying)
        {
            // Highest at mid-stance (one leg vertical), lowest at double support.
            float lift = Mathf.Cos(2f * phase) * 0.5f - 0.5f;
            root.position += Vector3.up * (lift * bob * transform.lossyScale.y * weight);
        }
    }

    void Swing(Transform bone, float degrees, Vector3 axis)
    {
        if (bone != null)
            bone.rotation = Quaternion.AngleAxis(degrees * weight, axis) * bone.rotation;
    }

    void OnDrawGizmosSelected()
    {
        if (path.Count == 0)
            return;
        Gizmos.color = Color.cyan;
        Vector3 prev = transform.position;
        for (int i = 0; i < path.Count; i++)
        {
            Gizmos.DrawLine(prev, path[i]);
            Gizmos.DrawSphere(path[i], 0.05f);
            prev = path[i];
        }
    }
}
