using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// The look of every panel: frosted dark glass with rounded corners, a hairline edge and
/// soft type, drawn with IMGUI on a 1280×720 design canvas that scales to the window.
/// Rounded rectangles are generated once as 9-sliced textures, so panels of any size
/// stay crisp; colours and alpha are applied per draw.
/// </summary>
public static class GlassUI
{
    public const float DesignW = 1280f, DesignH = 720f;

    static readonly Dictionary<int, Texture2D> rounded = new();
    static readonly Dictionary<int, GUIStyle> slices = new();
    static readonly Dictionary<(int, FontStyle, TextAnchor, bool), GUIStyle> styles = new();
    static Font font;
    static Texture2D dot;

    /// <summary>Scale factor from design units to pixels.</summary>
    public static float Scale => Mathf.Min(Screen.width / DesignW, Screen.height / DesignH);
    /// <summary>Window width in design units.</summary>
    public static float Width => Screen.width / Scale;
    public static float Height => Screen.height / Scale;

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

    /// <summary>A glass panel: dark translucent fill, a faint lighter edge, rounded.</summary>
    public static void Panel(Rect r, float alpha = 1f, int radius = 16, Color? tint = null)
    {
        var glass = tint ?? Brand.Glass;
        Rounded(new Rect(r.x - 1f, r.y - 1f, r.width + 2f, r.height + 2f),
                new Color(1f, 1f, 1f, 0.10f * alpha), radius + 1);
        Rounded(r, new Color(glass.r, glass.g, glass.b, 0.72f * alpha), radius);
        // A sheen along the top, the "glass" in glassmorphism.
        Rounded(new Rect(r.x + 2f, r.y + 2f, r.width - 4f, Mathf.Min(18f, r.height * 0.3f)),
                new Color(1f, 1f, 1f, 0.05f * alpha), Mathf.Max(4, radius - 2));
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
        Rounded(r, new Color(1f, 1f, 1f, 0.12f * alpha), radius);
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
    {
        var key = (size, weight, anchor, wrap);
        if (styles.TryGetValue(key, out var style))
            return style;
        style = new GUIStyle(GUI.skin.label)
        {
            font = Font(),
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
    {
        var style = Style(size, weight, anchor, wrap);
        foreach (var state in new[] { style.normal, style.hover, style.active, style.focused })
            state.textColor = color;
        GUI.Label(r, text, style);
    }

    public static float TextHeight(string text, int size, float width, FontStyle weight = FontStyle.Normal)
        => Style(size, weight, TextAnchor.UpperLeft, true).CalcHeight(new GUIContent(text), width);

    public static float TextWidth(string text, int size, FontStyle weight = FontStyle.Normal)
        => Style(size, weight).CalcSize(new GUIContent(text)).x;

    /// <summary>A button drawn as a pill; returns true when clicked.</summary>
    public static bool Button(Rect r, string text, bool primary = false, bool enabled = true, int size = 15)
    {
        bool hover = enabled && r.Contains(Event.current.mousePosition);
        Color fill = !enabled ? new Color(1f, 1f, 1f, 0.08f)
            : primary ? (hover ? Color.Lerp(Brand.Accent, Color.white, 0.15f) : Brand.Accent)
            : (hover ? new Color(1f, 1f, 1f, 0.22f) : new Color(1f, 1f, 1f, 0.12f));
        Rounded(r, fill, Mathf.RoundToInt(Mathf.Min(r.height / 2f, 14f)));
        Label(r, text, size, enabled ? Color.white : new Color(1f, 1f, 1f, 0.4f), FontStyle.Bold, TextAnchor.MiddleCenter);
        return enabled && GUI.Button(r, GUIContent.none, GUIStyle.none);
    }

    /// <summary>A chip in a row of choices; returns true when clicked.</summary>
    public static bool Chip(Rect r, string text, bool selected, int size = 13)
    {
        bool hover = r.Contains(Event.current.mousePosition);
        Color fill = selected ? Brand.Accent : hover ? new Color(1f, 1f, 1f, 0.2f) : new Color(1f, 1f, 1f, 0.09f);
        Rounded(r, fill, Mathf.RoundToInt(r.height / 2f));
        Label(r, text, size, Color.white, selected ? FontStyle.Bold : FontStyle.Normal, TextAnchor.MiddleCenter);
        return GUI.Button(r, GUIContent.none, GUIStyle.none);
    }

    /// <summary>A text field on a glass background.</summary>
    public static string Field(Rect r, string value, string placeholder, int max = 200, int size = 15, string control = null)
    {
        Rounded(r, new Color(1f, 1f, 1f, 0.10f), 10);
        var inner = new Rect(r.x + 12f, r.y, r.width - 24f, r.height);
        if (string.IsNullOrEmpty(value))
            Label(inner, placeholder, size, new Color(1f, 1f, 1f, 0.35f));
        var style = Style(size);
        style.normal.textColor = style.focused.textColor = style.hover.textColor = Color.white;
        if (control != null)
            GUI.SetNextControlName(control);
        return GUI.TextField(inner, value ?? "", max, style);
    }

    public static Font Font()
    {
        if (font != null)
            return font;
        var installed = new HashSet<string>(UnityEngine.Font.GetOSInstalledFontNames() ?? Array.Empty<string>(),
                                            StringComparer.OrdinalIgnoreCase);
        // Wide-coverage faces first: the dates speak Mandarin, Hindi and Japanese too.
        foreach (var name in new[] { "Noto Sans", "Noto Sans CJK SC", "Segoe UI", "Helvetica Neue",
                                     "Arial Unicode MS", "Arial", "Liberation Sans", "DejaVu Sans", "Roboto" })
            if (installed.Contains(name))
            {
                var f = UnityEngine.Font.CreateDynamicFontFromOSFont(
                    new[] { name, "Noto Sans CJK SC", "Noto Sans Devanagari", "Microsoft YaHei",
                            "Yu Gothic", "Hiragino Sans", "Nirmala UI", "Arial Unicode MS" }, 16);
                if (f != null)
                    return font = f;
            }
        Font builtin = null;
        try { builtin = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf"); } catch (Exception) { }
        return font = builtin != null ? builtin : GUI.skin.font;
    }

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

    /// <summary>White rounded square with anti-aliased corners, alpha carrying the shape.</summary>
    static Texture2D MakeRounded(int size, int radius)
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
                pixels[y * size + x] = new Color32(255, 255, 255, (byte)(a * 255));
            }
        tex.SetPixels32(pixels);
        tex.Apply(false, true);
        return tex;
    }
}
