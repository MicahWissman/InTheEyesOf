#!/usr/bin/env python3
"""
Bake Geo-Aligned Recording
--------------------------
Transforms MPS world-frame data (closed_loop_trajectory.csv,
semidense_points.csv.gz) into ENU-aligned, Three.js-ready outputs for the
InTheEyesOf web viewer.  After baking, theta≈0 from Procrustes — the viewer
renders with no runtime rotation.

Usage
-----
  python scripts/bake_geo_aligned_recording.py \\
    --trajectory  <path/to/closed_loop_trajectory.csv> \\
    --points      <path/to/semidense_points.csv.gz> \\
    --out         <output_recording_dir> \\
    [--gps-offset <dlat_deg> <dlon_deg>] \\
    [--sample-hz  <hz>] \\
    [--max-points <n>] \\
    [--dist-std   <threshold>] \\
    [--recording-id    <id>] \\
    [--recording-title <title>]

Outputs  (drop into web-viewer/public/recordings/<id>/)
-------
  pointcloud.ply         — ENU-aligned cloud (Three.js X=east Y=up Z=-north)
  trajectory_latlon.json — trajectory; wx/wy/wz are Three.js world coords
  manifest_entry.json    — paste into manifest.json recordings array

Math
----
  1. Umeyama rigid alignment: world → ECEF  (using geo-tagged trajectory rows)
  2. ECEF → ENU at trajectory centroid
  3. ENU → Three.js: X=east, Y=up, Z=-north  (swap Y↔Z, negate new Z)
  4. Optional GPS offset (dlat, dlon) applied as ENU translation
  5. Confidence filter on semidense points (dist_std or inverse_distance_std)
  6. Subsample to --max-points (uniform stride after confidence filter)
"""

import csv
import gzip
import json
import math
import struct
import argparse
import sys
from pathlib import Path

import numpy as np

# ── WGS-84 constants ──────────────────────────────────────────────────────────
WGS84_A  = 6_378_137.0        # semi-major axis (m)
WGS84_E2 = 6.6943799901414e-3 # first eccentricity squared

# ── ENU → Three.js axis permutation ──────────────────────────────────────────
# ENU:      X=east  Y=north  Z=up
# Three.js: X=east  Y=up     Z=-north
R_ENU2THREE = np.array([
    [1,  0,  0],   # east   → X
    [0,  0,  1],   # up     → Y
    [0, -1,  0],   # -north → Z
], dtype=np.float64)


# ── Geodesy helpers ───────────────────────────────────────────────────────────

def ecef_to_wgs84(x: float, y: float, z: float) -> tuple[float, float, float]:
    """ECEF (m) → (lat_deg, lon_deg, alt_m) via iterative Bowring."""
    lon = math.atan2(y, x)
    p   = math.sqrt(x**2 + y**2)
    lat = math.atan2(z, p * (1 - WGS84_E2))
    for _ in range(10):
        N       = WGS84_A / math.sqrt(1 - WGS84_E2 * math.sin(lat)**2)
        lat_new = math.atan2(z + WGS84_E2 * N * math.sin(lat), p)
        if abs(lat_new - lat) < 1e-12:
            lat = lat_new
            break
        lat = lat_new
    N       = WGS84_A / math.sqrt(1 - WGS84_E2 * math.sin(lat)**2)
    cos_lat = math.cos(lat)
    alt     = (p / cos_lat - N) if abs(cos_lat) > 1e-10 \
              else (abs(z) / math.sin(lat) - N * (1 - WGS84_E2))
    return math.degrees(lat), math.degrees(lon), alt


def enu_rotation_at(lat_deg: float, lon_deg: float) -> np.ndarray:
    """3×3 rotation from ECEF to ENU at (lat, lon). Rows are [east, north, up]."""
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    sl, cl   = math.sin(lat), math.cos(lat)
    so, co   = math.sin(lon), math.cos(lon)
    return np.array([
        [-so,        co,        0 ],   # east
        [-sl * co,  -sl * so,  cl ],   # north
        [ cl * co,   cl * so,  sl ],   # up
    ], dtype=np.float64)


# ── Alignment ─────────────────────────────────────────────────────────────────

