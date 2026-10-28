#!/usr/bin/env python3
"""Merge single-SLAM pipeline runs into one multi-SLAM experience, keeping each person separable.

Per part: fit single-SLAM world -> multi-SLAM world (Umeyama on matching timestamps) and move the
part's Stage 1 events and Stage 3 anchors into the shared frame. No Gemini calls: narratives are
reused verbatim so every combined anchor maps 1:1 to the anchor in that person's own experience.
Then bake ONE world->Three.js transform from all parts' geo rows, so cloud, path and anchors share it.
Indoor sites with no GPS fix (geo_available = 0 everywhere) are pinned by hand with --manual-geo.

Run from the repo root in aria-dev. Outputs: narrative_anchors.json (map frame, tagged
source_recording / source_person / source_color / source_anchor_id), anchor_sources.csv,
baked/pointcloud.ply, baked/trajectory_latlon.json (with per-person "segments"), parts/<id>/.

Usage:
  scripts/combine_multislam_recordings.py --out pipeline_results/<site>_combined \
     --part ID:PERSON:SINGLE_SLAM_DIR:MULTI_SLAM_DIR[:SPEAKER] [--part ...] \
     [--manual-geo LAT,LON[,ALT] [--heading DEG]]
  PERSON is the tag label shown in the viewer; SPEAKER (optional) is the speaker's name, kept in the data.
  If Stage 1 ran directly on the multi slam/, pass it as both SINGLE_SLAM_DIR and MULTI_SLAM_DIR.
"""
import argparse, csv, json, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))   # scripts/ (bake_geo_aligned_recording)
import bake_geo_aligned_recording as B

PALETTE = ["#f59e0b", "#a855f7", "#22c55e", "#ef4444", "#3b82f6"]   # one colour per person
GAP_US = 60_000_000                                                  # 60 s between parts on the shared timeline

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--part", action="append", required=True)
ap.add_argument("--results", default="pipeline_results")
ap.add_argument("--max-points-per-part", type=int, default=200_000)
ap.add_argument("--manual-geo", help="LAT,LON[,ALT]: pin the centre of all trajectories here (no GPS fix)")
ap.add_argument("--heading", type=float, default=0.0,
                help="with --manual-geo: rotate the site clockwise on the map by DEG (0 = world +X east, +Y north)")
args = ap.parse_args()
out = Path(args.out); out.mkdir(parents=True, exist_ok=True)


def xyz(rows):
    return np.array([[float(r["tx_world_device"]), float(r["ty_world_device"]), float(r["tz_world_device"])] for r in rows])


def move(R, t, obj):
    p = np.array([obj["gx"], obj["gy"], obj["gz"]]) @ R.T + t
    obj["gx"], obj["gy"], obj["gz"] = (float(v) for v in p)


parts = []
for spec in args.part:
    pid, person, single, multi, *speaker = spec.split(":")
    single_rows = list(csv.DictReader(open(Path(single) / "closed_loop_trajectory.csv")))
    multi_rows, world_geo, ecef_geo = B.load_trajectory(Path(multi) / "closed_loop_trajectory.csv")
    s_by_t = {int(r["tracking_timestamp_us"]): r for r in single_rows}
    common = [r for r in multi_rows if int(r["tracking_timestamp_us"]) in s_by_t]
    A, M = xyz([s_by_t[int(r["tracking_timestamp_us"])] for r in common]), xyz(common)
    R, t = B.umeyama_rigid(A, M)
    res = np.linalg.norm(A @ R.T + t - M, axis=1)
    rmse = float(np.sqrt((res ** 2).mean()))
    print(f"{pid}: single->multi rigid fit on {len(common)} poses, RMSE {rmse*100:.1f} cm, max {res.max()*100:.1f} cm")
    if rmse > 0.25:
        sys.exit(f"{pid}: single and multi trajectories disagree (> 25 cm); rerun Stage 1 on the multi slam/ instead")

    pdir = out / "parts" / pid; pdir.mkdir(parents=True, exist_ok=True)
    np.savez(pdir / "single_to_multi.npz", R=R, t=t, rmse=rmse)
    src = Path(args.results) / pid
    events = json.load(open(src / "stage1" / "semantic_results.json"))
    for e in events:
        move(R, t, e)
    json.dump(events, open(pdir / "semantic_results.multi_world.json", "w"), indent=2, ensure_ascii=False)
    anchors = json.load(open(src / "narrative_anchors.world.json"))       # Stage 3 output, single SLAM frame
    for a in anchors:
        move(R, t, a)
    json.dump(anchors, open(pdir / "narrative_anchors.multi_world.json", "w"), indent=2, ensure_ascii=False)
    ts = [int(r["tracking_timestamp_us"]) for r in multi_rows]
    parts.append(dict(id=pid, person=person, speaker=(speaker or [None])[0], rows=multi_rows, world_geo=world_geo, ecef_geo=ecef_geo,
                      anchors=anchors, n_events=len(events), points=Path(multi) / "semidense_points.csv.gz",
                      t0=min(ts), t1=max(ts), fit_rmse_m=rmse))

