using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Plays speech from the NPC's mouth and moves the mouth with it. Live replies stream
/// in through a <see cref="StreamingAudioPlayer"/> on a head-mounted source of their own;
/// one-off clips (offline tests) go through <see cref="Speak"/>. The jaw follows the
/// loudness of whatever is playing, and when the avatar has viseme shapes (Rocketbox
/// AA_VI_*) the vowels follow the sound's colour: bright, hissy sound opens E and I,
/// dark, low sound rounds O and U, so lip-sync works in every language with no
/// per-language data.
/// </summary>
[RequireComponent(typeof(NpcAvatarLoader))]
public class NpcSpeaker : MonoBehaviour
{
    [Header("Lip-sync")]
    [Tooltip("Blendshape name suffixes to drive (case-insensitive), first one found on the " +
             "avatar wins. Matches Rocketbox 'AA_VI_10_aa' / 'AK_25_JawOpen' as well as " +
             "Ready Player Me 'viseme_aa' / 'jawOpen'.")]
    public string[] mouthShapes = { "_aa", "jawopen", "mouthopen" };
    [Tooltip("Amplitude to blendshape weight multiplier.")]
    public float mouthGain = 400f;
    public float mouthSmoothing = 20f;

    [Header("Audio")]
    [Tooltip("Bone the AudioSource is attached to so speech comes from the mouth.")]
    public string mouthBone = "Head";
    public float volume = 1f;

    [Header("Placeholder voice")]
    [Tooltip("Played for lines that have no server audio. Empty = load placeholderResource.")]
    public AudioClip placeholderClip;
    [Tooltip("Resources path of a prerecorded sample, e.g. Audio/sample_es. Empty (the default) = a " +
             "synthetic murmur, because that sample is a man's voice and it came out of Maria's mouth " +
             "whenever the speech provider was down.")]
    public string placeholderResource = "";

    [Header("Vowels")]
    [Tooltip("Viseme blendshape suffixes for the open, front and round vowels (Rocketbox names).")]
    public string jawShape = "jawopen";
    public string visemeA = "_aa", visemeE = "_e", visemeI = "_i", visemeO = "_o", visemeU = "_u";
    [Tooltip("Streamed-voice level to blendshape weight multiplier.")]
    public float streamGain = 380f;

    public bool IsSpeaking => (source != null && source.isPlaying && source.clip != null && !IsStreamClip(source.clip))
                              || (stream != null && stream.IsPlaying);

    StreamingAudioPlayer stream;
    AudioSource streamSource;
    readonly Dictionary<string, List<(SkinnedMeshRenderer smr, int index)>> shapes = new();
    readonly Dictionary<string, float> shapeWeights = new();

    static bool IsStreamClip(AudioClip clip) => clip != null && clip.name.EndsWith("-voice");

    /// <summary>Fired when a clip passed to Speak finishes.</summary>
    public event Action FinishedSpeaking;

    static readonly List<NpcSpeaker> everyone = new();

    /// <summary>Whoever is talking right now, or null. Only one NPC has the floor at a time.</summary>
    public static NpcSpeaker Talking
    {
        get
        {
            foreach (var s in everyone)
                if (s.IsSpeaking)
                    return s;
            return null;
        }
    }

    /// <summary>Someone other than <paramref name="me"/> is mid-line.</summary>
    public static bool SomeoneElseSpeaking(NpcSpeaker me)
    {
        var talking = Talking;
        return talking != null && talking != me;
    }

    AudioSource source;
    readonly List<(SkinnedMeshRenderer smr, int index)> mouthTargets = new();
    readonly float[] samples = new float[256];
    float mouthWeight;
    bool wasSpeaking;

    void OnEnable() => everyone.Add(this);
    void OnDisable() => everyone.Remove(this);

    void Awake()
    {
        GetComponent<NpcAvatarLoader>().Loaded += OnAvatarLoaded;

        source = gameObject.AddComponent<AudioSource>();
        source.playOnAwake = false;
        source.spatialBlend = 1f;
        source.minDistance = 1f;
        source.maxDistance = 15f;
        source.rolloffMode = AudioRolloffMode.Linear;
        source.volume = volume;
    }

    void OnAvatarLoaded(Transform avatar)
    {
        mouthTargets.Clear();
        var renderers = avatar.GetComponentsInChildren<SkinnedMeshRenderer>();
        shapes.Clear();
        foreach (var key in new[] { jawShape, visemeA, visemeE, visemeI, visemeO, visemeU })
        {
            var list = new List<(SkinnedMeshRenderer, int)>();
            foreach (var smr in renderers)
            {
                var m = smr.sharedMesh;
                if (m == null)
                    continue;
                for (int i = 0; i < m.blendShapeCount; i++)
                    if (m.GetBlendShapeName(i).EndsWith(key, StringComparison.OrdinalIgnoreCase))
                    {
                        list.Add((smr, i));
                        break;
                    }
            }
            shapes[key] = list;
            shapeWeights[key] = 0f;
        }
        foreach (string shape in mouthShapes)
        {
            foreach (var smr in renderers)
            {
                var mesh = smr.sharedMesh;
                for (int i = 0; i < mesh.blendShapeCount; i++)
                {
                    if (mesh.GetBlendShapeName(i).EndsWith(shape, StringComparison.OrdinalIgnoreCase))
                    {
                        mouthTargets.Add((smr, i));
                        break;
                    }
                }
            }
            if (mouthTargets.Count > 0)
                break;
        }

        if (mouthTargets.Count == 0)
            Debug.LogWarning("NpcSpeaker: no mouth blendshape found on avatar; lip-sync disabled.");

        // Reparent the source to the head so the voice is positioned at the mouth.
        var mouth = GetComponent<NpcAvatarLoader>().FindBone(mouthBone);
        if (mouth != null)
        {
            var moved = mouth.gameObject.AddComponent<AudioSource>();
            CopySettings(source, moved);
            Destroy(source);
            source = moved;
        }

        // The streamed voice gets its own source at the mouth, always playing its ring buffer.
        stream = GetComponent<StreamingAudioPlayer>();
        if (stream != null)
        {
            streamSource = (mouth != null ? mouth.gameObject : gameObject).AddComponent<AudioSource>();
            CopySettings(source, streamSource);
            stream.Attach(streamSource);
        }
    }

