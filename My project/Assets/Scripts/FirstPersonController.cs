using System.Collections;
using UnityEngine;
using UnityEngine.InputSystem;

/// <summary>
/// First-person controller reading the new Input System devices directly.
/// No Input Actions asset, no PlayerInput component, no legacy Input Manager.
/// Attach to a GameObject with a CharacterController; the camera must be a
/// CHILD of it. Yaw goes on the body, pitch on the camera.
/// </summary>
[RequireComponent(typeof(CharacterController))]
public class FirstPersonController : MonoBehaviour
{
    [Header("References")]
    [Tooltip("Child camera transform. Auto-finds Camera.main if left empty.")]
    public Transform cameraTransform;

    [Header("Movement")]
    public float walkSpeed = 2.0f;
    public float runSpeed = 4.0f;
    public float gravity = -9.81f;

    [Header("Look")]
    [Tooltip("Degrees per pixel of mouse movement. Start around 0.1.")]
    public float mouseSensitivity = 0.1f;
    public float pitchMin = -85f;
    public float pitchMax = 85f;

    [Header("Eye level")]
    [Tooltip("Once the NPC avatars are posed, raise or lower the camera to this bone's height on the " +
             "tallest standing character, so the player meets them eye to eye instead of staring at a " +
             "chest. Empty = leave the camera where the scene puts it.")]
    public string eyeLevelBone = "Bip01 LEye";
    [Tooltip("Seconds after the avatars load to wait for their idle mocap and feet grounding to settle before measuring.")]
    public float eyeLevelSettleSeconds = 1.5f;

    [Header("Debug")]
    public bool logInput = false;

    /// <summary>Cleared by <see cref="PlayerSeating"/> while sitting: look still works, WASD/gravity don't.</summary>
    public bool CanMove { get; set; } = true;

    CharacterController controller;
    float pitch;
    float verticalVelocity;

    void Awake()
    {
        controller = GetComponent<CharacterController>();

        if (cameraTransform == null && Camera.main != null)
            cameraTransform = Camera.main.transform;

        if (cameraTransform == null)
            Debug.LogError("FirstPersonController: no camera assigned and no Main Camera found.");
        else if (cameraTransform.parent != transform)
            Debug.LogWarning("FirstPersonController: camera should be a direct child of the player.");
    }

    void Start()
    {
        LockCursor(true);
        if (!string.IsNullOrEmpty(eyeLevelBone) && cameraTransform != null)
            StartCoroutine(MatchEyeLevel());
    }

    /// <summary>
    /// The avatars are 0.7 scale and the player 0.75, so nothing in the scene says how
    /// tall anyone really ends up; measure it. Waits for every NPC avatar to load and
    /// settle (mocap pose, feet grounding, our own drop onto the floor), then puts the
    /// camera at the height of the highest eye bone found: a seated character's eyes
    /// are lower, the standing ones are the reference.
    /// </summary>
    IEnumerator MatchEyeLevel()
    {
        var loaders = FindObjectsByType<NpcAvatarLoader>(FindObjectsSortMode.None);
        float giveUp = Time.time + 10f;
        while (Time.time < giveUp && (loaders.Length == 0 || System.Array.Exists(loaders, l => l.AvatarRoot == null)))
        {
            yield return null;
            loaders = FindObjectsByType<NpcAvatarLoader>(FindObjectsSortMode.None);
        }
        yield return new WaitForSeconds(eyeLevelSettleSeconds);

        float eyeY = float.MinValue;
        foreach (var loader in loaders)
        {
            var eye = loader.FindBone(eyeLevelBone);
            if (eye != null)
                eyeY = Mathf.Max(eyeY, eye.position.y);
        }
        if (eyeY == float.MinValue)
        {
            Debug.LogWarning($"FirstPersonController: no NPC bone '{eyeLevelBone}' to match eye level to; camera left as is.");
            yield break;
        }

        // Camera is a child, so convert the world height into our (scaled) local space
        // and keep it inside the capsule.
        float localY = (eyeY - transform.position.y) / Mathf.Max(transform.lossyScale.y, 0.0001f);
        localY = Mathf.Clamp(localY, 0f, controller.height * 0.5f);
        var local = cameraTransform.localPosition;
        Debug.Log($"FirstPersonController: eye level {eyeY:F3} -> camera local y {local.y:F3} -> {localY:F3}");
        local.y = localY;
        cameraTransform.localPosition = local;
    }

    void Update()
    {
        var keyboard = Keyboard.current;
        var mouse = Mouse.current;

        if (keyboard == null || mouse == null)
        {
            Debug.LogWarning("FirstPersonController: keyboard or mouse device not found.");
            return;
        }

        // Escape releases the cursor, click recaptures it.
        if (keyboard.escapeKey.wasPressedThisFrame)
            LockCursor(false);
        else if (mouse.leftButton.wasPressedThisFrame && Cursor.lockState != CursorLockMode.Locked)
            LockCursor(true);

        if (Cursor.lockState != CursorLockMode.Locked)
            return;

        Look(mouse);
        if (CanMove)
            Move(keyboard);
    }

    void Look(Mouse mouse)
    {
        // delta is raw pixels moved this frame, not a normalised axis.
        Vector2 delta = mouse.delta.ReadValue();

        if (logInput)
            Debug.Log($"mouse delta = {delta}");

        float yaw = delta.x * mouseSensitivity;
        float pitchDelta = delta.y * mouseSensitivity;

        // Yaw on the body so movement follows the view.
        transform.Rotate(Vector3.up * yaw);

        // Pitch only on the camera, clamped.
        pitch = Mathf.Clamp(pitch - pitchDelta, pitchMin, pitchMax);
        cameraTransform.localEulerAngles = new Vector3(pitch, 0f, 0f);
    }

    void Move(Keyboard keyboard)
    {
        float x = 0f;
        float z = 0f;

        if (keyboard.aKey.isPressed) x -= 1f;
        if (keyboard.dKey.isPressed) x += 1f;
        if (keyboard.sKey.isPressed) z -= 1f;
        if (keyboard.wKey.isPressed) z += 1f;

        if (logInput && (x != 0f || z != 0f))
            Debug.Log($"move input = ({x}, {z})");

        Vector3 input = Vector3.ClampMagnitude(new Vector3(x, 0f, z), 1f);
        Vector3 direction = transform.TransformDirection(input);

        float speed = keyboard.leftShiftKey.isPressed ? runSpeed : walkSpeed;

        // Small downward bias keeps isGrounded reliable on uneven collider meshes.
        if (controller.isGrounded && verticalVelocity < 0f)
            verticalVelocity = -2f;

        verticalVelocity += gravity * Time.deltaTime;

        Vector3 velocity = direction * speed;
        velocity.y = verticalVelocity;

        controller.Move(velocity * Time.deltaTime);
    }

    void LockCursor(bool locked)
    {
        Cursor.lockState = locked ? CursorLockMode.Locked : CursorLockMode.None;
        Cursor.visible = !locked;
    }
}