# ── one shared world -> Three.js transform (same maths as bake_geo_aligned_recording.py) ──
world_geo = np.vstack([p["world_geo"] for p in parts]); ecef_geo = np.vstack([p["ecef_geo"] for p in parts])
if args.manual_geo:
    # MPS world is gravity-aligned (+Z up), so placement is a yaw about up plus a translation
    lat0, lon0, alt0 = ([float(v) for v in args.manual_geo.split(",")] + [0.0])[:3]
    la, lo = np.radians(lat0), np.radians(lon0)
    N = B.WGS84_A / np.sqrt(1 - B.WGS84_E2 * np.sin(la) ** 2)
    c = np.array([(N + alt0) * np.cos(la) * np.cos(lo), (N + alt0) * np.cos(la) * np.sin(lo),
                  (N * (1 - B.WGS84_E2) + alt0) * np.sin(la)])
    h = np.radians(args.heading)
    R_w2enu = np.array([[np.cos(h), np.sin(h), 0], [-np.sin(h), np.cos(h), 0], [0, 0, 1]])
    R_w2e = B.enu_rotation_at(lat0, lon0).T @ R_w2enu
    centre = np.vstack([xyz(p["rows"]) for p in parts]).mean(0)
    t_w2e = c - R_w2e @ centre
    print(f"manual placement: trajectory centre -> {lat0:.7f},{lon0:.7f} alt {alt0} m, heading {args.heading} deg")
else:
    if not len(world_geo):
        sys.exit("no geo_available rows in any part; pin the site with --manual-geo LAT,LON")
    R_w2e, t_w2e = B.umeyama_rigid(world_geo, ecef_geo)
    res = np.linalg.norm(world_geo @ R_w2e.T + t_w2e - ecef_geo, axis=1)
    print(f"shared world->ECEF fit: RMSE {np.sqrt((res**2).mean()):.3f} m over {len(world_geo)} geo rows")
    c = ecef_geo.mean(0); lat0, lon0, alt0 = B.ecef_to_wgs84(*c)
R_e2enu = B.enu_rotation_at(lat0, lon0)
R_f = B.R_ENU2THREE @ R_e2enu @ R_w2e
t_f = B.R_ENU2THREE @ (R_e2enu @ (t_w2e - c))
to3 = lambda p: p @ R_f.T + t_f
(out / "baked").mkdir(exist_ok=True)
np.savez(out / "narrative_anchors.xform.npz", R=R_f, t=t_f)

# point cloud: stack every part's cloud (all in the shared world frame)
pts = np.vstack([B.load_semidense_points(p["points"], max_points=args.max_points_per_part) for p in parts])
p3 = to3(pts)
B.write_ply_binary(out / "baked" / "pointcloud.ply", p3, B.height_color(p3[:, 1]))

