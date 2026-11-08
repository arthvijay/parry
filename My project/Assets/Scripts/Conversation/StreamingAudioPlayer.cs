using System;
using UnityEngine;

/// <summary>
/// Plays a character's voice as it streams in. PCM16 frames from the socket (24 kHz mono)
/// are converted to floats on the receive thread and written into a fixed ring buffer;
/// a looping streaming <see cref="AudioClip"/> on the NPC's 3D AudioSource reads from it on
/// the audio thread, so playback starts with the first frame and never allocates.
///
/// The same audio-thread callback measures what is being played (loudness, low and high
/// band energy, zero-crossing rate), which <see cref="NpcSpeaker"/> turns into jaw and
/// vowel shapes: lip-sync that works for any language without pre-baked visemes.
/// <see cref="Flush"/> empties the buffer instantly for barge-in.
/// </summary>
[DisallowMultipleComponent]
public class StreamingAudioPlayer : MonoBehaviour
{
    public const int SampleRate = 24000;

    [Tooltip("Seconds of audio the ring buffer can hold.")]
    public int capacitySeconds = 30;

    readonly object gate = new();
    float[] ring;
    int readIndex, writeIndex, buffered;
    byte carry;
    bool hasCarry;
    AudioSource source;
    AudioClip clip;

    // Measured on the audio thread, read on the main thread.
    volatile float level, lowBand, highBand, crossings;
    float lowState, highState, lastSample;

    volatile bool turnOpen;          // between audio_start and audio_end
    volatile bool drainReported = true;
    float lastAudioAt = -10f;

    /// <summary>Raised on the main thread when a finished turn has played out completely.</summary>
    public event Action Drained;

    public float Level => level;
    public float LowBand => lowBand;
    public float HighBand => highBand;
    public float Crossings => crossings;

    public float BufferedSeconds
    {
        get { lock (gate) return buffered / (float)SampleRate; }
    }

    /// <summary>True while there is voice left to play (or it just ran out).</summary>
    public bool IsPlaying => BufferedSeconds > 0.005f || Time.unscaledTime - lastAudioAt < 0.12f;

    void Awake()
    {
        ring = new float[SampleRate * Mathf.Max(5, capacitySeconds)];
    }

    /// <summary>Start playing through <paramref name="target"/> (the NPC's head-mounted source).</summary>
    public void Attach(AudioSource target)
    {
        if (target == null)
            return;
        if (source != null && source != target)
            source.Stop();
        source = target;
        if (clip == null)
            clip = AudioClip.Create($"{name}-voice", SampleRate, 1, SampleRate, true, OnRead);
        source.clip = clip;
        source.loop = true;
        source.playOnAwake = false;
        if (!source.isPlaying)
            source.Play();
    }

    public AudioSource Source => source;

    /// <summary>A new turn begins; frames will follow. Safe from any thread.</summary>
    public void BeginTurn()
    {
        turnOpen = true;
        drainReported = false;
    }

    /// <summary>The server has sent the last frame of this turn.</summary>
    public void EndTurn() => turnOpen = false;

    /// <summary>Append PCM16 little-endian mono samples. Safe from any thread.</summary>
    public void Enqueue(byte[] data, int offset, int length)
    {
        if (data == null || length <= 0)
            return;
        lock (gate)
        {
            int i = offset, end = offset + length;
            if (hasCarry && i < end)
            {
                Write((short)(carry | (data[i] << 8)) / 32768f);
                i++;
                hasCarry = false;
            }
            for (; i + 1 < end; i += 2)
                Write((short)(data[i] | (data[i + 1] << 8)) / 32768f);
            if (i < end)
            {
                carry = data[i];
                hasCarry = true;
            }
        }
    }

    void Write(float sample)
    {
        if (buffered == ring.Length)
        {
            // Full: drop the oldest sample rather than block the socket.
            readIndex = (readIndex + 1) % ring.Length;
            buffered--;
        }
        ring[writeIndex] = sample;
        writeIndex = (writeIndex + 1) % ring.Length;
        buffered++;
    }

    /// <summary>Barge-in: silence now. Everything buffered is discarded.</summary>
    public void Flush()
    {
        lock (gate)
        {
            readIndex = writeIndex = buffered = 0;
            hasCarry = false;
        }
        turnOpen = false;
        drainReported = true;
        level = lowBand = highBand = 0f;
    }

    void Update()
    {
        // The streaming clip loops forever; keep it running whatever else used the source.
        if (source != null && source.clip == clip && !source.isPlaying && source.isActiveAndEnabled)
            source.Play();
        if (BufferedSeconds > 0.005f)
            lastAudioAt = Time.unscaledTime;
        if (!drainReported && !turnOpen && !IsPlaying)
        {
            drainReported = true;
            Drained?.Invoke();
        }
    }

    // Audio thread.
    void OnRead(float[] data)
    {
        int n = data.Length;
        int got;
        lock (gate)
        {
            got = Math.Min(n, buffered);
            for (int i = 0; i < got; i++)
            {
                data[i] = ring[readIndex];
                readIndex = (readIndex + 1) % ring.Length;
            }
            buffered -= got;
        }
        for (int i = got; i < n; i++)
            data[i] = 0f;

        // Soft edges: a starved buffer ramps to silence instead of clicking.
        if (got < n && got > 0)
        {
            int ramp = Math.Min(got, 48);
            for (int i = 0; i < ramp; i++)
                data[got - 1 - i] *= i / (float)ramp;
        }

        // What is being played, for the mouth.
        float sum = 0f, lowSum = 0f, highSum = 0f;
        int zc = 0;
        for (int i = 0; i < n; i++)
        {
            float s = data[i];
            sum += s * s;
            lowState += 0.12f * (s - lowState);           // ~500 Hz one-pole low-pass at 24 kHz
            float high = s - lowState;
            highState += 0.5f * (high - highState);
            lowSum += lowState * lowState;
            highSum += highState * highState;
            if ((s >= 0f) != (lastSample >= 0f))
                zc++;
            lastSample = s;
        }
        level = Mathf.Sqrt(sum / n);
        lowBand = Mathf.Sqrt(lowSum / n);
        highBand = Mathf.Sqrt(highSum / n);
        crossings = zc / (float)n;
    }

    void OnDestroy()
    {
        if (source != null && source.clip == clip)
            source.Stop();
        if (clip != null)
            Destroy(clip);
    }
}
