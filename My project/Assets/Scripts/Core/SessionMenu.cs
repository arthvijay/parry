using System.Collections;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.Networking;
using UnityEngine.SceneManagement;

/// <summary>
/// The app's own menu, so a whole session can be run from the game window: Esc (or F10)
/// opens it from any screen. Resume; restart this date; start a new session from the
/// matchmaker; fullscreen on or off (F11 works any time); quit. It also says whether the
/// orchestrator is reachable, which is the first thing to check when a date won't start.
///
/// It creates itself when the game starts and survives scene loads, so no scene needs it.
/// While it is open, the first-person controller ignores the mouse and keyboard.
/// </summary>
public class SessionMenu : MonoBehaviour
{
    public const string MatchmakerScene = "Assets/Scenes/Wish.unity";

    public static SessionMenu Instance { get; private set; }
    public static bool IsOpen => Instance != null && Instance.open;

    bool open;
    float openedAt;
    float hintUntil;
    string server = "checking…";
    bool serverUp;
    Coroutine pinging;

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Create()
    {
        if (Instance != null)
            return;
        var go = new GameObject("SessionMenu");
        DontDestroyOnLoad(go);
        go.AddComponent<SessionMenu>();
    }

    void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }
        Instance = this;
        SceneManager.sceneLoaded += (_, _) => { open = false; hintUntil = Time.unscaledTime + 6f; };
        hintUntil = Time.unscaledTime + 6f;
    }

    void Update()
    {
        var kb = Keyboard.current;
        if (kb == null)
            return;
        if (kb.f11Key.wasPressedThisFrame)
            ToggleFullscreen();
        // Esc belongs to a text field while one is being typed in.
        bool typing = GUIUtility.keyboardControl != 0;
        if (kb.f10Key.wasPressedThisFrame || (kb.escapeKey.wasPressedThisFrame && !typing))
            SetOpen(!open);
    }

    void SetOpen(bool value)
    {
        open = value;
        if (open)
        {
            openedAt = Time.unscaledTime;
            Cursor.lockState = CursorLockMode.None;
            Cursor.visible = true;
            pinging ??= StartCoroutine(Ping());
        }
        else if (pinging != null)
        {
            StopCoroutine(pinging);
            pinging = null;
        }
    }

    IEnumerator Ping()
    {
        while (true)
        {
            using (var req = UnityWebRequest.Get($"{DateSession.Base}/health"))
            {
                req.timeout = 3;
                yield return req.SendWebRequest();
                serverUp = req.result == UnityWebRequest.Result.Success;
                server = serverUp ? $"connected · {DateSession.Base}" : $"not reachable at {DateSession.Base}";
            }
            yield return new WaitForSecondsRealtime(3f);
        }
    }

    static void ToggleFullscreen()
    {
        if (Screen.fullScreen)
            Screen.fullScreenMode = FullScreenMode.Windowed;
        else
        {
            var r = Screen.currentResolution;
            Screen.SetResolution(r.width, r.height, FullScreenMode.FullScreenWindow);
        }
    }

    /// <summary>Loads a scene by path, in a build or in the editor's play mode.</summary>
    public static void Load(string scenePath)
    {
        Cursor.lockState = CursorLockMode.None;
#if UNITY_EDITOR
        if (SceneUtility.GetBuildIndexByScenePath(scenePath) < 0)
        {
            UnityEditor.SceneManagement.EditorSceneManager.LoadSceneInPlayMode(
                scenePath, new LoadSceneParameters(LoadSceneMode.Single));
            return;
        }
#endif
        SceneManager.LoadScene(scenePath);
    }

    static void Quit()
    {
#if UNITY_EDITOR
        UnityEditor.EditorApplication.isPlaying = false;
#else
        Application.Quit();
#endif
    }

    // ---- drawing --------------------------------------------------------------------

    void OnGUI()
    {
        var m = GlassUI.Begin();
        float W = GlassUI.Width, H = GlassUI.Height;
        GUI.depth = -1000;
        if (!open)
        {
            if (Time.unscaledTime < hintUntil)
            {
                float a = Mathf.Clamp01(hintUntil - Time.unscaledTime);
                GlassUI.Label(new Rect(16f, H - 26f, 260f, 18f), "Esc  menu      F11  fullscreen", 11,
                              new Color(1f, 1f, 1f, 0.45f * a));
            }
            GlassUI.End(m);
            return;
        }

        GlassUI.Rounded(new Rect(-10f, -10f, W + 20f, H + 20f), new Color(0f, 0f, 0f, 0.55f), 2);
        float appear = Mathf.SmoothStep(0f, 1f, Mathf.Clamp01((Time.unscaledTime - openedAt) / 0.18f));
        string scene = SceneManager.GetActiveScene().path;
        bool inDate = scene != MatchmakerScene;
        int buttons = inDate ? 5 : 4;
        float w = 380f, h = 150f + buttons * 50f;
        var r = new Rect((W - w) / 2f, (H - h) / 2f + (1f - appear) * 16f, w, h);
        GlassUI.Panel(r, appear);
        GlassUI.Label(new Rect(r.x, r.y + 20f, w, 34f), Brand.Name, 28, Brand.Accent, FontStyle.Bold, TextAnchor.MiddleCenter);
        GlassUI.Label(new Rect(r.x, r.y + 54f, w, 18f), inDate ? "On a date" : "Matchmaker", 12,
                      new Color(1f, 1f, 1f, 0.6f), FontStyle.Normal, TextAnchor.MiddleCenter);
        GlassUI.Dot(new Vector2(r.x + 36f, r.y + 88f), 9f, serverUp ? Brand.Good : Brand.Bad);
        GlassUI.Label(new Rect(r.x + 48f, r.y + 79f, w - 64f, 18f), "Server " + server, 11,
                      new Color(1f, 1f, 1f, 0.7f));

        float y = r.y + 112f;
        Rect Next() { var b = new Rect(r.x + 30f, y, w - 60f, 40f); y += 50f; return b; }
        if (GlassUI.Button(Next(), "Resume", true))
            SetOpen(false);
        if (inDate && GlassUI.Button(Next(), "Restart this date"))
            Load(scene);
        if (GlassUI.Button(Next(), "New session (back to the matchmaker)"))
            Load(MatchmakerScene);
        if (GlassUI.Button(Next(), Screen.fullScreen ? "Windowed" : "Fullscreen"))
            ToggleFullscreen();
        if (GlassUI.Button(Next(), "Quit"))
            Quit();
        GlassUI.Label(new Rect(r.x, r.yMax - 24f, w, 16f), "Esc to resume · the date's clock keeps running", 10,
                      new Color(1f, 1f, 1f, 0.45f), FontStyle.Normal, TextAnchor.MiddleCenter);
        GlassUI.End(m);
    }
}
