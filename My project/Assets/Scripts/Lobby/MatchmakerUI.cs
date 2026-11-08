using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using UnityEngine.SceneManagement;

/// <summary>
/// The front of the app, styled like the pitch deck: a night sky ("the bar at midnight"),
/// a lit Earth with an atmosphere glow and city lights (shaders in Assets/Shaders/Matchmaker),
/// and a start screen with the neon name, the two authored demo dates (one card per preset:
/// the Spanish date and the American date) and "create your own".
///
/// Create your own opens the matchmaker's studio.
/// Three steps on one glass panel: the face scan (<see cref="AvatarOnboarding"/>: selfie in,
/// avatar out), the language (dialect, city, level; the globe turns and pins the city), and
/// the date (who, what personality, where, and a free-text scene that sets the world).
/// Start Speed Date asks <c>POST /v1/matchmaker/generate</c> for the person, shows who you
/// are meeting, then flies you there: the globe rushes up to the pin while the clouds close
/// in, the venue loads behind the white, and the clouds part onto the spawn
/// (<see cref="CloudCurtain"/>). Everything in the scene is flat-shaded geometry built at
/// start (<see cref="LowPoly"/>); the type is IMGUI on <see cref="GlassUI"/>.
/// </summary>
public class MatchmakerUI : MonoBehaviour
{
    [Header("Server")]
    public string serverUrl = DateSession.DefaultServer;

    [Header("Look")]
    // The deck's night: ink at the zenith, wine towards the horizon, a rose glow below.
    public Color skyZenith = new(0.035f, 0.012f, 0.03f);
    public Color skyHorizon = new(0.17f, 0.05f, 0.11f);
    public Color skyBelow = new(0.30f, 0.09f, 0.15f);
    public Vector3 globeCentre = new(2.4f, -0.15f, 0f);
    public float globeRadius = 1.6f;
    [Tooltip("Degrees per second the globe idles at before a city is chosen.")]
    public float idleSpin = 5f;

    [Header("Timing")]
    [Tooltip("Seconds from the match card to the venue loading.")]
    public float tripSeconds = 7f;
    public float arriveSeconds = 2.4f;
    public float revealSeconds = 3.2f;

    enum Step { Start, Face, Language, Date, Matching, Matched, Boarding, Departing }

    Step step = Step.Start;
    float stepStart;
    string destinationScene = "Assets/Scenes/CancunCafe.unity";

    // Choices.
    Catalog catalog;
    string catalogError = "";
    string learnerName = "";
    string dialect = "es-MX";
    string city = "";
    string level = "B1";
    string dateGender = "female";
    string appearance = "latina";
    string personality = "playful_sarcastic";
    string venue = "auto";
    string scenePrompt = "";
    string notes = "";
    string matchError = "";
    DateScenario match;

    AvatarOnboarding onboarding;

    // The globe.
    Transform globe;
    Transform pin;
    float yaw, yawTarget;
    bool hasPin;
    string placeName = "";
    float pinLat, pinLon;
    Material skyMaterial, litMaterial, cloudMaterial, earthMaterial, atmosMaterial, starMaterial, pinMaterial;
    VisionPanel visionPanel;
    readonly List<Mesh> meshes = new();
    readonly List<Mesh> cloudMeshes = new();
    readonly List<Puff> puffs = new();
    System.Random cloudRng = new(11);
    Light sun;
    Camera cam;
    CloudCurtain curtain;
    float seaLift;
    bool loading;
    bool cloudsShown = true;

    class Puff
    {
        public Transform t;
        public float drift;
        public float size;
    }

    static readonly (float at, string title, string sub)[] Stages =
    {
        (0.00f, "Heading for {0}", "somewhere real, with real people in it"),
        (0.22f, "Setting the scene", "{1}"),
        (0.45f, "Meeting your match", "{2} is getting ready"),
        (0.66f, "Finding you a table", "the host will show you the way"),
        (0.82f, "Go.", "walk to the host · the mic is open, just talk"),
    };
    const float ZoomFrom = 0.08f, ZoomTo = 0.34f, CoverFrom = 0.08f, CoverTo = 0.64f;

    float Since => Time.time - stepStart;
    float Trip => step == Step.Boarding ? Mathf.Clamp01(Since / tripSeconds) : step == Step.Departing ? 1f : 0f;

    void Start()
    {
        Cursor.lockState = CursorLockMode.None;
        Cursor.visible = true;
        cam = Camera.main;
        if (!string.IsNullOrWhiteSpace(serverUrl) && serverUrl.TrimEnd('/') != DateSession.DefaultServer)
            DateSession.ServerUrl = serverUrl;
        learnerName = DateSession.LearnerName;

        Sky();
        BuildGlobe();
        BuildClouds();
        yaw = yawTarget = 40f;
        curtain = CloudCurtain.Get();
        curtain.Arrive(arriveSeconds);

        onboarding = GetComponent<AvatarOnboarding>();
        if (onboarding == null)
            onboarding = gameObject.AddComponent<AvatarOnboarding>();
        visionPanel = FindFirstObjectByType<VisionPanel>();
        if (visionPanel == null)
            visionPanel = gameObject.AddComponent<VisionPanel>();
        StartCoroutine(LoadCatalog());
        // Development aid, with SessionMenu's -shot: open on a given step.
        var args = Environment.GetCommandLineArgs();
        int at = Array.IndexOf(args, "-matchmaker-step");
        if (at >= 0 && at + 1 < args.Length && Enum.TryParse(args[at + 1], true, out Step wanted) && wanted <= Step.Date)
            step = wanted;
    }

