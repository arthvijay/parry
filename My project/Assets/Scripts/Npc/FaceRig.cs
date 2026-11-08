using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// An avatar's face addressed by ARKit blendshape names. Rocketbox calls them
/// "AK_44_MouthSmileLeft"; MediaPipe and the date's body language call them
/// "mouthSmileLeft". The prefix is stripped once, so weights can be set by the ARKit name.
/// </summary>
public class FaceRig
{
    readonly Dictionary<string, List<(SkinnedMeshRenderer smr, int index)>> shapes = new(StringComparer.OrdinalIgnoreCase);

    public FaceRig(Transform root)
    {
        if (root == null)
            return;
        foreach (var smr in root.GetComponentsInChildren<SkinnedMeshRenderer>(true))
        {
            var mesh = smr.sharedMesh;
            if (mesh == null)
                continue;
            for (int i = 0; i < mesh.blendShapeCount; i++)
            {
                string key = Key(mesh.GetBlendShapeName(i));
                if (!shapes.TryGetValue(key, out var list))
                    shapes[key] = list = new List<(SkinnedMeshRenderer, int)>();
                list.Add((smr, i));
            }
        }
    }

    /// <summary>"AK_44_MouthSmileLeft" → "MouthSmileLeft"; anything else unchanged.</summary>
    static string Key(string name)
    {
        if (name.Length > 6 && name.StartsWith("AK_", StringComparison.OrdinalIgnoreCase) && char.IsDigit(name[3]))
        {
            int cut = name.IndexOf('_', 3);
            if (cut > 0 && cut + 1 < name.Length)
                return name.Substring(cut + 1);
        }
        return name;
    }

    public bool Empty => shapes.Count == 0;
    public bool Has(string arkit) => shapes.ContainsKey(arkit);

    /// <summary>Weight 0-100 on every mesh carrying the shape.</summary>
    public void Set(string arkit, float weight)
    {
        if (!shapes.TryGetValue(arkit, out var list))
            return;
        foreach (var (smr, index) in list)
            if (smr != null)
                smr.SetBlendShapeWeight(index, Mathf.Clamp(weight, 0f, 100f));
    }
}
