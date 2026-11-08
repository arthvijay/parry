using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// The look of every panel, matched to the pitch deck: dark wine glass ("the bar at
/// midnight") with a hairline cream edge, cream type, a rose accent that glows, editorial
/// serif headlines, mono eyebrow labels and a neon script for the name. Drawn with IMGUI on
/// a 1280×720 design canvas that scales to the window. Rounded rectangles are generated
/// once as 9-sliced textures, so panels of any size stay crisp; colours and alpha are
/// applied per draw.
///
/// Type comes from fonts bundled in Resources/Fonts (Bricolage Grotesque for text, Fraunces
/// for headlines, JetBrains Mono for labels, Yellowtail for the neon name; all open
/// licences, in Resources/Fonts/licenses). Their import settings fall back to the system's
/// Noto fonts for Chinese, Japanese and Devanagari, so every dialect still renders.
/// </summary>
public static class GlassUI
{
    public const float DesignW = 1280f, DesignH = 720f;

    /// <summary>Which typeface: body text, editorial headline, mono label, neon script.</summary>
    public enum Face { Body, Display, Mono, Neon }

    static readonly Dictionary<int, Texture2D> rounded = new();
    static readonly Dictionary<int, GUIStyle> slices = new();
    static readonly Dictionary<(Face, int, FontStyle, TextAnchor, bool), GUIStyle> styles = new();
    static readonly Dictionary<Face, Font> fonts = new();
    static Texture2D dot;

    /// <summary>Scale factor from design units to pixels.</summary>
    public static float Scale => Mathf.Min(Screen.width / DesignW, Screen.height / DesignH);
    /// <summary>Window width in design units.</summary>
    public static float Width => Screen.width / Scale;
    public static float Height => Screen.height / Scale;

    // The deck's surfaces.
    static Color Hair(float a = 0.14f) => new(Brand.Cream.r, Brand.Cream.g, Brand.Cream.b, a);

    /// <summary>Switch IMGUI to design units; returns the previous matrix to restore.</summary>
    public static Matrix4x4 Begin()
    {
        var previous = GUI.matrix;
        float s = Scale;
        GUI.matrix = Matrix4x4.Scale(new Vector3(s, s, 1f));
        return previous;
    }

    public static void End(Matrix4x4 previous)
    {
        GUI.matrix = previous;
        GUI.color = Color.white;
    }

    // ---- shapes ---------------------------------------------------------------------

    /// <summary>A rounded rectangle filled with colour <paramref name="fill"/>.</summary>
    public static void Rounded(Rect r, Color fill, int radius = 14)
    {
        if (Event.current.type != EventType.Repaint)
            return;
        var style = Slice(radius);
        var was = GUI.color;
        GUI.color = fill;
        style.Draw(r, GUIContent.none, false, false, false, false);
        GUI.color = was;
    }

    /// <summary>A rounded hairline: the edge of a shape, with nothing inside.</summary>
    public static void Outline(Rect r, Color color, int radius = 14, float thickness = 1f)
    {
        // Four strips, inset by the radius at the corners, plus the corner arcs from a
        // ring texture: cheap, crisp, and transparent inside.
        if (Event.current.type != EventType.Repaint)
            return;
        var style = Ring(radius);
        var was = GUI.color;
        GUI.color = color;
        style.Draw(r, GUIContent.none, false, false, false, false);
        GUI.color = was;
    }

    /// <summary>A soft glow around a shape, like the deck's neon and its rose buttons.</summary>
    public static void Glow(Rect r, Color color, int radius = 14, float spread = 10f, int layers = 4)
    {
        for (int i = layers; i >= 1; i--)
        {
            float k = i / (float)layers;
            float g = spread * k;
            Rounded(new Rect(r.x - g, r.y - g, r.width + 2f * g, r.height + 2f * g),
                    new Color(color.r, color.g, color.b, color.a * 0.10f * (1.2f - k)), radius + Mathf.RoundToInt(g));
        }
    }

