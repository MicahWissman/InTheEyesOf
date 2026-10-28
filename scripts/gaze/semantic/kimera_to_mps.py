#!/usr/bin/env python3
"""
kimera_to_mps.py -- Adapt Kimera-VIO output back into the MPS-compatible files
the InTheEyesOf pipeline consumes, so the rest of the pipeline (Snap Rule
raycasting, trajectory export, baking) keeps working when SLAM is produced by
Kimera instead of by Meta's Machine Perception Services.

Inputs (from Kimera-VIO / Kimera-RPGO / Kimera-Mesher):
  --pose-csv  : Kimera odometry as a CSV. Column names are configurable.
  --mesh-ply  : (optional) Kimera-Mesher mesh .ply -> sampled to a point cloud.

Outputs (written under --out):
  closed_loop_trajectory.csv   world-frame pose + (optionally) ECEF geo-reference
  semidense_points.csv.gz      px_world/py_world/pz_world + dist_std

Optional geo-referencing:
  --gps gps.csv  (from extract_sensors.py: t_ns,lat,lon,alt_m,accuracy_m)
      Fits a Sim(3) (least-squares Umeyama) from the Kimera world frame to ECEF
      using the matched GPS fixes, then writes tx/ty/tz_ecef_device and sets
      geo_available=1 -- exactly what export_trajectory_latlon.py and
      bake_geo_aligned_recording.py expect. Without --gps, geo_available=0.

Usage:
  python scripts/gaze/semantic/kimera_to_mps.py \\
      --pose-csv kimera_odometry.csv \\
      --mesh-ply kimera_mesh.ply \\
      --gps /path/Carona_02_gps.csv \\
      --out /path/mps_kimera

NOTE: Kimera-VIO-VIO is open-loop VIO. For loop closure you must run
Kimera-RPGO and feed its optimized pose graph into --pose-csv; otherwise the
trajectory drifts. The world frame is gravity-aligned and metric, but the yaw
and origin are arbitrary (Kimera anchors at its start) -- that is what the
Sim(3) with --gps fixes.
"""
import os
import csv
import gzip
import argparse
import math
from pathlib import Path

import numpy as np


def _column(header, *candidates, default=None):
    for c in candidates:
        if isinstance(c, (list, tuple)):
            for cc in c:
                if cc in header:
                    return cc
        elif c in header:
            return c
    return default


def load_pose_csv(path, t_col, pos_cols, quat_cols, quat_order):
    """Return (timestamps_ns, positions Nx3, quat Nx4 as [w,x,y,z])."""
    header = None
    rows = []
    with open(path, newline="") as f:
        r = csv.reader(f)
        for row in r:
            if header is None:
                header = row
                continue
            if not row or all(v == "" for v in row):
                continue
            rows.append(row)
    ns = _column(header, *t_col)
    xs = _column(header, *pos_cols[0])
    ys = _column(header, *pos_cols[1])
    zs = _column(header, *pos_cols[2])
    qc = [_column(header, *q) for q in quat_cols]
    missing = [n for n, v in zip(["t", "x", "y", "z"] + ["q0", "q1", "q2", "q3"],
                                 [ns, xs, ys, zs] + qc) if v is None]
    if missing:
        raise SystemExit(f"pose CSV missing columns: {missing}; header={header}")

    idx = {c: header.index(c) for c in [ns, xs, ys, zs] + qc}
    t = np.empty(len(rows), dtype=np.int64)
    P = np.empty((len(rows), 3))
    Q = np.empty((len(rows), 4))
    for i, row in enumerate(rows):
        t[i] = int(row[idx[ns]])
        P[i] = [float(row[idx[xs]]), float(row[idx[ys]]), float(row[idx[zs]])]
        q = [float(row[idx[c]]) for c in qc]
        # normalize + convert to wxyz
        q = np.asarray(q, dtype=np.float64)
        q /= np.linalg.norm(q) + 1e-12
        if quat_order == "xyzw":
            Q[i] = [q[3], q[0], q[1], q[2]]
        else:                       # wxyz
            Q[i] = q
    return t, P, Q


