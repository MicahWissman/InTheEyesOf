#!/usr/bin/env python3
"""
Fit per-recording linear time maps between two Aria devices from matched
transcript segments (the SAME utterance captured by both mics).

    t_target = slope * t_source + offset     (one fit per source recording)

slope ~ 1 means the device clocks barely drift; offset is the per-recording
start difference. Because each source recording (Adine1/2/3) has its own clock
origin, each gets its own fit. Writes timemap.json and prints diagnostics
(residuals, drift, and the duration mismatch of the matched segments — a check
on how well the control points actually correspond).

Usage:
  python fit_device_timemap.py --base-dir /path/to/Carona --out timemap.json
"""

import os
import csv
import json
import argparse
import numpy as np

# source(Adine) recording -> (source_csv, target_csv, [(src_seg_idx, dst_seg_idx), ...])
CONFIG = {
    "Adine1": ("CaronaAdine1_forJavi_m3.csv", "Carona_02_m3.csv",
               [(11, 16), (12, 17), (18, 22), (56, 50), (90, 97), (100, 113), (237, 274)]),
    "Adine2": ("CaronaAdine2_forJavi_m3.csv", "Carona_03_m3.csv",
               [(5, 0), (422, 448), (498, 558)]),
    "Adine3": ("CaronaAdine3_forJavi_m3.csv", "Carona_03_m3.csv",
               [(2, 576), (30, 596), (157, 713)]),
}


def load(path):
    return {int(r["seg_idx"]): (float(r["t_start_s"]), float(r["t_end_s"]))
            for r in csv.DictReader(open(path))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-dir", default=".")
    ap.add_argument("--out", default="timemap.json")
    ap.add_argument("--config", help='JSON {name:{"src":csv,"dst":csv,"pairs":[[src_idx,dst_idx],...]}} '
                                      'of control points (default: the baked-in m3 set)')
    ap.add_argument("--fixed-slope", action="store_true",
                    help="force slope=1 with a robust median offset (use when the device clocks "
                         "are synced; robust to sparse/noisy control points)")
    args = ap.parse_args()

    if args.config:
        raw = json.load(open(args.config))
        config = {k: (v["src"], v["dst"], [tuple(p) for p in v["pairs"]]) for k, v in raw.items()}
    else:
        config = CONFIG

    timemap = {}
    for name, (src_csv, dst_csv, pairs) in config.items():
        src = load(os.path.join(args.base_dir, src_csv))
        dst = load(os.path.join(args.base_dir, dst_csv))
        xs = np.array([src[a][0] for a, _ in pairs])
        ys = np.array([dst[b][0] for _, b in pairs])
        if args.fixed_slope:
            slope, offset = 1.0, float(np.median(ys - xs))
        else:
            slope, offset = np.polyfit(xs, ys, 1)
        res = ys - (slope * xs + offset)
        dur_mismatch = [abs((src[a][1] - src[a][0]) - (dst[b][1] - dst[b][0])) for a, b in pairs]
        timemap[name] = {
            "target": dst_csv.split("_m3")[0],
            "slope": round(float(slope), 6),
            "offset_s": round(float(offset), 3),
            "n_points": len(pairs),
            "rms_residual_s": round(float(np.sqrt((res ** 2).mean())), 3),
            "max_residual_s": round(float(np.abs(res).max()), 3),
            "drift_ms_per_min": round(float((slope - 1) * 60 * 1000), 1),
            "mean_seg_dur_mismatch_s": round(float(np.mean(dur_mismatch)), 2),
        }
        print(f"{name} -> {timemap[name]['target']}: "
              f"t_target = {slope:.6f}*t + {offset:.2f}  | "
              f"rms={timemap[name]['rms_residual_s']}s drift={timemap[name]['drift_ms_per_min']}ms/min "
              f"dur_mismatch={timemap[name]['mean_seg_dur_mismatch_s']}s")

    with open(args.out, "w") as f:
        json.dump(timemap, f, indent=2)
    print(f"\nSaved {args.out}")


def apply_map(timemap, recording, t_seconds):
    """Map a source (Adine) time to the target (Carona) timeline."""
    m = timemap[recording]
    return m["slope"] * t_seconds + m["offset_s"]


if __name__ == "__main__":
    main()
