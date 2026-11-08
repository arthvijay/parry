using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

/// <summary>
/// The venue's mood, from the date's lighting preset and ambience list. The scanned world
/// is a Gaussian splat with its light baked in, so the grade happens in post-processing: a
/// runtime URP Volume sets white balance, colour filter, exposure and vignette for the whole
/// frame, splats included. Unity lights carry the same mood onto the avatars (and a
/// flickering candle or a neon accent where the preset has one). Ambient loops come from
/// the orchestrator when it has them, and are synthesised otherwise: rain, night crickets,
/// a distant city, a warm pad. Ducked while anyone speaks.
/// </summary>
public class VenueAmbience : MonoBehaviour
{
    public static VenueAmbience Instance { get; private set; }

    [Range(0f, 1f)] public float ambienceVolume = 0.3f;
    [Tooltip("Ambience level while a character or the learner is speaking.")]
    [Range(0f, 1f)] public float duckTo = 0.45f;

    struct Preset
    {
        public float temperature, tint, exposure, saturation, vignette, sun;
        public Color filter, sunColor, ambient, accent;
        public bool candle;
    }

    static readonly Dictionary<string, Preset> Presets = new()
    {
        ["warm_sunset_lounge"] = new Preset { temperature = 28f, tint = 6f, exposure = 0.05f, saturation = 12f, vignette = 0.22f,
            filter = new Color(1f, 0.9f, 0.8f), sun = 1.1f, sunColor = new Color(1f, 0.72f, 0.5f), ambient = new Color(0.55f, 0.43f, 0.38f) },
        ["cool_rainy_evening"] = new Preset { temperature = -22f, tint = -4f, exposure = -0.35f, saturation = -18f, vignette = 0.32f,
            filter = new Color(0.82f, 0.88f, 1f), sun = 0.6f, sunColor = new Color(0.65f, 0.72f, 0.88f), ambient = new Color(0.3f, 0.34f, 0.43f) },
        ["candlelit_night"] = new Preset { temperature = 35f, tint = 4f, exposure = -0.75f, saturation = -6f, vignette = 0.42f,
            filter = new Color(1f, 0.8f, 0.62f), sun = 0.35f, sunColor = new Color(1f, 0.62f, 0.38f), ambient = new Color(0.2f, 0.15f, 0.13f),
            candle = true, accent = new Color(1f, 0.62f, 0.3f) },
        ["city_night_neon"] = new Preset { temperature = -10f, tint = 22f, exposure = -0.6f, saturation = 18f, vignette = 0.38f,
            filter = new Color(0.86f, 0.8f, 1f), sun = 0.45f, sunColor = new Color(0.6f, 0.52f, 0.95f), ambient = new Color(0.24f, 0.2f, 0.34f),
            accent = new Color(1f, 0.25f, 0.6f) },
    };

    readonly List<AudioSource> loops = new();
    Light accentLight;
    Preset current;
    bool hasAccent;
    float duck = 1f;

    public static VenueAmbience Ensure()
    {
        if (Instance != null)
            return Instance;
        return new GameObject("Venue Ambience").AddComponent<VenueAmbience>();
    }

