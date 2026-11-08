using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

/// <summary>
/// A small JSON reader and writer for the stream protocol. <see cref="UnityEngine.JsonUtility"/>
/// cannot read dictionaries (blendshape weights, face contours) or dispatch on a "type"
/// field, so live messages are parsed here into Dictionary/List/string/double/bool/null.
/// Well-shaped payloads (the date scenario, the verdict) still go through JsonUtility.
/// </summary>
public static class Json
{
    public static object Parse(string text)
    {
        if (string.IsNullOrEmpty(text))
            return null;
        int i = 0;
        try
        {
            var value = ReadValue(text, ref i);
            return value;
        }
        catch (Exception)
        {
            return null;
        }
    }

    public static Dictionary<string, object> Obj(string text) => Parse(text) as Dictionary<string, object>;

    // ---- typed access ------------------------------------------------------------

    public static string Str(this Dictionary<string, object> d, string key, string fallback = "")
        => d != null && d.TryGetValue(key, out var v) && v is string s ? s : fallback;

    public static double Num(this Dictionary<string, object> d, string key, double fallback = 0)
        => d != null && d.TryGetValue(key, out var v) && v is double n ? n : fallback;

    public static float F(this Dictionary<string, object> d, string key, float fallback = 0f)
        => (float)d.Num(key, fallback);

    public static int Int(this Dictionary<string, object> d, string key, int fallback = 0)
        => (int)Math.Round(d.Num(key, fallback));

    public static bool Bool(this Dictionary<string, object> d, string key, bool fallback = false)
        => d != null && d.TryGetValue(key, out var v) && v is bool b ? b : fallback;

    public static Dictionary<string, object> Get(this Dictionary<string, object> d, string key)
        => d != null && d.TryGetValue(key, out var v) ? v as Dictionary<string, object> : null;

    public static List<object> List(this Dictionary<string, object> d, string key)
        => d != null && d.TryGetValue(key, out var v) ? v as List<object> : null;

    public static bool Has(this Dictionary<string, object> d, string key)
        => d != null && d.ContainsKey(key) && d[key] != null;

    // ---- writing -----------------------------------------------------------------

    public static string Write(object value)
    {
        var sb = new StringBuilder();
        WriteValue(sb, value);
        return sb.ToString();
    }

    static void WriteValue(StringBuilder sb, object value)
    {
        switch (value)
        {
            case null:
                sb.Append("null");
                break;
            case string s:
                WriteString(sb, s);
                break;
            case bool b:
                sb.Append(b ? "true" : "false");
                break;
            case float f:
                sb.Append(f.ToString("R", CultureInfo.InvariantCulture));
                break;
            case double d:
                sb.Append(d.ToString("R", CultureInfo.InvariantCulture));
                break;
            case int n:
                sb.Append(n.ToString(CultureInfo.InvariantCulture));
                break;
            case long l:
                sb.Append(l.ToString(CultureInfo.InvariantCulture));
                break;
            case IDictionary<string, object> map:
                sb.Append('{');
                bool first = true;
                foreach (var pair in map)
                {
                    if (!first)
                        sb.Append(',');
                    first = false;
                    WriteString(sb, pair.Key);
                    sb.Append(':');
                    WriteValue(sb, pair.Value);
                }
                sb.Append('}');
                break;
            case System.Collections.IEnumerable list:
                sb.Append('[');
                bool firstItem = true;
                foreach (var item in list)
                {
                    if (!firstItem)
                        sb.Append(',');
                    firstItem = false;
                    WriteValue(sb, item);
                }
                sb.Append(']');
                break;
            default:
                WriteString(sb, value.ToString());
                break;
        }
    }

    static void WriteString(StringBuilder sb, string s)
    {
        sb.Append('"');
        foreach (char c in s)
        {
            switch (c)
            {
                case '"': sb.Append("\\\""); break;
                case '\\': sb.Append("\\\\"); break;
                case '\n': sb.Append("\\n"); break;
                case '\r': sb.Append("\\r"); break;
                case '\t': sb.Append("\\t"); break;
                default:
                    if (c < 0x20)
                        sb.Append("\\u").Append(((int)c).ToString("x4"));
                    else
                        sb.Append(c);
                    break;
            }
        }
        sb.Append('"');
    }

