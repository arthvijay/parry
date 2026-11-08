using UnityEditor;
using UnityEditor.SceneManagement;

/// <summary>
/// When the editor is sitting on an empty, unsaved scene (a fresh open, or the scene
/// Unity falls back to), opens the matchmaker scene, where the date starts.
/// </summary>
[InitializeOnLoad]
static class OpenDemoScene
{
    const string StartScene = "Assets/Scenes/Wish.unity";

    static OpenDemoScene()
    {
        EditorApplication.delayCall += Open;
    }

    static void Open()
    {
        if (EditorApplication.isPlayingOrWillChangePlaymode)
            return;
        var active = EditorSceneManager.GetActiveScene();
        if (!string.IsNullOrEmpty(active.path) || active.isDirty || EditorSceneManager.sceneCount > 1)
            return;
        if (AssetDatabase.LoadAssetAtPath<SceneAsset>(StartScene) == null)
            return;
        EditorSceneManager.OpenScene(StartScene, OpenSceneMode.Single);
        UnityEngine.Debug.Log($"OpenDemoScene: opened {StartScene}");
    }
}
