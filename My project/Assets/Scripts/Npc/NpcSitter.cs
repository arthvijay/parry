using System.Collections;
using UnityEngine;

/// <summary>
/// Sits the NPC in a <see cref="Seat"/>: the NPC root moves to the floor in
/// front of the chair, <see cref="NpcIdleAnimation"/> switches to the seated
/// idles, and every frame the avatar is shifted so the mocap pelvis lands on
/// the cushion (the Rocketbox actor and this avatar differ in size, and the
/// chair is whatever height the scanned world says it is). <see cref="Stand"/>
/// or any <see cref="NpcWalker.Walk"/> gets her up again.
/// </summary>
[RequireComponent(typeof(NpcAvatarLoader))]
public class NpcSitter : MonoBehaviour
{
    [Tooltip("Hip joint height above the cushion, metres at avatar scale 1.")]
    public float hipsAboveSeat = 0.12f;
    [Tooltip("Pelvis bone whose position is pinned to the seat.")]
    public string pelvisBone = "Bip01 Pelvis";
    [Tooltip("Seconds to ease the avatar onto the cushion when sitting down.")]
    public float settleTime = 0.5f;

    public Seat Seat { get; private set; }
    public bool IsSeated => Seat != null;

    NpcAvatarLoader loader;
    NpcIdleAnimation anim;
    NpcWalker walker;
    Transform pelvis;
    Vector3 standingAvatarOffset;   // AvatarRoot.localPosition before sitting
    float sitStart;
    Coroutine pending;

    void Awake()
    {
        loader = GetComponent<NpcAvatarLoader>();
        anim = GetComponent<NpcIdleAnimation>();
        walker = GetComponent<NpcWalker>();
        loader.Loaded += _ => pelvis = loader.FindBone(pelvisBone);
    }

    /// <summary>Sit in the seat with this id as soon as it exists (seats.json may load after us).</summary>
    public void Sit(string seatId)
    {
        if (pending != null)
            StopCoroutine(pending);
        pending = StartCoroutine(SitWhenAvailable(seatId));
    }

    IEnumerator SitWhenAvailable(string seatId)
    {
        float giveUp = Time.time + 10f;
        Seat seat = null;
        while (Time.time < giveUp && ((seat = SeatManager.Find(seatId)) == null || loader.AvatarRoot == null))
            yield return null;
        pending = null;
        if (seat == null)
        {
            Debug.LogWarning($"{name}: no seat '{seatId}' to sit in.");
            yield break;
        }
        Sit(seat);
    }

    public bool Sit(Seat seat)
    {
        if (seat == null || !seat.Claim(transform))
        {
            Debug.LogWarning($"{name}: seat '{seat?.id}' is taken.");
            return false;
        }
        if (Seat != null && Seat != seat)
            Seat.Release(transform);

        walker?.Stop();
        bool wasSeated = Seat != null;
        Seat = seat;
        if (!wasSeated && loader.AvatarRoot != null)
            standingAvatarOffset = loader.AvatarRoot.localPosition;
        sitStart = Time.time;

        transform.SetPositionAndRotation(seat.FloorInFront(0.35f * transform.lossyScale.y),
                                         Quaternion.Euler(0f, seat.Yaw, 0f));
        if (anim != null)
            anim.Sitting = true;
        return true;
    }

    /// <summary>Get up: release the seat, go back to the standing idles and feet-on-floor grounding.</summary>
    public void Stand()
    {
        if (pending != null)
        {
            StopCoroutine(pending);
            pending = null;
        }
        if (Seat == null)
            return;
        Seat.Release(transform);
        Seat = null;
        if (anim != null)
            anim.Sitting = false;
        if (loader.AvatarRoot != null)
        {
            loader.AvatarRoot.localPosition = standingAvatarOffset;
            loader.ReGroundFeet();
        }
    }

    void LateUpdate()
    {
        if (Seat == null || pelvis == null || loader.AvatarRoot == null)
            return;
        if (anim != null && !anim.HasSitClips)
            return; // standing pose: pinning the pelvis to the cushion would bury her legs

        // Where the clip put the pelvis this frame vs where the cushion is; shift the
        // whole avatar by the difference so the hips land on the seat and the feet go
        // wherever the pose puts them. The shift sticks (the clip only writes bones),
        // so after the first frame this is just correcting animation drift.
        Vector3 target = Seat.Position + Vector3.up * (hipsAboveSeat * transform.lossyScale.y);
        Vector3 delta = target - pelvis.position;
        bool settled = Time.time - sitStart >= settleTime;
        float k = settled || settleTime <= 0f ? 1f : Mathf.Clamp01(Time.deltaTime * 8f / settleTime);
        loader.AvatarRoot.position += delta * k;
    }

    void OnDestroy()
    {
        if (Seat != null)
            Seat.Release(transform);
    }
}
