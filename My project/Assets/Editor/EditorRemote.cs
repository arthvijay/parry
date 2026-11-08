using System;
using System.IO;
using System.Linq;
using System.Reflection;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

/// <summary>
/// Development aid: lets a script outside the editor drive it through a file, so a play
/// session can be tested headlessly. Write one command per line to Temp/remote_cmd.txt;
/// replies are appended to Temp/remote_out.txt.
///   play | stop | refresh | open Assets/Scenes/X.unity | shot /abs/path.png
///   call TypeName.Method [text]  (first object of that type; text = first string argument)
///   key KeyName            (sends a key-down to the Game view)
/// </summary>
[InitializeOnLoad]
static class EditorRemote
{
    static readonly string Cmd = Path.GetFullPath("Temp/remote_cmd.txt");
    static readonly string Out = Path.GetFullPath("Temp/remote_out.txt");
    static double next;
    static double releaseAt = -1;

    static EditorRemote() { EditorApplication.update += Poll; }

    static void Reply(string s) => File.AppendAllText(Out, $"{DateTime.Now:HH:mm:ss} {s}\n");

    static void Poll()
    {
        if (releaseAt > 0 && EditorApplication.timeSinceStartup >= releaseAt && UnityEngine.InputSystem.Keyboard.current != null)
        {
            releaseAt = -1;
            UnityEngine.InputSystem.InputSystem.QueueStateEvent(UnityEngine.InputSystem.Keyboard.current,
                new UnityEngine.InputSystem.LowLevel.KeyboardState());
        }
        if (EditorApplication.timeSinceStartup < next) return;
        next = EditorApplication.timeSinceStartup + 0.25;
        if (!File.Exists(Cmd)) return;
        string[] lines;
        try { lines = File.ReadAllLines(Cmd); File.Delete(Cmd); }
        catch (IOException) { return; }
        foreach (var line in lines.Where(l => !string.IsNullOrWhiteSpace(l)))
        {
            try { Run(line.Trim()); }
            catch (Exception e) { Reply($"ERR {line}: {e.GetType().Name}: {e.Message}"); }
        }
    }

    static void Run(string line)
    {
        var parts = line.Split(new[] { ' ' }, 2);
        string verb = parts[0], arg = parts.Length > 1 ? parts[1] : "";
        switch (verb)
        {
            case "play": EditorApplication.isPlaying = true; Reply("OK play"); break;
            case "stop": EditorApplication.isPlaying = false; Reply("OK stop"); break;
            case "open": EditorSceneManager.OpenScene(arg, OpenSceneMode.Single); Reply($"OK open {arg}"); break;
            case "state":
                Reply($"OK playing={EditorApplication.isPlaying} scene={EditorSceneManager.GetActiveScene().path} " +
                      $"compiling={EditorApplication.isCompiling}");
                break;
            case "shot":
                FocusGame();
                ScreenCapture.CaptureScreenshot(arg);
                Reply($"OK shot {arg}");
                break;
            case "refresh": AssetDatabase.Refresh(); Reply("OK refresh"); break;
            case "log": Debug.Log($"EditorRemote: {arg}"); Reply("OK log"); break;
            case "cam": Cam(arg); break;
            case "camoff":
                if (free != null) UnityEngine.Object.Destroy(free.gameObject);
                Reply("OK camoff"); break;
            case "where": Where(arg); break;
            case "near": Near(arg); break;
            case "fps":
                FrameTimingManager.CaptureFrameTimings();
                var timings = new FrameTiming[8];
                uint got = FrameTimingManager.GetLatestTimings(8, timings);
                double gpu = 0, cpu = 0;
                for (int i = 0; i < got; i++) { gpu += timings[i].gpuFrameTime; cpu += timings[i].cpuFrameTime; }
                Reply($"OK fps={1f / Mathf.Max(0.0001f, Time.smoothDeltaTime):F1} frame={Time.smoothDeltaTime * 1000f:F1}ms " +
                      $"gpu={(got > 0 ? gpu / got : -1):F1}ms cpu={(got > 0 ? cpu / got : -1):F1}ms ({got} timings)");
                break;
            case "splat": Splat(arg); break;
            case "tables": Tables(arg); break;
            case "press": Press(arg); break;
            case "call": Call(arg); break;
            case "key": Key(arg); break;
            default: Reply($"ERR unknown {verb}"); break;
        }
    }

