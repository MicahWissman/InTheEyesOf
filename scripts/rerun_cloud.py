#!/usr/bin/env python3
"""
rerun_cloud.py — visualise a recording's baked point cloud + SLAM camera path in rerun.

Reads the same files the web viewer & render_walkthrough.py use, all in the same
baked Three.js/ENU frame (X=east, Y=up, Z=-north):
  pointcloud.ply         — the map (positions + RGB)
  trajectory_latlon.json — the real recorded device path (wx/wy/wz)

It logs to rerun so you can scrub the timeline and watch the camera move through
the point cloud, with the SLAM trajectory drawn as a line.

It reuses scripts/render_walkthrough.py for trajectory loading + camera math.

Usage
-----
  # Launch the rerun viewer live (needs a display)
  python scripts/rerun_cloud.py --spawn

  # Or save a .rrd to open offline:  rerun cloud.rrd
  python scripts/rerun_cloud.py --save cloud.rrd
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
WEB_VIEWER_RECORDINGS = REPO_ROOT / "web-viewer" / "public" / "recordings"

# reuse the walkthrough's data + camera helpers (same coordinate frame)
from scripts.render_walkthrough import (  # noqa: E402
    UP,
    load_trajectory,
    build_path,
    make_intrinsic,
)

POINT_CLOUD_FILE = "pointcloud.ply"
TRAJECTORY_FILE = "trajectory_latlon.json"


def quat_from_matrix(R: np.ndarray) -> np.ndarray:
    """Numeric quaternion [x,y,z,w] from a 3x3 rotation matrix (Shepperd's method)."""
    m00, m01, m02 = R[0]
    m10, m11, m12 = R[1]
    m20, m21, m22 = R[2]
    tr = m00 + m11 + m22
    if tr > 0:
        s = np.sqrt(tr + 1.0) * 2.0
        w = 0.25 * s
        x = (m21 - m12) / s
        y = (m02 - m20) / s
        z = (m10 - m01) / s
    elif m00 > m11 and m00 > m22:
        s = np.sqrt(1.0 + m00 - m11 - m22) * 2.0
        w = (m21 - m12) / s
        x = 0.25 * s
        y = (m01 + m10) / s
        z = (m02 + m20) / s
    elif m11 > m22:
        s = np.sqrt(1.0 + m11 - m00 - m22) * 2.0
        w = (m02 - m20) / s
        x = (m01 + m10) / s
        y = 0.25 * s
        z = (m12 + m21) / s
    else:
        s = np.sqrt(1.0 + m22 - m00 - m11) * 2.0
        w = (m10 - m01) / s
        x = (m02 + m20) / s
        y = (m12 + m21) / s
        z = 0.25 * s
    q = np.array([x, y, z, w])
    q /= np.linalg.norm(q)
    return q


def world_from_camera(eye: np.ndarray, target: np.ndarray, up: np.ndarray = UP) -> np.ndarray:
    """3x3 rotation (columns = camera right, up, forward) for a rerun Transform3D."""
    f = target - eye
    fn = np.linalg.norm(f)
    if fn < 1e-9:
        return np.eye(3)
    f = f / fn
    right = np.cross(f, up)
    rn = np.linalg.norm(right)
    if rn < 1e-6:
        right = np.cross(f, np.array([0.0, 0.0, 1.0]))
        rn = np.linalg.norm(right)
    right = right / rn
    up_cam = np.cross(right, f)
    return np.column_stack([right, up_cam, f])


def load_point_cloud_np(rec_dir: Path, max_points: int):
    """Read PLY positions+RGB directly with numpy (fast, no Open3D dependency)."""
    import struct

    path = rec_dir / POINT_CLOUD_FILE
    buf = path.read_bytes()
    end = buf.index(b"end_header") + len(b"end_header\n")
    header = buf[:end].decode()
    n = None
    props = []
    for line in header.splitlines():
        if line.startswith("element vertex "):
            n = int(line.split()[2])
        elif line.startswith("property "):
            props.append(line.split()[2])
    stride = 0
    offsets = {}
    for i, p in enumerate(props):
        offsets[p] = stride
        stride += 4 if p in ("x", "y", "z") else 1
    data = buf[end : end + n * stride]
    xyz = np.zeros((n, 3), dtype=np.float32)
    rgb = np.zeros((n, 3), dtype=np.uint8)
    for i, p in enumerate(("x", "y", "z")):
        xyz[:, i] = np.frombuffer(data, dtype=np.float32, count=n, offset=offsets[p])
    for i, p in enumerate(("red", "green", "blue")):
        rgb[:, i] = np.frombuffer(data, dtype=np.uint8, count=n, offset=offsets[p])
    if n > max_points:
        step = int(np.ceil(n / max_points))
        xyz = xyz[::step]
        rgb = rgb[::step]
    return xyz, rgb



def path_total(P: np.ndarray) -> float:
    return float(np.linalg.norm(np.diff(P, axis=0), axis=1).sum())


def make_cameras(path: dict, look_ahead_m: float, max_cameras: int):
    """Sub-sample the smoothed SLAM path into camera poses (eye + look target)."""
    pts = path["pts"]
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    arc = np.concatenate([[0.0], np.cumsum(seg)])
    n = len(pts)
    idx = np.unique(np.linspace(0, n - 1, min(max_cameras, n)).astype(int))
    eyes = pts[idx]
    targets = np.empty_like(eyes)
    for j, i in enumerate(idx):
        want = arc[i] + look_ahead_m
        jj = int(np.searchsorted(arc, want))
        targets[j] = pts[min(jj, n - 1)]
    return eyes, targets


def main(argv=None) -> int:
    import rerun as rr

    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--recording", default="carona_adine")
    p.add_argument("--recording-dir", type=Path, default=None)
    p.add_argument("--max-points", type=int, default=500_000,
                   help="downsample the cloud to this many points for viewer speed")
    p.add_argument("--max-cameras", type=int, default=400,
                   help="subsample the camera path to this many poses")
    p.add_argument("--look-ahead-m", type=float, default=8.0,
                   help="camera looks this far ahead along the path")
    p.add_argument("--point-radius", type=float, default=0.04,
                   help="point radius in metres (rendering size)")
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--vfov", type=float, default=55.0)
    p.add_argument("--spawn", action="store_true",
                   help="open the rerun viewer live (needs a display)")
    p.add_argument("--save", type=Path, default=None,
                   help="write a .rrd file to open offline with `rerun <file>`")
    p.add_argument("--app-id", default="InTheEyesOf-CaronaAdine")
    args = p.parse_args(argv)

    rec_dir = args.recording_dir or (WEB_VIEWER_RECORDINGS / args.recording)
    if not rec_dir.exists():
        sys.exit(f"recording dir not found: {rec_dir}")

    print(f"== rerun · {args.recording} ==")
    P, ts, _ = load_trajectory(rec_dir)
    path = build_path(P, 0.0, path_total(P))
    print(f"  trajectory: {len(P):,} samples → {len(path['pts']):,} path points")

    xyz, rgb = load_point_cloud_np(rec_dir, args.max_points)
    print(f"  point cloud: {len(xyz):,} points")

    eyes, targets = make_cameras(path, args.look_ahead_m, args.max_cameras)
    print(f"  camera poses: {len(eyes)}")

    K = np.asarray(make_intrinsic(args.width, args.height, args.vfov).intrinsic_matrix)

    rr.init(args.app_id, spawn=args.spawn)
    # world is the baked Three.js frame; rerun is Y-up so log coordinates as-is
    rr.log("world/map",
           rr.Points3D(xyz, colors=rgb, radii=np.full(len(xyz), args.point_radius)),
           static=True)
    rr.log("world/trajectory", rr.LineStrips3D([path["pts"]]), static=True)
    rr.log("world/camera", rr.Pinhole(image_from_camera=K,
                                      resolution=[args.width, args.height]), static=True)

    for i, (eye, tgt) in enumerate(zip(eyes, targets)):
        rr.set_time_sequence("frame", i)
        R = world_from_camera(eye, tgt)
        q = quat_from_matrix(R)
        rr.log("world/camera", rr.Transform3D(
            translation=eye, quaternion=rr.Quaternion(xyzw=q)))
        fwd = tgt - eye
        fn = np.linalg.norm(fwd)
        if fn > 1e-6:
            rr.log("world/camera/view_dir",
                   rr.Arrows3D(origins=[eye], vectors=[fwd / fn], radii=[0.05]))

    if args.save:
        rr.save(args.save)
        print(f"  saved → {args.save}")
    elif not args.spawn:
        out = REPO_ROOT / "pipeline_results" / "walkthrough" / args.recording / f"{args.recording}.rrd"
        out.parent.mkdir(parents=True, exist_ok=True)
        rr.save(out)
        print(f"  no --save/--spawn given → wrote {out}")
    else:
        print("  spawned viewer — the stream stays live; Ctrl-C to stop")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
