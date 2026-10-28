#!/usr/bin/env python3
"""
vrs_to_euroc.py -- Export a Project Aria .vrs recording to a EuRoC-style
stereo-inertial dataset for open-source visual-inertial SLAM
(Kimera-VIO / Kimera-RPGO, ORB-SLAM3, and most VIO pipelines).

The Aria Gen1 *SLAM* cameras (camera-slam-left / camera-slam-right) are the
right choice for VIO: they are 640x480 monochrome *global-shutter* fisheye
cameras (the RGB camera is rolling-shutter and much harder for VIO). We dump
the two SLAM streams as cam0/cam1 and the 1000 Hz IMU as imu0.

Two output modes:
  * default (rectify): the fisheye SLAM frames are undistorted to a *pinhole*
    model. This is what Kimera-VIO requires (it assumes a pinhole + radial-
    tangential camera, like EuRoC). The fisheye periphery (extreme FOV) is
    dropped by the choice of target HFOV (--hfov, default 120 deg).
  * --no-rectify: raw fisheye frames are written unchanged (for ORB-SLAM3,
    which understands fisheye natively).

Output layout (standard EuRoC/MAV directory):
    <out>/mav0/cam0/data/<timestamp_ns>.png   + data.csv
    <out>/mav0/cam1/data/<timestamp_ns>.png   + data.csv
    <out>/mav0/imu0/data.csv
    <out>/mav0/imu1/data.csv                  (optional --second-imu)
    <out>/mav0/cam0/sensor.yaml               (Kimera calibration)
    <out>/mav0/cam1/sensor.yaml
    <out>/mav0/imucal.yaml                    (body->IMU transform)
    <out>/mav0/orb_slam3_stereo_inertial.yaml (ORB-SLAM3 pinhole config)
    <out>/mav0/device_calibration.json        (raw Aria calibration, reference)

Usage:
  python scripts/gaze/semantic/vrs_to_euroc.py \\
      --vrs vrs-files/Carona1-001.vrs \\
      --out /tmp/aria_euroc \\
      --limit 200            # extract only first 200 frames (testing)

Notes:
  * Timestamps are written in DEVICE-CLOCK nanoseconds (EuRoC format), which
    is what Aria uses natively and what VIO makers ingest.
  * IMU accel is m/s^2 and gyro rad/s (already SI from Aria).
  * This is an interchange extractor: it produces a lossless standard dataset +
    calibration. Wiring it into a specific Kimera build (ROS bag vs standalone
    dataset reader) is a separate small integration step -- see
    documentation/kimera_vio_migration.md.
"""
import os
import csv
import json
import argparse
from pathlib import Path

import numpy as np

try:
    from projectaria_tools.core import data_provider
    from projectaria_tools.core.sensor_data import TimeDomain
    import projectaria_tools.core.calibration as cal
except ImportError:
    raise SystemExit("ERROR: projectaria_tools not found. Activate the aria_tools env.")


def _bilinear_remap(img, map_x, map_y):
    """Vectorized bilinear remap (drop-in for cv2.remap INTER_LINEAR)."""
    H, W = img.shape
    x0 = np.floor(map_x).astype(np.int32)
    y0 = np.floor(map_y).astype(np.int32)
    fx = map_x - x0
    fy = map_y - y0
    x0c = np.clip(x0, 0, W - 1)
    x1c = np.clip(x0 + 1, 0, W - 1)
    y0c = np.clip(y0, 0, H - 1)
    y1c = np.clip(y0 + 1, 0, H - 1)
    v00 = img[y0c, x0c]
    v10 = img[y0c, x1c]
    v01 = img[y1c, x0c]
    v11 = img[y1c, x1c]
    return (v00 * (1 - fx) * (1 - fy) + v10 * fx * (1 - fy) +
            v01 * (1 - fx) * fy + v11 * fx * fy)


def _se3_to_matrix(T):
    """4x4 numpy array from a sophus SE3."""
    return np.asarray(T.to_matrix(), dtype=np.float64)