def load_mesh_points(ply_path, step=1):
    """Sample vertices from a Kimera-Mesher triangle mesh .ply.
    'step' keeps every Nth vertex (to decimate huge meshes)."""
    pts = []
    with open(ply_path, "rb") as f:
        line = f.readline()
        if b"ply" not in line.lower():
            raise SystemExit(f"not a .ply: {ply_path}")
        n_verts = 0
        ascii_mode = False
        while True:
            line = f.readline()
            if not line:
                break
            if line.startswith(b"element vertex"):
                n_verts = int(line.split()[-1])
            elif line.startswith(b"format"):
                ascii_mode = b"ascii" in line
            elif line.startswith(b"end_header"):
                break
        if ascii_mode:
            for i in range(n_verts):
                vals = f.readline().split()
                if i % step == 0:
                    pts.append([float(vals[0]), float(vals[1]), float(vals[2])])
        else:
            data = np.frombuffer(f.read(), dtype=np.float32, count=n_verts * 3)
            arr = data.reshape(-1, 3)[::step]
            pts = arr.astype(np.float64)
    return np.asarray(pts, dtype=np.float64)


def ecef_from_geodetic(lat, lon, alt):
    """WGS84 geodetic -> ECEF (meters). Arrays in, array out."""
    a = 6378137.0
    e2 = 6.6943799901414e-3
    lat = np.deg2rad(np.asarray(lat, dtype=np.float64))
    lon = np.deg2rad(np.asarray(lon, dtype=np.float64))
    N = a / np.sqrt(1 - e2 * np.sin(lat) ** 2)
    x = (N + alt) * np.cos(lat) * np.cos(lon)
    y = (N + alt) * np.cos(lat) * np.sin(lon)
    z = (N * (1 - e2) + alt) * np.sin(lat)
    return np.stack([x, y, z], axis=-1)


def umeyama_sim3(src, dst):
    """Least-squares Sim(3): dst ~= s * R @ src + t. Returns (R, t, s)."""
    src = np.asarray(src, dtype=np.float64)
    dst = np.asarray(dst, dtype=np.float64)
    assert src.shape == dst.shape and src.shape[1] == 3
    mu_s = src.mean(axis=0)
    mu_d = dst.mean(axis=0)
    src_c = src - mu_s
    dst_c = dst - mu_d
    H = src_c.T @ dst_c / len(src)
    U, S, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T)) if np.linalg.det(Vt.T @ U.T) != 0 else 1.0
    D = np.diag([1, 1, d])
    R = Vt.T @ D @ U.T
    var_s = src_c.var(axis=0).sum()
    s = (S * np.array([1, 1, d])).sum() / var_s if var_s > 0 else 1.0
    t = mu_d - s * R @ mu_s
    return R, t, s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pose-csv", required=True, help="Kimera odometry pose CSV")
    ap.add_argument("--out", required=True, help="directory for MPS-style outputs")
    ap.add_argument("--mesh-ply", help="optional Kimera-Mesher mesh .ply")
    ap.add_argument("--mesh-step", type=int, default=1, help="keep every Nth vertex")
    ap.add_argument("--gps", help="optional gps.csv (t_ns,lat,lon,alt_m,accuracy_m)")
    ap.add_argument("--gps-max-gap-s", type=float, default=5.0,
                    help="skip GPS fixes whose nearest pose is further than this")
    ap.add_argument("--t-col", nargs="*", default=["timestamp", "tracking_timestamp_us",
                                                   "t", "t_ns", "time_ns"])
    ap.add_argument("--pos-cols", nargs=3, default=["x", "y", "z"])
    ap.add_argument("--quat-cols", nargs=4, default=["qx", "qy", "qz", "qw"],
                    help="column names for the 4 quaternion components (order per --quat-order)")
    ap.add_argument("--quat-order", choices=["xyzw", "wxyz"], default="xyzw",
                    help="order of the 4 quaternion columns in --pose-csv (ROS=xyzw)")
    ap.add_argument("--dist-std", type=float, default=0.001,
                    help="constant dist_std written for the mesh points (passes <=0.15 filter)")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    pos_cols = [[args.pos_cols[0]], [args.pos_cols[1]], [args.pos_cols[2]]]
    quat_cols = [[args.quat_cols[0]], [args.quat_cols[1]],
                 [args.quat_cols[2]], [args.quat_cols[3]]]
    t_ns, P, Q = load_pose_csv(args.pose_csv, args.t_col, pos_cols, quat_cols, args.quat_order)
    print(f"pose: {len(t_ns)} samples (t range {t_ns[0]/1e9:.1f}s .. {t_ns[-1]/1e9:.1f}s, "
          f"{t_ns[-1]-t_ns[0]:.0f} ns)")
    t_us = (t_ns // 1000).astype(np.int64)

    # ---- optional GPS geo-reference (world -> ECEF Sim(3)) ----------------
    geo_available = np.zeros(len(t_ns), dtype=int)
    ECEF = np.zeros((len(t_ns), 3))
    if args.gps:
        R_eg, t_eg, s_eg, gps_n = _fit_gps_to_ecef(P, t_ns, args)
        if R_eg is not None:
            ECEF = (s_eg * (R_eg @ P.T).T + t_eg)
            geo_available[:] = 1
            print(f"geo-reference: Sim(3) from {gps_n} GPS fixes (scale={s_eg:.6f})")
        else:
            print("geo-reference: skipped (insufficient/too-distant GPS fixes)")

    # ---- write closed_loop_trajectory.csv --------------------------------
    traj = out / "closed_loop_trajectory.csv"
    with open(traj, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tracking_timestamp_us", "geo_available",
                    "tx_world_device", "ty_world_device", "tz_world_device",
                    "qw_world_device", "qx_world_device", "qy_world_device",
                    "qz_world_device", "tx_ecef_device", "ty_ecef_device", "tz_ecef_device"])
        for i in range(len(t_us)):
            w.writerow([t_us[i], geo_available[i],
                        f"{P[i,0]:.6f}", f"{P[i,1]:.6f}", f"{P[i,2]:.6f}",
                        f"{Q[i,0]:.8f}", f"{Q[i,1]:.8f}", f"{Q[i,2]:.8f}", f"{Q[i,3]:.8f}",
                        f"{ECEF[i,0]:.3f}", f"{ECEF[i,1]:.3f}", f"{ECEF[i,2]:.3f}"])
    print(f"wrote {traj} ({len(t_us)} rows)")

    # ---- write semidense_points.csv.gz -----------------------------------
    if args.mesh_ply:
        pts = load_mesh_points(args.mesh_ply, step=args.mesh_step)
        print(f"mesh: {len(pts)} vertices (step={args.mesh_step})")
        inv = 1.0 / args.dist_std if args.dist_std > 0 else 0.0
        with gzip.open(out / "semidense_points.csv.gz", "wt", newline="") as f:
            f.write("# generated by kimera_to_mps.py from mesh vertices\n")
            w = csv.writer(f)
            w.writerow(["px_world", "py_world", "pz_world", "dist_std", "inv_dist_std"])
            for p in pts:
                w.writerow([f"{p[0]:.5f}", f"{p[1]:.5f}", f"{p[2]:.5f}",
                            f"{args.dist_std:.4f}", f"{inv:.1f}"])
        print(f"wrote {out/'semidense_points.csv.gz'} ({len(pts)} points)")
    else:
        print("no --mesh-ply; semidense_points.csv.gz not written "
              "(pass --mesh-ply from Kimera-Mesher or point the pipeline at a .ply)")

    print("\nDone. Point the pipeline at this dir (auto-detected as the MPS root).")