    /// <summary>A glass panel: deep wine, translucent, a hairline cream edge, rounded.</summary>
    public static void Panel(Rect r, float alpha = 1f, int radius = 20, Color? tint = null)
    {
        var glass = tint ?? Brand.Glass;
        // A soft shadow under the panel lifts it off the scene.
        Rounded(new Rect(r.x + 2f, r.y + 10f, r.width, r.height), new Color(0f, 0f, 0f, 0.28f * alpha), radius + 4);
        Rounded(r, new Color(glass.r, glass.g, glass.b, 0.78f * alpha), radius);
        // A warm sheen along the top edge, the candlelight in the deck's glass.
        Rounded(new Rect(r.x + 1f, r.y + 1f, r.width - 2f, Mathf.Min(40f, r.height * 0.35f)),
                new Color(1f, 0.85f, 0.75f, 0.035f * alpha), Mathf.Max(4, radius - 1));
        Outline(r, Hair(0.14f * alpha), radius);
    }

    public static void Pill(Rect r, Color fill, string text, Color ink, int size = 13)
    {
        Rounded(r, fill, Mathf.RoundToInt(r.height / 2f));
        Label(r, text, size, ink, FontStyle.Bold, TextAnchor.MiddleCenter);
    }

    /// <summary>A horizontal bar filled to <paramref name="value"/> (0-1).</summary>
    public static void Bar(Rect r, float value, Color fill, float alpha = 1f)
    {
        int radius = Mathf.RoundToInt(r.height / 2f);
        Rounded(r, new Color(1f, 1f, 1f, 0.10f * alpha), radius);
        float w = Mathf.Max(r.height, r.width * Mathf.Clamp01(value));
        if (value > 0.001f)
            Rounded(new Rect(r.x, r.y, w, r.height), new Color(fill.r, fill.g, fill.b, fill.a * alpha), radius);
    }

    public static void Dot(Vector2 centre, float size, Color color)
    {
        if (Event.current.type != EventType.Repaint)
            return;
        if (dot == null)
            dot = MakeRounded(16, 8);
        var was = GUI.color;
        GUI.color = color;
        GUI.DrawTexture(new Rect(centre.x - size / 2f, centre.y - size / 2f, size, size), dot);
        GUI.color = was;
    }

    /// <summary>A line segment drawn as a thin rotated quad.</summary>
    public static void Line(Vector2 a, Vector2 b, float width, Color color)
    {
        if (Event.current.type != EventType.Repaint)
            return;
        var d = b - a;
        float length = d.magnitude;
        if (length < 0.01f)
            return;
        var was = GUI.color;
        var matrix = GUI.matrix;
        GUI.color = color;
        float angle = Mathf.Atan2(d.y, d.x) * Mathf.Rad2Deg;
        // The pivot is taken in screen space, after the design-canvas scale.
        Vector3 pivot = matrix.MultiplyPoint3x4(new Vector3(a.x, a.y, 0f));
        GUIUtility.RotateAroundPivot(angle, new Vector2(pivot.x, pivot.y));
        GUI.DrawTexture(new Rect(a.x, a.y - width / 2f, length, width), Texture2D.whiteTexture);
        GUI.matrix = matrix;
        GUI.color = was;
    }

    // ---- type -----------------------------------------------------------------------

    public static GUIStyle Style(int size, FontStyle weight = FontStyle.Normal,
                                 TextAnchor anchor = TextAnchor.MiddleLeft, bool wrap = false)
        => StyleFor(Face.Body, size, weight, anchor, wrap);

    public static GUIStyle StyleFor(Face face, int size, FontStyle weight = FontStyle.Normal,
                                    TextAnchor anchor = TextAnchor.MiddleLeft, bool wrap = false)
    {
        var key = (face, size, weight, anchor, wrap);
        if (styles.TryGetValue(key, out var style))
            return style;
        style = new GUIStyle(GUI.skin.label)
        {
            font = FontFor(face),
            fontSize = size,
            fontStyle = weight,
            alignment = anchor,
            wordWrap = wrap,
            richText = true,
            clipping = TextClipping.Clip,
            padding = new RectOffset(0, 0, 0, 0),
            margin = new RectOffset(0, 0, 0, 0),
        };
        styles[key] = style;
        return style;
    }