def build_rect_map(src_calib, hfov_deg):
    """Build a pinhole rectification remap (dst->src) for a fisheye camera.

    For each output pixel of the pinhole target we compute the camera ray and
    ask the SOURCE (fisheye) calibration where that ray lands.
    Returns (map_x, map_y, fx, fy, cx, cy)."""
    W, H = int(src_calib.get_image_size()[0]), int(src_calib.get_image_size()[1])
    fov = np.deg2rad(hfov_deg)
    fx = fy = (W / 2.0) / np.tan(fov / 2.0)
    cx = (W - 1) / 2.0
    cy = (H - 1) / 2.0
    u, v = np.meshgrid(np.arange(W), np.arange(H))
    flat = np.vstack([(u.ravel() - cx) / fx, (v.ravel() - cy) / fy, np.ones(u.size)])
    map_x = np.full((H, W), np.nan, dtype=np.float32)
    map_y = np.full((H, W), np.nan, dtype=np.float32)
    # project() accepts a single [3] point; loop is ~0.3 s for 640x480.
    for i in range(flat.shape[1]):
        try:
            sp = src_calib.project(flat[:, i])
            map_x.ravel()[i], map_y.ravel()[i] = float(sp[0]), float(sp[1])
        except Exception:
            pass  # leave NaN -> clamped below
    nan = np.isnan(map_x) | np.isnan(map_y)
    out_of = nan | (map_x < 0) | (map_y < 0) | (map_x >= W) | (map_y >= H)
    map_x = np.nan_to_num(map_x, nan=0.0)
    map_y = np.nan_to_num(map_y, nan=0.0)
    map_x[out_of] = 0.0
    map_y[out_of] = 0.0
    if out_of.any():
        print(f"  note: {int(out_of.sum())} dest pixels map outside fisheye FOV "
              "(edge) -> they sample the border pixel.")
    return map_x.astype(np.float32), map_y.astype(np.float32), fx, fy, cx, cy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vrs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cam0", default="camera-slam-left")
    ap.add_argument("--cam1", default="camera-slam-right")
    ap.add_argument("--imu", default="imu-right")
    ap.add_argument("--second-imu", default=None, help="optional imu-left (800 Hz)")
    ap.add_argument("--no-rectify", action="store_true",
                    help="export raw fisheye frames instead of pinhole (for ORB-SLAM3)")
    ap.add_argument("--hfov", type=float, default=120.0, help="target pinhole HFOV (deg)")
    ap.add_argument("--limit", type=int, default=0, help="stop after N frames (0 = all)")
    ap.add_argument("--rgb", action="store_true", help="also export the RGB stream to rgb/")
    ap.add_argument("--imu-noise-gyro", type=float, default=1.0e-3)
    ap.add_argument("--imu-noise-accel", type=float, default=1.0e-2)
    ap.add_argument("--imu-gyro-walk", type=float, default=1.0e-5)
    ap.add_argument("--imu-accel-walk", type=float, default=1.0e-3)
    args = ap.parse_args()

    vrs = Path(args.vrs)
    out = Path(args.out)
    if not vrs.exists():
        raise SystemExit(f"VRS not found: {vrs}")
    out.mkdir(parents=True, exist_ok=True)

    prov = data_provider.create_vrs_data_provider(str(vrs))
    labels = {prov.get_label_from_stream_id(s): s for s in prov.get_all_streams()}
    dc = prov.get_device_calibration()

    def sid(label):
        if label not in labels:
            raise SystemExit(f"stream '{label}' not found. Available: {sorted(labels)}")
        return labels[label]

    # ---- IMU (imu0) -------------------------------------------------------
    imu_s = sid(args.imu)
    imu_n = prov.get_num_data(imu_s)
    imu_dir = out / "mav0" / "imu0"
    imu_dir.mkdir(parents=True, exist_ok=True)
    imu_csv = imu_dir / "data.csv"
    with open(imu_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["#timestamp [ns]", "w_RS_S_x [rad s^-1]", "w_RS_S_y [rad s^-1]",
                    "w_RS_S_z [rad s^-1]", "a_RS_S_x [m s^-2]", "a_RS_S_y [m s^-2]",
                    "a_RS_S_z [m s^-2]"])
        for i in range(imu_n):
            d = prov.get_imu_data_by_index(imu_s, i)
            g, a = d.gyro_radsec, d.accel_msec2
            w.writerow([d.capture_timestamp_ns, g[0], g[1], g[2], a[0], a[1], a[2]])
    imu_hz = (imu_n - 1) / ((prov.get_last_time_ns(imu_s, TimeDomain.DEVICE_TIME) -
                             prov.get_first_time_ns(imu_s, TimeDomain.DEVICE_TIME)) / 1e9)
    print(f"IMU {args.imu}: {imu_n} samples (~{imu_hz:.0f} Hz) -> {imu_csv}")

    if args.second_imu:
        _dump_imu(prov, sid(args.second_imu), out / "mav0" / "imu1", "imu1")

    # ---- cameras ----------------------------------------------------------
    _dump_cameras(prov, dc, out, labels, sid, args)
    _write_calibration(out, dc, args)
    print(f"\nDone. Dataset -> {out}/mav0")


