using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Flat-shaded meshes for the front. Everything is triangles with one colour each, and
/// the colour is a swatch of one small palette texture picked by UV — so a single
/// material draws the Earth, the clouds and the pin, and nothing here needs an asset
/// beyond the land/sea map the Earth is read from.
/// </summary>
public static class LowPoly
{
    public enum Swatch { Ocean, Sand, Grass, Forest, Rock, Snow, Cloud, CloudShade, CloudUnder, Count }

    static readonly Color[] Palette =
    {
        new(0.20f, 0.46f, 0.72f),   // Ocean
        new(0.91f, 0.82f, 0.58f),   // Sand
        new(0.52f, 0.72f, 0.38f),   // Grass
        new(0.27f, 0.52f, 0.33f),   // Forest
        new(0.62f, 0.55f, 0.46f),   // Rock
        new(0.96f, 0.97f, 0.98f),   // Snow
        new(1.00f, 1.00f, 1.00f),   // Cloud, lit from above; also the pin
        new(0.86f, 0.91f, 0.98f),   // Cloud, sides
        new(0.72f, 0.80f, 0.92f),   // Cloud, underside
    };

    static Texture2D palette;

    public static Texture2D PaletteTexture()
    {
        if (palette == null)
        {
            palette = new Texture2D(Palette.Length, 1, TextureFormat.RGBA32, false)
            {
                filterMode = FilterMode.Point,
                wrapMode = TextureWrapMode.Clamp,
                hideFlags = HideFlags.HideAndDontSave,
            };
            palette.SetPixels(Palette);
            palette.Apply(false, true);
        }
        return palette;
    }

    /// <summary>One material for palette meshes: lit (the Earth, under the sun) or not (clouds, which carry their own shading).</summary>
    public static Material PaletteMaterial(bool lit)
    {
        var shader = lit
            ? Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard")
            : Shader.Find("Universal Render Pipeline/Unlit") ?? Shader.Find("Unlit/Texture");
        var m = new Material(shader);
        m.SetTexture("_BaseMap", PaletteTexture());
        m.SetTexture("_MainTex", PaletteTexture());
        if (lit)
        {
            m.SetFloat("_Smoothness", 0.08f);
            m.SetFloat("_Metallic", 0f);
        }
        return m;
    }

    /// <summary>An unlit material showing a vertical gradient: for the sky dome.</summary>
    public static Material GradientMaterial(Color below, Color horizon, Color zenith)
    {
        const int n = 64;
        var tex = new Texture2D(1, n, TextureFormat.RGBA32, false)
        {
            filterMode = FilterMode.Bilinear,
            wrapMode = TextureWrapMode.Clamp,
            hideFlags = HideFlags.HideAndDontSave,
        };
        var px = new Color[n];
        for (int i = 0; i < n; i++)
        {
            float v = i / (n - 1f);
            px[i] = v < 0.5f
                ? Color.Lerp(below, horizon, Mathf.SmoothStep(0f, 1f, v * 2f))
                : Color.Lerp(horizon, zenith, Mathf.Pow((v - 0.5f) * 2f, 0.7f));
        }
        tex.SetPixels(px);
        tex.Apply(false, true);
        var m = new Material(Shader.Find("Universal Render Pipeline/Unlit") ?? Shader.Find("Unlit/Texture"));
        m.SetTexture("_BaseMap", tex);
        m.SetTexture("_MainTex", tex);
        return m;
    }

    // ---- building -------------------------------------------------------------------

    /// <summary>Collects flat-shaded triangles; every triangle gets its own three vertices.</summary>
    public class Builder
    {
        readonly List<Vector3> verts = new();
        readonly List<Vector3> normals = new();
        readonly List<Vector2> uvs = new();
        readonly List<int> tris = new();

        public void Tri(Vector3 a, Vector3 b, Vector3 c, Swatch swatch)
        {
            var n = Vector3.Cross(b - a, c - a).normalized;
            var uv = new Vector2(((int)swatch + 0.5f) / (int)Swatch.Count, 0.5f);
            int i = verts.Count;
            verts.Add(a); verts.Add(b); verts.Add(c);
            normals.Add(n); normals.Add(n); normals.Add(n);
            uvs.Add(uv); uvs.Add(uv); uvs.Add(uv);
            tris.Add(i); tris.Add(i + 1); tris.Add(i + 2);
        }

        public Mesh Build(string name)
        {
            var mesh = new Mesh { name = name };
            if (verts.Count > 65535)
                mesh.indexFormat = UnityEngine.Rendering.IndexFormat.UInt32;
            mesh.SetVertices(verts);
            mesh.SetNormals(normals);
            mesh.SetUVs(0, uvs);
            mesh.SetTriangles(tris, 0);
            mesh.RecalculateBounds();
            return mesh;
        }
    }

