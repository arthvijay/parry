using UnityEngine;

/// <summary>
/// Small checklist in the top-right corner showing the quests from
/// <see cref="QuestManager"/>. Same IMGUI approach as the talk prompt, so it
/// needs no Canvas or scene wiring beyond this component.
/// </summary>
[RequireComponent(typeof(QuestManager))]
public class QuestHud : MonoBehaviour
{
    public int fontSize = 14;
    public float margin = 16f;
    public float padding = 10f;
    public float lineSpacing = 6f;
    public float boxSize = 12f;
    [Range(0f, 1f)] public float backgroundAlpha = 0.45f;
    public Color doneColor = new(0.55f, 0.85f, 0.55f);
    public Color todoColor = Color.white;

    QuestManager quests;
    GUIStyle titleStyle;
    GUIStyle itemStyle;

    void Awake()
    {
        quests = GetComponent<QuestManager>();
    }

    void OnGUI()
    {
        var list = quests.Quests;
        if (list == null || list.quests.Length == 0)
            return;

        if (itemStyle == null)
        {
            itemStyle = new GUIStyle(GUI.skin.label) { fontSize = fontSize, alignment = TextAnchor.MiddleLeft, wordWrap = false };
            itemStyle.normal.textColor = Color.white;
            titleStyle = new GUIStyle(itemStyle) { fontStyle = FontStyle.Bold };
        }

        // Measure so the panel hugs its contents.
        bool hasTitle = !string.IsNullOrEmpty(list.title);
        float lineHeight = itemStyle.CalcSize(new GUIContent("Ag")).y;
        float textWidth = hasTitle ? titleStyle.CalcSize(new GUIContent(list.title)).x : 0f;
        foreach (var q in list.quests)
            textWidth = Mathf.Max(textWidth, itemStyle.CalcSize(new GUIContent(q.text)).x);

        float indent = boxSize + 8f;
        int lines = list.quests.Length + (hasTitle ? 1 : 0);
        float width = indent + textWidth + padding * 2f;
        float height = lines * lineHeight + (lines - 1) * lineSpacing + padding * 2f;
        var panel = new Rect(Screen.width - width - margin, margin, width, height);

        var prevColor = GUI.color;
        GUI.color = new Color(0f, 0f, 0f, backgroundAlpha);
        GUI.DrawTexture(panel, Texture2D.whiteTexture);
        GUI.color = prevColor;

        float y = panel.y + padding;
        if (hasTitle)
        {
            GUI.Label(new Rect(panel.x + padding, y, width, lineHeight), list.title, titleStyle);
            y += lineHeight + lineSpacing;
        }

        foreach (var q in list.quests)
        {
            bool done = q.IsDone;
            var color = done ? doneColor : todoColor;

            // Checkbox: light outline, filled when done.
            var box = new Rect(panel.x + padding, y + (lineHeight - boxSize) / 2f, boxSize, boxSize);
            GUI.color = color;
            GUI.DrawTexture(box, Texture2D.whiteTexture);
            if (!done)
            {
                GUI.color = new Color(0f, 0f, 0f, 0.8f);
                GUI.DrawTexture(new Rect(box.x + 1.5f, box.y + 1.5f, boxSize - 3f, boxSize - 3f), Texture2D.whiteTexture);
            }
            GUI.color = prevColor;

            itemStyle.normal.textColor = done ? doneColor : todoColor;
            var textRect = new Rect(panel.x + padding + indent, y, textWidth, lineHeight);
            GUI.Label(textRect, q.text, itemStyle);
            if (done)
            {
                // Strike-through.
                float w = itemStyle.CalcSize(new GUIContent(q.text)).x;
                GUI.color = doneColor;
                GUI.DrawTexture(new Rect(textRect.x, y + lineHeight / 2f, w, 1f), Texture2D.whiteTexture);
                GUI.color = prevColor;
            }

            y += lineHeight + lineSpacing;
        }
    }
}