    // ---- reading -----------------------------------------------------------------

    static void SkipSpace(string s, ref int i)
    {
        while (i < s.Length && char.IsWhiteSpace(s[i]))
            i++;
    }

    static object ReadValue(string s, ref int i)
    {
        SkipSpace(s, ref i);
        if (i >= s.Length)
            throw new FormatException("unexpected end");
        char c = s[i];
        switch (c)
        {
            case '{': return ReadObject(s, ref i);
            case '[': return ReadArray(s, ref i);
            case '"': return ReadString(s, ref i);
            case 't': Expect(s, ref i, "true"); return true;
            case 'f': Expect(s, ref i, "false"); return false;
            case 'n': Expect(s, ref i, "null"); return null;
            default: return ReadNumber(s, ref i);
        }
    }

    static void Expect(string s, ref int i, string word)
    {
        if (string.CompareOrdinal(s, i, word, 0, word.Length) != 0)
            throw new FormatException("bad literal");
        i += word.Length;
    }

    static Dictionary<string, object> ReadObject(string s, ref int i)
    {
        var map = new Dictionary<string, object>();
        i++; // {
        SkipSpace(s, ref i);
        if (i < s.Length && s[i] == '}')
        {
            i++;
            return map;
        }
        while (true)
        {
            SkipSpace(s, ref i);
            string key = ReadString(s, ref i);
            SkipSpace(s, ref i);
            if (s[i] != ':')
                throw new FormatException("expected :");
            i++;
            map[key] = ReadValue(s, ref i);
            SkipSpace(s, ref i);
            if (s[i] == ',')
            {
                i++;
                continue;
            }
            if (s[i] == '}')
            {
                i++;
                return map;
            }
            throw new FormatException("expected , or }");
        }
    }

    static List<object> ReadArray(string s, ref int i)
    {
        var list = new List<object>();
        i++; // [
        SkipSpace(s, ref i);
        if (i < s.Length && s[i] == ']')
        {
            i++;
            return list;
        }
        while (true)
        {
            list.Add(ReadValue(s, ref i));
            SkipSpace(s, ref i);
            if (s[i] == ',')
            {
                i++;
                continue;
            }
            if (s[i] == ']')
            {
                i++;
                return list;
            }
            throw new FormatException("expected , or ]");
        }
    }

    static string ReadString(string s, ref int i)
    {
        if (s[i] != '"')
            throw new FormatException("expected string");
        i++;
        var sb = new StringBuilder();
        while (i < s.Length)
        {
            char c = s[i++];
            if (c == '"')
                return sb.ToString();
            if (c != '\\')
            {
                sb.Append(c);
                continue;
            }
            char e = s[i++];
            switch (e)
            {
                case '"': sb.Append('"'); break;
                case '\\': sb.Append('\\'); break;
                case '/': sb.Append('/'); break;
                case 'b': sb.Append('\b'); break;
                case 'f': sb.Append('\f'); break;
                case 'n': sb.Append('\n'); break;
                case 'r': sb.Append('\r'); break;
                case 't': sb.Append('\t'); break;
                case 'u':
                    sb.Append((char)int.Parse(s.Substring(i, 4), NumberStyles.HexNumber, CultureInfo.InvariantCulture));
                    i += 4;
                    break;
                default: sb.Append(e); break;
            }
        }
        throw new FormatException("unterminated string");
    }

    static double ReadNumber(string s, ref int i)
    {
        int start = i;
        while (i < s.Length && "+-0123456789.eE".IndexOf(s[i]) >= 0)
            i++;
        if (i == start)
            throw new FormatException("bad number");
        return double.Parse(s.Substring(start, i - start), NumberStyles.Float, CultureInfo.InvariantCulture);
    }
}
