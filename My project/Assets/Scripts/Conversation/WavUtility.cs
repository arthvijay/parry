using System;
using System.IO;
using UnityEngine;

/// <summary>Minimal WAV encode/decode: mic audio out to the server, NPC audio back from it.</summary>
public static class WavUtility
{
    /// <summary>Encode mono/stereo float samples as a 16-bit PCM WAV file.</summary>
    public static byte[] FromSamples(float[] samples, int channels, int sampleRate)
    {
        using var stream = new MemoryStream(44 + samples.Length * 2);
        using var w = new BinaryWriter(stream);

        int dataBytes = samples.Length * 2;
        w.Write(new[] { 'R', 'I', 'F', 'F' });
        w.Write(36 + dataBytes);
        w.Write(new[] { 'W', 'A', 'V', 'E' });
        w.Write(new[] { 'f', 'm', 't', ' ' });
        w.Write(16);                       // PCM chunk size
        w.Write((short)1);                 // PCM format
        w.Write((short)channels);
        w.Write(sampleRate);
        w.Write(sampleRate * channels * 2); // byte rate
        w.Write((short)(channels * 2));     // block align
        w.Write((short)16);                 // bits per sample
        w.Write(new[] { 'd', 'a', 't', 'a' });
        w.Write(dataBytes);
        foreach (float s in samples)
            w.Write((short)(Mathf.Clamp(s, -1f, 1f) * short.MaxValue));

        w.Flush();
        return stream.ToArray();
    }

    /// <summary>
    /// Decode a PCM WAV (8/16/24/32-bit int or 32-bit float, any channel count) into a clip.
    /// Returns null if the bytes aren't a WAV we understand.
    /// </summary>
    public static AudioClip ClipFromWav(byte[] wav, string name = "speech")
    {
        if (wav == null || wav.Length < 12 || Tag(wav, 0) != "RIFF" || Tag(wav, 8) != "WAVE")
        {
            Debug.LogWarning("WavUtility: not a RIFF/WAVE file.");
            return null;
        }

        int format = 0, channels = 0, sampleRate = 0, bits = 0;
        int dataStart = -1, dataLength = 0;
        for (int pos = 12; pos + 8 <= wav.Length;)
        {
            string id = Tag(wav, pos);
            int size = BitConverter.ToInt32(wav, pos + 4);
            int body = pos + 8;
            if (id == "fmt " && body + 16 <= wav.Length)
            {
                format = BitConverter.ToInt16(wav, body);
                channels = BitConverter.ToInt16(wav, body + 2);
                sampleRate = BitConverter.ToInt32(wav, body + 4);
                bits = BitConverter.ToInt16(wav, body + 14);
                if (format == 0xFFFE && size >= 26) // WAVE_FORMAT_EXTENSIBLE: real format is in the sub-format GUID
                    format = BitConverter.ToInt16(wav, body + 24);
            }
            else if (id == "data")
            {
                dataStart = body;
                dataLength = Math.Min(size < 0 ? int.MaxValue : size, wav.Length - body);
                break;
            }
            pos = body + size + (size & 1);
        }

        if (dataStart < 0 || channels <= 0 || sampleRate <= 0 || (format != 1 && format != 3))
        {
            Debug.LogWarning($"WavUtility: unsupported WAV (format {format}, {channels} ch, {bits} bit).");
            return null;
        }

        int bytesPerSample = bits / 8;
        int count = dataLength / bytesPerSample;
        var samples = new float[count];
        for (int i = 0, p = dataStart; i < count; i++, p += bytesPerSample)
        {
            samples[i] = (format, bits) switch
            {
                (1, 8) => (wav[p] - 128) / 128f,
                (1, 16) => BitConverter.ToInt16(wav, p) / 32768f,
                (1, 24) => ((wav[p] << 8 | wav[p + 1] << 16 | wav[p + 2] << 24) >> 8) / 8388608f,
                (1, 32) => BitConverter.ToInt32(wav, p) / 2147483648f,
                (3, 32) => BitConverter.ToSingle(wav, p),
                _ => 0f,
            };
        }

        var clip = AudioClip.Create(name, count / channels, channels, sampleRate, false);
        clip.SetData(samples, 0);
        return clip;
    }

    static string Tag(byte[] b, int at) => System.Text.Encoding.ASCII.GetString(b, at, 4);

    /// <summary>Build an AudioClip from raw little-endian 16-bit mono PCM.</summary>
    public static AudioClip ClipFromPcm16(byte[] pcm, int sampleRate, string name = "speech")
    {
        int count = pcm.Length / 2;
        var samples = new float[count];
        for (int i = 0; i < count; i++)
            samples[i] = BitConverter.ToInt16(pcm, i * 2) / 32768f;

        var clip = AudioClip.Create(name, count, 1, sampleRate, false);
        clip.SetData(samples, 0);
        return clip;
    }

    /// <summary>Peak absolute sample value, to tell silence from speech.</summary>
    public static float Peak(float[] samples)
    {
        float peak = 0f;
        foreach (float s in samples)
            peak = Mathf.Max(peak, Mathf.Abs(s));
        return peak;
    }
}
