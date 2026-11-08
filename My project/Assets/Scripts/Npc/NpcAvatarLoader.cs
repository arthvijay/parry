using System;
using System.Collections;
using UnityEngine;

/// <summary>
/// Spawns the NPC's avatar model under this transform. Other NPC components
/// subscribe to <see cref="Loaded"/> to grab bones and blendshapes.
///
/// Default avatar is a Microsoft Rocketbox character (MIT licensed, realistic,
/// rigged, with viseme + ARKit blendshapes) imported from Assets/Resources.
/// Assign <see cref="avatarPrefab"/> to use any other humanoid instead.
/// </summary>
public class NpcAvatarLoader : MonoBehaviour
{
    [Tooltip("Humanoid prefab/model to spawn. Overrides Resource Path if set.")]
    public GameObject avatarPrefab;

    [Tooltip("Fallback: model path under a Resources folder, without extension.")]
    public string resourcePath = "Avatars/Female_Adult_08/Export/Female_Adult_08_facial";

    [Tooltip("Rotate the model so it faces this transform's forward. Flip to 180 if the avatar has its back to you.")]
    public float modelYawOffset = 0f;

    [Tooltip("Stand-in shown if the avatar fails to load.")]
    public GameObject placeholder;

    [Tooltip("Drop the NPC onto whatever collider is below once one exists. Lets her stand on " +
             "generated-world colliders that are loaded asynchronously at runtime.")]
    public bool snapToGround = true;
    public float snapMaxDrop = 20f;

    [Tooltip("After the idle mocap has posed the skeleton, shift the model so the lowest point of " +
             "the skinned mesh sits at this transform's origin. Rocketbox mocap moves the Bip01 root " +
             "to the capture actor's pelvis height, which leaves a differently-proportioned avatar hovering.")]
    public bool groundFeet = true;

    /// <summary>Root of the instantiated avatar, null until loaded.</summary>
    public Transform AvatarRoot { get; private set; }

    /// <summary>Fired once the avatar hierarchy exists.</summary>
    public event Action<Transform> Loaded;

    void Start()
    {
        var prefab = avatarPrefab != null ? avatarPrefab : Resources.Load<GameObject>(resourcePath);
        if (prefab == null)
        {
            Debug.LogError($"NpcAvatarLoader: no avatar prefab assigned and nothing at Resources/{resourcePath}");
            return;
        }

        var root = Instantiate(prefab, transform);
        root.name = "Avatar";
        root.transform.localPosition = Vector3.zero;
        root.transform.localRotation = Quaternion.Euler(0f, modelYawOffset, 0f);

        // Skinned meshes are culled by their bind-pose bounds, which can be wrong
        // once we start rotating bones by hand.
        foreach (var smr in root.GetComponentsInChildren<SkinnedMeshRenderer>())
            smr.updateWhenOffscreen = true;

        if (placeholder != null)
            placeholder.SetActive(false);

        AvatarRoot = root.transform;
        Loaded?.Invoke(AvatarRoot);

        if (snapToGround)
            StartCoroutine(SnapToGround());
        if (groundFeet)
            StartCoroutine(GroundFeet());
    }

    /// <summary>Re-run the feet grounding, e.g. after standing up from a chair.</summary>
    public void ReGroundFeet()
    {
        if (groundFeet && AvatarRoot != null)
            StartCoroutine(GroundFeet());
    }

    /// <summary>
    /// Measures the posed mesh's lowest point and moves the avatar down (or up)
    /// so it coincides with our origin. Runs after a couple of frames so the
    /// animation graph has written its first pose, and re-measures briefly in
    /// case the first clip is still blending in.
    /// </summary>
    IEnumerator GroundFeet()
    {
        var renderers = AvatarRoot.GetComponentsInChildren<SkinnedMeshRenderer>();
        if (renderers.Length == 0)
            yield break;

        yield return null;
        yield return null;

        var baked = new Mesh();
        var verts = new System.Collections.Generic.List<Vector3>();
        float settleUntil = Time.time + 1f;
        while (Time.time < settleUntil)
        {
            // renderer.bounds can lag or fall back to the bind pose, so skin the
            // mesh ourselves with the current bone poses and take the true minimum.
            float lowest = float.MaxValue;
            foreach (var smr in renderers)
            {
                smr.BakeMesh(baked);
                baked.GetVertices(verts);
                var toWorld = smr.transform.localToWorldMatrix;
                foreach (var v in verts)
                    lowest = Mathf.Min(lowest, toWorld.MultiplyPoint3x4(v).y);
            }

            float offset = transform.position.y - lowest;
            if (Mathf.Abs(offset) > 0.001f)
            {
                AvatarRoot.position += Vector3.up * offset;
                Debug.Log($"{name}: grounded feet, moved avatar {offset:F3} in Y " +
                          $"(origin y={transform.position.y:F3}, posed mesh min y was {lowest:F3})");
            }
            yield return new WaitForSeconds(0.25f);
        }
        Destroy(baked);
    }

    /// <summary>
    /// Waits for a collider to appear below (WorldColliderLoader builds the
    /// generated world's collider a few frames in) and sets the feet on it.
    /// </summary>
    IEnumerator SnapToGround()
    {
        float giveUp = Time.time + 10f;
        while (Time.time < giveUp)
        {
            Vector3 from = transform.position + Vector3.up * 0.5f;
            float best = float.MaxValue;
            Transform bestHit = null;
            foreach (var hit in Physics.RaycastAll(from, Vector3.down, snapMaxDrop + 0.5f, ~0, QueryTriggerInteraction.Ignore))
                if (!hit.transform.IsChildOf(transform) && hit.distance < best) // skip our own interaction capsule
                {
                    best = hit.distance;
                    bestHit = hit.transform;
                }
            if (best < float.MaxValue)
            {
                transform.position = new Vector3(transform.position.x, from.y - best, transform.position.z);
                Debug.Log($"{name}: snapped to '{bestHit.name}' at y={transform.position.y:F3}");
                yield break;
            }
            yield return null;
        }
        Debug.LogWarning($"{name}: no ground found below to snap to.");
    }

    /// <summary>Find a bone by name anywhere under the avatar.</summary>
    public Transform FindBone(string name)
    {
        if (AvatarRoot == null)
            return null;
        foreach (var t in AvatarRoot.GetComponentsInChildren<Transform>())
            if (t.name == name)
                return t;
        return null;
    }
}