    static Camera free;

    /// <summary>cam x y z pitch yaw [fov]: a free camera over everything, for inspection shots.</summary>
    static void Cam(string arg)
    {
        var v = arg.Split(' ').Select(x => float.Parse(x, System.Globalization.CultureInfo.InvariantCulture)).ToArray();
        if (free == null)
        {
            free = new GameObject("Remote Camera").AddComponent<Camera>();
            free.depth = 100;
            free.nearClipPlane = 0.05f;
        }
        free.transform.SetPositionAndRotation(new Vector3(v[0], v[1], v[2]), Quaternion.Euler(v[3], v[4], 0f));
        free.fieldOfView = v.Length > 5 ? v[5] : 60f;
        Reply($"OK cam {arg}");
    }

    /// <summary>where name1,name2: world positions of objects whose name contains each term.</summary>
    static void Where(string arg)
    {
        foreach (var term in arg.Split(','))
            foreach (var t in UnityEngine.Object.FindObjectsByType<Transform>(FindObjectsSortMode.None))
                if (t.name.IndexOf(term.Trim(), StringComparison.OrdinalIgnoreCase) >= 0)
                    Reply($"  {t.name} pos={t.position.ToString("F2")} yaw={t.eulerAngles.y:F0} scale={t.lossyScale.x:F2}");
        Reply($"OK where {arg}");
    }

    /// <summary>near x y z r: every enabled renderer whose bounds come within r of the point.</summary>
    static void Near(string arg)
    {
        var v = arg.Split(' ').Select(x => float.Parse(x, System.Globalization.CultureInfo.InvariantCulture)).ToArray();
        var p = new Vector3(v[0], v[1], v[2]);
        foreach (var r in UnityEngine.Object.FindObjectsByType<Renderer>(FindObjectsSortMode.None))
            if (r.enabled && r.gameObject.activeInHierarchy && r.bounds.SqrDistance(p) < v[3] * v[3])
            {
                string path = r.transform.name;
                for (var t = r.transform.parent; t != null; t = t.parent) path = t.name + "/" + path;
                Reply($"  {path} [{r.GetType().Name}] size={r.bounds.size.ToString("F2")} mat={r.sharedMaterial?.name}");
            }
        Reply($"OK near {arg}");
    }

    /// <summary>splat shOrder sortNth: change the Gaussian splat renderer's quality live.</summary>
    static void Splat(string arg)
    {
        var v = arg.Split(' ');
        foreach (var gs in UnityEngine.Object.FindObjectsByType<GaussianSplatting.Runtime.GaussianSplatRenderer>(FindObjectsSortMode.None))
        {
            gs.m_SHOrder = int.Parse(v[0]);
            gs.m_SortNthFrame = int.Parse(v[1]);
            Reply($"  {gs.name} sh={gs.m_SHOrder} sort={gs.m_SortNthFrame} splats={gs.splatCount}");
        }
        Reply($"OK splat {arg}");
    }