def umeyama_rigid(src: np.ndarray, dst: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Umeyama rigid-body alignment (rotation + translation, no scale).
    Finds R, t minimising ||dst_i - (R @ src_i + t)||².
    src, dst: N×3.  Returns R (3×3), t (3,).
    """
    n    = src.shape[0]
    mu_s = src.mean(0);  mu_d = dst.mean(0)
    S    = (src - mu_s).T @ (dst - mu_d) / n   # 3×3 cross-covariance
    U, _, Vt = np.linalg.svd(S)
    D    = np.diag([1.0, 1.0, np.linalg.det(Vt.T @ U.T)])   # reflection guard
    R    = Vt.T @ D @ U.T
    t    = mu_d - R @ mu_s
    return R, t


# ── I/O helpers ───────────────────────────────────────────────────────────────

def _open_csv(path: Path):
    """Yield non-comment lines from a plain or gzip-compressed CSV."""
    opener = gzip.open if path.suffix == ".gz" else open
    mode   = "rt" if path.suffix == ".gz" else "r"
    with opener(path, mode) as f:
        for line in f:
            if not line.startswith("#"):
                yield line


def load_trajectory(
    path: Path,
) -> tuple[list[dict], np.ndarray, np.ndarray]:
    """
    Read closed_loop_trajectory.csv.
    Returns:
      rows_all   — all CSV rows as dicts (for trajectory output)
      world_geo  — N×3 world positions where geo_available == 1
      ecef_geo   — N×3 matching ECEF positions
    """
    rows_all  = []
    world_geo = []
    ecef_geo  = []
    for row in csv.DictReader(_open_csv(path)):
        rows_all.append(row)
        if row["geo_available"].strip() == "1":
            world_geo.append([float(row["tx_world_device"]),
                               float(row["ty_world_device"]),
                               float(row["tz_world_device"])])
            ecef_geo.append([float(row["tx_ecef_device"]),
                              float(row["ty_ecef_device"]),
                              float(row["tz_ecef_device"])])
    return rows_all, np.array(world_geo, dtype=np.float64), \
                     np.array(ecef_geo,  dtype=np.float64)


def load_semidense_points(
    path: Path,
    dist_std_max: float = 0.005,
    max_points:   int   = 200_000,
) -> np.ndarray:
    """
    Read semidense_points.csv[.gz].
    Confidence filter: dist_std or inverse_distance_std <= dist_std_max.
    Returns N×3 float64 in world frame.
    """
    print(f"Reading {path} …")
    rows = list(csv.DictReader(_open_csv(path)))
    print(f"  {len(rows):,} raw points")

    # Detect confidence column (varies by MPS version)
    if rows:
        if "inverse_distance_std" in rows[0]:
            conf_col = "inverse_distance_std"
        elif "dist_std" in rows[0]:
            conf_col = "dist_std"
        else:
            conf_col = None
    else:
        conf_col = None

    if conf_col:
        rows = [r for r in rows if float(r[conf_col]) <= dist_std_max]
        print(f"  {len(rows):,} after confidence filter ({conf_col} ≤ {dist_std_max})")
    else:
        print("  Warning: no confidence column found — keeping all points")

    if len(rows) > max_points:
        step = max(1, len(rows) // max_points)
        rows = rows[::step][:max_points]
        print(f"  Subsampled to {len(rows):,} (stride {step})")

    return np.array(
        [[float(r["px_world"]), float(r["py_world"]), float(r["pz_world"])]
         for r in rows],
        dtype=np.float64,
    )


def height_color(y_vals: np.ndarray) -> np.ndarray:
    """Map Three.js Y (up) to a blue→cyan→white gradient for visual depth cues."""
    lo, hi = np.percentile(y_vals, 2), np.percentile(y_vals, 98)
    t = np.clip((y_vals - lo) / max(hi - lo, 1e-9), 0, 1)
    r = (t * 180).astype(np.uint8)
    g = (150 + t * 105).astype(np.uint8)
    b = np.full(len(y_vals), 220, dtype=np.uint8)
    return np.stack([r, g, b], axis=1)


def write_ply_binary(
    path: Path,
    xyz:  np.ndarray,
    rgb:  np.ndarray,
) -> None:
    """
    Write binary-little-endian PLY matching the existing viewer format.
    xyz: N×3 float64, rgb: N×3 uint8.
    """
    n = len(xyz)
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        "comment Created by bake_geo_aligned_recording\n"
        f"element vertex {n}\n"
        "property double x\n"
        "property double y\n"
        "property double z\n"
        "property uchar red\n"
        "property uchar green\n"
        "property uchar blue\n"
        "end_header\n"
    ).encode("ascii")

    # Numpy structured dtype — 3×float64 + 3×uint8 = 27 bytes, no padding
    dt = np.dtype([
        ("x", "<f8"), ("y", "<f8"), ("z", "<f8"),
        ("r", "u1"),  ("g", "u1"),  ("b", "u1"),
    ])
    assert dt.itemsize == 27, f"unexpected struct size {dt.itemsize}"

    buf = np.empty(n, dtype=dt)
    buf["x"] = xyz[:, 0];  buf["y"] = xyz[:, 1];  buf["z"] = xyz[:, 2]
    buf["r"] = rgb[:, 0];  buf["g"] = rgb[:, 1];  buf["b"] = rgb[:, 2]

    with open(path, "wb") as f:
        f.write(header)
        f.write(buf.tobytes())
    print(f"  Wrote {n:,} vertices → {path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Bake geo-aligned MPS data for InTheEyesOf web viewer.")
    ap.add_argument("--trajectory",       required=True,
                    help="closed_loop_trajectory.csv")
    ap.add_argument("--points",           required=True,
                    help="semidense_points.csv or .csv.gz")
    ap.add_argument("--out",              required=True,
                    help="Output directory (becomes the recording folder)")
    ap.add_argument("--gps-offset",       nargs=2, type=float,
                    metavar=("DLAT", "DLON"), default=None,
                    help="Manual GPS correction in degrees (dlat dlon)")
    ap.add_argument("--sample-hz",        type=float, default=1.0,
                    help="Trajectory output sample rate (default 1 Hz)")
    ap.add_argument("--max-points",       type=int, default=200_000,
                    help="Max semidense points output (default 200 000)")
    ap.add_argument("--dist-std",         type=float, default=0.005,
                    help="Max dist_std for confidence filter (default 0.005)")
    ap.add_argument("--recording-id",     default="my_recording",
                    help="Recording ID for manifest entry")
    ap.add_argument("--recording-title",  default="My Recording",
                    help="Display title for manifest entry")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Load trajectory ─────────────────────────────────────────────────
    print("Loading trajectory …")
    traj_rows, world_geo, ecef_geo = load_trajectory(Path(args.trajectory))
    if len(world_geo) < 3:
        sys.exit(f"ERROR: only {len(world_geo)} geo-tagged rows — need ≥ 3 for alignment.")
    print(f"  {len(traj_rows):,} total rows, {len(world_geo):,} geo-tagged")

    # ── 2. Umeyama: world → ECEF ───────────────────────────────────────────
    print("Fitting world → ECEF transform (Umeyama rigid) …")
    R_w2e, t_w2e = umeyama_rigid(world_geo, ecef_geo)
    residuals = np.linalg.norm(world_geo @ R_w2e.T + t_w2e - ecef_geo, axis=1)
    print(f"  RMSE {np.sqrt(np.mean(residuals**2)):.3f} m  "
          f"(max {residuals.max():.3f} m, n={len(world_geo)})")

    # ── 3. ECEF → ENU at centroid ──────────────────────────────────────────
    ecef_centroid       = ecef_geo.mean(0)
    lat0, lon0, alt0    = ecef_to_wgs84(*ecef_centroid)
    R_e2enu             = enu_rotation_at(lat0, lon0)
    print(f"ENU origin: {lat0:.6f}°N  {lon0:.6f}°E  (alt {alt0:.1f} m)")

    # ── 4. Optional GPS correction ─────────────────────────────────────────
    shift_enu = np.zeros(3)   # [east, north, up] metres
    if args.gps_offset:
        dlat, dlon = args.gps_offset
        shift_enu[0] = math.radians(dlon) * math.cos(math.radians(lat0)) * WGS84_A
        shift_enu[1] = math.radians(dlat) * WGS84_A
        print(f"GPS offset ({dlat:+g}°, {dlon:+g}°) → "
              f"ΔE {shift_enu[0]:+.2f} m  ΔN {shift_enu[1]:+.2f} m")

    # ── 5. Combined world → Three.js transform ─────────────────────────────
    #
    #   p_ecef  = R_w2e @ p_world + t_w2e
    #   p_enu   = R_e2enu @ (p_ecef - ecef_centroid) + shift_enu
    #   p_three = R_ENU2THREE @ p_enu
    #
    #   Collapsed:
    #     R_final = R_ENU2THREE @ R_e2enu @ R_w2e
    #     t_final = R_ENU2THREE @ (R_e2enu @ (t_w2e - ecef_centroid) + shift_enu)
    R_final = R_ENU2THREE @ R_e2enu @ R_w2e
    t_final = R_ENU2THREE @ (R_e2enu @ (t_w2e - ecef_centroid) + shift_enu)

    def to_three(pts: np.ndarray) -> np.ndarray:
        """Apply full world → Three.js transform. pts: (N,3) or (3,)."""
        return pts @ R_final.T + t_final

    # ── 6. Transform and write point cloud ─────────────────────────────────
    print("Loading semidense point cloud …")
    pts_world = load_semidense_points(
        Path(args.points),
        dist_std_max=args.dist_std,
        max_points=args.max_points,
    )
    print("Transforming to Three.js space …")
    pts_three = to_three(pts_world)
    colors    = height_color(pts_three[:, 1])    # Y = up in Three.js

    ply_path = out_dir / "pointcloud.ply"
    print(f"Writing PLY …")
    write_ply_binary(ply_path, pts_three, colors)

    # ── 7. Build trajectory_latlon.json ────────────────────────────────────
    print("Building trajectory_latlon.json …")
    sample_us  = int(1_000_000 / args.sample_hz)
    last_t     = None
    traj_points: list[dict] = []

    for row in traj_rows:
        t = int(row["tracking_timestamp_us"])
        if last_t is not None and (t - last_t) < sample_us:
            continue

        wx = float(row["tx_world_device"])
        wy = float(row["ty_world_device"])
        wz = float(row["tz_world_device"])
        p_three = to_three(np.array([wx, wy, wz]))

        # Prefer measured ECEF for lat/lon; fall back to Umeyama projection
        if row["geo_available"].strip() == "1":
            ex, ey, ez = (float(row["tx_ecef_device"]),
                          float(row["ty_ecef_device"]),
                          float(row["tz_ecef_device"]))
        else:
            ex, ey, ez = R_w2e @ np.array([wx, wy, wz]) + t_w2e

        lat, lon, alt = ecef_to_wgs84(ex, ey, ez)
        if args.gps_offset:
            lat += args.gps_offset[0]
            lon += args.gps_offset[1]

        traj_points.append({
            "t":   t,
            "lat": round(lat, 8),
            "lon": round(lon, 8),
            "alt": round(alt, 2),
            "wx":  round(float(p_three[0]), 4),
            "wy":  round(float(p_three[1]), 4),
            "wz":  round(float(p_three[2]), 4),
        })
        last_t = t

    traj_json = {
        "start_t":    traj_points[0]["t"],
        "end_t":      traj_points[-1]["t"],
        "sample_hz":  args.sample_hz,
        "count":      len(traj_points),
        "baked":      True,
        "enu_origin": {"lat": round(lat0, 8), "lon": round(lon0, 8),
                       "alt": round(alt0, 2)},
        "path":       traj_points,
    }
    traj_path = out_dir / "trajectory_latlon.json"
    with open(traj_path, "w") as f:
        json.dump(traj_json, f, separators=(",", ":"))
    print(f"  Wrote {len(traj_points)} points → {traj_path}")

    # ── 8. Manifest entry template ─────────────────────────────────────────
    manifest_entry = {
        "id":               args.recording_id,
        "title":            args.recording_title,
        "anchorsFile":      "narrative_anchors.json",
        "pointCloudFile":   "pointcloud.ply",
        "semanticGraphFile":"semantic_graph.json",
        "trajectoryFile":   "trajectory_latlon.json",
    }
    manifest_path = out_dir / "manifest_entry.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest_entry, f, indent=2)
    print(f"  Wrote manifest entry template → {manifest_path}")

    print(f"""
Done.
  Drop folder contents into:  web-viewer/public/recordings/{args.recording_id}/
  Add manifest_entry.json contents to manifest.json recordings array.
  The baked trajectory_latlon.json carries "baked": true so the viewer
  can skip runtime Procrustes rotation (theta should be ≈ 0).
""")


if __name__ == "__main__":
    main()
