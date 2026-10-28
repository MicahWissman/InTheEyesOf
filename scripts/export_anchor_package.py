#!/usr/bin/env python3
"""
Export a self-contained ANCHOR PACKAGE for people who do not run the pipeline.

For every narrative anchor it writes a human-readable JSON record (time window,
topic, AI summary, verbatim expert transcript, gaze/body/hand context, related
anchors) plus N RGB frames from the expert's visual field while they were
fixating the anchor. No SLAM output (poses, point cloud, world coordinates) is
shipped; positions are given only as WGS84 lat/lon.

Two steps, so un-anonymized frames never land in the share folder:

  select   Re-derive the per-sample gaze (same load_data raycast as the
           summarizer), take event windows from semantic_results.json, group
           events into anchors (same
           complete-linkage radius as the synthesizer), pick frames, rectify
           them to an upright pinhole view, and write them + selection.json to
           a private STAGING dir.

  publish  Blur faces + licence plates in the staged frames with EgoBlur,
           draw per-anchor contact sheets (gaze marked there only), and write
           the share folder: anchors.json, per-anchor JSON, images, CSVs,
           README.

Frame selection (per anchor, default 20):
  * candidates = RGB frames nearest each gaze sample inside the anchor's
    viewing events, padded by --pad-s on both sides
  * role "fixation" = inside the event window and the gaze surface hit lies
    within --fixation_radius_m of the event centroid (the expert is looking at
    the anchor's target); otherwise "context"
  * fixation frames are split into equal-count time bins and the best-scoring
    frame of each bin is kept (score = sharpness rank + gaze quality); context
    frames top up the set the same way only when fixation frames run out

Usage (aria_tools env):
  python scripts/export_anchor_package.py select  --config tour1.json
  python scripts/export_anchor_package.py publish --config tour1.json \
      --face-model ego_blur_face.jit [--lp-model ego_blur_lp.jit]
"""
import argparse
import csv
import json
import math
import os
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.ndimage import laplace
from scipy.spatial.distance import pdist
from scipy.spatial.transform import Rotation as Rot

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "gaze", "semantic"))

SCHEMA_VERSION = "1.0"
EARTH_R = 6378137.0


# ── shared helpers ────────────────────────────────────────────────────────────

def load_config(path):
    cfg = json.load(open(path))
    cfg.setdefault("images_per_anchor", 20)
    cfg.setdefault("pad_s", 3.0)
    cfg.setdefault("group_radius_m", 30.0)
    cfg.setdefault("fixation_radius_m", 1.0)
    cfg.setdefault("transcript_context_s", 5.0)
    cfg.setdefault("image_size", 1024)
    cfg.setdefault("focal_px", 420.0)
    cfg.setdefault("jpeg_quality", 90)
    # EgoBlur's demo default is 0.9, but small/distant faces in Aria frames score
    # 0.4-0.7; false positives (foliage, lamps) only cost a harmless blur.
    cfg.setdefault("face_threshold", 0.3)
    cfg.setdefault("lp_threshold", 0.5)
    return cfg


def iso_utc(ns):
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).isoformat(timespec="milliseconds")


class Geo:
    """World (SLAM) point -> WGS84 lat/lon via the verified bake transform.

    world -> Three.js (R, t from the bake) -> ENU (east=x, north=-z, up=y) ->
    local tangent-plane lat/lon around the bake's ENU origin (sub-decimetre over
    a ~1 km tour)."""

    def __init__(self, xform_npz, baked_traj_json):
        x = np.load(xform_npz)
        self.R, self.t = x["R"], x["t"]
        o = json.load(open(baked_traj_json))["enu_origin"]
        self.lat0, self.lon0 = o["lat"], o["lon"]

    def latlon(self, p_world):
        p = np.asarray(p_world, dtype=float) @ self.R.T + self.t
        east, north = p[0], -p[2]
        lat = self.lat0 + math.degrees(north / EARTH_R)
        lon = self.lon0 + math.degrees(east / (EARTH_R * math.cos(math.radians(self.lat0))))
        return round(lat, 7), round(lon, 7)


