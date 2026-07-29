#!/usr/bin/env python3
"""
Convert ECEF trajectory to WGS84 lat/lon/alt and downsample for web viewer.

Usage:
  python scripts/export_trajectory_latlon.py <mps_slam_dir> <output_json> [sample_hz]

Example:
  python scripts/export_trajectory_latlon.py \
    ../vrs_files/mps_gilbert-test-2_vrs/slam \
    web-viewer/public/recordings/gilbert-test-2/trajectory_latlon.json \
    1
"""

import sys
import json
import math
import csv
from pathlib import Path

WGS84_A = 6378137.0
WGS84_E2 = 6.6943799901414e-3


def ecef_to_wgs84(x: float, y: float, z: float) -> tuple[float, float, float]:
    """ECEF (meters) → WGS84 (degrees lat, degrees lon, meters alt)."""
    lon = math.atan2(y, x)
    p = math.sqrt(x ** 2 + y ** 2)
    lat = math.atan2(z, p * (1 - WGS84_E2))
    for _ in range(10):
        N = WGS84_A / math.sqrt(1 - WGS84_E2 * math.sin(lat) ** 2)
        lat_new = math.atan2(z + WGS84_E2 * N * math.sin(lat), p)
        if abs(lat_new - lat) < 1e-12:
            lat = lat_new
            break
        lat = lat_new
    N = WGS84_A / math.sqrt(1 - WGS84_E2 * math.sin(lat) ** 2)
    cos_lat = math.cos(lat)
    if abs(cos_lat) > 1e-10:
        alt = p / cos_lat - N
    else:
        alt = abs(z) / math.sin(lat) - N * (1 - WGS84_E2)
    return math.degrees(lat), math.degrees(lon), alt


def main():
    if len(sys.argv) < 3:
        print("Usage: export_trajectory_latlon.py <slam_dir> <output_json> [sample_hz=1]")
        sys.exit(1)

    slam_dir = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    sample_hz = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0

    traj_path = slam_dir / "closed_loop_trajectory.csv"
    if not traj_path.exists():
        print(f"Error: {traj_path} not found")
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    sample_interval_us = int(1_000_000 / sample_hz)
    last_t = None
    points = []
    skipped_no_geo = 0

    print(f"Reading {traj_path} ...")
    with open(traj_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["geo_available"].strip() != "1":
                skipped_no_geo += 1
                continue
            t = int(row["tracking_timestamp_us"])
            if last_t is not None and (t - last_t) < sample_interval_us:
                continue
            x = float(row["tx_ecef_device"])
            y = float(row["ty_ecef_device"])
            z = float(row["tz_ecef_device"])
            lat, lon, alt = ecef_to_wgs84(x, y, z)
            points.append({
                "t": t,
                "lat": round(lat, 8),
                "lon": round(lon, 8),
                "alt": round(alt, 2),
                "wx": round(float(row["tx_world_device"]), 4),
                "wy": round(float(row["ty_world_device"]), 4),
                "wz": round(float(row["tz_world_device"]), 4),
            })
            last_t = t

    if not points:
        print("No geo-tagged points found. Check geo_available column.")
        sys.exit(1)

    out = {
        "start_t": points[0]["t"],
        "end_t": points[-1]["t"],
        "sample_hz": sample_hz,
        "count": len(points),
        "path": points,
    }

    with open(output_path, "w") as f:
        json.dump(out, f, separators=(",", ":"))

    print(f"Exported {len(points)} points → {output_path}")
    if skipped_no_geo:
        print(f"  (skipped {skipped_no_geo} rows without geo data)")


if __name__ == "__main__":
    main()
