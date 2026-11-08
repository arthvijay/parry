using System;
using System.Collections.Generic;
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
    [Tooltip("Outfit style from the matchmaker; any style with \"black\" in it (black_dress) dresses the clothes in black.")]
    public string outfit = "";

    // Average skin tone of the Rocketbox body textures, the reference the tint is measured from.
    static readonly Color BaseSkin = new(0.80f, 0.62f, 0.52f);
    static readonly Color BaseHair = new(0.30f, 0.22f, 0.17f);

    void Awake()
    {
        GetComponent<NpcAvatarLoader>().Loaded += root =>
        {
            Polish(root);
            Debug.Log($"AvatarTinter: {name} loaded, outfit '{outfit}'");
            Dress(root, outfit);
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

    /// <summary>
    /// Materials that read well in the venue: no sky reflections (the scene's sky probe is
    /// a blue default that tints hair and skin), soft skin, matte hair.
    /// </summary>
    public static void Polish(Transform root)
    {
        if (root == null)
            return;
        foreach (var renderer in root.GetComponentsInChildren<Renderer>(true))
        {
            var materials = renderer.materials;
            foreach (var m in materials)
            {
                if (m == null)
                    continue;
                string n = m.name.ToLowerInvariant();
                bool isHair = n.Contains("opacity") || n.Contains("hair") || n.Contains("lash") || n.Contains("brow");
                if (m.HasProperty("_EnvironmentReflections"))
                    m.SetFloat("_EnvironmentReflections", 0f);
                m.EnableKeyword("_ENVIRONMENTREFLECTIONS_OFF");
                if (m.HasProperty("_Smoothness"))
                    m.SetFloat("_Smoothness", isHair ? 0.08f : 0.32f);
                if (m.HasProperty("_Metallic"))
                    m.SetFloat("_Metallic", 0f);
            }
            renderer.materials = materials;
        }
    }

    static readonly Dictionary<Texture, RenderTexture> blackOutfits = new();

    /// <summary>
    /// Re-dye the clothing painted into the body texture. Rocketbox bodies carry their
    /// clothes in one texture with the skin, so a small shader keeps the skin and turns
    /// the fabric black with its folds; the result is cached per texture.
    /// </summary>
    public static void Dress(Transform root, string style)
    {
        if (root == null || string.IsNullOrEmpty(style) || style.IndexOf("black", StringComparison.OrdinalIgnoreCase) < 0)
            return;
        var shader = Resources.Load<Shader>("Shaders/OutfitRecolor");
        if (shader == null || !shader.isSupported)
        {
            Debug.LogWarning("AvatarTinter: outfit shader unavailable; clothes left as modelled");
            return;
        }
        foreach (var renderer in root.GetComponentsInChildren<Renderer>(true))
        {
            var materials = renderer.materials;
            foreach (var m in materials)
            {
                if (m == null || !m.name.ToLowerInvariant().Contains("body") || !m.HasProperty("_BaseMap"))
                    continue;
                var source = m.GetTexture("_BaseMap");
                if (source == null)
                    continue;
                if (!blackOutfits.TryGetValue(source, out var dyed) || dyed == null)
                {
                    dyed = new RenderTexture(source.width, source.height, 0, RenderTextureFormat.ARGB32,
                                             RenderTextureReadWrite.sRGB) { name = source.name + "_black", useMipMap = true, autoGenerateMips = true };
                    var mat = new Material(shader);
                    Graphics.Blit(source, dyed, mat);
                    Destroy(mat);
                    blackOutfits[source] = dyed;
                }
                m.SetTexture("_BaseMap", dyed);
                Debug.Log($"AvatarTinter: {root.name} dressed in {style} ({source.name})");
                if (m.HasProperty("_Smoothness"))
                    m.SetFloat("_Smoothness", 0.45f); // a satin sheen on the fabric
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
