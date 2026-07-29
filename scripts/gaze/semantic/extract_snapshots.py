#!/usr/bin/env python3
"""
Extract candidate RGB snapshots per transcript segment from a VRS, keyed by
seg_idx — frames of what the wearer saw while that segment was spoken, so you can
pick the best one per segment.

Per segment it samples --frames evenly-spaced interior timestamps (default 3:
before / center / after — avoiding boundary transition frames), pulls the CLOSEST
camera-rgb frame at each, optionally overlays the segment's mean gaze, uprights +
downscales, and writes:
    seg_<idx>_<f>.jpg          (f = 0..frames-1; or seg_<idx>.jpg when --frames 1)
With --update-csv it adds:
    snapshot_path        the CENTER candidate (a sensible default pick)
    snapshot_candidates  ";"-joined list of all candidates for that segment

Timestamp: uses t_start_device_ns/t_end_device_ns if present (fusion tables have
them, in the device clock — same domain as the RGB frames), else
audio_t0_ns + t_s*1e9.

Primary use (the EXPERT's own view) — run on the Adine fusion + Adine VRS:
  python extract_snapshots.py --vrs CaronaAdine1.vrs \
      --segments CaronaAdine1_fusion_m8.csv --output-dir snaps_Adine1 \
      --frames 3 --gaze-overlay --update-csv

NB: the gaze overlay uses the pipeline's crude pinhole projection (uncalibrated
fisheye) and the segment-MEAN gaze, so all candidates share the same dot — a rough
"look-here" indicator, not pixel-exact.
"""
import os
import csv
import argparse
import numpy as np
from PIL import Image, ImageDraw
from projectaria_tools.core import data_provider
from projectaria_tools.core.sensor_data import TimeDomain, TimeQueryOptions


def grab(dp, rgb, t_ns, gaze, rotate, max_size):
    """Closest RGB frame at t_ns -> processed PIL image (optional gaze overlay,
    upright, downscaled). gaze = (yaw, pitch) or None. Returns None on failure."""
    idx = dp.get_index_by_time_ns(rgb, int(t_ns), TimeDomain.DEVICE_TIME, TimeQueryOptions.CLOSEST)
    fd = dp.get_image_data_by_index(rgb, idx)
    if not fd:
        return None
    img = Image.fromarray(fd[0].to_numpy_array())
    if gaze is not None:
        yaw, pitch = gaze
        w, h = img.size
        px = w / 2 + np.tan(yaw) * (w / 1.5)
        py = h / 2 + np.tan(pitch) * (h / 1.5)
        d = ImageDraw.Draw(img)
        rr = 18
        d.ellipse([px - rr, py - rr, px + rr, py + rr], outline="red", width=5)
    arr = np.array(img)
    if rotate % 4:
        arr = np.rot90(arr, k=rotate)
    img = Image.fromarray(arr)
    img.thumbnail((max_size, max_size))
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vrs", required=True)
    ap.add_argument("--segments", required=True, help="CSV with seg_idx + t_*_device_ns (or t_start_s)")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--audio-t0", help="device-clock origin (file or int) if the CSV lacks t_*_device_ns")
    ap.add_argument("--frames", type=int, default=3,
                    help="candidate frames per segment, evenly spaced inside it "
                         "(default 3: before/center/after; 1 = just the midpoint)")
    ap.add_argument("--gaze-overlay", action="store_true",
                    help="overlay the segment mean gaze (needs gaze_yaw/pitch_mean_rad)")
    ap.add_argument("--rotate", type=int, default=3,
                    help="np.rot90 k to upright the Aria RGB (0 = native; default 3)")
    ap.add_argument("--max-size", type=int, default=1024, help="downscale longest side (px)")
    ap.add_argument("--update-csv", action="store_true",
                    help="write <segments>_snap.csv with snapshot_path + snapshot_candidates")
    ap.add_argument("--limit", type=int, help="only the first N segments (smoke test)")
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    dp = data_provider.create_vrs_data_provider(args.vrs)
    rgb = dp.get_stream_id_from_label("camera-rgb")

    audio_t0 = None
    if args.audio_t0:
        audio_t0 = (int(open(args.audio_t0).read().strip())
                    if os.path.exists(args.audio_t0) else int(args.audio_t0))

    rows = list(csv.DictReader(open(args.segments)))
    if args.limit:
        rows = rows[:args.limit]

    out_name = os.path.basename(args.output_dir.rstrip("/"))
    n = max(1, args.frames)
    fracs = [(i + 1) / (n + 1) for i in range(n)]   # interior, evenly spaced
    center = n // 2                                  # the middle candidate

    seg_saved = frame_saved = 0
    for r in rows:
        si = int(r["seg_idx"])
        if r.get("t_start_device_ns") and r.get("t_end_device_ns"):
            t0, t1 = int(r["t_start_device_ns"]), int(r["t_end_device_ns"])
        elif audio_t0 is not None:
            t0 = audio_t0 + int(float(r["t_start_s"]) * 1e9)
            t1 = audio_t0 + int(float(r["t_end_s"]) * 1e9)
        else:
            raise SystemExit("CSV lacks t_*_device_ns columns; pass --audio-t0")

        gaze = None
        if args.gaze_overlay and r.get("gaze_yaw_mean_rad") not in (None, ""):
            gaze = (float(r["gaze_yaw_mean_rad"]), float(r["gaze_pitch_mean_rad"]))

        paths = []
        for fi, frac in enumerate(fracs):
            t_ns = t0 + int(frac * (t1 - t0))
            try:
                img = grab(dp, rgb, t_ns, gaze, args.rotate, args.max_size)
            except Exception as e:
                img = None
                print(f"  seg {si} frame {fi}: {str(e)[:50]}")
            if img is None:
                continue
            fn = f"seg_{si:04d}.jpg" if n == 1 else f"seg_{si:04d}_{fi}.jpg"
            img.save(os.path.join(args.output_dir, fn), quality=88)
            paths.append(f"{out_name}/{fn}")
            frame_saved += 1

        if paths:
            seg_saved += 1
            r["snapshot_path"] = paths[center] if center < len(paths) else paths[0]
        else:
            r["snapshot_path"] = ""
        if n > 1:
            r["snapshot_candidates"] = ";".join(paths)
        if seg_saved and seg_saved % 50 == 0:
            print(f"  {seg_saved} segments ({frame_saved} frames)...")

    print(f"wrote {frame_saved} frames for {seg_saved}/{len(rows)} segments to {args.output_dir}/")
    if args.update_csv:
        out_csv = args.segments[:-4] + "_snap.csv"
        cols = list(rows[0].keys())
        for c in ("snapshot_path", "snapshot_candidates"):
            if c not in cols and any(c in r for r in rows):
                cols.append(c)
        with open(out_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print(f"-> {out_csv} (snapshot_path = center pick; snapshot_candidates = all)")


if __name__ == "__main__":
    main()