    public static void Label(Rect r, string text, int size, Color color,
                             FontStyle weight = FontStyle.Normal,
                             TextAnchor anchor = TextAnchor.MiddleLeft, bool wrap = false)
        => Text(r, text, size, color, Face.Body, weight, anchor, wrap);

    /// <summary>Text in any of the four faces.</summary>
    public static void Text(Rect r, string text, int size, Color color, Face face,
                            FontStyle weight = FontStyle.Normal,
                            TextAnchor anchor = TextAnchor.MiddleLeft, bool wrap = false)
    {
        var style = StyleFor(face, size, weight, anchor, wrap);
        foreach (var state in new[] { style.normal, style.hover, style.active, style.focused })
            state.textColor = color;
        GUI.Label(r, text, style);
    }

    /// <summary>An editorial headline (Fraunces), the deck's titles.</summary>
    public static void Headline(Rect r, string text, int size, Color color,
                                TextAnchor anchor = TextAnchor.MiddleLeft, bool wrap = false)
        => Text(r, text, size, color, Face.Display, FontStyle.Normal, anchor, wrap);

    /// <summary>The neon name: a script with a rose glow behind it.</summary>
    public static void Neon(Rect r, string text, int size, Color color, TextAnchor anchor = TextAnchor.MiddleLeft)
    {
        float pulse = 0.85f + 0.15f * Mathf.Sin(Time.unscaledTime * 1.7f);
        var glow = new Color(color.r, color.g, color.b, 0.22f * pulse);
        foreach (var o in new[] { new Vector2(-2f, 0f), new Vector2(2f, 0f), new Vector2(0f, -2f), new Vector2(0f, 2f),
                                  new Vector2(-3f, -3f), new Vector2(3f, 3f) })
            Text(new Rect(r.x + o.x, r.y + o.y, r.width, r.height), text, size, glow, Face.Neon, FontStyle.Normal, anchor);
        Text(r, text, size, Color.Lerp(color, Color.white, 0.35f), Face.Neon, FontStyle.Normal, anchor);
    }

    /// <summary>The deck's eyebrow: a short rose dash, then spaced mono capitals.</summary>
    public static void Eyebrow(Rect r, string text, Color? color = null, int size = 11)
    {
        var c = color ?? Brand.Accent;
        Rounded(new Rect(r.x, r.y + r.height / 2f - 1f, 22f, 2f), c, 1);
        Text(new Rect(r.x + 32f, r.y, r.width - 32f, r.height), Spaced(text), size, c, Face.Mono, FontStyle.Bold);
    }

    /// <summary>Capitals with a thin space between letters, for mono labels.</summary>
    public static string Spaced(string text)
    {
        if (string.IsNullOrEmpty(text))
            return "";
        var up = text.ToUpperInvariant();
        var sb = new System.Text.StringBuilder(up.Length * 2);
        foreach (char ch in up)
        {
            sb.Append(ch);
            if (ch != ' ')
                sb.Append(' ');
        }
        return sb.ToString().TrimEnd();
    }

    public static float TextHeight(string text, int size, float width, FontStyle weight = FontStyle.Normal)
        => StyleFor(Face.Body, size, weight, TextAnchor.UpperLeft, true).CalcHeight(new GUIContent(text), width);

    public static float TextWidth(string text, int size, FontStyle weight = FontStyle.Normal)
        => StyleFor(Face.Body, size, weight).CalcSize(new GUIContent(text)).x;

    public static float TextWidth(string text, int size, Face face, FontStyle weight = FontStyle.Normal)
        => StyleFor(face, size, weight).CalcSize(new GUIContent(text)).x;

