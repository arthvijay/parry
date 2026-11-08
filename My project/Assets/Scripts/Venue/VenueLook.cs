using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

/// <summary>
/// A cheap "finished game" look for the venue, built at runtime so no scene needs editing:
/// URP post-processing (neutral tonemapping, soft bloom on the sunlit sea, a warm grade,
/// a light vignette), FXAA on the cameras, and a soft warm key light on the date's face
/// so the characters read against the scanned room. Everything here is a fullscreen pass
/// or a single light: a few tenths of a millisecond on integrated graphics.
/// </summary>
public class VenueLook : MonoBehaviour
{
    [Header("Grade")]
    public float postExposure = 0.15f;
    public float contrast = 10f;
    public float saturation = 8f;
    public float temperature = 8f;
    public float bloomIntensity = 0.35f;
    public float vignette = 0.22f;
    [Tooltip("Distance (m) where the background starts to soften, and where it is fully soft.")]
    public float focusStart = 6f, focusEnd = 22f;

    [Header("Scanned room")]
    [Tooltip("Spherical harmonics order for the splats: 3 = full view-dependent shading.")]
    public int splatShOrder = 3;
    [Tooltip("Re-sort the splats every N frames; 1 = no popping when the camera moves.")]
    public int splatSortEvery = 1;

    [Header("Face light")]
    public float faceLightIntensity = 1.4f;
    public float faceLightRange = 2.6f;
    public Color faceLightColor = new(1f, 0.86f, 0.72f);

    Volume volume;
    VolumeProfile profile;
    Light faceLight;
    NpcAvatarLoader dateLoader;
    Transform dateHead;

    void Start()
    {
        profile = ScriptableObject.CreateInstance<VolumeProfile>();
        var tone = profile.Add<Tonemapping>(true);
        tone.mode.Override(TonemappingMode.Neutral);
        var bloom = profile.Add<Bloom>(true);
        bloom.intensity.Override(bloomIntensity);
        bloom.threshold.Override(1.05f);
        bloom.scatter.Override(0.65f);
        var grade = profile.Add<ColorAdjustments>(true);
        grade.postExposure.Override(postExposure);
        grade.contrast.Override(contrast);
        grade.saturation.Override(saturation);
        var white = profile.Add<WhiteBalance>(true);
        white.temperature.Override(temperature);
        var vig = profile.Add<Vignette>(true);
        vig.intensity.Override(vignette);
        vig.smoothness.Override(0.45f);
        // Gaussian depth of field (half resolution, cheap): the table and the date sharp, the
        // far room soft, like a camera lens, which also hides the scan's distant smearing.
        var dof = profile.Add<DepthOfField>(true);
        dof.mode.Override(DepthOfFieldMode.Gaussian);
        dof.gaussianStart.Override(focusStart);
        dof.gaussianEnd.Override(focusEnd);
        dof.gaussianMaxRadius.Override(0.6f);
        dof.highQualitySampling.Override(false);

        // Measured on integrated graphics: full shading and per-frame sorting cost about
        // the same as the reduced settings the scene was saved with.
        foreach (var gs in FindObjectsByType<GaussianSplatting.Runtime.GaussianSplatRenderer>(FindObjectsSortMode.None))
        {
            gs.m_SHOrder = splatShOrder;
            gs.m_SortNthFrame = splatSortEvery;
        }

        var go = new GameObject("Venue Look Volume");
        go.transform.SetParent(transform, false);
        volume = go.AddComponent<Volume>();
        volume.isGlobal = true;
        volume.priority = 10f;
        volume.sharedProfile = profile;

        faceLight = new GameObject("Date Face Light").AddComponent<Light>();
        faceLight.transform.SetParent(transform, false);
        faceLight.type = LightType.Point;
        faceLight.range = faceLightRange;
        faceLight.intensity = faceLightIntensity;
        faceLight.color = faceLightColor;
        faceLight.shadows = LightShadows.None;
        faceLight.enabled = false;
    }

    void OnDestroy()
    {
        if (profile != null)
            Destroy(profile);
    }

    void LateUpdate()
    {
        // Post-processing on whichever cameras are drawing (the first-person one, and the
        // cinematic two-shot when it is created).
        foreach (var cam in Camera.allCameras)
        {
            var data = cam.GetUniversalAdditionalCameraData();
            if (data != null && !data.renderPostProcessing)
            {
                data.renderPostProcessing = true;
                data.antialiasing = AntialiasingMode.FastApproximateAntialiasing;
            }
        }

        // The key light sits between the date's face and the learner, a little above.
        var date = CastClient.Date;
        if (date == null)
        {
            faceLight.enabled = false;
            return;
        }
        if (dateLoader == null || dateLoader.gameObject != date)
        {
            dateLoader = date.GetComponent<NpcAvatarLoader>();
            dateHead = null;
        }
        if (dateHead == null && dateLoader != null)
            dateHead = dateLoader.FindBone("Bip01 Head");
        var cam0 = Camera.main;
        if (dateHead == null || cam0 == null)
            return;
        Vector3 toViewer = cam0.transform.position - dateHead.position;
        toViewer.y = 0f;
        toViewer = toViewer.sqrMagnitude > 0.001f ? toViewer.normalized : date.transform.forward;
        faceLight.transform.position = dateHead.position + toViewer * 0.75f + Vector3.up * 0.35f
                                       + Vector3.Cross(Vector3.up, toViewer) * 0.25f;
        faceLight.enabled = true;
    }
}
