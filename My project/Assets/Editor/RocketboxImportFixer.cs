using System.IO;
using UnityEditor;
using UnityEngine;

/// <summary>
/// Fixes Microsoft Rocketbox avatar imports for URP. Adapted from the
/// MIT-licensed FixRocketboxMaxImport.cs shipped in the Rocketbox repo.
/// Applies to anything under a folder named "Avatars".
/// </summary>
public class RocketboxImportFixer : AssetPostprocessor
{
    bool IsAvatarAsset => assetPath.Contains("/Avatars/");
    // Rocketbox mocap FBXs (Biped skeleton only, no mesh) live in Avatars/Animations.
    bool IsAnimationAsset => assetPath.Contains("/Avatars/Animations/");

    void OnPreprocessTexture()
    {
        if (!IsAvatarAsset)
            return;

        string file = Path.GetFileName(assetPath).ToLower();
        var importer = (TextureImporter)assetImporter;

        // Textures named *_normal* are normal maps; avoids the "fix now?" dialog.
        if (file.Contains("normal"))
        {
            importer.textureType = TextureImporterType.NormalMap;
            importer.convertToNormalmap = false;
        }

        // Hair/lash alpha maps: dilate colour into transparent pixels so clipped edges don't fringe.
        if (file.Contains("opacity"))
            importer.alphaIsTransparency = true;
    }

    void OnPreprocessModel()
    {
        if (!IsAvatarAsset)
            return;

        var importer = (ModelImporter)assetImporter;
        importer.importBlendShapes = true;
        importer.materialImportMode = ModelImporterMaterialImportMode.ImportStandard;
        importer.materialLocation = ModelImporterMaterialLocation.InPrefab;
        importer.materialSearch = ModelImporterMaterialSearch.RecursiveUp;
        // Generic keeps the Biped bones as plain transforms, which NpcLookAt drives directly.
        // Clips are bound by bone path, and the mocap files share the character's
        // exact "Bip01/Bip01 Pelvis/..." hierarchy, so no Humanoid retargeting is needed.
        importer.animationType = ModelImporterAnimationType.Generic;
        // The character FBX carries a 5 s static take; only import clips from the mocap files.
        importer.importAnimation = IsAnimationAsset;
    }

    void OnPreprocessAnimation()
    {
        if (!IsAnimationAsset)
            return;

        var importer = (ModelImporter)assetImporter;
        var clips = importer.defaultClipAnimations;
        string clipName = Path.GetFileNameWithoutExtension(assetPath);
        for (int i = 0; i < clips.Length; i++)
        {
            clips[i].name = clips.Length == 1 ? clipName : $"{clipName}_{i}";
            clips[i].loopTime = true;
            clips[i].loopPose = true;
            // Keep the actor exactly where the take puts her (no root motion extraction).
            clips[i].lockRootRotation = true;
            clips[i].lockRootHeightY = true;
            clips[i].lockRootPositionXZ = true;
        }
        importer.clipAnimations = clips;
    }

    void OnPostprocessMaterial(Material material)
    {
        if (!IsAvatarAsset)
            return;

        // 3ds Max materials bake the colour into the texture; Unity multiplies by
        // the flat colour, which would tint everything.
        material.color = Color.white;

        // The FBX references .tga paths but we ship .png, so match textures by
        // naming convention (f110_head_color_a.png -> head material base map).
        string texDir = Path.Combine(Path.GetDirectoryName(Path.GetDirectoryName(assetPath)), "Textures");
        string lower = material.name.ToLower();
        string part = lower.Contains("head") ? "head" : lower.Contains("opacity") ? "opacity" : "body";
        AssignTexture(material, "_BaseMap", texDir, part, "color");
        AssignTexture(material, "_BumpMap", texDir, part, "normal");

        if (part == "opacity")
        {
            // Hair/eyelash cards: alpha-clipped opaque avoids transparency sorting
            // artifacts between overlapping strands.
            material.SetFloat("_Surface", 0f);
            material.SetFloat("_AlphaClip", 1f);
            material.SetFloat("_Cutoff", 0.4f);
            material.SetFloat("_Cull", 0f); // double-sided, cards are single quads
            material.SetFloat("_SpecularHighlights", 0f);
            material.EnableKeyword("_ALPHATEST_ON");
            material.EnableKeyword("_SPECULARHIGHLIGHTS_OFF");
            material.DisableKeyword("_SURFACE_TYPE_TRANSPARENT");
            material.SetOverrideTag("RenderType", "TransparentCutout");
            material.renderQueue = (int)UnityEngine.Rendering.RenderQueue.AlphaTest;
        }
        else if (material.HasProperty("_Surface") && material.GetFloat("_Surface") == 1f)
        {
            // Transparent materials look like glass with highlights.
            material.SetFloat("_SpecularHighlights", 0f);
            material.EnableKeyword("_SPECULARHIGHLIGHTS_OFF");
        }
    }

    static void AssignTexture(Material material, string property, string dir, string part, string kind)
    {
        if (!material.HasProperty(property) || material.GetTexture(property) != null || !Directory.Exists(dir))
            return;

        foreach (string file in Directory.GetFiles(dir))
        {
            string name = Path.GetFileName(file).ToLower();
            if (name.EndsWith(".meta") || !name.Contains(part) || !name.Contains(kind))
                continue;

            var tex = AssetDatabase.LoadAssetAtPath<Texture2D>(file.Replace('\\', '/'));
            if (tex == null)
                continue;

            material.SetTexture(property, tex);
            if (property == "_BumpMap")
                material.EnableKeyword("_NORMALMAP");
            return;
        }
    }

    void OnPostprocessMeshHierarchy(GameObject go)
    {
        if (!IsAvatarAsset)
            return;

        // Rocketbox FBXs can carry several LODs; keep only the high-poly one active.
        string name = go.name.ToLower();
        if (name.Contains("poly") && !name.Contains("hipoly"))
            go.SetActive(false);
    }
}
