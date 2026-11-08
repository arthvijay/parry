using System.IO;
using GLTFast;
using UnityEngine;

/// <summary>
/// Loads the WorldLabs collider mesh (the *_collider.glb exported alongside the
/// .spz splat) from StreamingAssets and turns it into MeshColliders.
/// Attach to the same GameObject as the GaussianSplatRenderer so the collider
/// inherits its transform.
/// </summary>
public class WorldColliderLoader : MonoBehaviour
{
    [Tooltip("Path relative to StreamingAssets.")]
    public string colliderFile = "Worlds/rustic_kitchen_with_natural_light_collider.glb";

    [Tooltip("glTF is right-handed and glTFast converts by negating X on import, but the splat " +
             "importer reads .spz positions raw. Mirror X back so the two line up. (Mirroring Z " +
             "instead leaves the collider rotated 180 degrees about Y.)")]
    public bool mirrorX = true;

    [Tooltip("Render the collider mesh so you can check it lines up with the splat.")]
    public bool showColliderMesh = false;

    // Player controllers frozen until the collider exists, so nobody falls
    // through the floor while the glb is still loading.
    FirstPersonController[] heldPlayers;

    void Awake()
    {
        heldPlayers = FindObjectsByType<FirstPersonController>(FindObjectsSortMode.None);
        foreach (var p in heldPlayers)
            p.enabled = false;
    }

    async void Start()
    {
        try
        {
            await LoadCollider();
        }
        finally
        {
            foreach (var p in heldPlayers)
                if (p != null) p.enabled = true;
        }
    }

    async System.Threading.Tasks.Task LoadCollider()
    {
        string path = Path.Combine(Application.streamingAssetsPath, colliderFile);
        if (!File.Exists(path))
        {
            Debug.LogError($"WorldColliderLoader: collider file not found at {path}");
            return;
        }

        var gltf = new GltfImport();
        if (!await gltf.LoadFile(path))
        {
            Debug.LogError($"WorldColliderLoader: failed to load {path}");
            return;
        }

        var root = new GameObject("Collider");
        root.transform.SetParent(transform, false);

        if (!await gltf.InstantiateMainSceneAsync(root.transform))
        {
            Debug.LogError("WorldColliderLoader: failed to instantiate collider scene");
            return;
        }

        foreach (var filter in root.GetComponentsInChildren<MeshFilter>())
        {
            var mesh = filter.sharedMesh;
            if (mesh == null)
                continue;

            PrepareMesh(mesh);

            filter.gameObject.AddComponent<MeshCollider>().sharedMesh = mesh;

            var renderer = filter.GetComponent<MeshRenderer>();
            if (renderer != null)
                renderer.enabled = showColliderMesh;
        }

        // Physics needs a step to register the new colliders before the
        // CharacterController's first Move, otherwise it can still fall through.
        Physics.SyncTransforms();
    }

    void PrepareMesh(Mesh mesh)
    {
        if (mirrorX)
        {
            var verts = mesh.vertices;
            for (int i = 0; i < verts.Length; i++)
                verts[i].x = -verts[i].x;
            mesh.vertices = verts;
        }

        // CharacterController only collides with the front face of triangles,
        // and a generated collider mesh (mirrored, then negatively scaled by the
        // parent) has no reliable winding. Add a reversed copy of every triangle
        // so the collider is double-sided and winding stops mattering.
        mesh.indexFormat = UnityEngine.Rendering.IndexFormat.UInt32;
        for (int s = 0; s < mesh.subMeshCount; s++)
        {
            var tris = mesh.GetTriangles(s);
            var both = new int[tris.Length * 2];
            tris.CopyTo(both, 0);
            for (int i = 0; i < tris.Length; i += 3)
            {
                both[tris.Length + i] = tris[i];
                both[tris.Length + i + 1] = tris[i + 2];
                both[tris.Length + i + 2] = tris[i + 1];
            }
            mesh.SetTriangles(both, s);
        }

        mesh.RecalculateBounds();
    }
}
