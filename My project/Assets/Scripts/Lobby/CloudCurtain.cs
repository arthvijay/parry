using System.Collections.Generic;
using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>
/// The white-out that carries a trip across a scene load, and the clouds that part on
/// the other side.
///
/// The front does the flying: its own low-poly clouds stream past the camera as
/// <see cref="Cover"/> rises, and the last stretch of cover brings up a flat white wash
/// (IMGUI, on top of every camera) so the load hitch happens behind solid white. The
/// object is DontDestroyOnLoad; once the destination has loaded, <see cref="Reveal"/>
/// hangs a shell of low-poly clouds in front of whatever camera it finds, drops the
/// wash, and the clouds fly apart onto the spawn. <see cref="Arrive"/> is the plain
/// fade-in used when the front itself starts.
/// </summary>
public class CloudCurtain : MonoBehaviour
{
    public static CloudCurtain Current { get; private set; }

    /// <summary>The curtain, made if there isn't one.</summary>
    public static CloudCurtain Get()
    {
        if (Current == null)
        {
            var go = new GameObject("CloudCurtain");
            DontDestroyOnLoad(go);
            Current = go.AddComponent<CloudCurtain>();
        }
        return Current;
    }

    /// <summary>How far into the clouds the front is, 0–1. The wash comes up over the last stretch.</summary>
    public float Cover { get => cover; set => cover = Mathf.Clamp01(value); }

    enum Mode { Steady, Arriving, Revealing }

    Mode mode = Mode.Steady;
    float cover, wash;
    float modeStart, modeSeconds;
    bool sceneLanded;

    // The clouds that part on arrival.
    Material cloudMaterial;
    readonly List<Mesh> cloudMeshes = new();
    readonly List<(Transform t, Vector3 start, Vector3 dir, float scale)> shards = new();

    void OnDestroy()
    {
        if (Current == this)
            Current = null;
        SceneManager.sceneLoaded -= OnSceneLoaded;
        if (cloudMaterial != null)
            Destroy(cloudMaterial);
        foreach (var m in cloudMeshes)
            Destroy(m);
    }

    /// <summary>Start white and fade onto the current scene.</summary>
    public void Arrive(float seconds)
    {
        wash = 1f;
        mode = Mode.Arriving;
        modeStart = Time.unscaledTime;
        modeSeconds = seconds;
    }

    /// <summary>
    /// Hold white through the coming scene load, then part a shell of clouds over
    /// <paramref name="seconds"/> onto whatever loaded, and go away.
    /// </summary>
    public void Reveal(float seconds)
    {
        cover = wash = 1f;
        mode = Mode.Revealing;
        modeSeconds = seconds;
        sceneLanded = false;
        modeStart = Time.unscaledTime;
        SceneManager.sceneLoaded += OnSceneLoaded;
    }

    void OnSceneLoaded(Scene scene, LoadSceneMode loadMode)
    {
        SceneManager.sceneLoaded -= OnSceneLoaded;
        sceneLanded = true;
        modeStart = Time.unscaledTime + 0.3f; // a beat of white while the new scene settles
    }

    void Update()
    {
        float dt = Time.unscaledDeltaTime;
        switch (mode)
        {
            case Mode.Steady:
            {
                float want = Mathf.SmoothStep(0f, 1f, Mathf.InverseLerp(0.72f, 1f, cover));
                wash = Mathf.MoveTowards(wash, want, dt * 2.5f);
                break;
            }
            case Mode.Arriving:
            {
                float p = Mathf.Clamp01((Time.unscaledTime - modeStart) / modeSeconds);
                wash = 1f - Mathf.SmoothStep(0f, 1f, p);
                if (p >= 1f)
                    mode = Mode.Steady;
                break;
            }
            case Mode.Revealing:
            {
                if (!sceneLanded)
                {
                    if (Time.unscaledTime - modeStart > 4f)
                        OnSceneLoaded(default, default);   // the load never told us; don't stay white forever
                    wash = 1f;
                    break;
                }
                if (shards.Count == 0)
                {
                    var cam = Camera.main ?? (Camera.allCamerasCount > 0 ? Camera.allCameras[0] : null);
                    if (cam == null) { wash = 1f; break; }   // the scene hasn't a camera yet
                    Shell(cam);
                    modeStart = Time.unscaledTime;
                }
                float p = Mathf.Clamp01((Time.unscaledTime - modeStart) / modeSeconds);
                wash = 1f - Mathf.SmoothStep(0f, 1f, Mathf.InverseLerp(0f, 0.22f, p));   // white gives way to the clouds
                float e = Mathf.SmoothStep(0f, 1f, Mathf.InverseLerp(0.18f, 1f, p));    // which then fly apart
                foreach (var (t, start, dir, scale) in shards)
                {
                    if (t == null) continue;
                    t.localPosition = start + dir * (e * 8f);
                    t.localScale = Vector3.one * (scale * (1f - 0.7f * e));
                }
                if (p >= 1f)
                    Destroy(gameObject);
                break;
            }
        }
    }

    /// <summary>Hang clouds across the camera's view, close, in two layers, with no gaps.</summary>
    void Shell(Camera cam)
    {
        if (cloudMaterial == null)
        {
            cloudMaterial = LowPoly.PaletteMaterial(false);
            for (int i = 0; i < 5; i++)
                cloudMeshes.Add(LowPoly.Cloud(700 + i));
        }
        var rng = new System.Random(3);
        float R(float lo, float hi) => lo + (float)rng.NextDouble() * (hi - lo);
        void Layer(float depth, int cols, int rows, float size, float jitter)
        {
            float hh = depth * Mathf.Tan(cam.fieldOfView * 0.5f * Mathf.Deg2Rad) * 1.15f;
            float hw = hh * cam.aspect;
            for (int r = 0; r < rows; r++)
                for (int c = 0; c < cols; c++)
                {
                    var local = new Vector3(
                        Mathf.Lerp(-hw, hw, (c + 0.5f) / cols) + R(-jitter, jitter),
                        Mathf.Lerp(-hh, hh, (r + 0.5f) / rows) + R(-jitter, jitter),
                        depth + R(-0.2f, 0.2f));
                    var go = new GameObject("Cloud");
                    go.transform.SetParent(cam.transform, false);
                    go.transform.localPosition = local;
                    go.transform.localRotation = Quaternion.Euler(0f, R(-30f, 30f), 0f);
                    float s = size * R(0.9f, 1.25f);
                    go.transform.localScale = Vector3.one * s;
                    go.AddComponent<MeshFilter>().sharedMesh = cloudMeshes[rng.Next(cloudMeshes.Count)];
                    var mr = go.AddComponent<MeshRenderer>();
                    mr.sharedMaterial = cloudMaterial;
                    mr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
                    mr.receiveShadows = false;
                    // Fly outward from the middle of the view and a little back past the camera.
                    var dir = new Vector3(local.x, local.y, -0.6f * depth).normalized;
                    shards.Add((go.transform, local, dir, s));
                }
        }
        Layer(4.5f, 4, 3, 2.2f, 0.5f);
        Layer(2.6f, 4, 3, 1.5f, 0.3f);
    }

    void OnGUI()
    {
        if (Event.current.type != EventType.Repaint || wash <= 0f)
            return;
        GUI.depth = -100;                 // over every scene's own UI
        var prev = GUI.color;
        GUI.color = new Color(1f, 1f, 1f, wash);
        GUI.DrawTexture(new Rect(0f, 0f, Screen.width, Screen.height), Texture2D.whiteTexture);
        GUI.color = prev;
    }
}