def _fit_gps_to_ecef(P, t_ns, args):
    """Load GPS fixes (device-clock ns -> ECEF) and fit a Sim(3) from the
    Kimera world positions (P) to ECEF at the matched timestamps."""
    pas = t_ns.argsort()
    t_ns_sorted = t_ns[pas]
    P_sorted = P[pas]
    rows = []
    with open(args.gps, newline="") as f:
        for r in csv.DictReader(f):
            if all(k in r for k in ("t_ns", "lat", "lon", "alt_m")):
                rows.append((int(r["t_ns"]), float(r["lat"]), float(r["lon"]),
                             float(r["alt_m"])))
    if len(rows) < 3:
        return None, None, None, len(rows)
    gps_t = np.array([r[0] for r in rows], dtype=np.int64)
    gps_ecef = ecef_from_geodetic([r[1] for r in rows], [r[2] for r in rows],
                                  [r[3] for r in rows])
    # match each GPS fix to nearest pose index
    pos = np.searchsorted(t_ns_sorted, gps_t, side="left")
    pos = np.clip(pos, 0, len(t_ns_sorted) - 1)
    dt = np.abs(t_ns_sorted[pos] - gps_t)
    keep = dt <= int(args.gps_max_gap_s * 1e9)
    if keep.sum() < 3:
        return None, None, None, int(keep.sum())
    src = P_sorted[pos[keep]]
    dst = gps_ecef[keep]
    R, t, s = umeyama_sim3(src, dst)
    # reorder back to original (unsorted) pose order: ECEF = s R P^T + t
    # (caller applies to P in original order; return the same R,t,s)
    return R, t, s, int(keep.sum())


if __name__ == "__main__":
    main()
