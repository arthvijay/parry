using UnityEngine;

/// <summary>
/// The learner's own body at the table: the Rocketbox model chosen in onboarding, tinted
/// with the colours sampled from their selfie, sitting in their chair with the seated
/// mocap, and wearing their live face (<see cref="LocalFaceController"/>). Hidden in the
/// first-person view, shown when <see cref="DateCameraRig"/> cuts to the two-shot.
/// </summary>
[DefaultExecutionOrder(150)]
public class PlayerAvatar : MonoBehaviour
{
    public static PlayerAvatar Instance { get; private set; }

    [Tooltip("Avatar scale; the NPCs in the venue are 0.9.")]
    public float scale = 0.9f;
    public float hipsAboveSeat = 0.12f;
    public string pelvisBone = "Bip01 Pelvis";

    public bool Visible { get; private set; }
    public Transform Head { get; private set; }

    GameObject body;
    NpcAvatarLoader loader;
    NpcIdleAnimation anim;
    Transform pelvis;
    PlayerSeating seating;
    Seat seat;
    float seatedAt;

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
        if (body != null)
            Destroy(body);
    }

    void Start()
    {
        var fpc = FindFirstObjectByType<FirstPersonController>();
        seating = fpc != null ? fpc.GetComponent<PlayerSeating>() : null;
        var look = DateSession.Look;

        body = new GameObject("Player Avatar");
        body.transform.localScale = Vector3.one * scale;
        body.SetActive(false); // components first, then Awake/Start in order
        loader = body.AddComponent<NpcAvatarLoader>();
        loader.resourcePath = DateSession.AvatarResource(look.base_model);
        loader.snapToGround = false;
        loader.groundFeet = false;
        anim = body.AddComponent<NpcIdleAnimation>();
        var tint = body.AddComponent<AvatarTinter>();
        tint.skin = look.skin_hex;
        tint.hair = look.hair_hex;
        body.AddComponent<LocalFaceController>();
        loader.Loaded += root =>
        {
            pelvis = loader.FindBone(pelvisBone);
            Head = loader.FindBone("Bip01 Head");
            SetVisible(Visible);
        };
        body.SetActive(true);
    }

    public void SetVisible(bool visible)
    {
        Visible = visible;
        if (loader == null || loader.AvatarRoot == null)
            return;
        foreach (var r in loader.AvatarRoot.GetComponentsInChildren<Renderer>(true))
            r.enabled = visible;
    }

    public bool Seated => seat != null;

    void Update()
    {
        var current = seating != null ? seating.Seat : null;
        if (current == seat)
            return;
        seat = current;
        if (seat == null)
        {
            if (anim != null)
                anim.Sitting = false;
            SetVisible(false);
            return;
        }
        body.transform.SetPositionAndRotation(seat.FloorInFront(0.35f * scale), Quaternion.Euler(0f, seat.Yaw, 0f));
        if (anim != null)
            anim.Sitting = true;
        seatedAt = Time.time;
    }

    void LateUpdate()
    {
        if (seat == null || pelvis == null || loader.AvatarRoot == null || (anim != null && !anim.HasSitClips))
            return;
        // Hips on the cushion whatever the clip's actor size, as NpcSitter does for NPCs.
        Vector3 target = seat.Position + Vector3.up * (hipsAboveSeat * scale);
        float k = Time.time - seatedAt > 0.5f ? 1f : Mathf.Clamp01(Time.deltaTime * 16f);
        loader.AvatarRoot.position += (target - pelvis.position) * k;
    }
}