# ── select ────────────────────────────────────────────────────────────────────

def sharpness(img):
    """Variance of the Laplacian on a 4x-downsampled grayscale centre crop."""
    g = img[::4, ::4].mean(axis=2)
    h, w = g.shape
    g = g[h // 6: -h // 6, w // 6: -w // 6]
    return float(laplace(g).var())


def pick_stratified(cands, k):
    """Split time-sorted candidates into k equal-count bins, keep each bin's best."""
    if k <= 0 or not cands:
        return []
    cands = sorted(cands, key=lambda c: c["t_ns"])
    if len(cands) <= k:
        return cands
    bins = np.array_split(np.arange(len(cands)), k)
    return [max((cands[i] for i in b), key=lambda c: c["score"]) for b in bins]


def cmd_select(cfg):
    import spatial_transcript_summarizer as S
    from projectaria_tools.core import calibration, data_provider
    from projectaria_tools.core.sensor_data import TimeDomain, TimeQueryOptions

    stage = cfg["staging_dir"]
    os.makedirs(stage, exist_ok=True)

    # 1. Per-sample gaze, same loader/raycast as Stage 1. Stage 1 subsamples the
    # point cloud with an unseeded RNG, so its DBSCAN labels can't be replayed;
    # events (windows + centroids) are taken from semantic_results.json and a
    # sample counts as fixation when its surface hit is within fixation_radius_m
    # of the event centroid. Seeded so this export is repeatable.
    np.random.seed(0)
    merged, _ = S.load_data(cfg["mps_root"])
    merged = merged.reset_index(drop=True)
    ref = json.load(open(cfg["semantic_results"]))

    # 2. Events -> anchors, same complete linkage as narrative_synthesizer.
    cent = np.array([[e["gx"], e["gy"], e["gz"]] for e in ref])
    labels = fcluster(linkage(pdist(cent), method="complete"), t=cfg["group_radius_m"], criterion="distance")
    groups = defaultdict(list)
    for i, lab in enumerate(labels):
        groups[lab].append(i)
    by_span = {(min(ref[i]["start_ts"] for i in g), max(ref[i]["end_ts"] for i in g)): g for g in groups.values()}

    anchors = json.load(open(cfg["anchors_world"]))
    for a in anchors:
        a["_events"] = by_span.get((a["start_ts"], a["end_ts"]))
        if a["_events"] is None:
            sys.exit(f"anchor {a['id']} has no matching event group (radius mismatch?)")

    # 3. Camera: rectified, upright pinhole view of the RGB fisheye.
    dp = data_provider.create_vrs_data_provider(cfg["vrs"])
    rgb = dp.get_stream_id_from_label("camera-rgb")
    src = dp.get_device_calibration().get_camera_calib("camera-rgb")
    size, f = cfg["image_size"], cfg["focal_px"]
    dst = calibration.get_linear_camera_calibration(size, size, f, "camera-rgb", src.get_transform_device_camera())
    dst_rot = calibration.rotate_camera_calib_cw90deg(dst)
    T_cam_dev = np.linalg.inv(dst_rot.get_transform_device_camera().to_matrix())

    ts_us = merged["tracking_timestamp_us"].to_numpy()
    q = merged[["qx_world_device", "qy_world_device", "qz_world_device", "qw_world_device"]].to_numpy()
    tw = merged[["tx_world_device", "ty_world_device", "tz_world_device"]].to_numpy()
    gw = merged[["gx", "gy", "gz"]].to_numpy()
    qual = merged["gaze_quality"].to_numpy()

    def gaze_px(i):
        p_dev = Rot.from_quat(q[i]).as_matrix().T @ (gw[i] - tw[i])
        p_cam = (T_cam_dev @ np.append(p_dev, 1.0))[:3]
        if p_cam[2] <= 0:
            return None
        uv = dst_rot.project(p_cam)
        return None if uv is None else [round(float(uv[0]), 1), round(float(uv[1]), 1)]

    raw_cache = {}

    def raw_frame(idx):
        if idx not in raw_cache:
            raw_cache.clear()  # frames are visited mostly in order; keep memory flat
            raw_cache[idx] = dp.get_image_data_by_index(rgb, idx)[0].to_numpy_array()
        return raw_cache[idx]

    pad_us = int(cfg["pad_s"] * 1e6)
    n_img = cfg["images_per_anchor"]
    selection = []
    for a in anchors:
        cands = {}
        for ei in a["_events"]:
            e = ref[ei]
            lo, hi = e["start_ts"] - pad_us, e["end_ts"] + pad_us
            for i in np.nonzero((ts_us >= lo) & (ts_us <= hi))[0]:
                fix = bool(e["start_ts"] <= ts_us[i] <= e["end_ts"] and
                           np.linalg.norm(gw[i] - [e["gx"], e["gy"], e["gz"]]) <= cfg["fixation_radius_m"])
                t_ns = int(ts_us[i]) * 1000
                idx = dp.get_index_by_time_ns(rgb, t_ns, TimeDomain.DEVICE_TIME, TimeQueryOptions.CLOSEST)
                prev = cands.get(idx)
                if prev and (prev["role"] == "fixation" or not fix):
                    continue
                cands[idx] = {"rgb_index": int(idx), "sample": int(i), "t_ns": t_ns,
                              "role": "fixation" if fix else "context", "event_id": e["id"],
                              "gaze_quality": float(qual[i])}
        cl = list(cands.values())
        for c in cl:
            c["sharpness"] = sharpness(raw_frame(c["rgb_index"]))
            c["gaze_px"] = gaze_px(c["sample"])
        ranks = {id(c): r for r, c in enumerate(sorted(cl, key=lambda c: c["sharpness"]))}
        for c in cl:
            c["score"] = ranks[id(c)] / max(len(cl) - 1, 1) + 0.5 * c["gaze_quality"] + (0.0 if c["gaze_px"] else -1.0)
        fixation = [c for c in cl if c["role"] == "fixation"]
        chosen = pick_stratified(fixation, n_img)
        chosen += pick_stratified([c for c in cl if c["role"] == "context"], n_img - len(chosen))
        chosen.sort(key=lambda c: c["t_ns"])

        adir = os.path.join(stage, f"anchor_{a['id']:02d}")
        os.makedirs(adir, exist_ok=True)
        for k, c in enumerate(chosen):
            raw = dp.get_image_data_by_index(rgb, c["rgb_index"])[0].to_numpy_array()
            rect = np.rot90(calibration.distort_by_calibration(raw, dst, src), k=3)
            c["file"] = f"anchor_{a['id']:02d}/img_{k:02d}.jpg"
            Image.fromarray(np.ascontiguousarray(rect)).save(os.path.join(stage, c["file"]), quality=cfg["jpeg_quality"])
            for key in ("sample", "score"):
                c.pop(key)
            c["sharpness"] = round(c["sharpness"], 1)
        nfix = sum(c["role"] == "fixation" for c in chosen)
        print(f"anchor {a['id']:2d}: {len(cl):4d} candidates ({len(fixation)} fixation) -> "
              f"{len(chosen)} images ({nfix} fixation)  {a['narrative_title']}")
        selection.append({"anchor_id": a["id"], "event_ids": [ref[i]["id"] for i in a["_events"]],
                          "event_windows_us": [[ref[i]["start_ts"], ref[i]["end_ts"]] for i in a["_events"]],
                          "expert_world_mid": tw[int(np.argmin(np.abs(ts_us - (a["start_ts"] + a["end_ts"]) // 2)))].tolist(),
                          "images": chosen})

    json.dump({"camera": {"model": "linear (pinhole), rectified from Aria RGB fisheye, rotated upright",
                          "width": size, "height": size, "focal_px": f,
                          "principal_point": [size / 2, size / 2]},
               "anchors": selection}, open(os.path.join(stage, "selection.json"), "w"), indent=1)
    print(f"staged -> {stage}  (NOT anonymized; run `publish`)")


# ── publish ───────────────────────────────────────────────────────────────────

class EgoBlur:
    """Face + licence-plate blurring with Meta's EgoBlur TorchScript models.

    Mirrors the reference demo (facebookresearch/EgoBlur script/demo_ego_blur.py):
    BGR CHW tensor in, NMS, score threshold, boxes scaled up before an
    elliptical blur. Runs on CPU: the d2go export traces constants on the CPU,
    so CUDA inputs fail with a device mismatch."""

    def __init__(self, face_model, lp_model, face_thr, lp_thr, nms_iou=0.3, scale=1.15):
        import torch
        import torchvision  # noqa: F401  registers torchvision::nms before torch.jit.load
        self.torch = torch
        self.dev = "cpu"
        self.models = []
        if face_model:
            self.models.append((torch.jit.load(face_model, map_location=self.dev).eval(), face_thr))
        if lp_model:
            self.models.append((torch.jit.load(lp_model, map_location=self.dev).eval(), lp_thr))
        self.nms_iou, self.scale = nms_iou, scale

    def boxes(self, rgb):
        import torchvision
        bgr = np.ascontiguousarray(rgb[:, :, ::-1].transpose(2, 0, 1))
        x = self.torch.from_numpy(bgr).to(self.dev)
        out = []
        with self.torch.no_grad():
            for model, thr in self.models:
                b, _, s, _ = model(x)
                keep = torchvision.ops.nms(b, s, self.nms_iou)
                b, s = b[keep].cpu().numpy(), s[keep].cpu().numpy()
                out += [bb for bb, ss in zip(b, s) if ss > thr]
        return out

    def apply(self, rgb):
        img = Image.fromarray(rgb)
        bl = img.filter(ImageFilter.GaussianBlur(radius=max(img.size) / 40))
        mask = Image.new("L", img.size, 0)
        d = ImageDraw.Draw(mask)
        found = self.boxes(rgb)
        for x0, y0, x1, y1 in found:
            cx, cy, w, h = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) * self.scale, (y1 - y0) * self.scale
            d.ellipse([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], fill=255)
        return Image.composite(bl, img, mask), len(found)


def contact_sheet(paths, imgs_meta, title, out, cols=5, thumb=320):
    rows = math.ceil(len(paths) / cols)
    head = 56
    sheet = Image.new("RGB", (cols * thumb, rows * thumb + head), (18, 18, 18))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 22)
        small = ImageFont.truetype("DejaVuSans.ttf", 15)
    except OSError:
        font = small = ImageFont.load_default()
    d.text((12, 14), title, fill=(240, 240, 240), font=font)
    for k, (p, m) in enumerate(zip(paths, imgs_meta)):
        im = Image.open(p)
        s = thumb / im.width
        im = im.resize((thumb, thumb))
        dd = ImageDraw.Draw(im)
        if m["gaze_px"]:
            gx, gy = m["gaze_px"][0] * s, m["gaze_px"][1] * s
            dd.ellipse([gx - 12, gy - 12, gx + 12, gy + 12], outline=(255, 40, 40), width=3)
        tag = f"{m['t_rec_s']:.1f}s" + ("" if m["role"] == "fixation" else " ctx")
        dd.rectangle([0, thumb - 24, 8 + 9 * len(tag), thumb], fill=(0, 0, 0))
        dd.text((4, thumb - 22), tag, fill=(255, 255, 255), font=small)
        sheet.paste(im, ((k % cols) * thumb, head + (k // cols) * thumb))
    sheet.save(out, quality=85)


def cmd_publish(cfg, face_model, lp_model):
    if not face_model:
        sys.exit("publish needs --face-model (EgoBlur .jit); "
                 "images are not written to the share folder un-anonymized.")
    stage, share = cfg["staging_dir"], cfg["share_dir"]
    sel = json.load(open(os.path.join(stage, "selection.json")))
    anchors = {a["id"]: a for a in json.load(open(cfg["anchors_world"]))}
    geo = Geo(cfg["xform_npz"], cfg["baked_trajectory"])
    audio_t0 = int(open(cfg["audio_t0"]).read().strip())
    utc_off = int(cfg["utc_minus_device_ns"])
    segs = list(csv.DictReader(open(cfg["segments_csv"])))
    fusion = list(csv.DictReader(open(cfg["fusion_csv"])))
    graph = json.load(open(cfg["semantic_graph"]))
    ctx_ns = int(cfg["transcript_context_s"] * 1e9)

    def t_rec(ns):
        return round((ns - audio_t0) / 1e9, 2)

    blur = EgoBlur(face_model, lp_model, cfg["face_threshold"], cfg["lp_threshold"])
    os.makedirs(os.path.join(share, "anchors", "images"), exist_ok=True)
    os.makedirs(os.path.join(share, "anchors", "contact_sheets"), exist_ok=True)

    records, total_boxes = [], 0
    for s in sel["anchors"]:
        a = anchors[s["anchor_id"]]
        aid = a["id"]
        wins = [(lo * 1000, hi * 1000) for lo, hi in s["event_windows_us"]]

        # images: blur, then write
        imgs, paths = [], []
        for m in s["images"]:
            rgb = np.asarray(Image.open(os.path.join(stage, m["file"])).convert("RGB"))
            out_img, nb = blur.apply(rgb)
            total_boxes += nb
            rel = f"images/{m['file']}"
            p = os.path.join(share, "anchors", rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            out_img.save(p, quality=cfg["jpeg_quality"])
            paths.append(p)
            imgs.append({"file": rel, "role": m["role"], "t_device_ns": m["t_ns"], "t_rec_s": t_rec(m["t_ns"]),
                         "utc": iso_utc(m["t_ns"] + utc_off), "gaze_px": m["gaze_px"],
                         "gaze_on_surface": m["gaze_quality"] >= 0.5, "sharpness": m["sharpness"],
                         "regions_blurred": nb})
        sheet_rel = f"contact_sheets/anchor_{aid:02d}.jpg"
        contact_sheet(paths, imgs, f"#{aid}  {a['narrative_title']}", os.path.join(share, "anchors", sheet_rel))

        # verbatim transcript in the viewing windows (+context, like the summarizer)
        def overlaps(r):
            t0 = audio_t0 + int(float(r["t_start_s"]) * 1e9)
            t1 = audio_t0 + int(float(r["t_end_s"]) * 1e9)
            return any(t1 >= lo - ctx_ns and t0 <= hi + ctx_ns for lo, hi in wins)
        tseg = [r for r in segs if overlaps(r)]
        frows = [r for r in fusion if overlaps(r)]
        body = Counter(r["body_state"] for r in frows)
        lh = [float(r["left_hand_visible_frac"]) for r in frows]
        rh = [float(r["right_hand_visible_frac"]) for r in frows]

        related = []
        for l in graph["links"]:
            if aid in (l["source"], l["target"]):
                other = l["target"] if l["source"] == aid else l["source"]
                related.append({"anchor_id": other, "title": anchors[other]["narrative_title"],
                                "weight": round(l["weight"], 3), "link_types": l["types"], "rationale": l["rationale"]})
        related.sort(key=lambda r: -r["weight"])

        start_ns, end_ns = a["start_ts"] * 1000, a["end_ts"] * 1000
        lat, lon = geo.latlon([a["gx"], a["gy"], a["gz"]])  # anchors_world: SLAM world frame
        elat, elon = geo.latlon(s["expert_world_mid"])
        rec = {
            "id": aid,
            "title": a["narrative_title"],
            "topic": {"objects": a.get("objects", []), "actions": a.get("actions", []),
                      "spatial_props": a.get("spatial_props", {})},
            "summary": a.get("narrative_description", ""),
            "expert_transcript": [{"seg_idx": int(r["seg_idx"]), "t_rec_s": [float(r["t_start_s"]), float(r["t_end_s"])],
                                   "text": r["transcript"]} for r in tseg],
            "time": {
                "start_rec_s": t_rec(start_ns), "end_rec_s": t_rec(end_ns),
                "span_s": round((end_ns - start_ns) / 1e9, 1),
                "start_utc": iso_utc(start_ns + utc_off), "end_utc": iso_utc(end_ns + utc_off),
                "start_device_ns": start_ns, "end_device_ns": end_ns,
                "viewing_windows_rec_s": [[t_rec(lo), t_rec(hi)] for lo, hi in wins],
                "viewing_total_s": round(sum(hi - lo for lo, hi in wins) / 1e9, 1),
            },
            "location": {"gaze_target_latlon": [lat, lon], "expert_position_latlon": [elat, elon]},
            "context": {
                "body_state_counts": dict(body),
                "left_hand_visible_frac": round(float(np.mean(lh)), 3) if lh else None,
                "right_hand_visible_frac": round(float(np.mean(rh)), 3) if rh else None,
                "gaze_sample_count": a.get("sample_count"),
                "gaze_on_surface_frac": round(1.0 - a.get("fallback_ratio", 0.0), 3),
                "fusion_seg_idx": [int(r["seg_idx"]) for r in frows],
            },
            "related_anchors": related,
            "contact_sheet": sheet_rel,
            "images": imgs,
        }
        records.append(rec)
        json.dump(rec, open(os.path.join(share, "anchors", "images", f"anchor_{aid:02d}", "anchor.json"), "w"),
                  indent=2, ensure_ascii=False)
        print(f"anchor {aid:2d}: {len(imgs)} images, {sum(i['regions_blurred'] for i in imgs)} regions blurred")

    doc = {
        "schema_version": SCHEMA_VERSION,
        "recording": cfg["recording"],
        "camera": sel["camera"],
        "time_base": ("t_rec_s = seconds since the first audio sample of the recording (same clock as "
                      "Tour1_seg0_segments.csv and Tour1_seg0_fusion.csv); *_device_ns = Aria device clock; "
                      "utc = device clock + constant offset from MPS."),
        "provenance": {
            "title, summary, topic": "AI-synthesized (Gemini, via the InTheEyesOf research service) from the transcript "
                                     "and gaze context. Interpretation, not ground truth.",
            "expert_transcript": "Verbatim speech, automatic transcription (faster-whisper large-v3); may contain ASR errors.",
            "related_anchors": "Semantic graph edges (embedding similarity + spatial proximity); rationale is AI-written.",
            "images": ("Aria RGB camera frames, rectified to a pinhole view and rotated upright; "
                       + ("faces and licence plates" if lp_model else "faces (licence plates NOT blurred)")
                       + f" blurred with EgoBlur (face score >= {cfg['face_threshold']}). gaze_px = where the "
                       "expert's gaze ray hit a surface, projected into the image (null if outside the frame)."),
            "location": "WGS84, derived from the device's GPS-aligned trajectory.",
        },
        "anchor_count": len(records),
        "anchors": records,
    }
    json.dump(doc, open(os.path.join(share, "anchors", "anchors.json"), "w"), indent=2, ensure_ascii=False)
    for src, name in cfg.get("share_copies", {}).items():
        os.makedirs(os.path.dirname(os.path.join(share, name)), exist_ok=True)
        shutil.copy(src, os.path.join(share, name))
    print(f"published -> {share}  ({len(records)} anchors, {sum(len(r['images']) for r in records)} images, "
          f"{total_boxes} regions blurred)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["select", "publish"])
    ap.add_argument("--config", required=True, help="JSON with input/output paths (see tour config example)")
    ap.add_argument("--face-model", help="EgoBlur face model (.jit)")
    ap.add_argument("--lp-model", help="EgoBlur licence-plate model (.jit)")
    args = ap.parse_args()
    cfg = load_config(args.config)
    if args.step == "select":
        cmd_select(cfg)
    else:
        cmd_publish(cfg, args.face_model, args.lp_model)


if __name__ == "__main__":
    main()
