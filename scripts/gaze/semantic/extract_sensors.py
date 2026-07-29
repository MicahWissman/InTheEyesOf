#!/usr/bin/env python3
"""
Extract the raw sensor streams needed for a fusion table from an Aria VRS:
  <prefix>_imu.csv       imu-right + imu-left: stream, t_ns, ax/ay/az, gx/gy/gz
  <prefix>_gps.csv       t_ns, lat, lon, alt_m, accuracy_m
  <prefix>_audio_t0.txt  device-clock ns of audio sample 0 (the fusion offset)

Audio WAV is handled separately by vrs_to_audio_direct.py. This mirrors the
sensor part of the upstream extract_adine.py.

Usage:
  python extract_sensors.py --vrs Carona_02.vrs --out-prefix /path/Carona_02
"""
import os
import csv
import sys
import argparse
from projectaria_tools.core import data_provider


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vrs", required=True)
    ap.add_argument("--out-prefix", required=True)
    args = ap.parse_args()

    dp = data_provider.create_vrs_data_provider(args.vrs)
    labels = {dp.get_label_from_stream_id(s): s for s in dp.get_all_streams()}

    # audio_t0 (device-clock ns of first audio sample)
    mic = labels["mic"]
    _, rec0 = dp.get_audio_data_by_index(mic, 0)
    audio_t0_ns = rec0.capture_timestamps_ns[0]
    with open(f"{args.out_prefix}_audio_t0.txt", "w") as f:
        f.write(str(audio_t0_ns))
    print(f"audio_t0_ns = {audio_t0_ns} ({audio_t0_ns/1e9:.1f}s)")

    # IMU (all imu-* streams)
    imu_sids = [labels[k] for k in labels if "imu" in k]
    with open(f"{args.out_prefix}_imu.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["stream", "t_ns", "ax", "ay", "az", "gx", "gy", "gz"])
        for s in imu_sids:
            lab = dp.get_label_from_stream_id(s)
            m = dp.get_num_data(s)
            for i in range(m):
                d = dp.get_imu_data_by_index(s, i)
                wr.writerow([lab, d.capture_timestamp_ns,
                             d.accel_msec2[0], d.accel_msec2[1], d.accel_msec2[2],
                             d.gyro_radsec[0], d.gyro_radsec[1], d.gyro_radsec[2]])
                if i % 200000 == 0:
                    sys.stderr.write(f"\r  IMU {lab}: {i}/{m}")
                    sys.stderr.flush()
            sys.stderr.write(f"\r  IMU {lab}: {m} samples\n")

    # GPS
    gps = labels.get("gps")
    if gps:
        m = dp.get_num_data(gps)
        with open(f"{args.out_prefix}_gps.csv", "w", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(["t_ns", "lat", "lon", "alt_m", "accuracy_m"])
            for i in range(m):
                d = dp.get_gps_data_by_index(gps, i)
                wr.writerow([d.capture_timestamp_ns, d.latitude, d.longitude,
                             d.altitude, getattr(d, "accuracy", None)])
        print(f"GPS: {m} fixes")
    else:
        print("GPS: no stream found")

    print(f"done -> {args.out_prefix}_{{imu.csv,gps.csv,audio_t0.txt}}")


if __name__ == "__main__":
    main()
