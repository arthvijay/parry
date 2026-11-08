using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Puts the learner's face on an avatar. Every ARKit blendshape the face tracker reads
/// (smile, jaw, brows, blinks, cheek, eye look…) is set on the avatar's matching shape,
/// and the head's yaw, pitch and roll turn the head bone, smoothed and clamped so a lost
/// frame never snaps the neck. Works on the onboarding preview and on the seated player
/// avatar the cinematic camera shows across the table.
/// </summary>
[DefaultExecutionOrder(250)]
public class LocalFaceController : MonoBehaviour
{
    [Tooltip("Avatar root to drive; empty = this object's NpcAvatarLoader avatar.")]
    public Transform avatarRoot;
    public string headBone = "Bip01 Head";
    [Tooltip("Mirror left/right, so the avatar moves like a reflection of the learner.")]
    public bool mirror = true;
    [Range(0f, 2f)] public float expressionGain = 1.2f;
    public float maxYaw = 40f, maxPitch = 25f, maxRoll = 20f;
    public float smoothing = 14f;
    [Tooltip("Flip signs if the rig turns the wrong way.")]
    public Vector3 headAxisSigns = new(1f, 1f, 1f);

    FaceRig face;
    Transform head;
    Transform root;
    float yaw, pitch, roll;
    readonly Dictionary<string, float> weights = new();

    void Start()
    {
        var loader = GetComponent<NpcAvatarLoader>();
        if (avatarRoot != null)
            Bind(avatarRoot);
        else if (loader != null)
        {
            loader.Loaded += Bind;
            if (loader.AvatarRoot != null)
                Bind(loader.AvatarRoot);
        }
    }

    public void Bind(Transform target)
    {
        root = target;
        face = new FaceRig(target);
        head = null;
        foreach (var t in target.GetComponentsInChildren<Transform>())
            if (t.name == headBone)
                head = t;
    }

    void LateUpdate()
    {
        var feed = VisionFeed.Instance;
        if (feed == null || root == null || face == null)
            return;
        bool fresh = feed.HasFace && Time.unscaledTime - feed.LastReadingAt < 0.6f;
        float k = 1f - Mathf.Exp(-smoothing * Time.deltaTime);

        foreach (var pair in feed.Blendshapes)
        {
            string name = mirror ? Mirror(pair.Key) : pair.Key;
            float target = fresh ? Mathf.Clamp01(pair.Value * expressionGain) * 100f : 0f;
            weights.TryGetValue(name, out float current);
            float w = Mathf.Lerp(current, target, k);
            weights[name] = w;
            face.Set(name, w);
        }

        float side = mirror ? -1f : 1f;
        yaw = Mathf.Lerp(yaw, fresh ? Mathf.Clamp(feed.HeadYaw * side, -maxYaw, maxYaw) : 0f, k);
        pitch = Mathf.Lerp(pitch, fresh ? Mathf.Clamp(feed.HeadPitch, -maxPitch, maxPitch) : 0f, k);
        roll = Mathf.Lerp(roll, fresh ? Mathf.Clamp(feed.HeadRoll * side, -maxRoll, maxRoll) : 0f, k);
        if (head != null)
        {
            // Around the character's own axes, on top of whatever the idle pose did.
            var body = root.parent != null ? root.parent : root;
            head.rotation = Quaternion.AngleAxis(yaw * headAxisSigns.x, body.up)
                          * Quaternion.AngleAxis(-pitch * headAxisSigns.y, body.right)
                          * Quaternion.AngleAxis(roll * headAxisSigns.z, body.forward)
                          * head.rotation;
        }
    }

    /// <summary>mouthSmileLeft ↔ mouthSmileRight, so the avatar mirrors the learner.</summary>
    static string Mirror(string name)
    {
        if (name.EndsWith("Left"))
            return name.Substring(0, name.Length - 4) + "Right";
        if (name.EndsWith("Right"))
            return name.Substring(0, name.Length - 5) + "Left";
        return name;
    }
}
