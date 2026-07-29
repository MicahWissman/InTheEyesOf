#!/usr/bin/env python3
"""
Merge recordings that share a world frame (e.g. the Carona multi-SLAM 0/ and 1/
halves) into one combined recording for the viewer:
  - anchors: concatenated in order, each tagged with `source_recording` (so
    cross-part edges can be identified); node id = position in the merged list.
  - trajectory: the two paths concatenated into one continuous track.
  - point cloud: the parts' clouds stacked (same world frame).

Build the convergence graph over the merged anchors afterward so edges can form
ACROSS the parts (cross-part convergence). Rationales for within-part edges can
then be transplanted from the parts' own graphs (same anchor pairs); only the new
cross-part edges need fresh computation.

Run in an env with open3d (e.g. aria_tools) for the point-cloud merge.

Usage:
  python merge_recordings.py --part Carona_02_companion --part Carona_03_companion \
      --out Carona_02_03_companion
"""
import os
import json
import argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", action="append", required=True,
                    help="recording folder name (repeatable, in order)")
    ap.add_argument("--out", required=True, help="merged recording folder name")
    ap.add_argument("--base", default="web-viewer/public/recordings")
    args = ap.parse_args()

    outdir = os.path.join(args.base, args.out)
    os.makedirs(outdir, exist_ok=True)

    # 1. anchors — concat, tag source
    merged = []
    for part in args.part:
        a = json.load(open(os.path.join(args.base, part, "narrative_anchors.json")))
        for x in a:
            x["source_recording"] = part
        merged += a
        print(f"  {part}: {len(a)} anchors")
    json.dump(merged, open(os.path.join(outdir, "narrative_anchors.json"), "w"),
              indent=2, ensure_ascii=False)
    print(f"merged anchors: {len(merged)}")

    # 2. trajectory — concat the path arrays into one continuous track
    path, hz = [], 2
    for part in args.part:
        tp = os.path.join(args.base, part, "trajectory_latlon.json")
        if os.path.exists(tp):
            t = json.load(open(tp))
            path += t.get("path", [])
            hz = t.get("sample_hz", hz)
    if path:
        json.dump({"start_t": path[0]["t"], "end_t": path[-1]["t"], "sample_hz": hz,
                   "count": len(path), "path": path},
                  open(os.path.join(outdir, "trajectory_latlon.json"), "w"))
        print(f"merged trajectory: {len(path)} points")

    # 3. point cloud — stack the parts' clouds (same world frame)
    try:
        import numpy as np
        import open3d as o3d
        clouds = []
        for part in args.part:
            pc = o3d.io.read_point_cloud(os.path.join(args.base, part, "pointcloud.ply"))
            clouds.append(np.asarray(pc.points))
        allpts = np.vstack(clouds)
        merged_pc = o3d.geometry.PointCloud()
        merged_pc.points = o3d.utility.Vector3dVector(allpts)
        o3d.io.write_point_cloud(os.path.join(outdir, "pointcloud.ply"), merged_pc)
        print(f"merged point cloud: {len(allpts)} points")
    except Exception as e:
        print(f"  point cloud merge skipped ({e}); copy one part's pointcloud.ply manually")


if __name__ == "__main__":
    main()
