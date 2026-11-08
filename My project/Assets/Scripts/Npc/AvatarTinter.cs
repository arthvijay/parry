using System;
using UnityEngine;

/// <summary>
/// The parametric part of an avatar: skin and hair tinted toward target colours on the
/// Rocketbox materials, and a resting expression held on the face. The textures already
/// carry a skin tone, so the tint is a per-channel ratio between the target and that
/// base tone (clamped, so a texture is coloured, never flattened), applied to material
/// instances so other characters sharing the model are untouched.
/// </summary>
[RequireComponent(typeof(NpcAvatarLoader))]
public class AvatarTinter : MonoBehaviour
{
    [Tooltip("Target skin colour (hex). Empty = as textured.")]
    public string skin = "";
    [Tooltip("Target hair colour (hex). Empty = as textured.")]
    public string hair = "";
    [Tooltip("Resting smile, 0-1, held on mouthSmileLeft/Right.")]
    public float restingSmile;

    // Average skin tone of the Rocketbox body textures, the reference the tint is measured from.
    static readonly Color BaseSkin = new(0.80f, 0.62f, 0.52f);
    static readonly Color BaseHair = new(0.30f, 0.22f, 0.17f);

    void Awake()
    {
        GetComponent<NpcAvatarLoader>().Loaded += root =>
        {
            Apply(root, skin, hair);
            if (restingSmile > 0f)
                SetShape(root, "mouthsmileleft", restingSmile * 100f);
            if (restingSmile > 0f)
                SetShape(root, "mouthsmileright", restingSmile * 100f);
        };
    }

    /// <summary>Tint every skin and hair material under <paramref name="root"/>.</summary>
    public static void Apply(Transform root, string skinHex, string hairHex)
    {
        if (root == null)
            return;
        bool hasSkin = TryColor(skinHex, out var skinColor);
        bool hasHair = TryColor(hairHex, out var hairColor);
        if (!hasSkin && !hasHair)
            return;
        foreach (var renderer in root.GetComponentsInChildren<Renderer>(true))
        {
            var materials = renderer.materials; // instances
            for (int i = 0; i < materials.Length; i++)
            {
                var m = materials[i];
                if (m == null)
                    continue;
                string n = m.name.ToLowerInvariant();
                bool isHair = n.Contains("opacity") || n.Contains("hair") || n.Contains("lash") || n.Contains("brow");
                bool isSkin = !isHair && (n.Contains("head") || n.Contains("body") || n.Contains("skin"));
                if (isHair && hasHair)
                    SetColor(m, Ratio(hairColor, BaseHair, 0.25f, 1.8f));
                else if (isSkin && hasSkin)
                    SetColor(m, Ratio(skinColor, BaseSkin, 0.45f, 1.5f));
            }
            renderer.materials = materials;
        }
    }

    static Color Ratio(Color target, Color reference, float min, float max)
        => new(Mathf.Clamp(target.r / reference.r, min, max),
               Mathf.Clamp(target.g / reference.g, min, max),
               Mathf.Clamp(target.b / reference.b, min, max), 1f);

    static void SetColor(Material m, Color c)
    {
        if (m.HasProperty("_BaseColor"))
            m.SetColor("_BaseColor", c);
        if (m.HasProperty("_Color"))
            m.SetColor("_Color", c);
    }

    static bool TryColor(string hex, out Color color)
    {
        color = Color.white;
        return !string.IsNullOrEmpty(hex) && ColorUtility.TryParseHtmlString(hex, out color);
    }

    /// <summary>Set every blendshape whose name ends with <paramref name="suffix"/> (case-insensitive).</summary>
    public static void SetShape(Transform root, string suffix, float weight)
    {
        foreach (var smr in root.GetComponentsInChildren<SkinnedMeshRenderer>(true))
        {
            var mesh = smr.sharedMesh;
            if (mesh == null)
                continue;
            for (int i = 0; i < mesh.blendShapeCount; i++)
                if (mesh.GetBlendShapeName(i).EndsWith(suffix, StringComparison.OrdinalIgnoreCase))
                    smr.SetBlendShapeWeight(i, weight);
        }
    }
}
