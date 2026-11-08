using UnityEngine;
using UnityEngine.InputSystem;

/// <summary>
/// Lets the player sit down: near a free <see cref="Seat"/> a prompt appears,
/// the sit key parks the camera on the chair facing the seat's direction and
/// disables walking; the sit key again (or any movement key) stands back up
/// where they were. Talking to NPCs keeps working while seated.
/// </summary>
[RequireComponent(typeof(FirstPersonController), typeof(CharacterController))]
public class PlayerSeating : MonoBehaviour
{
    [Tooltip("Sit / stand. E is push-to-talk, so this is separate.")]
    public Key sitKey = Key.F;
    [Tooltip("A seat this close to the player (metres) can be taken.")]
    public float sitRange = 1.6f;
    [Tooltip("Eye height above the cushion when seated, metres.")]
    public float eyeAboveSeat = 0.8f;
    [Tooltip("Seconds to glide onto / off the chair.")]
    public float transitionTime = 0.35f;
    public int fontSize = 20;

    public Seat Seat { get; private set; }
    public bool IsSeated => Seat != null;

    FirstPersonController fpc;
    CharacterController controller;
    Seat nearby;
    Vector3 standPosition;
    Quaternion standRotation;
    Vector3 fromPos, toPos;
    Quaternion fromRot, toRot;
    float moveStart = -1f;
    bool standingUp;

    void Awake()
    {
        fpc = GetComponent<FirstPersonController>();
        controller = GetComponent<CharacterController>();
    }

    void Update()
    {
        var keyboard = Keyboard.current;
        if (keyboard == null || Cursor.lockState != CursorLockMode.Locked)
            return;

        if (moveStart >= 0f)
        {
            Glide();
            return;
        }

        if (Seat != null)
        {
            bool moveKey = keyboard.wKey.wasPressedThisFrame || keyboard.aKey.wasPressedThisFrame
                        || keyboard.sKey.wasPressedThisFrame || keyboard.dKey.wasPressedThisFrame
                        || keyboard.spaceKey.wasPressedThisFrame;
            if (keyboard[sitKey].wasPressedThisFrame || moveKey)
                Stand();
            return;
        }

        nearby = SeatManager.Nearest(transform.position, sitRange, s => s.playerCanSit && s.IsFree);
        if (nearby != null && keyboard[sitKey].wasPressedThisFrame)
            Sit(nearby);
    }

    public bool Sit(Seat seat)
    {
        if (seat == null || !seat.Claim(transform))
            return false;
        Seat = seat;
        nearby = null;
        standPosition = transform.position;
        standRotation = transform.rotation;

        // Camera is a child at some local height; put the root where the eyes end
        // up eyeAboveSeat over the cushion.
        float cameraRise = fpc.cameraTransform != null
            ? fpc.cameraTransform.position.y - transform.position.y : 0f;
        BeginGlide(seat.Position + Vector3.up * (eyeAboveSeat - cameraRise), Quaternion.Euler(0f, seat.Yaw, 0f));
        fpc.CanMove = false;
        controller.enabled = false;
        standingUp = false;
        return true;
    }

    public void Stand()
    {
        if (Seat == null)
            return;
        Seat.Release(transform);
        Seat = null;
        standingUp = true;
        BeginGlide(standPosition, Quaternion.Euler(0f, transform.eulerAngles.y, 0f));
    }

    void BeginGlide(Vector3 pos, Quaternion rot)
    {
        fromPos = transform.position;
        fromRot = transform.rotation;
        toPos = pos;
        toRot = rot;
        moveStart = Time.time;
    }

    void Glide()
    {
        float t = transitionTime > 0f ? Mathf.Clamp01((Time.time - moveStart) / transitionTime) : 1f;
        t = Mathf.SmoothStep(0f, 1f, t);
        transform.SetPositionAndRotation(Vector3.Lerp(fromPos, toPos, t), Quaternion.Slerp(fromRot, toRot, t));
        if (t < 1f)
            return;
        moveStart = -1f;
        if (standingUp)
        {
            standingUp = false;
            controller.enabled = true;
            fpc.CanMove = true;
        }
    }

    void OnGUI()
    {
        if (Cursor.lockState != CursorLockMode.Locked || moveStart >= 0f)
            return;
        bool dateOn = FullDuplexStreamClient.Instance != null && FullDuplexStreamClient.Instance.DateRunning;
        string text = Seat != null ? (dateOn ? "V  switch camera" : $"{sitKey}  stand up")
                    : nearby != null ? $"{sitKey}  sit down"
                    : null;
        if (text == null)
            return;
        var m = GlassUI.Begin();
        float w = GlassUI.TextWidth(text, 15) + 40f;
        var r = new Rect((GlassUI.Width - w) / 2f, GlassUI.Height * 0.8f - 48f, w, 36f);
        GlassUI.Panel(r);
        GlassUI.Label(r, text, 15, Color.white, FontStyle.Bold, TextAnchor.MiddleCenter);
        GlassUI.End(m);
    }
}
