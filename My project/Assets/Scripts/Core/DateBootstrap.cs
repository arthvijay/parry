using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>
/// Puts the speed date's systems into whatever scene loads, so scenes need no hand edits.
/// A venue (any scene with an <see cref="NpcManager"/>) gets the stream client, the cast,
/// the date HUD, the verdict, gaze telemetry, the player's avatar and the vision panel,
/// reusing what the scene already has; the old quest list is hidden (the milestones panel
/// replaces it). The webcam starts in every scene, so the face tracker is warm from the
/// matchmaker's face scan to the last line of the date.
/// </summary>
public static class DateBootstrap
{
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
    static void Install()
    {
        SceneManager.sceneLoaded -= OnSceneLoaded;
        SceneManager.sceneLoaded += OnSceneLoaded;
    }

    static void OnSceneLoaded(Scene scene, LoadSceneMode mode)
    {
        VisionFeed.Ensure().StartCamera();
        var npcs = Object.FindFirstObjectByType<NpcManager>();
        if (npcs == null)
            return;

        var root = new GameObject("Speed Date");
        T Need<T>(GameObject host = null) where T : Component
        {
            var found = Object.FindFirstObjectByType<T>();
            return found != null ? found : (host != null ? host : root).AddComponent<T>();
        }

        Need<FullDuplexStreamClient>();
        Need<ScenarioClient>();
        Need<CastClient>();
        Need<ChemistryAndWingmanHUD>();
        Need<SpatialTelemetryBroadcaster>();
        Need<PlayerAvatar>();
        Need<VisionPanel>();
        Need<VenueLook>();
        var quests = Object.FindFirstObjectByType<QuestManager>();
        if (quests == null)
            quests = root.AddComponent<QuestManager>();
        Need<DateVerdictReceipt>(quests.gameObject);
        foreach (var hud in Object.FindObjectsByType<QuestHud>(FindObjectsSortMode.None))
            hud.enabled = false;
        Debug.Log($"DateBootstrap: speed date ready in {scene.name}");
    }
}
