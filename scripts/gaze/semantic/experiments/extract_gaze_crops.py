#!/usr/bin/env python3
"""
VISUAL-GROUNDING PILOT — STAGE A: extract gaze-centered RGB crops.
Runs in the `aria_tools` conda env (needs projectaria_tools).

For N sampled anchors it:
  - picks a representative timestamp (anchor midpoint),
  - finds the nearest MPS eye-gaze sample,
  - projects the gaze ray into the RGB camera using the CALIBRATED fisheye
    model (get_gaze_vector_reprojection) at the expert's measured fixation
    depth -- NOT the old pinhole approximation,
  - pulls the nearest RGB frame from the .vrs,
  - saves a foveal crop around the gaze pixel + a marked full-frame preview,
  - writes manifest.json carrying the transcript-derived objects for Stage B.

Stage B (dino_ground.py, base env) consumes manifest.json.

Usage (defaults target StegerCenter1):
  /opt/homebrew/Caskroom/miniconda/base/envs/aria_tools/bin/python extract_gaze_crops.py \
    --anchors web-viewer/public/recordings/StegerCenter1_enriched2/narrative_anchors.json \
    --vrs ../../reccordings_aria/StegerCenter1.vrs \
    --gaze-csv ../../reccordings_aria/mps_StegerCenter1_vrs/eye_gaze/general_eye_gaze.csv \
    --out scripts/gaze/semantic/experiments/pilot_out --n 12
(invoke the env python directly; `conda run` swallows --n)
"""

import os
import json
import argparse
import numpy as np
from PIL import Image, ImageDraw

from projectaria_tools.core import data_provider
from projectaria_tools.core.sensor_data import TimeDomain, TimeQueryOptions
import projectaria_tools.core.mps as mps
from projectaria_tools.core.mps.utils import get_nearest_eye_gaze, get_gaze_vector_reprojection

CROP_FRAC = 0.20       # half-window of the foveal crop, as fraction of max(w,h)
RGB_LABEL = "camera-rgb"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anchors", required=True)
    ap.add_argument("--vrs", required=True)
    ap.add_argument("--gaze-csv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=12, help="number of anchors to sample")
    ap.add_argument("--rot90", type=int, default=3,
                    help="np.rot90 k applied to crop to make it upright for DINO "
                         "(Aria raw RGB is rotated 90 deg CW; k=3 undoes it)")
    args = ap.parse_args()

    crops_dir = os.path.join(args.out, "crops")
    prev_dir = os.path.join(args.out, "previews")
    os.makedirs(crops_dir, exist_ok=True)
    os.makedirs(prev_dir, exist_ok=True)

    anchors = json.load(open(args.anchors))
    usable = [(i, a) for i, a in enumerate(anchors) if a.get("start_ts") and a.get("end_ts")]
    idx = np.linspace(0, len(usable) - 1, min(args.n, len(usable))).astype(int)
    sampled = [usable[i] for i in sorted(set(idx))]
    print(f"Sampling {len(sampled)} / {len(anchors)} anchors")

    eyegazes = mps.read_eyegaze(args.gaze_csv)
    provider = data_provider.create_vrs_data_provider(args.vrs)
    rgb_stream = provider.get_stream_id_from_label(RGB_LABEL)
    device_calib = provider.get_device_calibration()
    rgb_calib = device_calib.get_camera_calib(RGB_LABEL)

    manifest = []
    for orig_i, a in sampled:
        aid = a.get("id")
        if aid is None:
            aid = orig_i
        key = orig_i  # always-unique filename key (anchor ids can collide/be null)
        rep_ts_us = int((a["start_ts"] + a["end_ts"]) // 2)

        # nearest calibrated eye-gaze sample
        eg = get_nearest_eye_gaze(eyegazes, rep_ts_us * 1000)
        depth = float(eg.depth) if (eg.depth and eg.depth > 0) else 1.0
        depth = min(max(depth, 0.35), 10.0)

        # calibrated fisheye reprojection into the RAW rgb frame (make_upright=False)
        reproj = get_gaze_vector_reprojection(eg, RGB_LABEL, device_calib, rgb_calib, depth, False)
        if reproj is None:
            print(f"  anchor {aid}: gaze outside RGB FOV; skipping")
            continue
        px, py = float(reproj[0]), float(reproj[1])

        # nearest RGB frame
        try:
            vrs_idx = provider.get_index_by_time_ns(
                rgb_stream, rep_ts_us * 1000, TimeDomain.DEVICE_TIME, TimeQueryOptions.CLOSEST)
            fd = provider.get_image_data_by_index(rgb_stream, vrs_idx)
            img = Image.fromarray(fd[0].to_numpy_array())
        except Exception as e:
            print(f"  anchor {aid}: frame fetch failed ({e}); skipping")
            continue

        w, h = img.size
        # foveal crop (clamped), rotated upright for the detector
        hw = int(CROP_FRAC * max(w, h))
        box = (int(max(px - hw, 0)), int(max(py - hw, 0)),
               int(min(px + hw, w)), int(min(py + hw, h)))
        crop = img.crop(box)
        if args.rot90:
            crop = Image.fromarray(np.rot90(np.array(crop), k=args.rot90))

        crop_path = os.path.join(crops_dir, f"anchor_{key:03d}.png")
        crop.save(crop_path)

        # marked preview (full frame, downscaled) for visual sanity-check
        prev = img.copy()
        d = ImageDraw.Draw(prev)
        r = max(w, h) // 60
        d.ellipse([px - r, py - r, px + r, py + r], outline="red", width=6)
        d.rectangle(box, outline="yellow", width=4)
        prev.thumbnail((640, 640))
        prev.save(os.path.join(prev_dir, f"anchor_{key:03d}.jpg"))

        manifest.append({
            "anchor_id": aid,
            "cluster_id": a.get("cluster_id"),
            "narrative_title": a.get("narrative_title"),
            "rep_ts_us": rep_ts_us,
            "gaze_px": round(px, 1), "gaze_py": round(py, 1),
            "fixation_depth_m": round(depth, 2),
            "img_w": w, "img_h": h,
            "crop_path": os.path.relpath(crop_path, args.out),
            "transcript_objects": a.get("objects", []) or [],
        })
        print(f"  anchor {aid:>3}: gaze=({px:.0f},{py:.0f}) depth={depth:.2f}m "
              f"crop={box} objs={len(manifest[-1]['transcript_objects'])}")

    with open(os.path.join(args.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nWrote {len(manifest)} crops + manifest to {args.out}")
    print("Inspect previews/ to verify the gaze point lands on the intended object.")


if __name__ == "__main__":
    main()