    void OnDestroy()
    {
        foreach (var m in new[] { skyMaterial, litMaterial, cloudMaterial, earthMaterial, atmosMaterial, starMaterial, pinMaterial })
            if (m != null)
                Destroy(m);
        foreach (var m in meshes)
            if (m != null)
                Destroy(m);
    }

    // ---- server ----------------------------------------------------------------------

    IEnumerator LoadCatalog()
    {
        using var req = UnityWebRequest.Get($"{DateSession.Base}/v1/matchmaker/catalog");
        req.timeout = 8;
        yield return req.SendWebRequest();
        if (req.result == UnityWebRequest.Result.Success)
        {
            try { catalog = JsonUtility.FromJson<Catalog>(req.downloadHandler.text); }
            catch (Exception e) { catalogError = e.Message; }
        }
        else
            catalogError = "The orchestrator isn't running: uv run python -m orchestrator";
        if (catalog != null && catalog.dialects.Length > 0)
        {
            // Arriving from a receipt's "next date unlocked": open on that dialect.
            string next = DateSession.NextDialect;
            DateSession.NextDialect = null;
            if (!string.IsNullOrEmpty(next) && Array.Exists(catalog.dialects, d => d.code == next))
                dialect = next;
            ChooseDialect(dialect);
        }
    }

