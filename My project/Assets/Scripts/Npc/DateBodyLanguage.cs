using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// How the date feels, shown on their body. The chemistry director's posture drives it:
/// at 70 or more they lean in and smile (mouthSmile +0.4) with a slight head tilt; from
/// 40 they sit neutral; below 40 they lean back, the smile goes and a faint frown comes.
/// They blink, laugh when the learner laughs at a good moment, and raise their brows when
/// surprised. Rotations are layered on the mocap pose in world space around the
/// character's own axes, so they do not depend on how the rig's bones are oriented.
/// </summary>
[DefaultExecutionOrder(200)]
[RequireComponent(typeof(NpcAvatarLoader))]
public class DateBodyLanguage : MonoBehaviour
{
    [Range(0f, 1f)] public float restingSmile = 0.15f;
    public string spineBone = "Bip01 Spine1";
    public string headBone = "Bip01 Head";
    [Tooltip("Degrees the upper body leans toward the learner when it is going well.")]
    public float leanForward = 8f;
    [Tooltip("Degrees it leans away when it is not.")]
    public float leanBack = -7f;
    public float easeSpeed = 2.5f;

    public int Chemistry { get; private set; } = 50;
    public string Posture { get; private set; } = "neutral";

    NpcAvatarLoader loader;
    NpcSpeaker speaker;
    FaceRig face;
    Transform spine, head;
    float lean, tilt, smile, frown, brow, laugh;
    float nextBlink, blinkUntil;
    float reactUntil;

    void Awake()
    {
        loader = GetComponent<NpcAvatarLoader>();
        speaker = GetComponent<NpcSpeaker>();
        loader.Loaded += Bind;
        if (loader.AvatarRoot != null)
            Bind(loader.AvatarRoot); // added after the avatar appeared
        nextBlink = Time.time + Random.Range(1.5f, 4f);
        smile = restingSmile * 100f;
    }

    void Bind(Transform root)
    {
        face = new FaceRig(root);
        spine = loader.FindBone(spineBone);
        head = loader.FindBone(headBone);
    }

    void OnEnable()
    {
        if (FullDuplexStreamClient.Instance != null)
            FullDuplexStreamClient.Instance.Message += OnMessage;
    }

    void OnDisable()
    {
        if (FullDuplexStreamClient.Instance != null)
            FullDuplexStreamClient.Instance.Message -= OnMessage;
    }

    void OnMessage(string type, Dictionary<string, object> msg)
    {
        if (type == "chemistry_update")
        {
            Chemistry = msg.Int("chemistry_score", Chemistry);
            Posture = msg.Str("npc_posture", Posture);
        }
        else if (type == "signal")
        {
            string kind = msg.Str("kind");
            if (kind == "laugh" || (kind == "smile" && Chemistry >= 50))
            {
                laugh = kind == "laugh" ? 1f : 0.5f;
                reactUntil = Time.time + 1.6f;
            }
        }
    }

    void LateUpdate()
    {
        float dt = Time.deltaTime;
        float k = 1f - Mathf.Exp(-easeSpeed * dt);
        bool good = Posture == "lean_forward_smile";
        bool bad = Posture == "lean_back_glance_away";
        bool talking = speaker != null && speaker.IsSpeaking;

        lean = Mathf.Lerp(lean, good ? leanForward : bad ? leanBack : 0f, k);
        tilt = Mathf.Lerp(tilt, good && !talking ? 5f : 0f, k);
        float reacting = Time.time < reactUntil ? laugh : 0f;
        float smileTarget = restingSmile * 100f + (good ? 40f : bad ? -restingSmile * 100f : 0f) + reacting * 45f;
        smile = Mathf.Lerp(smile, Mathf.Clamp(smileTarget, 0f, 100f), k * 1.5f);
        frown = Mathf.Lerp(frown, bad ? 25f : 0f, k);
        brow = Mathf.Lerp(brow, reacting > 0.9f ? 35f : good ? 10f : 0f, k);

        if (spine != null)
            spine.rotation = Quaternion.AngleAxis(lean, transform.right) * spine.rotation;
        if (head != null && Mathf.Abs(tilt) > 0.01f)
            head.rotation = Quaternion.AngleAxis(tilt, transform.forward) * head.rotation;

        if (face == null || face.Empty)
            return;
        face.Set("MouthSmileLeft", smile);
        face.Set("MouthSmileRight", smile);
        face.Set("CheekSquintLeft", smile * 0.35f);
        face.Set("CheekSquintRight", smile * 0.35f);
        face.Set("MouthFrownLeft", frown);
        face.Set("MouthFrownRight", frown);
        face.Set("BrowInnerUp", brow);

        // Blinks, a little more often when interested.
        if (Time.time >= nextBlink)
        {
            blinkUntil = Time.time + 0.12f;
            nextBlink = Time.time + Random.Range(good ? 2f : 2.8f, good ? 4.5f : 6f);
        }
        float blink = Time.time < blinkUntil ? 100f : 0f;
        face.Set("EyeBlinkLeft", blink);
        face.Set("EyeBlinkRight", blink);
    }
}
