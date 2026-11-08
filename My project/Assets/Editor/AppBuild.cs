using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEngine;

/// <summary>
/// Builds the game as a standalone app, so a date runs in its own clean window instead of
/// inside the editor. Menu: Build ▸ Linux App (or Windows / macOS). From a terminal,
/// with the project closed in the editor:
///
///   Unity -batchmode -quit -projectPath "My project" -executeMethod AppBuild.BuildLinux
///
/// or simply <c>./play build</c>. The app lands in <c>Builds/&lt;platform&gt;/</c> at the
/// repository root, and <c>./play</c> starts the orchestrator and opens it.
/// </summary>
public static class AppBuild
{
    // The matchmaker first; the venues are loaded by path from it.
    static readonly string[] Scenes =
    {
        "Assets/Scenes/Wish.unity",
        "Assets/Scenes/CancunCafe.unity",
        "Assets/Scenes/SampleScene.unity",
    };

    [MenuItem("Build/Linux App", priority = 1)]
    public static void BuildLinux() => Build(BuildTarget.StandaloneLinux64, "Linux", ".x86_64");

    [MenuItem("Build/Windows App", priority = 2)]
    public static void BuildWindows() => Build(BuildTarget.StandaloneWindows64, "Windows", ".exe");

    [MenuItem("Build/macOS App", priority = 3)]
    public static void BuildMac() => Build(BuildTarget.StandaloneOSX, "macOS", ".app");

    static void Build(BuildTarget target, string folder, string extension)
    {
        string name = ProductName();
        // The name is set only for the build and put back after, so it never lands in
        // ProjectSettings (it lives in BrandConfig.json alone).
        string previousName = PlayerSettings.productName;
        PlayerSettings.productName = name;
        try { BuildWith(target, folder, extension, name); }
        finally
        {
            PlayerSettings.productName = previousName;
            AssetDatabase.SaveAssets();
        }
    }

    static void BuildWith(BuildTarget target, string folder, string extension, string name)
    {
        // An app, not a demo in the editor: it keeps talking when the window loses focus
        // (the date's voice and the open mic must not stall), and the window can be resized.
        PlayerSettings.runInBackground = true;
        PlayerSettings.resizableWindow = true;
        PlayerSettings.fullScreenMode = FullScreenMode.Windowed;
        PlayerSettings.defaultScreenWidth = 1600;
        PlayerSettings.defaultScreenHeight = 900;
        PlayerSettings.visibleInBackground = true;

        // Shaders the scripts find by name at runtime, which no scene material references.
        AlwaysInclude("Universal Render Pipeline/Unlit");

        string root = Path.GetFullPath(Path.Combine(Application.dataPath, "..", ".."));
        string output = Path.Combine(root, "Builds", folder, name + extension);
        Directory.CreateDirectory(Path.GetDirectoryName(output));

        var missing = Scenes.Where(s => AssetDatabase.LoadAssetAtPath<SceneAsset>(s) == null).ToArray();
        if (missing.Length > 0)
            throw new BuildFailedException("Missing scenes: " + string.Join(", ", missing));

        var options = new BuildPlayerOptions
        {
            scenes = Scenes,
            locationPathName = output,
            target = target,
            options = BuildOptions.None,
        };
        BuildReport report = BuildPipeline.BuildPlayer(options);
        var summary = report.summary;
        string line = $"AppBuild: {summary.result} {target} -> {output} " +
                      $"({summary.totalSize / (1024 * 1024)} MB, {summary.totalErrors} errors, " +
                      $"{summary.totalTime.TotalSeconds:0} s)";
        Debug.Log(line);
        // Say what the errors were, not just how many.
        foreach (var step in report.steps)
            foreach (var message in step.messages)
                if (message.type == LogType.Error || message.type == LogType.Exception)
                    Debug.Log($"AppBuild: error in '{step.name}': {message.content}");
        if (summary.result != BuildResult.Succeeded)
        {
            if (Application.isBatchMode)
                EditorApplication.Exit(1);
            throw new BuildFailedException(line);
        }
        if (!Application.isBatchMode)
            EditorUtility.RevealInFinder(output);
    }

    /// <summary>Adds shaders to Graphics ▸ Always Included Shaders, so Shader.Find still
    /// finds them in a build (Unity strips every shader no included material uses).</summary>
    static void AlwaysInclude(params string[] names)
    {
        var settings = AssetDatabase.LoadAllAssetsAtPath("ProjectSettings/GraphicsSettings.asset")
            .FirstOrDefault();
        if (settings == null)
            return;
        var so = new SerializedObject(settings);
        var list = so.FindProperty("m_AlwaysIncludedShaders");
        foreach (var name in names)
        {
            var shader = Shader.Find(name);
            if (shader == null)
            {
                Debug.LogWarning($"AppBuild: shader '{name}' not found; not included");
                continue;
            }
            bool present = false;
            for (int i = 0; i < list.arraySize; i++)
                present |= list.GetArrayElementAtIndex(i).objectReferenceValue == shader;
            if (present)
                continue;
            list.InsertArrayElementAtIndex(list.arraySize);
            list.GetArrayElementAtIndex(list.arraySize - 1).objectReferenceValue = shader;
            Debug.Log($"AppBuild: always including '{name}'");
        }
        if (so.ApplyModifiedPropertiesWithoutUndo())
            AssetDatabase.SaveAssets();
    }

    /// <summary>The product name, from the one place it lives (Resources/BrandConfig.json).</summary>
    static string ProductName()
    {
        var asset = AssetDatabase.LoadAssetAtPath<TextAsset>("Assets/Resources/BrandConfig.json");
        try
        {
            var brand = asset != null ? JsonUtility.FromJson<BrandName>(asset.text) : null;
            if (!string.IsNullOrWhiteSpace(brand?.name))
                return brand.name.Trim();
        }
        catch (Exception e)
        {
            Debug.LogWarning($"AppBuild: BrandConfig.json unreadable ({e.Message})");
        }
        return PlayerSettings.productName;
    }

    [Serializable]
    class BrandName { public string name; }
}