    /// <summary>The authored demo date: same café, same person, every time.</summary>
    IEnumerator GeneratePreset(PresetInfo preset)
    {
        step = Step.Matching;
        stepStart = Time.time;
        matchError = "";
        city = preset.city;
        Pin(preset.lat, preset.lon, preset.city);
        DateSession.LearnerName = learnerName;
        string body = Json.Write(new Dictionary<string, object>
        {
            ["preset"] = preset.id, ["learner_name"] = learnerName, ["proficiency"] = level,
            ["date_gender"] = dateGender == "male" ? "male" : "female",
        });
        using var req = new UnityWebRequest($"{DateSession.Base}/v1/matchmaker/preset", "POST")
        {
            uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(body)) { contentType = "application/json" },
            downloadHandler = new DownloadHandlerBuffer(),
            timeout = 30,
        };
        yield return req.SendWebRequest();
        while (Since < 2.2f)
            yield return null;
        yield return Matched(req);
    }

    IEnumerator Generate()
    {
        step = Step.Matching;
        stepStart = Time.time;
        matchError = "";
        DateSession.LearnerName = learnerName;
        string body = Json.Write(new Dictionary<string, object>
        {
            ["learner_name"] = learnerName, ["language"] = dialect, ["proficiency"] = level,
            ["venue_style"] = venue, ["date_gender"] = dateGender, ["date_ethnicity"] = appearance,
            ["personality_archetype"] = personality, ["custom_notes"] = notes,
            ["scene_prompt"] = scenePrompt, ["city"] = string.IsNullOrEmpty(city) ? null : city,
        });
        using var req = new UnityWebRequest($"{DateSession.Base}/v1/matchmaker/generate", "POST")
        {
            uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(body)) { contentType = "application/json" },
            downloadHandler = new DownloadHandlerBuffer(),
            timeout = 90,
        };
        yield return req.SendWebRequest();
        // Let the matchmaking moment breathe even when the templates answer instantly.
        while (Since < 2.2f)
            yield return null;
        yield return Matched(req);
    }

    IEnumerator Matched(UnityWebRequest req)
    {
        if (req.result != UnityWebRequest.Result.Success || !DateSession.SetScenario(req.downloadHandler.text))
        {
            matchError = FullDuplexStreamClient.Describe(req);
            step = Step.Date;
            yield break;
        }
        match = DateSession.Scenario;
        destinationScene = DateSession.ScenePath(match.venue_scene);
        var c = FindCity(match.city);
        if (c != null)
            Pin(c.lat, c.lon, c.name);
        step = Step.Matched;
        stepStart = Time.time;
        Debug.Log($"Matchmaker: {match.date_character.display_name} in {match.city}, {match.venue?.label} → {destinationScene}");
    }

    CityInfo FindCity(string name)
    {
        if (catalog == null)
            return null;
        foreach (var d in catalog.dialects)
            foreach (var c in d.cities)
                if (string.Equals(c.name, name, StringComparison.OrdinalIgnoreCase))
                    return c;
        return null;
    }

    void ChooseDialect(string code)
    {
        dialect = code;
        var d = Array.Find(catalog?.dialects ?? Array.Empty<DialectInfo>(), x => x.code == code);
        if (d != null && d.cities.Length > 0)
        {
            if (Array.Find(d.cities, c => c.name == city) == null)
                city = d.cities[0].name;
            var c = Array.Find(d.cities, x => x.name == city);
            Pin(c.lat, c.lon, c.name);
        }
    }

    // ---- the trip ----------------------------------------------------------------------

    void Update()
    {
        if (step == Step.Matched && Since > 3.2f)
        {
            step = Step.Boarding;
            stepStart = Time.time;
        }
        if (step == Step.Boarding && Since >= tripSeconds)
            Depart();

        float t = Trip;
        if (visionPanel != null)
            visionPanel.enabled = step == Step.Face;
        if (step <= Step.Matching)
            yawTarget = hasPin ? pinLon + 25f : yawTarget + idleSpin * Time.deltaTime;
        else
            yawTarget = pinLon;
        yaw = Mathf.LerpAngle(yaw, yawTarget, 1f - Mathf.Exp(-3f * Time.deltaTime));
        globe.rotation = Quaternion.Euler(-12f, 0f, 0f) * Quaternion.Euler(0f, yaw, 0f);

        float zoom = Mathf.SmoothStep(0f, 1f, Mathf.InverseLerp(ZoomFrom, ZoomTo, t));
        float scale = Mathf.Lerp(1f, 3.5f, zoom);
        globe.localScale = Vector3.one * scale;
        var pinWorldDir = globe.rotation * PinLocal(pinLat, pinLon);
        var zoomed = new Vector3(0.4f, -0.2f, 0f) - pinWorldDir * globeRadius * scale;
        globe.position = Vector3.Lerp(globeCentre, zoomed, zoom);
        if (pin != null)
            pin.localScale = Vector3.one * (0.032f + 0.008f * Mathf.Sin(Time.time * 4f));

        float cover = step < Step.Boarding ? 0f : Mathf.SmoothStep(0f, 1f, Mathf.InverseLerp(CoverFrom, CoverTo, t));
        MoveClouds(cover);
        // The night sky stays clear until the trip: the clouds rush in for the flight.
        bool showClouds = step >= Step.Matched;
        if (showClouds != cloudsShown)
        {
            cloudsShown = showClouds;
            foreach (var p in puffs)
                p.t.gameObject.SetActive(showClouds);
        }
        if (curtain != null && step != Step.Departing)
            curtain.Cover = cover;
    }

    void Depart()
    {
        if (loading)
            return;
        loading = true;
        step = Step.Departing;
        stepStart = Time.time;
        if (curtain != null)
            curtain.Reveal(revealSeconds);
#if UNITY_EDITOR
        if (SceneUtility.GetBuildIndexByScenePath(destinationScene) < 0)
        {
            UnityEditor.SceneManagement.EditorSceneManager.LoadSceneInPlayMode(destinationScene, new LoadSceneParameters(LoadSceneMode.Single));
            return;
        }
#endif
        SceneManager.LoadScene(destinationScene);
    }

    // ---- the sky, the globe and the clouds ---------------------------------------------

    void Sky()
    {
        if (cam != null)
        {
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = skyHorizon;
        }
        var dome = new GameObject("Sky");
        dome.transform.SetParent(transform, false);
        dome.transform.position = cam != null ? cam.transform.position : Vector3.zero;
        dome.transform.localScale = Vector3.one * 60f;
        skyMaterial = LowPoly.GradientMaterial(skyBelow, skyHorizon, skyZenith);
        Piece(dome, LowPoly.Dome(), skyMaterial);

        RenderSettings.ambientMode = AmbientMode.Flat;
        RenderSettings.ambientLight = new Color(0.20f, 0.14f, 0.20f);
        sun = new GameObject("Sun").AddComponent<Light>();
        sun.transform.SetParent(transform, false);
        sun.type = LightType.Directional;
        sun.color = new Color(1f, 0.93f, 0.85f);
        sun.intensity = 1.3f;
        sun.shadows = LightShadows.None;
        // From the upper left and a little behind the camera: the Earth's lit face turns
        // towards the studio, the night side and its city lights to the right.
        sun.transform.rotation = Quaternion.Euler(20f, 40f, 0f);
        Stars();
        Glow();
    }

    /// <summary>A starfield: tiny twinkling quads on a far sphere around the camera.</summary>
    void Stars()
    {
        var shader = Shader.Find("Matchmaker/Stars");
        if (shader == null || cam == null)
            return;
        var rng = new System.Random(7);
        var verts = new List<Vector3>(); var cols = new List<Color>(); var uvs = new List<Vector2>(); var tris = new List<int>();
        for (int i = 0; i < 1600; i++)
        {
            // Mostly in front of and around the camera; none below the horizon glow.
            var dir = new Vector3((float)rng.NextDouble() * 2f - 1f, (float)rng.NextDouble() * 1.4f - 0.25f,
                                  (float)rng.NextDouble() * 1.6f - 0.2f).normalized;
            var c = dir * 48f;
            float size = 0.05f + 0.20f * Mathf.Pow((float)rng.NextDouble(), 4f);
            var right = Vector3.Cross(dir, Vector3.up).normalized * size;
            var up = Vector3.Cross(right, dir).normalized * size;
            int b = verts.Count;
            verts.Add(c - right - up); verts.Add(c + right - up); verts.Add(c + right + up); verts.Add(c - right + up);
            uvs.Add(new Vector2(0, 0)); uvs.Add(new Vector2(1, 0)); uvs.Add(new Vector2(1, 1)); uvs.Add(new Vector2(0, 1));
            float bright = 0.25f + 0.75f * (float)rng.NextDouble();
            float warm = (float)rng.NextDouble();
            var tint = warm < 0.2f ? new Color(1f, 0.82f, 0.7f) : warm > 0.85f ? new Color(0.75f, 0.85f, 1f) : Color.white;
            var col = new Color(tint.r * bright, tint.g * bright, tint.b * bright, (float)rng.NextDouble());
            for (int k = 0; k < 4; k++) cols.Add(col);
            tris.AddRange(new[] { b, b + 1, b + 2, b, b + 2, b + 3 });
        }
        var mesh = new Mesh { name = "Stars" };
        mesh.SetVertices(verts); mesh.SetColors(cols); mesh.SetUVs(0, uvs); mesh.SetTriangles(tris, 0);
        mesh.bounds = new Bounds(Vector3.zero, Vector3.one * 200f);
        starMaterial = new Material(shader);
        var go = new GameObject("Stars");
        go.transform.SetParent(transform, false);
        go.transform.position = cam.transform.position;
        Piece(go, mesh, starMaterial);
    }

    /// <summary>Bloom, filmic tonemapping and a vignette, so the Earth's limb, the city
    /// lights and the neon read like the deck.</summary>
    void Glow()
    {
        if (cam == null)
            return;
        var data = cam.GetUniversalAdditionalCameraData();
        data.renderPostProcessing = true;
        data.antialiasing = AntialiasingMode.SubpixelMorphologicalAntiAliasing;
        data.antialiasingQuality = AntialiasingQuality.High;
        var volume = gameObject.AddComponent<Volume>();
        volume.isGlobal = true;
        volume.priority = 10f;
        var profile = volume.profile;
        var bloom = profile.Add<Bloom>(true);
        bloom.intensity.Override(0.9f);
        bloom.threshold.Override(0.75f);
        bloom.scatter.Override(0.72f);
        bloom.tint.Override(new Color(1f, 0.82f, 0.86f));
        var tone = profile.Add<Tonemapping>(true);
        tone.mode.Override(TonemappingMode.ACES);
        var vignette = profile.Add<Vignette>(true);
        vignette.intensity.Override(0.32f);
        vignette.smoothness.Override(0.5f);
        vignette.color.Override(new Color(0.07f, 0.02f, 0.05f));
        var grade = profile.Add<ColorAdjustments>(true);
        grade.postExposure.Override(0.15f);
        grade.contrast.Override(12f);
        grade.saturation.Override(8f);
    }

    void BuildGlobe()
    {
        globe = new GameObject("Globe").transform;
        globe.SetParent(transform, false);
        globe.position = globeCentre;
        litMaterial = LowPoly.PaletteMaterial(true);
        cloudMaterial = LowPoly.PaletteMaterial(false);
        var map = Resources.Load<Texture2D>("Wish/earth_map");
        if (map == null)
            Debug.LogWarning("MatchmakerUI: no land/sea map at Resources/Wish/earth_map; the Earth will be all ocean");
        var earth = new GameObject("Earth");
        earth.transform.SetParent(globe, false);
        earth.transform.localScale = Vector3.one * globeRadius;
        var earthShader = Shader.Find("Matchmaker/Earth");
        if (earthShader == null || map == null)
        {
            Piece(earth, LowPoly.Earth(map), litMaterial);   // the flat-shaded fallback
            return;
        }
        map.filterMode = FilterMode.Bilinear;
        map.anisoLevel = 4;
        earthMaterial = new Material(earthShader);
        earthMaterial.SetTexture("_MainTex", map);
        Piece(earth, LowPoly.SmoothSphere(160, 80), earthMaterial);

        var atmosShader = Shader.Find("Matchmaker/Atmosphere");
        if (atmosShader != null)
        {
            atmosMaterial = new Material(atmosShader);
            var halo = new GameObject("Atmosphere");
            halo.transform.SetParent(globe, false);
            halo.transform.localScale = Vector3.one * globeRadius * 1.09f;
            Piece(halo, LowPoly.SmoothSphere(96, 48), atmosMaterial);
        }
        SunToMaterials();
    }

    void SunToMaterials()
    {
        if (sun == null)
            return;
        var toSun = -sun.transform.forward;
        foreach (var m in new[] { earthMaterial, atmosMaterial })
            if (m != null)
                m.SetVector("_SunDir", new Vector4(toSun.x, toSun.y, toSun.z, 0f));
    }

    void BuildClouds()
    {
        if (cloudMaterial != null)
        {
            // Clouds at dusk, lit by the city below and the last of the sun.
            cloudMaterial.SetColor("_BaseColor", new Color(0.62f, 0.48f, 0.60f));
            cloudMaterial.SetColor("_Color", new Color(0.62f, 0.48f, 0.60f));
        }
        for (int i = 0; i < 5; i++)
            cloudMeshes.Add(LowPoly.Cloud(100 + i));
        for (int i = 0; i < 34; i++)
            Spawn(true);
    }

    float R(float lo, float hi) => lo + (float)cloudRng.NextDouble() * (hi - lo);

    Puff Spawn(bool anywhere)
    {
        var go = new GameObject("Cloud");
        go.transform.SetParent(transform, false);
        go.transform.rotation = Quaternion.Euler(0f, R(-40f, 40f), 0f);
        var puff = new Puff { t = go.transform, drift = R(0.10f, 0.22f), size = R(0.9f, 1.7f) };
        go.transform.localScale = Vector3.one * puff.size;
        var mr = Piece(go, cloudMeshes[cloudRng.Next(cloudMeshes.Count)], cloudMaterial);
        mr.shadowCastingMode = ShadowCastingMode.Off;
        ResetPuff(puff, anywhere);
        puffs.Add(puff);
        return puff;
    }

    void ResetPuff(Puff p, bool anywhere)
    {
        float z = anywhere ? R(-3f, 15f) : R(14f, 19f);
        p.t.position = new Vector3(R(-10f, 10f), R(-2.7f, -1.8f), z);
    }

    void MoveClouds(float cover)
    {
        float dt = Time.deltaTime;
        float camZ = cam != null ? cam.transform.position.z : -5f;
        float rush = cover * cover * 11f;
        float lift = Mathf.SmoothStep(0f, 1f, cover) * 2.4f;
        float dLift = lift - seaLift;
        seaLift = lift;
        foreach (var p in puffs)
        {
            var pos = p.t.position;
            pos.x += p.drift * dt;
            pos.z -= rush * dt;
            pos.y += dLift;
            if (pos.x > 11f)
                pos.x -= 22f;
            if (pos.z < camZ - 2.5f)
            {
                ResetPuff(p, false);
                pos = p.t.position;
                pos.x = Mathf.Lerp(pos.x, R(-2.5f, 2.5f), cover);
                pos.y = Mathf.Lerp(pos.y + seaLift, R(-1.5f, 1.8f), cover);
            }
            p.t.position = pos;
        }
        int want = 34 + Mathf.RoundToInt(Mathf.InverseLerp(0.3f, 0.9f, cover) * 30f);
        while (puffs.Count < want)
        {
            var extra = Spawn(false);
            extra.t.position = new Vector3(R(-3f, 3f), R(-1.5f, 2f), extra.t.position.z);
        }
    }

    MeshRenderer Piece(GameObject go, Mesh mesh, Material material)
    {
        if (!meshes.Contains(mesh))
            meshes.Add(mesh);
        go.AddComponent<MeshFilter>().sharedMesh = mesh;
        var mr = go.AddComponent<MeshRenderer>();
        mr.sharedMaterial = material;
        mr.shadowCastingMode = ShadowCastingMode.Off;
        mr.receiveShadows = false;
        return mr;
    }

    static Vector3 PinLocal(float lat, float lon)
    {
        float la = lat * Mathf.Deg2Rad, lo = lon * Mathf.Deg2Rad;
        return new Vector3(Mathf.Cos(la) * Mathf.Sin(lo), Mathf.Sin(la), -Mathf.Cos(la) * Mathf.Cos(lo));
    }

    void Pin(float lat, float lon, string name)
    {
        if (pin != null)
            Destroy(pin.gameObject);
        pinLat = lat;
        pinLon = lon;
        placeName = name;
        hasPin = true;
        var marker = new GameObject("Pin");
        if (pinMaterial == null)
        {
            pinMaterial = new Material(cloudMaterial);
            // Over-bright, so the bloom turns it into a beacon.
            pinMaterial.SetColor("_BaseColor", new Color(1.7f, 0.42f, 0.72f));
            pinMaterial.SetColor("_Color", new Color(1.7f, 0.42f, 0.72f));
        }
        Piece(marker, LowPoly.Ball(LowPoly.Swatch.Cloud), pinMaterial);
        pin = marker.transform;
        pin.SetParent(globe, false);
        pin.localPosition = PinLocal(lat, lon) * (globeRadius * 1.005f);
    }

    // ---- the studio --------------------------------------------------------------------

    void OnGUI()
    {
        GUI.depth = -200;
        var m = GlassUI.Begin();
        float W = GlassUI.Width;

        if (step > Step.Start && step < Step.Boarding)
        {
            GlassUI.Neon(new Rect(56f, 14f, 300f, 60f), Brand.Name, 44, Brand.Accent);
            if (step <= Step.Date && GlassUI.Button(new Rect(W - 330f, 26f, 130f, 34f), "←  Start", false, true, 13))
                step = Step.Start;
        }
        PinLabel();
        switch (step)
        {
            case Step.Start:
                StartScreen();
                break;
            case Step.Face:
            case Step.Language:
            case Step.Date:
                Studio(new Rect(60f, 110f, 620f, 580f));
                break;
            case Step.Matching:
                Matching(new Rect(60f, 250f, 520f, 180f));
                break;
            case Step.Matched:
                MatchCard(new Rect(60f, 200f, 560f, 300f));
                break;
            default:
                Status();
                break;
        }
        GlassUI.End(m);
    }

    /// <summary>The first thing the app shows: the neon name, the promise, the two demo
    /// dates (one card per authored preset) and the way into the matchmaker.</summary>
    void StartScreen()
    {
        float x = 72f, y = 70f;
        GlassUI.Eyebrow(new Rect(x, y, 420f, 20f), "Speed date · 3:00");
        GlassUI.Neon(new Rect(x - 6f, y + 20f, 560f, 130f), Brand.Name, 112, Brand.Accent);
        GlassUI.Headline(new Rect(x, y + 152f, 620f, 44f), "Keep up. Flirt back.", 34, Brand.Cream);
        GlassUI.Headline(new Rect(x, y + 192f, 620f, 44f), "<i>Speak like a local.</i>", 34, Brand.Accent);
        GlassUI.Label(new Rect(x, y + 244f, 560f, 40f),
                      "Three minutes across the table from someone who only speaks their dialect. They read your face, warm up or cool off, and print you a receipt.",
                      14, Brand.Muted, FontStyle.Normal, TextAnchor.UpperLeft, true);

        float cy = y + 300f;
        GlassUI.Eyebrow(new Rect(x, cy, 400f, 18f), "Jump straight in", Brand.Warn);
        var presets = catalog?.presets ?? Array.Empty<PresetInfo>();
        float cw = 280f, gap = 16f;
        for (int i = 0; i < Mathf.Min(2, presets.Length); i++)
            if (DemoCard(new Rect(x + i * (cw + gap), cy + 28f, cw, 128f), presets[i]))
                StartCoroutine(GeneratePreset(presets[i]));
        if (presets.Length == 0)
            GlassUI.Label(new Rect(x, cy + 28f, 560f, 40f),
                          string.IsNullOrEmpty(catalogError) ? "Loading the demo dates…" : catalogError, 13,
                          string.IsNullOrEmpty(catalogError) ? Brand.Muted : Brand.Bad, FontStyle.Normal, TextAnchor.UpperLeft, true);

        float ry = cy + 172f;
        GlassUI.Label(new Rect(x, ry, 90f, 30f), "Your date is", 12, Brand.Dim);
        if (GlassUI.Chip(new Rect(x + 92f, ry, 92f, 30f), "a woman", dateGender != "male", 12))
            dateGender = "female";
        if (GlassUI.Chip(new Rect(x + 192f, ry, 92f, 30f), "a man", dateGender == "male", 12))
            dateGender = "male";
        if (GlassUI.Button(new Rect(x + 360f, ry - 4f, 216f, 38f), "Create your own date  →", false, true, 14))
            step = Step.Face;

        GlassUI.Label(new Rect(x, GlassUI.Height - 40f, 700f, 18f),
                      "Esc  menu      F11  fullscreen      a microphone and a webcam make it real", 11, Brand.Dim);
    }

    /// <summary>One authored demo date as a card; returns true when clicked.</summary>
    bool DemoCard(Rect r, PresetInfo p)
    {
        bool hover = r.Contains(Event.current.mousePosition);
        if (hover)
            GlassUI.Glow(r, Brand.Accent, 18, 12f);
        GlassUI.Panel(r, 1f, 18);
        if (hover)
            GlassUI.Outline(r, new Color(1f, 0.24f, 0.43f, 0.8f), 18);
        string language = string.IsNullOrEmpty(p.language) ? p.dialect : p.language;
        GlassUI.Text(new Rect(r.x + 18f, r.y + 14f, r.width - 36f, 16f), GlassUI.Spaced(language), 10, Brand.Warn,
                     GlassUI.Face.Mono, FontStyle.Bold);
        string who = dateGender == "male" ? p.dates?.male : p.dates?.female;
        string venueName = string.IsNullOrEmpty(p.venue) ? (p.label ?? "").Split('·')[0].Trim() : p.venue;
        GlassUI.Headline(new Rect(r.x + 18f, r.y + 32f, r.width - 36f, 36f),
                         string.IsNullOrEmpty(who) ? venueName : $"{who} <i>at</i> {venueName}", 23, Brand.Cream);
        GlassUI.Label(new Rect(r.x + 18f, r.y + 68f, r.width - 36f, 18f), p.city, 12, Brand.Muted);
        GlassUI.Label(new Rect(r.x + 18f, r.yMax - 32f, r.width - 36f, 20f), "▶  Play this date", 13,
                      hover ? Brand.Cream : Brand.Accent, FontStyle.Bold);
        return GUI.Button(r, GUIContent.none, GUIStyle.none);
    }

    void Studio(Rect panel)
    {
        GlassUI.Panel(panel);
        // Step tabs.
        string[] tabs = { "1  Face scan", "2  Language", "3  Your date" };
        for (int i = 0; i < 3; i++)
        {
            var r = new Rect(panel.x + 20f + i * 196f, panel.y + 16f, 186f, 30f);
            var tab = Step.Face + i;
            if (GlassUI.Chip(r, tabs[i], step == tab) && (tab <= step || onboarding != null))
                step = tab;
        }
        var body = new Rect(panel.x + 20f, panel.y + 62f, panel.width - 40f, panel.height - 124f);
        if (!string.IsNullOrEmpty(catalogError))
            GlassUI.Label(new Rect(body.x, panel.yMax - 92f, body.width, 18f), catalogError, 12, Brand.Bad);

        switch (step)
        {
            case Step.Face:
                GlassUI.Label(new Rect(body.x, body.y, body.width, 20f), "Let's scan your face. Your avatar is built from your photo and mirrors you live.", 13, Brand.Muted);
                onboarding?.Draw(new Rect(body.x, body.y + 28f, body.width, body.height - 28f));
                break;
            case Step.Language:
                LanguageStep(body);
                break;
            case Step.Date:
                DateStep(body);
                break;
        }

        // Footer.
        var back = new Rect(panel.x + 20f, panel.yMax - 54f, 110f, 38f);
        var next = new Rect(panel.xMax - 220f, panel.yMax - 54f, 200f, 38f);
        if (GlassUI.Button(back, "Back"))
            step = step - 1;
        if (step == Step.Face && GlassUI.Button(next, "Next  →", true))
            step = Step.Language;
        else if (step == Step.Language && GlassUI.Button(next, "Next  →", true, catalog != null))
            step = Step.Date;
        else if (step == Step.Date && GlassUI.Button(next, "Start Speed Date  ❤", true, catalog != null))
            StartCoroutine(Generate());
        if (!string.IsNullOrEmpty(matchError))
            GlassUI.Label(new Rect(panel.x + 140f, panel.yMax - 50f, panel.width - 380f, 32f), matchError, 11, Brand.Bad, FontStyle.Normal, TextAnchor.MiddleLeft, true);
    }

    void LanguageStep(Rect r)
    {
        float y = r.y;
        GlassUI.Label(new Rect(r.x, y, 220f, 20f), "Your name (how your date says it)", 12, Brand.Muted);
        learnerName = GlassUI.Field(new Rect(r.x + 230f, y - 6f, r.width - 230f, 32f), learnerName, "e.g. Arth", 40, 14);
        y += 38f;
        GlassUI.Eyebrow(new Rect(r.x, y, r.width, 18f), "DIALECT");
        y += 22f;
        var dialects = catalog?.dialects ?? Array.Empty<DialectInfo>();
        float cw = (r.width - 8f) / 2f;
        for (int i = 0; i < dialects.Length; i++)
        {
            var chip = new Rect(r.x + (i % 2) * (cw + 8f), y + (i / 2) * 36f, cw, 30f);
            string chipLabel = (DateSession.IsUnlocked(dialects[i].code) ? "🔓 " : "") + dialects[i].label;
            if (GlassUI.Chip(chip, chipLabel, dialect == dialects[i].code, 12))
                ChooseDialect(dialects[i].code);
        }
        y += Mathf.CeilToInt(dialects.Length / 2f) * 36f + 8f;

        var d = Array.Find(dialects, x => x.code == dialect);
        if (d != null && d.cities.Length > 1)
        {
            GlassUI.Eyebrow(new Rect(r.x, y, r.width, 18f), "CITY");
            y += 22f;
            for (int i = 0; i < d.cities.Length; i++)
                if (GlassUI.Chip(new Rect(r.x + i * 150f, y, 142f, 30f), d.cities[i].name, city == d.cities[i].name, 12))
                {
                    city = d.cities[i].name;
                    Pin(d.cities[i].lat, d.cities[i].lon, city);
                }
            y += 42f;
        }

        GlassUI.Eyebrow(new Rect(r.x, y, r.width, 18f), "YOUR LEVEL");
        y += 22f;
        var levels = catalog?.levels ?? Array.Empty<LevelInfo>();
        float lw = (r.width - 5 * 8f) / Mathf.Max(1, levels.Length);
        for (int i = 0; i < levels.Length; i++)
            if (GlassUI.Chip(new Rect(r.x + i * (lw + 8f), y, lw, 30f), levels[i].cefr, level == levels[i].cefr, 13))
                level = levels[i].cefr;
        y += 36f;
        string band = level.StartsWith("A") ? "Beginner: slower, simpler, forgiving chemistry"
            : level.StartsWith("B") ? "Intermediate: normal speed, everyday slang"
            : "Native: full speed, ruthless banter, a noisy room";
        GlassUI.Label(new Rect(r.x, y, r.width, 18f), band, 12, Brand.AccentSoft);
    }

    void DateStep(Rect r)
    {
        float y = r.y;
        Row(r, ref y, "THEY ARE", catalog?.genders ?? Array.Empty<string>(), g => g == "female" ? "A woman" : g == "male" ? "A man" : "Non-binary",
            g => dateGender == g, g => dateGender = g, 3);
        var looks = catalog?.appearances ?? Array.Empty<Option>();
        Row(r, ref y, "APPEARANCE (their 3D look only)", Array.ConvertAll(looks, o => o.id), id => Array.Find(looks, o => o.id == id)?.label ?? id,
            id => appearance == id, id => appearance = id, 4, 11);
        var types = catalog?.archetypes ?? Array.Empty<Option>();
        Row(r, ref y, "PERSONALITY", Array.ConvertAll(types, o => o.id), id => Array.Find(types, o => o.id == id)?.label ?? id,
            id => personality == id, id => personality = id, 2);
        var venues = catalog?.venues ?? Array.Empty<Option>();
        var venueIds = new List<string> { "auto" };
        venueIds.AddRange(Array.ConvertAll(venues, o => o.id));
        Row(r, ref y, "VENUE", venueIds.ToArray(), id => id == "auto" ? "✨ Let my prompt decide" : Array.Find(venues, o => o.id == id)?.label ?? id,
            id => venue == id, id => venue = id, 3, 11);

        GlassUI.Eyebrow(new Rect(r.x, y, r.width, 18f), "SET THE SCENE");
        y += 20f;
        scenePrompt = GlassUI.Field(new Rect(r.x, y, r.width, 34f), scenePrompt, "a rooftop bar at sunset after the rain, city lights coming on", 300, 14);
        y += 42f;
        notes = GlassUI.Field(new Rect(r.x, y, r.width, 34f), notes, "about them: loves indie rock and photography, hates crypto bros", 300, 14);
    }

    void Row(Rect r, ref float y, string title, string[] ids, Func<string, string> label, Func<string, bool> selected,
             Action<string> choose, int perRow, int size = 12)
    {
        GlassUI.Eyebrow(new Rect(r.x, y, r.width, 18f), title);
        y += 20f;
        float w = (r.width - (perRow - 1) * 8f) / perRow;
        for (int i = 0; i < ids.Length; i++)
            if (GlassUI.Chip(new Rect(r.x + (i % perRow) * (w + 8f), y + (i / perRow) * 34f, w, 28f), label(ids[i]), selected(ids[i]), size))
                choose(ids[i]);
        y += Mathf.CeilToInt(ids.Length / (float)perRow) * 34f + 6f;
    }

    void Matching(Rect r)
    {
        GlassUI.Panel(r);
        string[] lines = { $"Searching {(string.IsNullOrEmpty(city) ? "the city" : city)}…", "Writing their story…", "Choosing the venue…", "Picking their first line…" };
        int i = Mathf.Min(lines.Length - 1, (int)(Since / 0.6f));
        GlassUI.Eyebrow(new Rect(r.x + 24f, r.y + 20f, r.width - 48f, 20f), "Matchmaking");
        GlassUI.Headline(new Rect(r.x + 24f, r.y + 46f, r.width - 48f, 44f), lines[i], 30, Brand.Cream);
        float t = Mathf.PingPong(Time.time * 0.8f, 1f);
        GlassUI.Bar(new Rect(r.x + 24f, r.y + 112f, r.width - 48f, 6f), Mathf.Clamp01(Since / 2.4f), Brand.Accent);
        GlassUI.Label(new Rect(r.x + 24f, r.y + 128f, r.width - 48f, 30f), "Someone in " + (string.IsNullOrEmpty(city) ? "the city" : city) + " is about to sit down.", 13,
                      new Color(1f, 1f, 1f, 0.5f + 0.3f * t));
    }

    void MatchCard(Rect r)
    {
        var c = match.date_character;
        float a = Mathf.SmoothStep(0f, 1f, Mathf.Clamp01(Since / 0.5f));
        r.y += (1f - a) * 24f;
        GlassUI.Panel(r, a);
        GlassUI.Eyebrow(new Rect(r.x + 24f, r.y + 18f, r.width - 48f, 18f), "It's a date");
        GlassUI.Headline(new Rect(r.x + 24f, r.y + 38f, r.width - 48f, 48f), $"{c.display_name}, <i>{c.age}</i>", 40, Brand.Cream);
        GlassUI.Label(new Rect(r.x + 24f, r.y + 86f, r.width - 48f, 22f), $"{Cap(c.occupation)} · {Label(match.personality_archetype)}", 15, Color.white);
        GlassUI.Label(new Rect(r.x + 24f, r.y + 114f, r.width - 48f, 20f), $"{match.venue?.label} · {match.city} · {match.dialect_label}", 13, Brand.AccentSoft);
        GlassUI.Label(new Rect(r.x + 24f, r.y + 144f, r.width - 48f, 60f), match.scene_description, 13, new Color(1f, 1f, 1f, 0.75f), FontStyle.Italic, TextAnchor.UpperLeft, true);
        string interests = c.interests != null && c.interests.Length > 0 ? "Into " + string.Join(", ", c.interests) : "";
        GlassUI.Label(new Rect(r.x + 24f, r.y + 210f, r.width - 48f, 40f), interests, 13, new Color(1f, 1f, 1f, 0.85f), FontStyle.Normal, TextAnchor.UpperLeft, true);
        GlassUI.Label(new Rect(r.x + 24f, r.yMax - 34f, r.width - 48f, 20f), "Three minutes. Speak their language. Don't freeze.", 12, new Color(1f, 1f, 1f, 0.6f));
    }

    static string Cap(string s) => string.IsNullOrEmpty(s) ? "" : char.ToUpperInvariant(s[0]) + s.Substring(1);

    string Label(string archetype)
    {
        var o = Array.Find(catalog?.archetypes ?? Array.Empty<Option>(), x => x.id == archetype);
        return o != null ? o.label : archetype;
    }

    void PinLabel()
    {
        if (!hasPin || cam == null || pin == null || Trip > ZoomFrom)
            return;
        var tip = pin.position;
        if (Vector3.Dot(tip - globe.position, cam.transform.forward) > 0f)
            return;
        var s = cam.WorldToScreenPoint(tip);
        float scale = GlassUI.Scale;
        var p = new Vector2(s.x / scale, (Screen.height - s.y) / scale);
        float tw = GlassUI.TextWidth(placeName, 13, FontStyle.Bold);
        var r = new Rect(p.x + 14f, p.y - 28f, tw + 34f, 26f);
        GlassUI.Rounded(r, new Color(0.07f, 0.02f, 0.05f, 0.85f), 13);
        GlassUI.Outline(r, new Color(1f, 0.24f, 0.43f, 0.6f), 13);
        GlassUI.Dot(new Vector2(r.x + 13f, r.center.y), 7f, Brand.Accent);
        GlassUI.Label(new Rect(r.x + 22f, r.y, r.width - 26f, r.height), placeName, 13, Brand.Cream, FontStyle.Bold);
    }

    void Status()
    {
        float t = Trip;
        int i = 0;
        for (int k = 0; k < Stages.Length; k++)
            if (t >= Stages[k].at)
                i = k;
        float a = Mathf.Clamp01((t - Stages[i].at) * tripSeconds / 0.5f);
        string where = match != null ? match.city : placeName.Split(',')[0];
        string scene = match?.venue?.label ?? "the place";
        string who = match?.date_character?.display_name ?? "your date";
        string title = string.Format(Stages[i].title, where, scene, who);
        string sub = string.Format(Stages[i].sub, where, scene, who);
        GlassUI.Headline(new Rect(96f, 256f, 1000f, 64f), title, 52, new Color(Brand.Cream.r, Brand.Cream.g, Brand.Cream.b, a));
        GlassUI.Label(new Rect(98f, 326f, 900f, 26f), sub, 18, new Color(Brand.Muted.r, Brand.Muted.g, Brand.Muted.b, a));
    }
}