    /// <summary>A button drawn as a pill; returns true when clicked. The primary one is
    /// rose with a glow; the others are hairline outlines on dark glass.</summary>
    public static bool Button(Rect r, string text, bool primary = false, bool enabled = true, int size = 15)
    {
        bool hover = enabled && r.Contains(Event.current.mousePosition);
        int radius = Mathf.RoundToInt(Mathf.Min(r.height / 2f, 22f));
        if (!enabled)
        {
            Rounded(r, new Color(1f, 1f, 1f, 0.05f), radius);
            Outline(r, Hair(0.08f), radius);
        }
        else if (primary)
        {
            Glow(r, Brand.Accent, radius, hover ? 14f : 9f);
            Rounded(r, hover ? Color.Lerp(Brand.Accent, Color.white, 0.12f) : Brand.Accent, radius);
        }
        else
        {
            Rounded(r, hover ? new Color(1f, 1f, 1f, 0.10f) : new Color(0.05f, 0.015f, 0.04f, 0.55f), radius);
            Outline(r, Hair(hover ? 0.45f : 0.22f), radius);
        }
        Label(r, text, size, enabled ? Brand.Cream : new Color(1f, 1f, 1f, 0.35f), FontStyle.Bold, TextAnchor.MiddleCenter);
        return enabled && GUI.Button(r, GUIContent.none, GUIStyle.none);
    }

    /// <summary>A chip in a row of choices; returns true when clicked.</summary>
    public static bool Chip(Rect r, string text, bool selected, int size = 13)
    {
        bool hover = r.Contains(Event.current.mousePosition);
        int radius = Mathf.RoundToInt(r.height / 2f);
        if (selected)
        {
            Glow(r, Brand.Accent, radius, 6f, 3);
            Rounded(r, Brand.Accent, radius);
        }
        else
        {
            Rounded(r, hover ? new Color(1f, 1f, 1f, 0.09f) : new Color(1f, 1f, 1f, 0.03f), radius);
            Outline(r, Hair(hover ? 0.4f : 0.16f), radius);
        }
        Label(r, text, size, selected ? Brand.Cream : Brand.Muted, selected ? FontStyle.Bold : FontStyle.Normal,
              TextAnchor.MiddleCenter);
        return GUI.Button(r, GUIContent.none, GUIStyle.none);
    }

    /// <summary>A text field on dark glass with a hairline edge.</summary>
    public static string Field(Rect r, string value, string placeholder, int max = 200, int size = 15, string control = null)
    {
        Rounded(r, new Color(0f, 0f, 0f, 0.28f), 12);
        Outline(r, Hair(0.18f), 12);
        var inner = new Rect(r.x + 14f, r.y, r.width - 28f, r.height);
        if (string.IsNullOrEmpty(value))
            Label(inner, placeholder, size, new Color(Brand.Muted.r, Brand.Muted.g, Brand.Muted.b, 0.5f));
        var style = Style(size);
        style.normal.textColor = style.focused.textColor = style.hover.textColor = Brand.Cream;
        if (control != null)
            GUI.SetNextControlName(control);
        return GUI.TextField(inner, value ?? "", max, style);
    }

    // ---- fonts ----------------------------------------------------------------------

    static readonly Dictionary<Face, string> Bundled = new()
    {
        [Face.Body] = "Fonts/BricolageGrotesque",
        [Face.Display] = "Fonts/Fraunces",
        [Face.Mono] = "Fonts/JetBrainsMono",
        [Face.Neon] = "Fonts/Yellowtail",
    };

    public static Font FontFor(Face face)
    {
        if (fonts.TryGetValue(face, out var f) && f != null)
            return f;
        f = Resources.Load<Font>(Bundled[face]);
        if (f == null)
            f = face == Face.Mono ? OsFont(true) : OsFont(false);
        return fonts[face] = f;
    }

    public static Font Font() => FontFor(Face.Body);

