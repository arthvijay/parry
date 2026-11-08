using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.InputSystem;

/// <summary>
/// Proximity interaction: when the player is close and roughly facing the NPC,
/// shows a prompt and fires <see cref="Interacted"/> on E. Hook the conversation
/// loop (mic -> STT -> LLM -> ElevenLabs -> NpcSpeaker.Speak) to that event.
/// Only one NPC is <see cref="Focused"/> at a time: with two in reach, the one the
/// player is looking at most directly wins, except that an NPC mid-turn keeps the
/// player's attention until the turn is over.
/// </summary>
public class NpcInteractable : MonoBehaviour
{
    static readonly List<NpcInteractable> all = new();
    static int arbitratedFrame = -1;

    /// <summary>The one NPC the player can talk to right now, or null.</summary>
    public static NpcInteractable Focused { get; private set; }

    [Tooltip("Shown in the prompt, e.g. 'Press E to talk to Sofía'.")]
    public string displayName = "Sofía";
    public float interactRange = 2.5f;
    [Tooltip("Player must be looking within this many degrees of the NPC.")]
    public float facingAngle = 45f;
    public Key interactKey = Key.E;

    [Tooltip("Until a conversation backend is connected, E plays a test line so " +
             "you can see the lip-sync working.")]
    public bool testSpeechOnInteract = true;

    /// <summary>Fired when the player presses the interact key while in range.</summary>
    public event Action Interacted;

    public bool PlayerInRange { get; private set; }

    Transform playerEyes;
    NpcSpeaker speaker;
    NpcConversation conversation;

    void Start()
    {
        speaker = GetComponent<NpcSpeaker>();
        conversation = GetComponent<NpcConversation>();

        var fpc = FindFirstObjectByType<FirstPersonController>();
        if (fpc != null)
            playerEyes = fpc.cameraTransform != null ? fpc.cameraTransform : fpc.transform;
    }

    void OnEnable() => all.Add(this);

    void OnDisable()
    {
        all.Remove(this);
        if (Focused == this)
            Focused = null;
    }

    void Update()
    {
        Arbitrate();
        PlayerInRange = Focused == this;
        if (!PlayerInRange)
            return;

        var keyboard = Keyboard.current;
        if (keyboard != null && keyboard[interactKey].wasPressedThisFrame)
        {
            Interacted?.Invoke();
            // With a real conversation backend the key is push-to-talk instead.
            bool live = conversation != null && conversation.IsConfigured;
            if (testSpeechOnInteract && !live && speaker != null && !speaker.IsSpeaking)
                speaker.SpeakTest();
        }
    }

    /// <summary>Pick this frame's <see cref="Focused"/> NPC once, whichever instance updates first.</summary>
    static void Arbitrate()
    {
        if (arbitratedFrame == Time.frameCount)
            return;
        arbitratedFrame = Time.frameCount;

        // Mid-turn (recording, waiting on the server, speaking) the current NPC keeps
        // the floor as long as the player is still roughly with them.
        if (Focused != null && Focused.MidTurn && Focused.CheckInRange(out _))
            return;

        NpcInteractable best = null;
        float bestAngle = float.PositiveInfinity;
        foreach (var npc in all)
            if (npc.CheckInRange(out float angle) && angle < bestAngle)
            {
                best = npc;
                bestAngle = angle;
            }
        Focused = best;
    }

    bool MidTurn => conversation != null && (conversation.Busy || conversation.IsRecording);

    bool CheckInRange(out float angle)
    {
        angle = float.PositiveInfinity;
        if (playerEyes == null)
            return false;

        // Aim at chest height rather than the feet.
        Vector3 target = transform.position + Vector3.up * 1.4f;
        Vector3 toNpc = target - playerEyes.position;
        if (toNpc.magnitude > interactRange)
            return false;

        angle = Vector3.Angle(playerEyes.forward, toNpc);
        return angle <= facingAngle;
    }

    void OnGUI()
    {
        if (!PlayerInRange || Cursor.lockState != CursorLockMode.Locked)
            return;
        var client = FullDuplexStreamClient.Instance;
        if (client != null && client.DateRunning)
            return; // the date HUD has the floor

        string text;
        if (conversation != null && !string.IsNullOrEmpty(conversation.Status))
            text = conversation.Status;
        else if (speaker != null && speaker.IsSpeaking)
            text = $"{displayName} is speaking…";
        else if (conversation != null && conversation.IsConfigured)
            text = $"🎙  Just talk to {displayName}";
        else
            text = $"{interactKey}  talk to {displayName}";

        var m = GlassUI.Begin();
        float w = GlassUI.TextWidth(text, 15) + 40f;
        var r = new Rect((GlassUI.Width - w) / 2f, GlassUI.Height * 0.8f, w, 36f);
        GlassUI.Panel(r);
        GlassUI.Label(r, text, 15, Color.white, FontStyle.Normal, TextAnchor.MiddleCenter);
        GlassUI.End(m);
    }
}