    /// <summary>tables floorY: finds table tops in the collision mesh (flat hits ~0.6-0.9 m above
    /// the floor), clustered, as candidate places to seat background patrons.</summary>
    static void Tables(string arg)
    {
        float floor = float.Parse(arg, System.Globalization.CultureInfo.InvariantCulture);
        var hits = new System.Collections.Generic.List<Vector3>();
        for (float x = -8f; x <= 14f; x += 0.15f)
            for (float z = -4f; z <= 18f; z += 0.15f)
                if (Physics.Raycast(new Vector3(x, floor + 1.15f, z), Vector3.down, out var hit, 1.0f)
                    && hit.normal.y > 0.92f && hit.point.y > floor + 0.45f && hit.point.y < floor + 1.0f)
                    hits.Add(hit.point);
        var clusters = new System.Collections.Generic.List<(Vector3 sum, int n)>();
        foreach (var h in hits)
        {
            int k = clusters.FindIndex(c => Vector3.Distance(c.sum / c.n, h) < 0.7f);
            if (k < 0) clusters.Add((h, 1)); else clusters[k] = (clusters[k].sum + h, clusters[k].n + 1);
        }
        foreach (var c in clusters.Where(c => c.n >= 6).OrderByDescending(c => c.n))
            Reply($"  table at {(c.sum / c.n).ToString("F2")} area~{c.n * 0.0225f:F2}m2");
        Reply($"OK tables ({hits.Count} hits)");
    }

    /// <summary>press KeyName: a real key press through the Input System (down now, up next frame).</summary>
    static void Press(string name)
    {
        var key = (UnityEngine.InputSystem.Key)Enum.Parse(typeof(UnityEngine.InputSystem.Key), name, true);
        var kb = UnityEngine.InputSystem.Keyboard.current;
        if (kb == null) { Reply("ERR no keyboard"); return; }
        // The project has no input settings asset, so these are in-memory defaults: let the
        // keyboard reach the game while the editor window is in the background.
        var settings = UnityEngine.InputSystem.InputSystem.settings;
        settings.backgroundBehavior = UnityEngine.InputSystem.InputSettings.BackgroundBehavior.IgnoreFocus;
        settings.editorInputBehaviorInPlayMode =
            UnityEngine.InputSystem.InputSettings.EditorInputBehaviorInPlayMode.AllDeviceInputAlwaysGoesToGameView;
        if (!kb.enabled) UnityEngine.InputSystem.InputSystem.EnableDevice(kb);
        UnityEngine.InputSystem.InputSystem.QueueStateEvent(kb, new UnityEngine.InputSystem.LowLevel.KeyboardState(key));
        releaseAt = EditorApplication.timeSinceStartup + 0.15; // held a few frames, then released
        Reply($"OK press {name}");
    }

    static void FocusGame()
    {
        var type = typeof(EditorWindow).Assembly.GetType("UnityEditor.GameView");
        var game = EditorWindow.GetWindow(type, false, null, false);
        game.Repaint();
    }

    static void Call(string arg)
    {
        string text = null;
        int space = arg.IndexOf(' ');
        if (space > 0) { text = arg[(space + 1)..]; arg = arg[..space]; }
        int dot = arg.LastIndexOf('.');
        string typeName = arg[..dot], method = arg[(dot + 1)..];
        var type = AppDomain.CurrentDomain.GetAssemblies().Select(a => a.GetType(typeName)).FirstOrDefault(t => t != null);
        if (type == null) { Reply($"ERR no type {typeName}"); return; }
        var target = UnityEngine.Object.FindFirstObjectByType(type) as MonoBehaviour;
        if (target == null) { Reply($"ERR no live {typeName}"); return; }
        var m = type.GetMethod(method, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static);
        if (m == null) { Reply($"ERR no method {method}"); return; }
        var ps = m.GetParameters();
        object[] args = ps.Select((p, i) => i == 0 && text != null && p.ParameterType == typeof(string) ? text
                                            : p.HasDefaultValue ? p.DefaultValue : null).ToArray();
        var result = m.Invoke(m.IsStatic ? null : target, args);
        if (result is System.Collections.IEnumerator routine) target.StartCoroutine(routine);
        Reply($"OK call {arg}");
    }

    static void Key(string name)
    {
        var type = typeof(EditorWindow).Assembly.GetType("UnityEditor.GameView");
        var game = EditorWindow.GetWindow(type, false, null, true);
        var code = (KeyCode)Enum.Parse(typeof(KeyCode), name);
        game.SendEvent(new Event { type = EventType.KeyDown, keyCode = code });
        game.SendEvent(new Event { type = EventType.KeyUp, keyCode = code });
        Reply($"OK key {name}");
    }
}