# trajectory: parts laid end to end on one timeline so the viewer's start_ts lookup stays unambiguous
path, segments, cursor = [], [], None
for i, p in enumerate(parts):
    offset = 0 if cursor is None else cursor + GAP_US - p["t0"]
    p["t_offset_us"], p["color"] = offset, PALETTE[i % len(PALETTE)]
    start, last = len(path), None
    for r in p["rows"]:
        t = int(r["tracking_timestamp_us"])
        if last is not None and t - last < 1_000_000:
            continue
        w = np.array([float(r["tx_world_device"]), float(r["ty_world_device"]), float(r["tz_world_device"])])
        e = ([float(r[k]) for k in ("tx_ecef_device", "ty_ecef_device", "tz_ecef_device")]
             if r["geo_available"].strip() == "1" else R_w2e @ w + t_w2e)
        lat, lon, alt = B.ecef_to_wgs84(*e); q = to3(w)
        path.append({"t": t + offset, "lat": round(lat, 8), "lon": round(lon, 8), "alt": round(alt, 2),
                     "wx": round(float(q[0]), 4), "wy": round(float(q[1]), 4), "wz": round(float(q[2]), 4),
                     "src": p["id"]})
        last = t
    cursor = p["t1"] + offset
    segments.append({"source_recording": p["id"], "person": p["person"], "speaker": p["speaker"], "color": p["color"],
                     "t_offset_us": offset, "path_start": start, "path_end": len(path) - 1})
json.dump({"start_t": path[0]["t"], "end_t": path[-1]["t"], "sample_hz": 1.0, "count": len(path), "baked": True,
           "enu_origin": {"lat": round(lat0, 8), "lon": round(lon0, 8), "alt": round(alt0, 2)},
           "geo_source": "manual" if args.manual_geo else "mps",
           "segments": segments, "path": path},
          open(out / "baked" / "trajectory_latlon.json", "w"), separators=(",", ":"))

# anchors: merged, tagged by person, shared timeline + map frame
merged_world, merged = [], []
for p in parts:
    for j, a in enumerate(p["anchors"]):      # j == the anchor's id in that person's own experience
        w = dict(a, source_recording=p["id"], source_person=p["person"], source_color=p["color"],
                 source_anchor_id=j)
        if p["speaker"]:
            w["source_speaker"] = p["speaker"]
        for k in ("start_ts", "end_ts"):
            if k in w:
                w[f"source_{k}"] = w[k]; w[k] = w[k] + p["t_offset_us"]
        m = dict(w)
        q = to3(np.array([w["gx"], w["gy"], w["gz"]]))
        m["world_gx"], m["world_gy"], m["world_gz"] = w["gx"], w["gy"], w["gz"]
        m["gx"], m["gy"], m["gz"] = (float(v) for v in q)
        m["id"] = w["id"] = len(merged)
        merged.append(m); merged_world.append(w)
json.dump(merged_world, open(out / "narrative_anchors.world.json", "w"), indent=2, ensure_ascii=False)
json.dump(merged, open(out / "narrative_anchors.json", "w"), indent=2, ensure_ascii=False)

with open(out / "anchor_sources.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["id", "person", "speaker", "source_recording", "source_anchor_id", "narrative_title", "relative_time",
                "source_start_ts", "source_end_ts", "gx", "gy", "gz"])
    for a in merged:
        w.writerow([a["id"], a["source_person"], a.get("source_speaker"), a["source_recording"], a["source_anchor_id"], a["narrative_title"],
                    a.get("relative_time"), a.get("source_start_ts"), a.get("source_end_ts"),
                    round(a["gx"], 3), round(a["gy"], 3), round(a["gz"], 3)])

json.dump({"parts": [{k: p[k] for k in ("id", "person", "speaker", "color", "t_offset_us", "fit_rmse_m", "n_events")}
                     | {"n_anchors": len(p["anchors"])} for p in parts],
           "enu_origin": [lat0, lon0, alt0], "geo_source": "manual" if args.manual_geo else "mps",
           "manual_geo": args.manual_geo, "heading_deg": args.heading if args.manual_geo else None, "points": int(len(pts)), "anchors": len(merged)},
          open(out / "combine_params.json", "w"), indent=2)
print(f"wrote {len(merged)} anchors, {len(pts)} points, {len(path)} path points -> {out}")
