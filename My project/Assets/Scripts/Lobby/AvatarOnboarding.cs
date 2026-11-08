using System;
using System.Collections;
using System.IO;
using UnityEngine;
using UnityEngine.Networking;

/// <summary>
/// The face scan: a live viewfinder, a selfie, and the learner's avatar built from it.
/// The photo goes to <c>POST /v1/avatar/from-selfie</c>, where the face tracker finds the
/// face and samples skin from the cheeks and forehead and hair from above the hairline;
/// those colours tint the chosen Rocketbox body. The avatar is rendered live next to the
/// photo on a slow turntable, already wearing the learner's face through the webcam, so
/// the scan visibly becomes them. The body is the learner's choice; nothing about the
/// person is inferred from the photo. Drawn inside <see cref="MatchmakerUI"/>'s panel.
/// </summary>
public class AvatarOnboarding : MonoBehaviour
{
    public Vector3 previewOrigin = new(0f, -100f, 0f);
    public int previewWidth = 384, previewHeight = 480;

    public PlayerLook Look { get; private set; }
    public bool Captured => selfie != null;
    public string Status { get; private set; } = "";
    public RenderTexture Preview { get; private set; }

    Texture2D selfie;
    GameObject rig, avatar;
    Camera previewCamera;
    string photoPath = "";
    bool working;

    void Start()
    {
        Look = DateSession.Look;
        VisionFeed.Ensure().StartCamera();
        if (!string.IsNullOrEmpty(Look.selfie_path) && File.Exists(Look.selfie_path))
            selfie = LoadTexture(File.ReadAllBytes(Look.selfie_path));
        BuildRig();
        BuildAvatar();
    }

    void OnDestroy()
    {
        if (rig != null)
            Destroy(rig);
        if (Preview != null)
            Preview.Release();
        if (selfie != null)
            Destroy(selfie);
    }

    // ---- the preview -----------------------------------------------------------------

    void BuildRig()
    {
        rig = new GameObject("Avatar Preview");
        rig.transform.position = previewOrigin;
        Preview = new RenderTexture(previewWidth, previewHeight, 24) { antiAliasing = 4 };
        previewCamera = new GameObject("Preview Camera").AddComponent<Camera>();
        previewCamera.transform.SetParent(rig.transform, false);
        previewCamera.transform.localPosition = new Vector3(0f, 1.45f, 1.25f);
        previewCamera.transform.localRotation = Quaternion.Euler(6f, 180f, 0f);
        previewCamera.fieldOfView = 30f;
        previewCamera.clearFlags = CameraClearFlags.SolidColor;
        previewCamera.backgroundColor = new Color(0.12f, 0.12f, 0.17f, 1f);
        previewCamera.targetTexture = Preview;
        previewCamera.nearClipPlane = 0.05f;
        previewCamera.farClipPlane = 10f;
        var key = new GameObject("Preview Key").AddComponent<Light>();
        key.transform.SetParent(rig.transform, false);
        key.transform.localPosition = new Vector3(0.7f, 2.0f, 1.4f);
        key.type = LightType.Point;
        key.range = 5f;
        key.intensity = 2.2f;
        key.color = new Color(1f, 0.93f, 0.88f);
        var rim = new GameObject("Preview Rim").AddComponent<Light>();
        rim.transform.SetParent(rig.transform, false);
        rim.transform.localPosition = new Vector3(-0.8f, 1.8f, -0.8f);
        rim.type = LightType.Point;
        rim.range = 4f;
        rim.intensity = 1.6f;
        rim.color = Brand.AccentSoft;
    }

    void BuildAvatar()
    {
        if (avatar != null)
            Destroy(avatar);
        avatar = new GameObject("Preview Avatar");
        avatar.transform.SetParent(rig.transform, false);
        avatar.SetActive(false);
        var loader = avatar.AddComponent<NpcAvatarLoader>();
        loader.resourcePath = DateSession.AvatarResource(Look.base_model);
        loader.snapToGround = false;
        loader.groundFeet = true;
        avatar.AddComponent<NpcIdleAnimation>();
        var tint = avatar.AddComponent<AvatarTinter>();
        tint.skin = Look.skin_hex;
        tint.hair = Look.hair_hex;
        avatar.AddComponent<LocalFaceController>();
        avatar.SetActive(true);
    }

