using System;
using UnityEngine;

/// <summary>
/// A place to sit. The splat world has no chair objects, so seats are anchors
/// placed from seats.json (see <see cref="SeatManager"/>): the transform sits on
/// the cushion, facing the way the sitter will face. Exactly one occupant at a
/// time, NPC (<see cref="NpcSitter"/>) or player (<see cref="PlayerSeating"/>).
/// </summary>
public class Seat : MonoBehaviour
{
    public string id = "";
    [Tooltip("Whether the player may take this seat (NPCs always can).")]
    public bool playerCanSit = true;
    [Tooltip("Cushion height above the floor, used only when nothing is found below the seat.")]
    public float heightAboveFloor = 0.6f;

    /// <summary>Who is sitting here, or null.</summary>
    public Transform Occupant { get; private set; }
    public bool IsFree => Occupant == null;

    /// <summary>Point on the cushion where the hips go.</summary>
    public Vector3 Position => transform.position;
    /// <summary>Direction the sitter faces (horizontal).</summary>
    public Vector3 Forward => transform.forward;
    public float Yaw => transform.eulerAngles.y;

    public event Action Changed;

    public bool Claim(Transform who)
    {
        if (Occupant != null && Occupant != who)
            return false;
        Occupant = who;
        Changed?.Invoke();
        return true;
    }

    public void Release(Transform who)
    {
        if (Occupant != who)
            return;
        Occupant = null;
        Changed?.Invoke();
    }

    /// <summary>
    /// Floor point in front of the chair where the sitter's feet go: raycast down
    /// just ahead of the cushion so the chair itself isn't hit.
    /// </summary>
    public Vector3 FloorInFront(float ahead = 0.35f)
    {
        Vector3 probe = Position + Forward * ahead + Vector3.up * 0.2f;
        float best = float.MaxValue;
        foreach (var hit in Physics.RaycastAll(probe, Vector3.down, 3f, ~0, QueryTriggerInteraction.Ignore))
            if (!hit.transform.IsChildOf(transform) && hit.distance < best)
                best = hit.distance;
        float y = best < float.MaxValue ? probe.y - best : Position.y - heightAboveFloor;
        return new Vector3(probe.x, y, probe.z);
    }

    void OnEnable() => SeatManager.Register(this);

    void OnDisable()
    {
        SeatManager.Unregister(this);
        Occupant = null;
    }

    void OnDrawGizmos()
    {
        Gizmos.color = IsFree ? new Color(0.3f, 0.9f, 0.3f) : new Color(0.9f, 0.4f, 0.2f);
        Gizmos.DrawWireCube(Position, new Vector3(0.4f, 0.04f, 0.4f));
        Gizmos.DrawLine(Position, Position + Forward * 0.3f);
    }
}
