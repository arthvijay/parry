using System.IO;
using System.Reflection;
using GaussianSplatting.Editor;
using GaussianSplatting.Runtime;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>
/// Converts a WorldLabs .spz (kept in the repo-level Assets/Worlds folder, outside
/// the Unity project) into a GaussianSplatAsset and points a scene's
/// GaussianSplatRenderer + WorldColliderLoader at it. Drives the package's
/// GaussianSplatAssetCreator window through reflection so the conversion can run
/// without clicking through the UI.
/// </summary>
public static class WorldSplatImporter
{
    const string kOutputFolder = "Assets/GaussianAssets";

    /// <summary>One splat world and the scene that shows it.</summary>
    struct World
    {
        public string spz;        // relative to <repo>/Assets/Worlds
        public string collider;   // relative to StreamingAssets (see tools/spz_to_collider.py)
        public string scene;      // scene whose renderer/loader get patched
    }

    static readonly World ModernHouse = new World
    {
        spz = "ModernHouse/modern_house_with_lush_landscaping_2m.spz",
        collider = "Worlds/modern_house_with_lush_landscaping_collider.glb",
        scene = "Assets/Scenes/SampleScene.unity",
    };

    static readonly World CancunCafe = new World
    {
        spz = "CancunCafe/cancun_cafe_model.spz",
        collider = "Worlds/cancun_cafe_collider.glb",
        scene = "Assets/Scenes/CancunCafe.unity",
    };

    // Repo-level Assets/Worlds, i.e. <repo>/Assets/Worlds, not <repo>/My project/Assets.
    static string WorldsDir => Path.GetFullPath(Path.Combine(Application.dataPath, "../../Assets/Worlds"));

    [MenuItem("Tools/Worlds/Use Modern House (SampleScene)")]
    static void UseModernHouse() => UseWorld(ModernHouse);

    [MenuItem("Tools/Worlds/Use Cancun Cafe (CancunCafe)")]
    static void UseCancunCafe() => UseWorld(CancunCafe);

    // Runs each import once, the first time the editor loads without the converted
    // asset present. No-op afterwards.
    [InitializeOnLoadMethod]
    static void AutoImport()
    {
        AutoImport(ModernHouse);
        AutoImport(CancunCafe);
    }

    static void AutoImport(World world)
    {
        if (AssetDatabase.LoadAssetAtPath<GaussianSplatAsset>(AssetPathFor(world.spz)) != null)
            return;
        if (!File.Exists(Path.Combine(WorldsDir, world.spz)))
            return;
        EditorApplication.delayCall += () => UseWorld(world);
    }

    static string AssetPathFor(string spzRelative) =>
        $"{kOutputFolder}/{Path.GetFileNameWithoutExtension(spzRelative)}.asset";

    static void UseWorld(World world)
    {
        string spzPath = Path.Combine(WorldsDir, world.spz);
        if (!File.Exists(spzPath))
        {
            Debug.LogError($"WorldSplatImporter: .spz not found at {spzPath}");
            return;
        }
        if (!File.Exists(world.scene))
        {
            Debug.LogError($"WorldSplatImporter: scene not found at {world.scene}");
            return;
        }

        var asset = CreateSplatAsset(spzPath);
        if (asset == null)
            return;

        PatchScene(world.scene, asset, world.collider);
        Debug.Log($"WorldSplatImporter: {world.scene} now uses {AssetDatabase.GetAssetPath(asset)} (collider: {world.collider})");
    }

    static GaussianSplatAsset CreateSplatAsset(string spzPath)
    {
        string assetPath = AssetPathFor(spzPath);
        var existing = AssetDatabase.LoadAssetAtPath<GaussianSplatAsset>(assetPath);
        if (existing != null)
            return existing;

        const BindingFlags kPrivate = BindingFlags.Instance | BindingFlags.NonPublic;
        var type = typeof(GaussianSplatAssetCreator);
        var creator = ScriptableObject.CreateInstance<GaussianSplatAssetCreator>();
        try
        {
            type.GetField("m_InputFile", kPrivate).SetValue(creator, spzPath);
            type.GetField("m_ImportCameras", kPrivate).SetValue(creator, false);
            type.GetField("m_OutputFolder", kPrivate).SetValue(creator, kOutputFolder);

            // Awake() pulls the last quality picked in the window from EditorPrefs;
            // pin Medium so every world is converted the same way as RusticKitchen.
            var qualityField = type.GetField("m_Quality", kPrivate);
            qualityField.SetValue(creator, System.Enum.Parse(qualityField.FieldType, "Medium"));
            type.GetMethod("ApplyQualityLevel", kPrivate).Invoke(creator, null);

            type.GetMethod("CreateAsset", kPrivate).Invoke(creator, null);

            var error = (string)type.GetField("m_ErrorMessage", kPrivate).GetValue(creator);
            if (!string.IsNullOrEmpty(error))
            {
                Debug.LogError($"WorldSplatImporter: {error}");
                return null;
            }
        }
        finally
        {
            Object.DestroyImmediate(creator);
        }

        var asset = AssetDatabase.LoadAssetAtPath<GaussianSplatAsset>(assetPath);
        if (asset == null)
            Debug.LogError($"WorldSplatImporter: expected asset at {assetPath} after conversion");
        return asset;
    }

    static void PatchScene(string scenePath, GaussianSplatAsset asset, string colliderFile)
    {
        var scene = SceneManager.GetSceneByPath(scenePath);
        bool wasOpen = scene.isLoaded;
        if (!wasOpen)
            scene = EditorSceneManager.OpenScene(scenePath, OpenSceneMode.Additive);

        foreach (var root in scene.GetRootGameObjects())
        {
            foreach (var renderer in root.GetComponentsInChildren<GaussianSplatRenderer>(true))
            {
                Undo.RecordObject(renderer, "Set world splat");
                renderer.m_Asset = asset;
                EditorUtility.SetDirty(renderer);
            }
            foreach (var loader in root.GetComponentsInChildren<WorldColliderLoader>(true))
            {
                Undo.RecordObject(loader, "Set world collider");
                loader.colliderFile = colliderFile;
                EditorUtility.SetDirty(loader);
            }
        }

        EditorSceneManager.MarkSceneDirty(scene);
        EditorSceneManager.SaveScene(scene);
        if (!wasOpen)
            EditorSceneManager.CloseScene(scene, true);
    }
}
