#!/usr/bin/env python3
"""
Generate a walkable collider mesh (.glb) from a Gaussian splat .spz file.

WorldLabs ships a *_collider.glb next to each .spz, but when that's missing this
builds an approximation: splat centres are voxelised into an occupancy grid,
holes are closed, the surface is extracted with marching cubes, floaters are
dropped and the result is decimated. The output uses the raw .spz coordinate
frame, matching WorldColliderLoader's mirrorX expectation.

Usage:
    python tools/spz_to_collider.py in.spz out_collider.glb [--voxel 0.05] ...

Deps: numpy scipy scikit-image trimesh fast_simplification
"""
import argparse
import gzip
import struct

import numpy as np
import trimesh
from scipy import ndimage
from scipy.spatial import cKDTree
from skimage import measure


def read_spz(path):
    """Returns (pos[N,3], alpha[N], scale[N,3]) from a v2 .spz. Mirrors SPZFileReader.cs."""
    with gzip.open(path, "rb") as f:
        data = f.read()
    magic, version, n, packed = struct.unpack("<IIII", data[:16])
    if magic != 0x5053474E or version != 2:
        raise ValueError(f"not a v2 spz: magic={magic:#x} version={version}")
    frac_bits = (packed >> 8) & 0xFF

    off = 16
    pos_b = np.frombuffer(data, np.uint8, n * 9, off).reshape(n, 3, 3).astype(np.int32)
    off += n * 9
    alpha = np.frombuffer(data, np.uint8, n, off).astype(np.float32) / 255
    off += n
    off += n * 3  # rgb, unused
    scale_b = np.frombuffer(data, np.uint8, n * 3, off).reshape(n, 3).astype(np.float32)

    fx = pos_b[..., 0] | (pos_b[..., 1] << 8) | (pos_b[..., 2] << 16)
    fx = np.where(fx & 0x800000, fx - 0x1000000, fx)  # sign-extend 24-bit
    pos = fx.astype(np.float32) / (1 << frac_bits)
    scale = np.exp(scale_b / 16 - 10)
    return pos, alpha, scale