    /// <summary>Unit icosphere as outward-wound triangles (Unity's clockwise front faces).</summary>
    public static List<(Vector3 a, Vector3 b, Vector3 c)> Icosphere(int subdivisions)
    {
        float t = (1f + Mathf.Sqrt(5f)) / 2f;
        var v = new Vector3[]
        {
            new(-1, t, 0), new(1, t, 0), new(-1, -t, 0), new(1, -t, 0),
            new(0, -1, t), new(0, 1, t), new(0, -1, -t), new(0, 1, -t),
            new(t, 0, -1), new(t, 0, 1), new(-t, 0, -1), new(-t, 0, 1),
        };
        for (int i = 0; i < v.Length; i++)
            v[i].Normalize();
        int[] f =
        {
            0, 11, 5, 0, 5, 1, 0, 1, 7, 0, 7, 10, 0, 10, 11,
            1, 5, 9, 5, 11, 4, 11, 10, 2, 10, 7, 6, 7, 1, 8,
            3, 9, 4, 3, 4, 2, 3, 2, 6, 3, 6, 8, 3, 8, 9,
            4, 9, 5, 2, 4, 11, 6, 2, 10, 8, 6, 7, 9, 8, 1,
        };
        var faces = new List<(Vector3, Vector3, Vector3)>();
        for (int i = 0; i < f.Length; i += 3)
            faces.Add(Outward(v[f[i]], v[f[i + 1]], v[f[i + 2]]));
        for (int s = 0; s < subdivisions; s++)
        {
            var next = new List<(Vector3, Vector3, Vector3)>(faces.Count * 4);
            foreach (var (a, b, c) in faces)
            {
                Vector3 ab = ((a + b) / 2f).normalized, bc = ((b + c) / 2f).normalized, ca = ((c + a) / 2f).normalized;
                next.Add((a, ab, ca)); next.Add((ab, b, bc)); next.Add((ca, bc, c)); next.Add((ab, bc, ca));
            }
            faces = next;
        }
        return faces;
    }

    /// <summary>Wind a sphere face so its normal points away from the origin.</summary>
    static (Vector3, Vector3, Vector3) Outward(Vector3 a, Vector3 b, Vector3 c) =>
        Vector3.Dot(Vector3.Cross(b - a, c - a), a + b + c) >= 0f ? (a, b, c) : (a, c, b);

    // ---- the pieces -----------------------------------------------------------------

    /// <summary>
    /// A faceted Earth, radius 1: each face coloured by what the land/sea map says is
    /// under it. Longitude 0 faces −z, matching <see cref="Wish"/>'s pin maths. Five
    /// subdivisions is 20,480 faces, each under 100 km across, so coastal cities sit on
    /// their coast rather than in the sea a face-width away.
    /// </summary>
    public static Mesh Earth(Texture2D map, int subdivisions = 5)
    {
        var b = new Builder();
        var votes = new int[(int)Swatch.Count];
        var samples = new Vector3[7];
        foreach (var (p, q, r) in Icosphere(subdivisions))
        {
            Array.Clear(votes, 0, votes.Length);
            var centre = (p + q + r) / 3f;
            // Sample the centre, each corner pulled part-way in, and the edge midpoints.
            samples[0] = centre;
            samples[1] = Vector3.Lerp(p, centre, 0.4f); samples[2] = Vector3.Lerp(q, centre, 0.4f); samples[3] = Vector3.Lerp(r, centre, 0.4f);
            samples[4] = Vector3.Lerp(p, q, 0.5f); samples[5] = Vector3.Lerp(q, r, 0.5f); samples[6] = Vector3.Lerp(r, p, 0.5f);
            foreach (var s in samples)
                votes[(int)Classify(map, s.normalized)]++;
            // A face is sea only if it's mostly sea: coasts lean land, so peninsulas and
            // islands keep their shape instead of eroding a face at a time.
            int land = samples.Length - votes[(int)Swatch.Ocean];
            if (land < 3)
            {
                b.Tri(p, q, r, Swatch.Ocean);
                continue;
            }
            int best = (int)Swatch.Sand;
            for (int i = 0; i < votes.Length; i++)
                if (i != (int)Swatch.Ocean && votes[i] > votes[best])
                    best = i;
            b.Tri(p, q, r, (Swatch)best);
        }
        return b.Build("Earth");
    }

