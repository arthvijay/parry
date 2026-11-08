using UnityEngine;

/// <summary>
/// The speed-dating bell, synthesised: a struck bell's inharmonic partials, each with its
/// own decay. Rung when the date starts and when time is up.
/// </summary>
public static class SpeedDateChime
{
    static AudioSource source;
    static AudioClip clip;

    public static void Play(float volume = 0.7f)
    {
        if (source == null)
        {
            var go = new GameObject("Speed Date Bell");
            Object.DontDestroyOnLoad(go);
            source = go.AddComponent<AudioSource>();
            source.spatialBlend = 0f;
            source.playOnAwake = false;
        }
        if (clip == null)
            clip = Make();
        source.PlayOneShot(clip, volume);
    }

    static AudioClip Make()
    {
        const int rate = 44100;
        const float seconds = 2.4f;
        int n = (int)(rate * seconds);
        var data = new float[n];
        // Partials of a small hand bell (ratios to the fundamental) and their decay rates.
        float f = 1046.5f;
        (float ratio, float amp, float decay)[] partials =
        {
            (1f, 0.55f, 2.2f), (2.76f, 0.30f, 3.5f), (5.40f, 0.18f, 5f), (8.93f, 0.10f, 7f), (0.5f, 0.12f, 1.6f),
        };
        for (int i = 0; i < n; i++)
        {
            float t = i / (float)rate;
            float strike = Mathf.Clamp01(t * 400f);
            float s = 0f;
            foreach (var (ratio, amp, decay) in partials)
                s += amp * Mathf.Exp(-decay * t) * Mathf.Sin(2f * Mathf.PI * f * ratio * t);
            data[i] = s * strike * 0.6f;
        }
        var c = AudioClip.Create("SpeedDateBell", n, 1, rate, false);
        c.SetData(data, 0);
        return c;
    }
}
