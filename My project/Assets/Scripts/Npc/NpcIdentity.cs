using System;
using UnityEngine;

/// <summary>Links a spawned NPC back to its npcs.json entry.</summary>
public class NpcIdentity : MonoBehaviour
{
    public string id;
    [NonSerialized] public NpcDefinition definition;
}
