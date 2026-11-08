using UnityEngine;
using UnityEngine.InputSystem;

/// <summary>
/// The two ways to watch the date, toggled with V while seated. First person: eyes over
/// the cushion, facing the date across the table (the default; gaze is eye contact).
/// Cinematic: an over-the-shoulder two-shot from behind the learner's chair, framing the
/// learner's own avatar (wearing their live face) and the date reacting to them, with a
/// slow handheld drift. The first-person camera keeps tracking the mouse underneath, so
/// gaze telemetry carries on in either view.
/// </summary>
public class DateCameraRig : MonoBehaviour
{
    public enum Mode { FirstPerson, Cinematic }

    public Key toggleKey = Key.V;
    public Mode mode = Mode.FirstPerson;
    [Tooltip("Shoulder offset of the cinematic camera from the learner's seat (right, up, back), metres.")]
    public Vector3 shoulder = new(0.55f, 1.25f, 0.95f);
    public float fieldOfView = 42f;
    public float blendSeconds = 0.6f;

    FirstPersonController fpc;
    PlayerSeating seating;
    Camera fpCamera;
    Camera cinematic;
    float blend;          // 0 = first person, 1 = cinematic
    Vector3 lookPoint;

    public bool IsCinematic => mode == Mode.Cinematic;

    void Start()
    {
        fpc = GetComponent<FirstPersonController>();
        seating = GetComponent<PlayerSeating>();
        fpCamera = fpc != null && fpc.cameraTransform != null ? fpc.cameraTransform.GetComponent<Camera>() : Camera.main;
        if (fpCamera == null)
            return;
        var go = new GameObject("Cinematic Date Camera");
        cinematic = go.AddComponent<Camera>();
        cinematic.CopyFrom(fpCamera);
        cinematic.fieldOfView = fieldOfView;
        cinematic.depth = fpCamera.depth + 1;
        cinematic.enabled = false;
    }

    void OnDestroy()
    {
        if (cinematic != null)
            Destroy(cinematic.gameObject);
    }

    void Update()
    {
        if (cinematic == null)
            return;
        var kb = Keyboard.current;
        bool seated = seating != null && seating.IsSeated;
        if (kb != null && kb[toggleKey].wasPressedThisFrame && seated && Cursor.lockState == CursorLockMode.Locked)
            mode = mode == Mode.FirstPerson ? Mode.Cinematic : Mode.FirstPerson;
        if (!seated)
            mode = Mode.FirstPerson;

        float target = mode == Mode.Cinematic ? 1f : 0f;
        blend = Mathf.MoveTowards(blend, target, Time.deltaTime / Mathf.Max(0.05f, blendSeconds));
        bool showCinematic = blend > 0.001f;
        cinematic.enabled = showCinematic;
        fpCamera.enabled = !showCinematic; // the cinematic camera covers the whole screen
        if (PlayerAvatar.Instance != null)
            PlayerAvatar.Instance.SetVisible(showCinematic);
        if (!showCinematic)
            return;

        // Where the shot wants to be, then eased from the first-person pose.
        var seat = seating.Seat;
        Vector3 right = seat.transform.right, forward = seat.Forward;
        Vector3 shotPos = seat.Position + right * shoulder.x + Vector3.up * shoulder.y - forward * shoulder.z;
        var date = CastClient.Date;
        Vector3 dateHead = date != null ? date.transform.position + Vector3.up * 1.15f : seat.Position + forward * 1.5f + Vector3.up * 1f;
        Vector3 me = PlayerAvatar.Instance != null && PlayerAvatar.Instance.Head != null
            ? PlayerAvatar.Instance.Head.position : seat.Position + Vector3.up * 0.7f;
        Vector3 wanted = Vector3.Lerp(me, dateHead, 0.62f);
        lookPoint = lookPoint == Vector3.zero ? wanted : Vector3.Lerp(lookPoint, wanted, 1f - Mathf.Exp(-3f * Time.deltaTime));
        // A slow handheld drift, so the shot breathes.
        float t = Time.time;
        shotPos += right * (Mathf.Sin(t * 0.37f) * 0.03f) + Vector3.up * (Mathf.Sin(t * 0.51f) * 0.02f);
        var shotRot = Quaternion.LookRotation(lookPoint - shotPos, Vector3.up);

        float e = Mathf.SmoothStep(0f, 1f, blend);
        var from = fpCamera.transform;
        cinematic.transform.SetPositionAndRotation(Vector3.Lerp(from.position, shotPos, e),
                                                   Quaternion.Slerp(from.rotation, shotRot, e));
        cinematic.fieldOfView = Mathf.Lerp(fpCamera.fieldOfView, fieldOfView, e);
    }
}