def _dump_imu(prov, s, imu_dir, name):
    imu_dir.mkdir(parents=True, exist_ok=True)
    with open(imu_dir / "data.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["#timestamp [ns]", "w_RS_S_x [rad s^-1]", "w_RS_S_y [rad s^-1]",
                    "w_RS_S_z [rad s^-1]", "a_RS_S_x [m s^-2]", "a_RS_S_y [m s^-2]",
                    "a_RS_S_z [m s^-2]"])
        n = prov.get_num_data(s)
        for i in range(n):
            d = prov.get_imu_data_by_index(s, i)
            g, a = d.gyro_radsec, d.accel_msec2
            w.writerow([d.capture_timestamp_ns, g[0], g[1], g[2], a[0], a[1], a[2]])
    print(f"IMU {name}: {n} samples -> {imu_dir/'data.csv'}")


def _dump_cameras(prov, dc, out, labels, sid, args):
    cams = [("cam0", args.cam0), ("cam1", args.cam1)]
    from PIL import Image
    rect = {}
    for name, label in cams:
        s = sid(label)
        cc = dc.get_camera_calib(label)
        n = prov.get_num_data(s)
        fps = (n - 1) / ((prov.get_last_time_ns(s, TimeDomain.DEVICE_TIME) -
                          prov.get_first_time_ns(s, TimeDomain.DEVICE_TIME)) / 1e9)
        print(f"{name} ({label}): {n} frames (~{fps:.1f} fps), "
              f"image {int(cc.get_image_size()[0])}x{int(cc.get_image_size()[1])}")
        (out / "mav0" / name / "data").mkdir(parents=True, exist_ok=True)
        if not args.no_rectify:
            mx, my, fx, fy, cx, cy = build_rect_map(cc, args.hfov)
            rect[name] = (mx, my, fx, fy, cx, cy)
            print(f"  {name}: built pinhole rect map (fx={fx:.1f})", flush=True)

    # frames + data.csv
    lim = args.limit if args.limit > 0 else None
    for name, label in cams:
        s = sid(label)
        cam_dir = out / "mav0" / name
        n = prov.get_num_data(s)
        count = min(lim, n) if lim else n
        rows = []
        for i in range(count):
            img, rec = prov.get_image_data_by_index(s, i)
            ts = int(rec.capture_timestamp_ns)
            arr = img.to_numpy_array().astype(np.float32)
            if not args.no_rectify:
                mx, my, _, _, _, _ = rect[name]
                arr = _bilinear_remap(arr, mx, my)
            Image.fromarray(arr.astype(np.uint8)).save(cam_dir / "data" / f"{ts}.png")
            rows.append((ts, f"{ts}.png"))
            if (i + 1) % 500 == 0:
                print(f"  {name}: {i + 1}/{count} frames ...", flush=True)
        with open(cam_dir / "data.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["#timestamp [ns]", "filename"])
            for ts, fname in rows:
                w.writerow([ts, fname])
        print(f"  wrote {cam_dir/'data.csv'} ({len(rows)} rows)")

    if args.rgb:
        lab = "camera-rgb"
        if lab in labels:
            rgb_dir = out / "mav0" / "rgb"
            rgb_dir.mkdir(parents=True, exist_ok=True)
            s = sid(lab)
            n = prov.get_num_data(s)
            with open(rgb_dir / "data.csv", "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["#timestamp [ns]", "filename"])
                for i in range(n):
                    img, rec = prov.get_image_data_by_index(s, i)
                    ts = int(rec.capture_timestamp_ns)
                    Image.fromarray(img.to_numpy_array().astype(np.uint8)).save(
                        rgb_dir / f"{ts}.png")
                    w.writerow([ts, f"{ts}.png"])
            print(f"  wrote rgb/ ({n} frames)")
        else:
            print("  RGB stream not present; skipping.")


def _write_calibration(out, dc, args):
    """Write sensor.yaml (Kimera), imucal.yaml, orb_slam3.yaml, and the raw
    Aria device calibration json for reference."""
    mav = out / "mav0"
    # Cameras
    cc0 = dc.get_camera_calib(args.cam0)
    cc1 = dc.get_camera_calib(args.cam1)
    T_B_C0 = _se3_to_matrix(cc0.get_transform_device_camera())
    T_B_C1 = _se3_to_matrix(cc1.get_transform_device_camera())
    # relative stereo: T_C1_C0 maps points in cam1 -> cam0
    T_C1_C0 = np.linalg.inv(T_B_C1) @ T_B_C0
    baseline = float(np.linalg.norm(T_C1_C0[:3, 3]))

    # pinhole intrinsics (rectify) or native fisheye (--no-rectify)
    if not args.no_rectify:
        W, H = int(cc0.get_image_size()[0]), int(cc0.get_image_size()[1])
        fov = np.deg2rad(args.hfov)
        fx = fy = (W / 2.0) / np.tan(fov / 2.0)
        cx, cy = (W - 1) / 2.0, (H - 1) / 2.0
        model, dist = "pinhole", [0.0, 0.0, 0.0, 0.0]
    else:
        W, H = int(cc0.get_image_size()[0]), int(cc0.get_image_size()[1])
        fx, fy = float(cc0.get_focal_lengths()[0]), float(cc0.get_focal_lengths()[1])
        cx, cy = float(cc0.get_principal_point()[0]), float(cc0.get_principal_point()[1])
        model, dist = "fisheye624", [0.0, 0.0, 0.0, 0.0]

    for name, T_B_C in (("cam0", T_B_C0), ("cam1", T_B_C1)):
        s = _kimera_sensor_yaml(name, W, H, fx, fy, cx, cy, model, dist, T_B_C, T_B_C)
        (mav / name / "sensor.yaml").write_text(s)

    imu_calib = dc.get_imu_calib(args.imu)
    T_BS = _se3_to_matrix(imu_calib.get_transform_device_imu())
    (mav / "imucal.yaml").write_text(_body_yaml(T_BS))

    orb = _orb_yaml(fx, fy, cx, cy, baseline, args)
    (mav / "orb_slam3_stereo_inertial.yaml").write_text(orb)

    ref = _dump_device_calib(dc, args)
    (mav / "device_calibration.json").write_text(json.dumps(ref, indent=2))
    print(f"  wrote calibration (sensor.yaml, imucal.yaml, orb_slam3, device_calibration.json)")


def _kimera_sensor_yaml(name, W, H, fx, fy, cx, cy, model, dist, T_B_C, T_B_S):
    """Minimal EuRoC/Kimera sensor.yaml. fx/fy in px, cx/cy px, dist = distortion.
    T_B_C / T_B_S are 4x4 body->camera / body->sensor transforms."""
    lines = [
        f'sensor_type: "{model}"',
        f"resolution: [{W}, {H}]",
        f"intrinsics: [{fx:.8f}, {fy:.8f}, {cx:.8f}, {cy:.8f}]",
        "distortion: [" + ", ".join("%.8f" % float(v) for v in dist) + "]",
        f"model: {'pinhole' if model == 'pinhole' else 'fisheye624'}",
        "",
        "T_B_C:",
    ]
    for row in np.asarray(T_B_C):
        lines.append("  - [%s]" % ", ".join("%.9f" % float(v) for v in row))
    lines.append("T_B_S:")
    for row in np.asarray(T_B_S):
        lines.append("  - [%s]" % ", ".join("%.9f" % float(v) for v in row))
    return "\n".join(lines) + "\n"


def _body_yaml(T_BS):
    lines = ["# Body->IMU transform (maps IMU points -> body/device frame)", "T_BS:"]
    for row in np.asarray(T_BS):
        lines.append("  - [%s]" % ", ".join("%.9f" % float(v) for v in row))
    return "\n".join(lines) + "\n"


def _orb_yaml(fx, fy, cx, cy, baseline, args):
    return f"""%YAML:1.0
---
# ORB-SLAM3 stereo-inertial config (pinhole, pre-rectified images).
# Verify the extrinsic sign/baseline against your ORB-SLAM3 build before trusting
# an absolute metric map.
FileVersion: "1.0"

Camera.type: "Rectified"
Camera.fx: {fx:.6f}
Camera.fy: {fy:.6f}
Camera.cx: {cx:.6f}
Camera.cy: {cy:.6f}
Camera.k1: 0.0
Camera.k2: 0.0
Camera.p1: 0.0
Camera.p2: 0.0
Camera.k3: 0.0
Camera.fps: 30.0
Camera.RGB: 0

Stereo.b: {baseline:.6f}
Stereo.bf: {baseline * fx:.6f}
Stereo.Rectification: "none"

IMU.NoiseGyro: {args.imu_noise_gyro:.8e}
IMU.NoiseAcc: {args.imu_noise_accel:.8e}
IMU.GyroWalk: {args.imu_gyro_walk:.8e}
IMU.AccelWalk: {args.imu_accel_walk:.8e}
IMU.frequency: 1000.0
"""


def _dump_device_calib(dc, args):
    """Best-effort JSON dump of the Aria calibration we use."""
    out = {}
    for label in (args.cam0, args.cam1):
        cc = dc.get_camera_calib(label)
        enum = cc.get_model_name()
        out[label] = {
            "label": cc.get_label(),
            "model": enum.name if hasattr(enum, "name") else str(enum),
            "image_size": [int(cc.get_image_size()[0]), int(cc.get_image_size()[1])],
            "focal_lengths": [float(v) for v in cc.get_focal_lengths()],
            "principal_point": [float(v) for v in cc.get_principal_point()],
            "projection_params": [float(v) for v in cc.get_projection_params()],
            "T_Device_Camera": _se3_to_matrix(cc.get_transform_device_camera()).tolist(),
            "time_offset_sec_device_camera": cc.get_time_offset_sec_device_camera(),
        }
    return out


if __name__ == "__main__":
    main()
