#!/usr/bin/env python3
"""
Build a multimodal fusion table (one row per transcript segment), joining on the
device clock: transcript x eye-gaze x head-IMU x GPS(+speed) x hand-tracking,
with body_state = walking / scanning / dwelling. Column set matches the upstream
Adine fusion tables so device-1 and device-2 tables are directly comparable.

Generalized from fuse_adine.py — all inputs are explicit paths so it runs for any
recording/device.

CLOCK:  transcript is WAV-relative; sensors are device-time.
        t_device_ns = audio_t0_ns + seg_seconds * 1e9
        gaze/hand us -> ns (x1000); IMU/GPS already ns.

Usage:
  python build_fusion.py --transcript Carona_02_m3.csv --gaze .../general_eye_gaze.csv \
     --hand .../hand_tracking_results.csv --imu Carona_02_imu.csv --gps Carona_02_gps.csv \
     --audio-t0 Carona_02_audio_t0.txt --out Carona_02_fusion.csv
"""
import os
import csv
import json
import argparse
import numpy as np
import pandas as pd

WALK_SPEED = 0.5     # m/s -> walking
GYRO_SCAN = 0.25     # rad/s (stationary) above this -> scanning, else dwelling
SMOOTH_FIXES = 5     # GPS speed smoothing window (fixes ~ seconds)


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = np.radians(lat2 - lat1); dl = np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def wmean(ts, v, lo, hi):
    i0 = np.searchsorted(ts, lo, "left"); i1 = np.searchsorted(ts, hi, "right")
    if i1 <= i0:
        j = min(max(np.searchsorted(ts, (lo + hi) // 2), 0), len(ts) - 1)
        return v[j]
    return np.nanmean(v[i0:i1], axis=0)


def wstd(ts, v, lo, hi):
    i0 = np.searchsorted(ts, lo, "left"); i1 = np.searchsorted(ts, hi, "right")
    return float(np.nanstd(v[i0:i1])) if i1 > i0 + 1 else 0.0


def load_segments(path):
    """Native CSV (t_start_s,t_end_s,transcript) or whisper JSON ({'segments':[...]})."""
    if path.endswith(".json"):
        return [(float(s["start"]), float(s["end"]), s["text"].strip())
                for s in json.load(open(path))["segments"]]
    out = []
    for r in csv.DictReader(open(path)):
        out.append((float(r["t_start_s"]), float(r["t_end_s"]), r["transcript"].strip()))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--gaze", required=True)
    ap.add_argument("--hand")
    ap.add_argument("--imu", required=True)
    ap.add_argument("--gps")
    ap.add_argument("--audio-t0", required=True, help="file with audio_t0_ns, or the integer itself")
    ap.add_argument("--out", required=True)
    ap.add_argument("--discourse", help="sidecar discourse CSV (seg_idx,level,label,confidence) "
                                        "to join per segment")
    args = ap.parse_args()

    AUDIO_T0_NS = int(open(args.audio_t0).read().strip()) if os.path.exists(args.audio_t0) else int(args.audio_t0)
    print(f"audio_t0_ns = {AUDIO_T0_NS} ({AUDIO_T0_NS/1e9:.1f}s)")

    segs = load_segments(args.transcript)
    print(f"transcript: {len(segs)} segments")

    disc = None
    if args.discourse and os.path.exists(args.discourse):
        disc = {int(r["seg_idx"]): r for r in csv.DictReader(open(args.discourse))}
        print(f"discourse: {len(disc)} labeled segments")

    # gaze (us -> ns)
    g = pd.read_csv(args.gaze)
    g_ts = (g["tracking_timestamp_us"].to_numpy() * 1000).astype(np.int64)
    o = np.argsort(g_ts); g_ts = g_ts[o]
    g_yaw = ((g["left_yaw_rads_cpf"] + g["right_yaw_rads_cpf"]) / 2).to_numpy()[o]
    g_pitch = g["pitch_rads_cpf"].to_numpy()[o]
    g_depth = g["depth_m"].to_numpy()[o]
    g_vals = np.column_stack([g_yaw, g_pitch, g_depth])
    print(f"gaze: {len(g_ts)} samples")

    # IMU (imu-right)
    im = pd.read_csv(args.imu); im = im[im["stream"] == "imu-right"]
    i_ts = im["t_ns"].to_numpy().astype(np.int64)
    o = np.argsort(i_ts); i_ts = i_ts[o]
    accel_mag = np.sqrt(im["ax"] ** 2 + im["ay"] ** 2 + im["az"] ** 2).to_numpy()[o]
    gyro_mag = np.sqrt(im["gx"] ** 2 + im["gy"] ** 2 + im["gz"] ** 2).to_numpy()[o]
    print(f"IMU(imu-right): {len(i_ts)} samples")

    # GPS + smoothed speed
    have_gps = args.gps and os.path.exists(args.gps)
    if have_gps:
        gp = pd.read_csv(args.gps).sort_values("t_ns").reset_index(drop=True)
        p_ts = gp["t_ns"].to_numpy().astype(np.int64)
        p_lat = gp["lat"].to_numpy(); p_lon = gp["lon"].to_numpy()
        t_s = p_ts / 1e9
        dist = haversine_m(p_lat[:-1], p_lon[:-1], p_lat[1:], p_lon[1:])
        dt = np.diff(t_s); dt[dt == 0] = 1e-3
        spd = np.concatenate([[0.0], dist / dt])
        spd = pd.Series(spd).rolling(SMOOTH_FIXES, center=True, min_periods=1).median().to_numpy()
        print(f"GPS: {len(p_ts)} fixes")

    # hand (us -> ns)
    have_hand = args.hand and os.path.exists(args.hand)
    if have_hand:
        h = pd.read_csv(args.hand)
        h_ts = (h["tracking_timestamp_us"].to_numpy() * 1000).astype(np.int64)
        o = np.argsort(h_ts); h_ts = h_ts[o]
        h_lc = h["left_tracking_confidence"].to_numpy()[o]
        h_rc = h["right_tracking_confidence"].to_numpy()[o]
        print(f"hand: {len(h_ts)} frames")

    rows = []
    for k, (start, end, text) in enumerate(segs):
        t0 = AUDIO_T0_NS + int(start * 1e9)
        t1 = AUDIO_T0_NS + int(end * 1e9)
        tm = (t0 + t1) // 2
        gm = wmean(g_ts, g_vals, t0, t1)
        am = float(wmean(i_ts, accel_mag, t0, t1))
        gym = float(wmean(i_ts, gyro_mag, t0, t1))
        row = {
            "seg_idx": k, "t_start_s": round(start, 2), "t_end_s": round(end, 2),
            "t_start_device_ns": t0, "t_end_device_ns": t1,
            "transcript": text,
            "gaze_yaw_mean_rad": round(float(gm[0]), 4),
            "gaze_pitch_mean_rad": round(float(gm[1]), 4),
            "gaze_depth_mean_m": round(float(gm[2]), 3),
            "gaze_yaw_std_rad": round(wstd(g_ts, g_yaw, t0, t1), 4),
            "head_accel_mag_mean": round(am, 3),
            "head_gyro_mag_mean": round(gym, 4),
        }
        if have_gps:
            j = min(max(np.searchsorted(p_ts, tm), 0), len(p_ts) - 1)
            speed = float(spd[j])
            row["gps_speed_mps"] = round(speed, 3)
            row["body_state"] = "walking" if speed > WALK_SPEED else ("scanning" if gym > GYRO_SCAN else "dwelling")
            row["lat"] = round(float(p_lat[j]), 7); row["lon"] = round(float(p_lon[j]), 7)
        else:
            row["gps_speed_mps"] = ""
            row["body_state"] = "scanning" if gym > GYRO_SCAN else "dwelling"
            row["lat"] = ""; row["lon"] = ""
        if have_hand:
            i0 = np.searchsorted(h_ts, t0, "left"); i1 = np.searchsorted(h_ts, t1, "right")
            row["left_hand_visible_frac"] = round(float(np.mean(h_lc[i0:i1] >= 0)), 3) if i1 > i0 else 0.0
            row["right_hand_visible_frac"] = round(float(np.mean(h_rc[i0:i1] >= 0)), 3) if i1 > i0 else 0.0
        if disc is not None:
            d = disc.get(k, {})
            row["discourse_level"] = d.get("level", "")
            row["discourse_label"] = d.get("label", "")
            row["discourse_confidence"] = d.get("confidence", "")
        rows.append(row)

    df = pd.DataFrame(rows)
    df.to_csv(args.out, index=False)
    print(f"\nwrote {args.out}  ({len(df)} rows)")
    print("body_state:", df["body_state"].value_counts().to_dict())


if __name__ == "__main__":
    main()