    /// <summary>A system font, for when the bundled ones are missing.</summary>
    static Font OsFont(bool mono)
    {
        var installed = new HashSet<string>(UnityEngine.Font.GetOSInstalledFontNames() ?? Array.Empty<string>(),
                                            StringComparer.OrdinalIgnoreCase);
        var candidates = mono
            ? new[] { "JetBrains Mono", "Menlo", "Consolas", "DejaVu Sans Mono", "Liberation Mono", "Noto Sans Mono", "Courier New" }
            : new[] { "Noto Sans", "Noto Sans CJK SC", "Segoe UI", "Helvetica Neue", "Arial Unicode MS", "Arial",
                      "Liberation Sans", "DejaVu Sans", "Roboto" };
        foreach (var name in candidates)
            if (installed.Contains(name))
            {
                var f = UnityEngine.Font.CreateDynamicFontFromOSFont(
                    new[] { name, "Noto Sans CJK SC", "Noto Sans Devanagari", "Microsoft YaHei",
                            "Yu Gothic", "Hiragino Sans", "Nirmala UI", "Arial Unicode MS" }, 16);
                if (f != null)
                    return f;
            }
        Font builtin = null;
        try { builtin = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf"); } catch (Exception) { }
        return builtin != null ? builtin : GUI.skin.font;
    }

    // ---- receipt type: a monospaced face, like a thermal printer ------------------

    public static Font Mono() => FontFor(Face.Mono);

    public static GUIStyle MonoStyle(int size, FontStyle weight = FontStyle.Normal,
                                     TextAnchor anchor = TextAnchor.MiddleLeft, bool wrap = false)
        => StyleFor(Face.Mono, size, weight, anchor, wrap);

    public static void MonoLabel(Rect r, string text, int size, Color color,
                                 FontStyle weight = FontStyle.Normal,
                                 TextAnchor anchor = TextAnchor.MiddleLeft, bool wrap = false)
        => Text(r, text, size, color, Face.Mono, weight, anchor, wrap);

    public static float MonoHeight(string text, int size, float width, FontStyle weight = FontStyle.Normal)
        => MonoStyle(size, weight, TextAnchor.UpperLeft, true).CalcHeight(new GUIContent(text), width);

    // ---- motion ---------------------------------------------------------------------

    /// <summary>Frame-rate independent ease toward a target.</summary>
    public static float Ease(float current, float target, float speed)
        => Mathf.Lerp(current, target, 1f - Mathf.Exp(-speed * Time.unscaledDeltaTime));

    // ---- textures -------------------------------------------------------------------

    static GUIStyle Slice(int radius)
    {
        radius = Mathf.Clamp(radius, 2, 48);
        if (slices.TryGetValue(radius, out var style) && style.normal.background != null)
            return style;
        if (!rounded.TryGetValue(radius, out var tex) || tex == null)
            rounded[radius] = tex = MakeRounded(radius * 2 + 4, radius);
        style = new GUIStyle
        {
            normal = { background = tex },
            border = new RectOffset(radius + 1, radius + 1, radius + 1, radius + 1),
        };
        slices[radius] = style;
        return style;
    }

    static readonly Dictionary<int, GUIStyle> rings = new();

    static GUIStyle Ring(int radius)
    {
        radius = Mathf.Clamp(radius, 2, 48);
        if (rings.TryGetValue(radius, out var style) && style.normal.background != null)
            return style;
        var tex = MakeRounded(radius * 2 + 4, radius, ring: true);
        style = new GUIStyle
        {
            normal = { background = tex },
            border = new RectOffset(radius + 1, radius + 1, radius + 1, radius + 1),
        };
        rings[radius] = style;
        return style;
    }

    /// <summary>White rounded square with anti-aliased corners, alpha carrying the shape;
    /// with <paramref name="ring"/>, only a one-pixel edge.</summary>
    static Texture2D MakeRounded(int size, int radius, bool ring = false)
    {
        var tex = new Texture2D(size, size, TextureFormat.RGBA32, false)
        {
            wrapMode = TextureWrapMode.Clamp,
            filterMode = FilterMode.Bilinear,
            hideFlags = HideFlags.HideAndDontSave,
        };
        var pixels = new Color32[size * size];
        for (int y = 0; y < size; y++)
            for (int x = 0; x < size; x++)
            {
                float cx = Mathf.Clamp(x + 0.5f, radius, size - radius);
                float cy = Mathf.Clamp(y + 0.5f, radius, size - radius);
                float d = Vector2.Distance(new Vector2(x + 0.5f, y + 0.5f), new Vector2(cx, cy));
                float a = Mathf.Clamp01(radius - d + 0.5f);
                if (ring)
                {
                    // radius - d is the distance in from the edge, corners and straight
                    // sides alike: keep a one-pixel band.
                    a *= Mathf.Clamp01(1.5f - (radius - d));
                }
                pixels[y * size + x] = new Color32(255, 255, 255, (byte)(a * 255));
            }
        tex.SetPixels32(pixels);
        tex.Apply(false, true);
        return tex;
    }
}