    void Update()
    {
        if (avatar != null)
            avatar.transform.localRotation = Quaternion.Euler(0f, Mathf.Sin(Time.time * 0.4f) * 18f, 0f);
    }

    // ---- choices ---------------------------------------------------------------------

    public void SetBody(string baseModel)
    {
        if (Look.base_model == baseModel)
            return;
        Look.base_model = baseModel;
        DateSession.Look = Look;
        BuildAvatar();
    }

    public void CaptureSelfie()
    {
        var feed = VisionFeed.Instance;
        if (feed == null || !feed.Running || working)
        {
            Status = feed == null || !feed.Running ? "No camera: use a photo instead." : Status;
            return;
        }
        var jpeg = feed.CaptureJpeg(640, 92);
        if (jpeg != null)
            StartCoroutine(Analyse(jpeg));
    }

    public void UsePhoto(string path)
    {
        photoPath = path;
        if (working || string.IsNullOrWhiteSpace(path))
            return;
        try
        {
            var bytes = File.ReadAllBytes(path.Trim().Trim('"'));
            var tex = LoadTexture(bytes);
            if (tex == null)
                throw new IOException("not an image");
            var jpeg = tex.EncodeToJPG(92);
            Destroy(tex);
            StartCoroutine(Analyse(jpeg));
        }
        catch (Exception e)
        {
            Status = $"Couldn't open that photo ({e.Message}).";
        }
    }

    IEnumerator Analyse(byte[] jpeg)
    {
        working = true;
        Status = "Scanning your face…";
        if (selfie != null)
            Destroy(selfie);
        selfie = LoadTexture(jpeg);
        string path = Path.Combine(Application.persistentDataPath, "selfie.jpg");
        try { File.WriteAllBytes(path, jpeg); } catch (Exception) { path = ""; }

        using var req = new UnityWebRequest($"{DateSession.Base}/v1/avatar/from-selfie", "POST")
        {
            uploadHandler = new UploadHandlerRaw(jpeg) { contentType = "image/jpeg" },
            downloadHandler = new DownloadHandlerBuffer(),
            timeout = 20,
        };
        yield return req.SendWebRequest();
        working = false;
        Look.selfie_path = path;
        if (req.result != UnityWebRequest.Result.Success)
        {
            Status = "Photo saved. The face tracker is offline, so the avatar keeps its default colours.";
            DateSession.Look = Look;
            yield break;
        }
        var result = Json.Obj(req.downloadHandler.text);
        if (!result.Bool("face_found"))
        {
            Status = $"No face found ({result.Str("reason", "try again, facing the camera")}).";
            yield break;
        }
        Look.skin_hex = result.Str("skin_hex", Look.skin_hex);
        Look.hair_hex = result.Str("hair_hex", Look.hair_hex);
        Look.from_selfie = true;
        DateSession.Look = Look;
        Status = "Avatar built from your photo.";
        BuildAvatar();
    }

    static Texture2D LoadTexture(byte[] bytes)
    {
        var tex = new Texture2D(2, 2, TextureFormat.RGB24, false);
        if (tex.LoadImage(bytes))
            return tex;
        Destroy(tex);
        return null;
    }

    // ---- drawing (inside MatchmakerUI's panel) -----------------------------------------

