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
///   call TypeName.Method   (first object of that type; coroutines are started)
///   key KeyName            (sends a key-down to the Game view)
/// </summary>
[InitializeOnLoad]
static class EditorRemote
{
    static readonly string Cmd = Path.GetFullPath("Temp/remote_cmd.txt");
    static readonly string Out = Path.GetFullPath("Temp/remote_out.txt");
    static double next;

    static EditorRemote() { EditorApplication.update += Poll; }

    static void Reply(string s) => File.AppendAllText(Out, $"{DateTime.Now:HH:mm:ss} {s}\n");

    static void Poll()
    {
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
            case "call": Call(arg); break;
            case "key": Key(arg); break;
            default: Reply($"ERR unknown {verb}"); break;
        }
    }

    static void FocusGame()
    {
        var type = typeof(EditorWindow).Assembly.GetType("UnityEditor.GameView");
        var game = EditorWindow.GetWindow(type, false, null, false);
        game.Repaint();
    }

    static void Call(string arg)
    {
        int dot = arg.LastIndexOf('.');
        string typeName = arg[..dot], method = arg[(dot + 1)..];
        var type = AppDomain.CurrentDomain.GetAssemblies().Select(a => a.GetType(typeName)).FirstOrDefault(t => t != null);
        if (type == null) { Reply($"ERR no type {typeName}"); return; }
        var target = UnityEngine.Object.FindFirstObjectByType(type) as MonoBehaviour;
        if (target == null) { Reply($"ERR no live {typeName}"); return; }
        var m = type.GetMethod(method, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static);
        if (m == null) { Reply($"ERR no method {method}"); return; }
        object[] args = m.GetParameters().Select(p => p.HasDefaultValue ? p.DefaultValue : null).ToArray();
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
