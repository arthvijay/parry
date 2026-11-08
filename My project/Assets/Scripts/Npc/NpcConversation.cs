using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// The talking part of an NPC in the speed date. There is no push-to-talk: the
/// microphone is always open through <see cref="FullDuplexStreamClient"/>, and this
/// component is where a character's streamed voice lands. It registers the NPC's
/// <see cref="StreamingAudioPlayer"/> under its npc id, flushes it the instant the learner
/// barges in, keeps the latest line for captions, and tells the server who the learner
/// is facing: walking up to the host opens the host's conversation and greeting.
/// </summary>
[RequireComponent(typeof(NpcSpeaker), typeof(NpcInteractable))]
public class NpcConversation : MonoBehaviour
{
    [Header("Character")]
    [Tooltip("npc_id on the stream: date_npc for the date, host for the host.")]
    public string npcId = "";
    [Tooltip("Shown as the caption of the greeting before the live line arrives.")]
    public string greeting = "";
    [Tooltip("Open this character's conversation when the player first walks up (the host).")]
    public bool greetOnApproach;

    /// <summary>Short state for the interact prompt; empty when idle.</summary>
    public string Status { get; private set; } = "";
    public bool Busy => speaker != null && speaker.IsSpeaking;
    public bool IsRecording => false;
    public bool IsConfigured => FullDuplexStreamClient.Instance != null && FullDuplexStreamClient.Instance.Ready;
    public string SessionId => npcId;

    public class Exchange
    {
        public string heard;
        public string reply;
        public float time;
    }

    /// <summary>The latest line this character said (or is saying).</summary>
    public Exchange Last { get; private set; }
    public event Action<Exchange> Replied;
    /// <summary>Fired once, when the greeting has been said (see <see cref="NpcMove.TriggerGreet"/>).</summary>
    public event Action Greeted;
    /// <summary>Scene actions for NpcSchedule's "action" trigger (none on the speed date stream yet).</summary>
    public event Action<string> Acted;

    NpcSpeaker speaker;
    NpcInteractable interactable;
    StreamingAudioPlayer player;
    FullDuplexStreamClient client;
    bool approached;
    bool greetingTurn;
    bool greetedFired;

    void Awake()
    {
        speaker = GetComponent<NpcSpeaker>();
        interactable = GetComponent<NpcInteractable>();
        player = GetComponent<StreamingAudioPlayer>();
        if (player == null)
            player = gameObject.AddComponent<StreamingAudioPlayer>();
    }

    void Start() => Bind();

    void Bind()
    {
        if (client != null || FullDuplexStreamClient.Instance == null || string.IsNullOrEmpty(npcId))
            return;
        client = FullDuplexStreamClient.Instance;
        client.Register(npcId, player);
        client.Message += OnMessage;
        client.AudioStarted += OnAudioStarted;
        client.AudioEnded += OnAudioEnded;
        client.AudioCleared += OnCleared;
    }

    void OnDestroy()
    {
        if (client == null)
            return;
        client.Unregister(npcId, player);
        client.Message -= OnMessage;
        client.AudioStarted -= OnAudioStarted;
        client.AudioEnded -= OnAudioEnded;
        client.AudioCleared -= OnCleared;
    }

    /// <summary>Rebind under a new id, e.g. when the cast is applied after spawn.</summary>
    public void SetId(string id)
    {
        if (id == npcId)
            return;
        OnDestroy();
        client = null;
        npcId = id;
        Bind();
    }

    void Update()
    {
        Bind();
        if (client == null || !client.Ready)
        {
            Status = client == null ? "" : client.Connected ? "Connecting…" : "Server unreachable";
            return;
        }
        if (greetOnApproach && !approached && interactable.PlayerInRange && !client.DateRunning)
        {
            approached = true;
            if (!string.IsNullOrEmpty(greeting))
                Last = new Exchange { reply = greeting, time = Time.time };
            client.Focus(npcId);
        }
        Status = Busy ? $"{interactable.displayName} is speaking…" : "";
    }

    void OnMessage(string type, Dictionary<string, object> msg)
    {
        if (type != "transcript" || msg.Str("speaker") != "npc" || msg.Str("npc_id") != npcId)
            return;
        Last = new Exchange { reply = msg.Str("text"), time = Time.time };
        if (msg.Bool("is_final"))
            Replied?.Invoke(Last);
    }

    void OnAudioStarted(string npc, int turn)
    {
        if (npc != npcId)
            return;
        greetingTurn = greetOnApproach && !greetedFired;
    }

    void OnAudioEnded(string npc)
    {
        if (npc != npcId || !greetingTurn || greetedFired)
            return;
        greetedFired = true;
        greetingTurn = false;
        Greeted?.Invoke();
    }

    void OnCleared(string npc)
    {
        if (npc == npcId)
            player.Flush();
    }

    /// <summary>For NpcSchedule's "action" moves and tests.</summary>
    public void RaiseAction(string action) => Acted?.Invoke(action);
}