    public void Draw(Rect r)
    {
        var feed = VisionFeed.Instance;
        float half = (r.width - 16f) / 2f;
        float h = Mathf.Min(r.height - 120f, half * 1.25f);

        // Left: the viewfinder, or the selfie once taken.
        var left = new Rect(r.x, r.y, half, h);
        GlassUI.Rounded(left, new Color(0f, 0f, 0f, 0.5f), 14);
        if (feed != null && feed.Running)
        {
            float camAspect = feed.Camera.width / (float)feed.Camera.height;
            float u = Mathf.Clamp01((half / h) / camAspect); // width fraction that fills the panel
            var coords = new Rect(0.5f + u / 2f, feed.Camera.videoVerticallyMirrored ? 1f : 0f, -u, feed.Camera.videoVerticallyMirrored ? -1f : 1f);
            GUI.DrawTextureWithTexCoords(left, feed.Camera, coords);
            // The face guide.
            var guide = new Rect(left.center.x - half * 0.26f, left.y + h * 0.16f, half * 0.52f, h * 0.6f);
            Color guideColor = feed.HasFace ? Brand.Good : new Color(1f, 1f, 1f, 0.5f);
            for (int i = 0; i < 48; i++)
            {
                float a0 = i / 48f * Mathf.PI * 2f, a1 = (i + 1) / 48f * Mathf.PI * 2f;
                var p0 = guide.center + new Vector2(Mathf.Cos(a0) * guide.width / 2f, Mathf.Sin(a0) * guide.height / 2f);
                var p1 = guide.center + new Vector2(Mathf.Cos(a1) * guide.width / 2f, Mathf.Sin(a1) * guide.height / 2f);
                if (i % 2 == 0)
                    GlassUI.Line(p0, p1, 2f, guideColor);
            }
            GlassUI.Pill(new Rect(left.x + 10f, left.yMax - 30f, half - 20f, 22f), new Color(0f, 0f, 0f, 0.55f),
                         feed.HasFace ? "Face found · hold still" : "Center your face in the oval", Color.white, 11);
        }
        else
            GlassUI.Label(left, feed != null && !string.IsNullOrEmpty(feed.Error) ? feed.Error : "Starting camera…", 13,
                          new Color(1f, 1f, 1f, 0.7f), FontStyle.Normal, TextAnchor.MiddleCenter, true);
        if (selfie != null)
        {
            var thumb = new Rect(left.x + 10f, left.y + 10f, 72f, 72f * selfie.height / selfie.width);
            GlassUI.Rounded(new Rect(thumb.x - 2f, thumb.y - 2f, thumb.width + 4f, thumb.height + 4f), Color.white, 6);
            GUI.DrawTexture(thumb, selfie, ScaleMode.ScaleAndCrop);
        }

        // Right: the avatar, live.
        var right = new Rect(r.x + half + 16f, r.y, half, h);
        GlassUI.Rounded(right, new Color(0.12f, 0.12f, 0.17f, 1f), 14);
        if (Preview != null)
            GUI.DrawTexture(right, Preview, ScaleMode.ScaleAndCrop);
        GlassUI.Pill(new Rect(right.x + 10f, right.yMax - 30f, half - 20f, 22f), new Color(0f, 0f, 0f, 0.55f),
                     Look.from_selfie ? "Your avatar · mirrors your face" : "Avatar · take a selfie to personalise", Color.white, 11);

        // Controls.
        float y = r.y + h + 12f;
        if (GlassUI.Button(new Rect(r.x, y, half, 38f), working ? "Scanning…" : selfie != null ? "Retake selfie" : "📸  Capture selfie", true, !working))
            CaptureSelfie();
        GlassUI.Label(new Rect(right.x, y, 60f, 38f), "Body", 12, new Color(1f, 1f, 1f, 0.6f));
        if (GlassUI.Chip(new Rect(right.x + 44f, y + 5f, (half - 50f) / 2f - 4f, 28f), "Woman", Look.base_model == "Female_Adult_08"))
            SetBody("Female_Adult_08");
        if (GlassUI.Chip(new Rect(right.x + 44f + (half - 50f) / 2f, y + 5f, (half - 50f) / 2f - 4f, 28f), "Man", Look.base_model == "Male_Adult_08"))
            SetBody("Male_Adult_08");
        y += 46f;
        photoPath = GlassUI.Field(new Rect(r.x, y, r.width - 110f, 32f), photoPath, "…or a photo file path", 400, 13);
        if (GlassUI.Button(new Rect(r.xMax - 100f, y, 100f, 32f), "Use photo", false, !working, 13))
            UsePhoto(photoPath);
        if (!string.IsNullOrEmpty(Status))
            GlassUI.Label(new Rect(r.x, y + 36f, r.width, 18f), Status, 12, Brand.AccentSoft);
    }
}