    void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(this);
            return;
        }
        Instance = this;
    }

    void OnDestroy()
    {
        if (Instance == this)
            Instance = null;
    }

    public void Apply(DateScenario s)
    {
        if (s == null)
            return;
        if (!Presets.TryGetValue(s.lighting_preset ?? "", out current))
            current = Presets["warm_sunset_lounge"];
        Grade(current);
        ApplyLights(current);
        // Fluent learners get a livelier, louder room.
        ambienceVolume *= s.proficiency switch { "A1" => 0.6f, "A2" => 0.7f, "C1" => 1.25f, "C2" => 1.4f, _ => 1f };
        StartCoroutine(Sounds(s.venue?.ambience ?? Array.Empty<string>()));
    }

    void Grade(Preset p)
    {
        var volume = gameObject.AddComponent<Volume>();
        volume.isGlobal = true;
        volume.priority = 50f;
        var profile = ScriptableObject.CreateInstance<VolumeProfile>();
        var wb = profile.Add<WhiteBalance>(true);
        wb.temperature.Override(p.temperature);
        wb.tint.Override(p.tint);
        var ca = profile.Add<ColorAdjustments>(true);
        ca.postExposure.Override(p.exposure);
        ca.saturation.Override(p.saturation);
        ca.colorFilter.Override(p.filter);
        var vignette = profile.Add<Vignette>(true);
        vignette.intensity.Override(p.vignette);
        vignette.smoothness.Override(0.45f);
        volume.profile = profile;
        foreach (var cam in FindObjectsByType<Camera>(FindObjectsSortMode.None))
        {
            var data = cam.GetUniversalAdditionalCameraData();
            if (data != null)
                data.renderPostProcessing = true;
        }
    }

    void ApplyLights(Preset p)
    {
        foreach (var l in FindObjectsByType<Light>(FindObjectsSortMode.None))
            if (l.type == LightType.Directional)
            {
                l.color = p.sunColor;
                l.intensity = p.sun;
            }
        RenderSettings.ambientMode = AmbientMode.Flat;
        RenderSettings.ambientLight = p.ambient;
        hasAccent = p.candle || p.accent.a > 0f;
        if (!hasAccent)
            return;
        var date = CastClient.Date;
        Vector3 at = date != null ? date.transform.position : Vector3.zero;
        accentLight = new GameObject(p.candle ? "Candle" : "Neon").AddComponent<Light>();
        accentLight.type = LightType.Point;
        accentLight.color = p.accent;
        accentLight.range = p.candle ? 3f : 6f;
        accentLight.intensity = p.candle ? 1.6f : 2.2f;
        accentLight.transform.position = at + Vector3.up * (p.candle ? 0.9f : 2.2f) + (date != null ? date.transform.forward * 0.6f : Vector3.zero);
    }

    void Update()
    {
        if (accentLight != null)
        {
            // A candle flickers; neon hums steady.
            if (current.candle)
                accentLight.intensity = 1.4f + Mathf.PerlinNoise(Time.time * 6f, 0.3f) * 0.6f;
            var date = CastClient.Date;
            if (date != null && accentLight.transform.position.sqrMagnitude < 0.01f)
                accentLight.transform.position = date.transform.position + Vector3.up * 0.9f + date.transform.forward * 0.6f;
        }
        var client = FullDuplexStreamClient.Instance;
        bool speech = client != null && (client.NpcSpeaking || client.UserSpeaking);
        duck = Mathf.MoveTowards(duck, speech ? duckTo : 1f, Time.deltaTime * 2f);
        foreach (var src in loops)
            if (src != null)
                src.volume = ambienceVolume * duck * (src.name.Contains("murmur") ? 0.7f : 1f);
    }

    // ---- sound ----------------------------------------------------------------------

    IEnumerator Sounds(string[] ids)
    {
        var available = new Dictionary<string, string>();
        string root = FullDuplexStreamClient.Instance != null ? FullDuplexStreamClient.Instance.Base : DateSession.Base;
        using (var list = UnityWebRequest.Get($"{root}/v1/ambience"))
        {
            list.timeout = 8;
            yield return list.SendWebRequest();
            if (list.result == UnityWebRequest.Result.Success)
            {
                var sounds = Json.Obj(list.downloadHandler.text).List("sounds");
                if (sounds != null)
                    foreach (var o in sounds)
                        if (o is Dictionary<string, object> d && d.Bool("ready") && d.Bool("loop"))
                            available[d.Str("id")] = d.Str("url");
            }
        }
        foreach (var id in ids)
        {
            AudioClip clip = null;
            if (available.TryGetValue(id, out var url))
            {
                using var req = UnityWebRequestMultimedia.GetAudioClip(url.StartsWith("http") ? url : root + url, AudioType.MPEG);
                req.timeout = 20;
                yield return req.SendWebRequest();
                if (req.result == UnityWebRequest.Result.Success)
                    clip = DownloadHandlerAudioClip.GetContent(req);
            }
            if (clip == null)
                clip = Synthesise(id);
            if (clip == null)
                continue;
            var src = new GameObject($"Ambience {id}").AddComponent<AudioSource>();
            src.transform.SetParent(transform, false);
            src.clip = clip;
            src.loop = true;
            src.spatialBlend = 0f;
            src.volume = 0f;
            src.Play();
            loops.Add(src);
        }
    }

    /// <summary>Loops for venues the server has no recording of.</summary>
    static AudioClip Synthesise(string id)
    {
        const int rate = 22050;
        const float seconds = 8f;
        int n = (int)(rate * seconds);
        var data = new float[n];
        var rng = new System.Random(id.GetHashCode());
        float Noise() => (float)(rng.NextDouble() * 2.0 - 1.0);
        float lp = 0f, brown = 0f;
        if (id.Contains("rain"))
        {
            for (int i = 0; i < n; i++)
            {
                lp += 0.35f * (Noise() - lp);
                data[i] = lp * 0.35f;
                if (rng.NextDouble() < 0.0009)  // droplets
                    for (int k = 0; k < 220 && i + k < n; k++)
                        data[i + k] += Mathf.Sin(k * 0.9f) * Mathf.Exp(-k / 40f) * 0.25f;
            }
        }
        else if (id.Contains("garden") || id.Contains("night"))
        {
            for (int i = 0; i < n; i++)
            {
                float t = i / (float)rate;
                lp += 0.02f * (Noise() - lp);
                float chirp = Mathf.Sin(2f * Mathf.PI * 4300f * t) * Mathf.Max(0f, Mathf.Sin(2f * Mathf.PI * 22f * t))
                              * (Mathf.Repeat(t, 1.3f) < 0.35f ? 1f : 0f);
                data[i] = lp * 0.5f + chirp * 0.05f;
            }
        }
        else if (id.Contains("city"))
        {
            for (int i = 0; i < n; i++)
            {
                brown = Mathf.Clamp(brown + Noise() * 0.02f, -1f, 1f) * 0.998f;
                data[i] = brown * 0.6f;
            }
        }
        else if (id.Contains("jazz") || id.Contains("pad"))
        {
            float[] chord = { 220f, 277.18f, 329.63f, 415.3f };
            for (int i = 0; i < n; i++)
            {
                float t = i / (float)rate, s = 0f;
                foreach (float f in chord)
                    s += Mathf.Sin(2f * Mathf.PI * f * t) * (0.5f + 0.5f * Mathf.Sin(2f * Mathf.PI * 0.125f * t + f));
                data[i] = s * 0.04f;
            }
        }
        else
            return null;
        // Cross-fade the ends so the loop has no seam.
        int fade = rate / 4;
        for (int i = 0; i < fade; i++)
        {
            float k = i / (float)fade;
            data[i] = data[i] * k + data[n - fade + i] * (1f - k);
        }
        var clip = AudioClip.Create($"synth-{id}", n - fade, 1, rate, false);
        var trimmed = new float[n - fade];
        Array.Copy(data, trimmed, n - fade);
        clip.SetData(trimmed, 0);
        return clip;
    }
}
