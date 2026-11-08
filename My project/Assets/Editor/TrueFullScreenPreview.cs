using UnityEditor;
using UnityEngine;
using System;
using System.Reflection;

public class TrueFullscreenPreview : EditorWindow
{
    private static EditorWindow fullscreenWindow;

    [MenuItem("Tools/Toggle True Fullscreen Game View %&f")] // Shortcut: Ctrl + Alt + F
    public static void ToggleFullscreen()
    {
        // If the window is already open, close it
        if (fullscreenWindow != null)
        {
            fullscreenWindow.Close();
            fullscreenWindow = null;
            return;
        }

        // Use reflection to get the internal GameView type
        Type gameViewType = Type.GetType("UnityEditor.GameView,UnityEditor");
        if (gameViewType == null)
        {
            Debug.LogError("Could not find UnityEditor.GameView type.");
            return;
        }

        // Create an undecorated editor window
        fullscreenWindow = CreateInstance<TrueFullscreenPreview>();
        
        // Hide the window title bar and make it an overlapping borderless window
        fullscreenWindow.titleContent = new GUIContent("Game Preview");
        
        // Set the window to cover the primary screen bounds
        fullscreenWindow.position = new Rect(0, 0, Screen.currentResolution.width, Screen.currentResolution.height);
        
        // Add the GameView as a child view to this window
        var childGameView = CreateInstance(gameViewType) as EditorWindow;
        
        // Try to hide the internal toolbar inside the game view via reflection
        try
        {
            PropertyInfo showToolbarProp = gameViewType.GetProperty("showToolbar", BindingFlags.Instance | BindingFlags.NonPublic);
            if (showToolbarProp != null)
            {
                showToolbarProp.SetValue(childGameView, false);
            }
        }
        catch (Exception) 
        {
            // Fallback for versions of Unity where showToolbar reflects differently
        }

        // Show the window as a borderless popup utility
        fullscreenWindow.ShowPopup();
        
        // Dock or focus the game view inside our popup container
        if (childGameView != null)
        {
            childGameView.ShowAsDropDown(new Rect(0,0,0,0), new Vector2(Screen.currentResolution.width, Screen.currentResolution.height));
        }
    }

    private void OnGUI()
    {
        // Fallback info if the dropdown fails to render over it
        GUILayout.Label("Press Ctrl + Alt + F (or Cmd + Option + F on Mac) to exit fullscreen.", EditorStyles.boldLabel);
    }
}