    /// <summary>The streamed voice's source, for volume and spatial tweaks.</summary>
    public AudioSource StreamSource => streamSource;

    /// <summary>Play a speech clip. Replaces anything currently playing.</summary>
    public void Speak(AudioClip clip)
    {
        source.Stop();
        source.clip = clip;
        source.Play();
    }

    public void Stop() => source.Stop();

    /// <summary>
    /// Speaks the prerecorded Spanish sample (or a synthetic "blah blah" of
    /// <paramref name="seconds"/> if the sample is missing) for lines that have
    /// no server audio, so lip-sync and positioning can be tested.
    /// </summary>
    public void SpeakTest(float seconds = 2.5f)
    {
        var clip = Placeholder();
        Speak(clip != null ? clip : MakeTestClip(seconds));
    }

    AudioClip Placeholder()
    {
        if (placeholderClip == null && !string.IsNullOrEmpty(placeholderResource))
        {
            placeholderClip = Resources.Load<AudioClip>(placeholderResource);
            if (placeholderClip == null)
            {
                Debug.LogWarning($"NpcSpeaker: no AudioClip at Resources/{placeholderResource}; using synthetic voice.");
                placeholderResource = ""; // don't retry every line
            }
        }
        return placeholderClip;
    }

    void Update()
    {
        bool speaking = IsSpeaking;

        if (stream != null && stream.IsPlaying)
        {
            DriveFromStream();
            if (wasSpeaking && !speaking)
                FinishedSpeaking?.Invoke();
            wasSpeaking = speaking;
            return;
        }
        RelaxVowels();

        float target = 0f;
        if (speaking)
        {
            source.GetOutputData(samples, 0);
            float sum = 0f;
            foreach (float s in samples)
                sum += s * s;
            target = Mathf.Clamp(Mathf.Sqrt(sum / samples.Length) * mouthGain, 0f, 100f);
        }

        mouthWeight = Mathf.Lerp(mouthWeight, target, mouthSmoothing * Time.deltaTime);
        foreach (var (smr, index) in mouthTargets)
            smr.SetBlendShapeWeight(index, mouthWeight);

        if (wasSpeaking && !speaking)
            FinishedSpeaking?.Invoke();
        wasSpeaking = speaking;
    }

    /// <summary>Jaw from loudness; E/I from bright sound, O/U from dark sound.</summary>
    void DriveFromStream()
    {
        float level = stream.Level;
        float open = Mathf.Clamp(level * streamGain, 0f, 100f);
        float bright = Mathf.Clamp01(stream.HighBand / (stream.LowBand + stream.HighBand + 1e-5f));
        float hiss = Mathf.Clamp01((stream.Crossings - 0.05f) / 0.2f);
        Set(jawShape, open * 0.7f);
        Set(visemeA, open * (1f - bright) * (1f - hiss));
        Set(visemeE, open * bright * 0.8f);
        Set(visemeI, open * hiss * 0.7f);
        Set(visemeO, open * (1f - bright) * 0.5f);
        Set(visemeU, open * (1f - bright) * hiss * 0.4f);
        mouthWeight = open;
    }

    void RelaxVowels()
    {
        foreach (var key in new[] { visemeE, visemeI, visemeO, visemeU })
            Set(key, 0f);
    }

    void Set(string key, float target)
    {
        if (!shapes.TryGetValue(key, out var list) || list.Count == 0)
            return;
        float w = Mathf.Lerp(shapeWeights[key], target, 1f - Mathf.Exp(-mouthSmoothing * Time.deltaTime));
        shapeWeights[key] = w;
        foreach (var (smr, index) in list)
            smr.SetBlendShapeWeight(index, w);
    }

    static void CopySettings(AudioSource from, AudioSource to)
    {
        to.playOnAwake = false;
        to.spatialBlend = from.spatialBlend;
        to.minDistance = from.minDistance;
        to.maxDistance = from.maxDistance;
        to.rolloffMode = from.rolloffMode;
        to.volume = from.volume;
    }

    static AudioClip MakeTestClip(float seconds)
    {
        const int rate = 44100;
        int count = Mathf.CeilToInt(seconds * rate);
        var data = new float[count];
        var rng = new System.Random(1);

        // Voice-ish buzz: a low fundamental with harmonics, chopped into
        // syllables by a slow envelope so the mouth visibly opens and closes.
        float pitch = 150f;
        for (int i = 0; i < count; i++)
        {
            float t = (float)i / rate;
            if (i % (rate / 6) == 0) // new "syllable" every ~170 ms
                pitch = 130f + (float)rng.NextDouble() * 60f;

            float env = Mathf.Max(0f, Mathf.Sin(t * 6f * Mathf.PI)); // ~3 syllables/s
            float v = Mathf.Sin(2f * Mathf.PI * pitch * t)
                    + 0.5f * Mathf.Sin(2f * Mathf.PI * pitch * 2f * t)
                    + 0.25f * Mathf.Sin(2f * Mathf.PI * pitch * 3f * t);
            data[i] = v * env * 0.15f;
        }

        var clip = AudioClip.Create("NpcTestSpeech", count, 1, rate, false);
        clip.SetData(data, 0);
        return clip;
    }
}