    static Swatch Classify(Texture2D map, Vector3 dir)
    {
        if (map == null)
            return Swatch.Ocean;
        float lat = Mathf.Asin(Mathf.Clamp(dir.y, -1f, 1f));
        float lon = Mathf.Atan2(dir.x, -dir.z);
        var c = map.GetPixelBilinear(lon / (2f * Mathf.PI) + 0.5f, lat / Mathf.PI + 0.5f);
        if (c.r > 0.72f && c.g > 0.72f && c.b > 0.72f)
            return Swatch.Snow;
        if (c.b > c.g)                       // the map's seas are blue; nothing on land is
            return Swatch.Ocean;
        Swatch nearest = Swatch.Grass;
        float bestD = float.MaxValue;
        foreach (var (swatch, r, g, bl) in new[] { (Swatch.Sand, 0.72f, 0.62f, 0.42f), (Swatch.Grass, 0.36f, 0.50f, 0.24f),
                                                    (Swatch.Forest, 0.14f, 0.28f, 0.14f), (Swatch.Rock, 0.42f, 0.38f, 0.32f) })
        {
            float d = (c.r - r) * (c.r - r) + (c.g - g) * (c.g - g) + (c.b - bl) * (c.b - bl);
            if (d < bestD) { bestD = d; nearest = swatch; }
        }
        return nearest;
    }

    /// <summary>
    /// A cloud: a few squashed icospheres pushed together, flat along the bottom, faces
    /// shaded by which way they look. About 2.5 wide, 1 tall, centred near the origin.
    /// Every puff is cut off by the base, so none of them reads as a whole ball.
    /// </summary>
    public static Mesh Cloud(int seed)
    {
        var rng = new System.Random(seed);
        float R(float lo, float hi) => lo + (float)rng.NextDouble() * (hi - lo);
        var b = new Builder();
        var ico = Icosphere(1);
        int puffs = 4 + rng.Next(4);
        const float floor = 0f;
        for (int i = 0; i < puffs; i++)
        {
            float radius = R(0.45f, 0.85f) * (i == 0 ? 1.15f : 1f);
            var squash = new Vector3(R(1f, 1.3f), R(0.5f, 0.7f), R(0.75f, 1f));
            // Sit each puff low enough that the base slices off its lower half or so.
            var centre = new Vector3(R(-1.0f, 1.0f), radius * squash.y * R(0.05f, 0.45f), R(-0.4f, 0.4f));
            foreach (var (p, q, r) in ico)
            {
                Vector3 A = Puff(p), B = Puff(q), C = Puff(r);
                var n = Vector3.Cross(B - A, C - A);
                if (n.sqrMagnitude < 1e-8f)
                    continue;                                   // squashed flat into the floor
                var swatch = n.normalized.y > 0.3f ? Swatch.Cloud : n.normalized.y > -0.35f ? Swatch.CloudShade : Swatch.CloudUnder;
                b.Tri(A, B, C, swatch);

                Vector3 Puff(Vector3 v)
                {
                    var w = centre + Vector3.Scale(v, squash) * radius;
                    w.y = Mathf.Max(w.y, floor);
                    return w;
                }
            }
        }
        return b.Build("Cloud");
    }

    /// <summary>A small faceted ball for the pin.</summary>
    public static Mesh Ball(Swatch swatch)
    {
        var b = new Builder();
        foreach (var (p, q, r) in Icosphere(1))
            b.Tri(p, q, r, swatch);
        return b.Build("Ball");
    }

    /// <summary>A sphere seen from inside, UV.y running from the bottom (0) to the top (1): the sky.</summary>
    public static Mesh Dome(int segments = 32, int rings = 16)
    {
        var verts = new Vector3[(rings + 1) * (segments + 1)];
        var uv = new Vector2[verts.Length];
        for (int i = 0; i <= rings; i++)
        {
            float lat = -Mathf.PI / 2f + Mathf.PI * i / rings;
            for (int j = 0; j <= segments; j++)
            {
                float lon = 2f * Mathf.PI * j / segments;
                int k = i * (segments + 1) + j;
                verts[k] = new Vector3(Mathf.Cos(lat) * Mathf.Sin(lon), Mathf.Sin(lat), -Mathf.Cos(lat) * Mathf.Cos(lon));
                uv[k] = new Vector2(j / (float)segments, i / (float)rings);
            }
        }
        var tris = new int[rings * segments * 6];
        int n = 0;
        for (int i = 0; i < rings; i++)
            for (int j = 0; j < segments; j++)
            {
                int a = i * (segments + 1) + j, b = a + 1, c = a + segments + 1, d = c + 1;
                // Anticlockwise from outside, so the inside is the front face.
                tris[n++] = a; tris[n++] = d; tris[n++] = c;
                tris[n++] = a; tris[n++] = b; tris[n++] = d;
            }
        var mesh = new Mesh { name = "Dome" };
        mesh.SetVertices(verts);
        mesh.SetUVs(0, uv);
        mesh.SetTriangles(tris, 0);
        mesh.RecalculateBounds();
        return mesh;
    }
}
