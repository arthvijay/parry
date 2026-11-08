using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;

/// <summary>
/// The front of the app: the matchmaker's studio over a low-poly Earth in the clouds.
///
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
    public Color skyZenith = new(0.36f, 0.58f, 0.86f);
    public Color skyHorizon = new(0.84f, 0.90f, 0.97f);
    public Color skyBelow = new(0.70f, 0.80f, 0.92f);
    public Vector3 globeCentre = new(2.4f, -0.15f, 0f);
    public float globeRadius = 1.6f;
    [Tooltip("Degrees per second the globe idles at before a city is chosen.")]
    public float idleSpin = 5f;

    [Header("Timing")]
    [Tooltip("Seconds from the match card to the venue loading.")]
    public float tripSeconds = 7f;
    public float arriveSeconds = 2.4f;
    public float revealSeconds = 3.2f;

    enum Step { Face, Language, Date, Matching, Matched, Boarding, Departing }

    Step step = Step.Face;
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
    Material skyMaterial, litMaterial, cloudMaterial;
    readonly List<Mesh> meshes = new();
    readonly List<Mesh> cloudMeshes = new();
    readonly List<Puff> puffs = new();
    System.Random cloudRng = new(11);
    Light sun;
    Camera cam;
    CloudCurtain curtain;
    float seaLift;
    bool loading;

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
        if (FindFirstObjectByType<VisionPanel>() == null)
            gameObject.AddComponent<VisionPanel>();
        StartCoroutine(LoadCatalog());
    }

    void OnDestroy()
    {
        foreach (var m in new[] { skyMaterial, litMaterial, cloudMaterial })
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
            ChooseDialect(dialect);
    }

    /// <summary>Starts an authored demo date (by preset id; empty = the first), as its button does.</summary>
    public void StartDemo(string presetId = "")
    {
        var demo = catalog?.presets == null ? null
            : string.IsNullOrEmpty(presetId) ? (catalog.presets.Length > 0 ? catalog.presets[0] : null)
            : Array.Find(catalog.presets, p => p.id == presetId);
        if (demo != null && step <= Step.Date)
            StartCoroutine(GeneratePreset(demo));
    }

    /// <summary>"Café Rayuela · Argentine latina (Spanish)" → "Argentine latina (Spanish)".</summary>
    static string DemoLabel(PresetInfo p)
    {
        int dot = p.label.IndexOf('·');
        return dot >= 0 ? p.label[(dot + 1)..].Trim() : p.label;
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
        if (step == Step.Face || step == Step.Language || step == Step.Date || step == Step.Matching)
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
            pin.localScale = Vector3.one * (0.075f + 0.02f * Mathf.Sin(Time.time * 4f));

        float cover = step < Step.Boarding ? 0f : Mathf.SmoothStep(0f, 1f, Mathf.InverseLerp(CoverFrom, CoverTo, t));
        MoveClouds(cover);
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
        RenderSettings.ambientLight = new Color(0.55f, 0.62f, 0.76f);
        sun = new GameObject("Sun").AddComponent<Light>();
        sun.transform.SetParent(transform, false);
        sun.type = LightType.Directional;
        sun.color = new Color(1f, 0.97f, 0.92f);
        sun.intensity = 1.4f;
        sun.shadows = LightShadows.None;
        sun.transform.rotation = Quaternion.Euler(30f, -40f, 0f);
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
        Piece(earth, LowPoly.Earth(map), litMaterial);
    }

    void BuildClouds()
    {
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
        Piece(marker, LowPoly.Ball(LowPoly.Swatch.Cloud), cloudMaterial);
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

        if (step < Step.Boarding)
        {
            GlassUI.Label(new Rect(60f, 22f, 400f, 56f), Brand.Name, 46, Brand.Ink, FontStyle.Bold);
            GlassUI.Label(new Rect(62f, 72f, 600f, 22f), Brand.Tagline, 15, new Color(Brand.Ink.r, Brand.Ink.g, Brand.Ink.b, 0.65f));
        }
        // The demos: one click to an authored date at Café Rayuela, one per personality.
        if (step <= Step.Date && catalog?.presets != null)
            for (int i = 0; i < catalog.presets.Length && i < 2; i++)
                if (GlassUI.Button(new Rect(400f + i * 270f, 34f, 260f, 40f), "▶  " + DemoLabel(catalog.presets[i]), true))
                    StartCoroutine(GeneratePreset(catalog.presets[i]));
        PinLabel();
        switch (step)
        {
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

    void Studio(Rect panel)
    {
        GlassUI.Panel(panel);
        // Step tabs.
        string[] tabs = { "1  Face scan", "2  Language", "3  Your date" };
        for (int i = 0; i < 3; i++)
        {
            var r = new Rect(panel.x + 20f + i * 196f, panel.y + 16f, 186f, 30f);
            if (GlassUI.Chip(r, tabs[i], (int)step == i) && (i <= (int)step || onboarding != null))
                step = (Step)i;
        }
        var body = new Rect(panel.x + 20f, panel.y + 62f, panel.width - 40f, panel.height - 124f);
        if (!string.IsNullOrEmpty(catalogError))
            GlassUI.Label(new Rect(body.x, panel.yMax - 92f, body.width, 18f), catalogError, 12, Brand.Bad);

        switch (step)
        {
            case Step.Face:
                GlassUI.Label(new Rect(body.x, body.y, body.width, 20f), "Let's scan your face. Your avatar is built from your photo and mirrors you live.", 13, new Color(1f, 1f, 1f, 0.8f));
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
        if (step != Step.Face && GlassUI.Button(back, "Back"))
            step = (Step)((int)step - 1);
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
        GlassUI.Label(new Rect(r.x, y, 200f, 20f), "Your name (how your date says it)", 12, new Color(1f, 1f, 1f, 0.6f));
        learnerName = GlassUI.Field(new Rect(r.x + 230f, y - 6f, r.width - 230f, 32f), learnerName, "e.g. Arth", 40, 14);
        y += 38f;
        GlassUI.Label(new Rect(r.x, y, r.width, 18f), "DIALECT", 11, new Color(1f, 1f, 1f, 0.55f), FontStyle.Bold);
        y += 22f;
        var dialects = catalog?.dialects ?? Array.Empty<DialectInfo>();
        float cw = (r.width - 8f) / 2f;
        for (int i = 0; i < dialects.Length; i++)
        {
            var chip = new Rect(r.x + (i % 2) * (cw + 8f), y + (i / 2) * 36f, cw, 30f);
            if (GlassUI.Chip(chip, dialects[i].label, dialect == dialects[i].code, 12))
                ChooseDialect(dialects[i].code);
        }
        y += Mathf.CeilToInt(dialects.Length / 2f) * 36f + 8f;

        var d = Array.Find(dialects, x => x.code == dialect);
        if (d != null && d.cities.Length > 1)
        {
            GlassUI.Label(new Rect(r.x, y, r.width, 18f), "CITY", 11, new Color(1f, 1f, 1f, 0.55f), FontStyle.Bold);
            y += 22f;
            for (int i = 0; i < d.cities.Length; i++)
                if (GlassUI.Chip(new Rect(r.x + i * 150f, y, 142f, 30f), d.cities[i].name, city == d.cities[i].name, 12))
                {
                    city = d.cities[i].name;
                    Pin(d.cities[i].lat, d.cities[i].lon, city);
                }
            y += 42f;
        }

        GlassUI.Label(new Rect(r.x, y, r.width, 18f), "YOUR LEVEL", 11, new Color(1f, 1f, 1f, 0.55f), FontStyle.Bold);
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
        // The two demo personalities, authored and ready: one click and the date starts.
        var presets = catalog?.presets ?? Array.Empty<PresetInfo>();
        if (presets.Length > 0)
        {
            var demoIds = Array.ConvertAll(presets, p => p.id);
            Row(r, ref y, "DEMO PERSONALITIES · Café Rayuela, Cancún", demoIds,
                id => "▶ " + DemoLabel(Array.Find(presets, p => p.id == id)),
                id => false, id => StartDemo(id), 2);
        }
        var types = catalog?.archetypes ?? Array.Empty<Option>();
        Row(r, ref y, "OR BUILD ONE · PERSONALITY", Array.ConvertAll(types, o => o.id), id => Array.Find(types, o => o.id == id)?.label ?? id,
            id => personality == id, id => personality = id, 2);
        var venues = catalog?.venues ?? Array.Empty<Option>();
        var venueIds = new List<string> { "auto" };
        venueIds.AddRange(Array.ConvertAll(venues, o => o.id));
        Row(r, ref y, "VENUE", venueIds.ToArray(), id => id == "auto" ? "✨ Let my prompt decide" : Array.Find(venues, o => o.id == id)?.label ?? id,
            id => venue == id, id => venue = id, 3, 11);

        GlassUI.Label(new Rect(r.x, y, r.width, 18f), "SET THE SCENE", 11, new Color(1f, 1f, 1f, 0.55f), FontStyle.Bold);
        y += 20f;
        scenePrompt = GlassUI.Field(new Rect(r.x, y, r.width, 34f), scenePrompt, "a rooftop bar at sunset after the rain, city lights coming on", 300, 14);
        y += 42f;
        notes = GlassUI.Field(new Rect(r.x, y, r.width, 34f), notes, "about them: loves indie rock and photography, hates crypto bros", 300, 14);
    }

    void Row(Rect r, ref float y, string title, string[] ids, Func<string, string> label, Func<string, bool> selected,
             Action<string> choose, int perRow, int size = 12)
    {
        GlassUI.Label(new Rect(r.x, y, r.width, 18f), title, 11, new Color(1f, 1f, 1f, 0.55f), FontStyle.Bold);
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
        GlassUI.Label(new Rect(r.x + 24f, r.y + 20f, r.width - 48f, 20f), "MATCHMAKING", 11, Brand.AccentSoft, FontStyle.Bold);
        GlassUI.Label(new Rect(r.x + 24f, r.y + 48f, r.width - 48f, 40f), lines[i], 24, Color.white, FontStyle.Bold);
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
        GlassUI.Label(new Rect(r.x + 24f, r.y + 18f, r.width - 48f, 18f), "IT'S A DATE", 11, Brand.AccentSoft, FontStyle.Bold);
        GlassUI.Label(new Rect(r.x + 24f, r.y + 40f, r.width - 48f, 44f), $"{c.display_name}, {c.age}", 34, Color.white, FontStyle.Bold);
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
        var r = new Rect(p.x + 12f, p.y - 24f, tw + 20f, 24f);
        GlassUI.Rounded(r, new Color(1f, 1f, 1f, 0.9f), 12);
        GlassUI.Label(r, placeName, 13, Brand.Ink, FontStyle.Bold, TextAnchor.MiddleCenter);
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
        GlassUI.Label(new Rect(96f, 262f, 900f, 56f), title, 44, new Color(Brand.Ink.r, Brand.Ink.g, Brand.Ink.b, a), FontStyle.Bold);
        GlassUI.Label(new Rect(96f, 322f, 900f, 26f), sub, 18, new Color(Brand.Ink.r, Brand.Ink.g, Brand.Ink.b, 0.6f * a));
    }
}