def snap_to_splats(mesh, pos, radius, max_move):
    """
    Marching cubes leaves the surface ~half a voxel outside the splats it was
    built from, which is enough for the player to visibly hover. Slide each
    vertex along its normal to the mean of the nearby splat centres. Done after
    decimation, and without re-merging vertices, so the two sides of a
    one-voxel-thick floor can collapse onto the same plane without the faces
    being dropped as duplicates.
    """
    tree = cKDTree(pos)
    verts = mesh.vertices.copy()
    normals = mesh.vertex_normals
    neighbours = tree.query_ball_point(verts, radius, workers=-1)
    for i, nb in enumerate(neighbours):
        if not nb:
            continue
        offset = np.dot(pos[nb] - verts[i], normals[i]).mean()
        verts[i] += normals[i] * np.clip(offset, -max_move, max_move)
    return trimesh.Trimesh(verts, mesh.faces, process=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spz")
    ap.add_argument("out")
    ap.add_argument("--voxel", type=float, default=0.05, help="voxel size in splat units")
    ap.add_argument("--shrink", type=float, default=0.4,
                    help="pull the surface inward by this many voxels so it sits on the splat centres "
                         "instead of the outer voxel faces (0 = raw marching-cubes shell)")
    ap.add_argument("--snap", type=float, default=1.5,
                    help="after decimation, slide vertices onto the mean of splat centres within this many "
                         "voxels (0 = off)")
    ap.add_argument("--height", type=float, default=8.0,
                    help="only mesh this far above the ground (splat units); ground is the max raw Y")
    ap.add_argument("--min-alpha", type=float, default=0.25, help="drop splats more transparent than this")
    ap.add_argument("--max-scale", type=float, default=0.15,
                    help="drop splats whose largest axis exceeds this (sky/background blobs)")
    ap.add_argument("--min-count", type=int, default=2, help="splats per voxel needed to count as solid")
    ap.add_argument("--bounds", type=float, nargs=6, metavar=("XMIN", "YMIN", "ZMIN", "XMAX", "YMAX", "ZMAX"),
                    help="only mesh this region (splat units); default = 2nd..98th percentile box")
    ap.add_argument("--close", type=int, default=1, help="binary closing iterations to seal small gaps")
    ap.add_argument("--min-component", type=int, default=200, help="drop mesh islands with fewer faces")
    ap.add_argument("--target-faces", type=int, default=150_000, help="decimate to roughly this many faces")
    ap.add_argument("--no-ground", action="store_true",
                    help="skip the safety ground quad at the lowest splat level (WorldLabs scenes sit on a flat "
                         "plane at max raw Y; the quad stops the player falling forever in sparse areas)")
    args = ap.parse_args()

    pos, alpha, scale = read_spz(args.spz)
    print(f"read {len(pos):,} splats")

    keep = (alpha >= args.min_alpha) & (scale.max(1) <= args.max_scale)
    pos = pos[keep]
    print(f"kept {len(pos):,} after alpha/scale filter")

    if args.bounds:
        lo = np.array(args.bounds[:3], np.float32)
        hi = np.array(args.bounds[3:], np.float32)
    else:
        lo = np.percentile(pos, 2, axis=0).astype(np.float32)
        hi = np.percentile(pos, 98, axis=0).astype(np.float32)
        # +Y is down: keep the whole floor (98th pct clips it) and cut off sky/far background.
        hi[1] = np.percentile(pos[:, 1], 99.9)
        lo[1] = max(lo[1], hi[1] - args.height)
    inside = np.all((pos >= lo) & (pos <= hi), axis=1)
    pos = pos[inside]
    print(f"bounds {lo} .. {hi}, {len(pos):,} splats inside")

    v = args.voxel
    dims = np.ceil((hi - lo) / v).astype(int) + 3  # 1-voxel empty border so the surface closes
    idx = np.floor((pos - lo) / v).astype(int) + 1
    counts = np.zeros(dims, np.int32)
    np.add.at(counts, (idx[:, 0], idx[:, 1], idx[:, 2]), 1)
    solid = counts >= args.min_count
    print(f"grid {dims}, {solid.sum():,} solid voxels")

    if args.close > 0:
        solid = ndimage.binary_closing(solid, iterations=args.close)

    # Normals point from solid towards empty (skimage's default 'descent').
    verts, faces, normals, _ = measure.marching_cubes(solid.astype(np.float32), level=0.5)
    verts = verts - normals * args.shrink
    verts = (verts - 1) * v + lo  # back to splat units
    mesh = trimesh.Trimesh(verts, faces, process=True)
    print(f"marching cubes: {len(mesh.faces):,} faces")

    parts = [p for p in mesh.split(only_watertight=False) if len(p.faces) >= args.min_component]
    mesh = trimesh.util.concatenate(parts)
    print(f"dropped floaters: {len(parts)} islands, {len(mesh.faces):,} faces")

    if len(mesh.faces) > args.target_faces:
        mesh = mesh.simplify_quadric_decimation(face_count=args.target_faces)
        print(f"decimated: {len(mesh.faces):,} faces")

    if args.snap > 0:
        mesh = snap_to_splats(mesh, pos, radius=args.snap * v, max_move=v)
        print("snapped vertices onto splat centres")

    if not args.no_ground:
        # Raw .spz frame has +Y pointing down (the scene flips it with a negative
        # Y scale), so the ground is the *largest* Y; the 99th percentile sits just
        # under the floor splats. Extend well past the bounds.
        y = float(np.percentile(pos[:, 1], 99))
        margin = 20.0
        x0, x1 = lo[0] - margin, hi[0] + margin
        z0, z1 = lo[2] - margin, hi[2] + margin
        ground = trimesh.Trimesh(
            [[x0, y, z0], [x1, y, z0], [x1, y, z1], [x0, y, z1]],
            [[0, 1, 2], [0, 2, 3]],
        )
        mesh = trimesh.util.concatenate([mesh, ground])
        print(f"added ground quad at y={y:.3f}")

    mesh.export(args.out)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
