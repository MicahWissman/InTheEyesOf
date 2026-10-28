# Migrating SLAM from Meta MPS to Kimera-VIO (standalone, additive)

> **Scope.** This is a **separate, optional authoring path**. It does **not** replace,
> modify, or interfere with the existing MPS-based pipeline. It produces files in
> the *same* MPS-compatible format, so the existing downstream steps (Snap Rule
> raycasting, `export_trajectory_latlon.py`, `bake_geo_aligned_recording.py`,
> the web viewer) consume them **unchanged**. Nothing here edits an existing script.
>
> **Motivation.** Kimera is BSD-2-Clause (MIT-compatible), runs fully offline, and
> produces a denser watertight mesh than MPS's semi-dense points — useful if you
> want to drop the cloud MPS dependency or remove the data upload. You keep using
> MPS for **eye-gaze** and **hand-tracking**; this path only replaces the **SLAM**
> portion (trajectory + point cloud / mesh).

---

## The separate pipeline (end to end)

```
 Carona1-001.vrs
      │  (1) vrs_to_euroc.py        -- extract SLAM stereo + IMU + calibration
      ▼
 mav0/ (EuRoC-style dataset)
      │  (2) Kimera-VIO + Kimera-RPGO + Kimera-Mesher   [external / ROS]
      ▼
 odometry (pose CSV)  +  mesh (.ply)
      │  (3) kimera_to_mps.py       -- adapt back to MPS-format inputs
      ▼
 closed_loop_trajectory.csv  +  semidense_points.csv.gz
      │  (4) existing pipeline consumes these UNCHANGED
      ▼
 narrative_anchors.json / pointcloud.ply / trajectory_latlon.json ...
```

### 1. Extract (new) — `scripts/gaze/semantic/vrs_to_euroc.py`
```bash
python scripts/gaze/semantic/vrs_to_euroc.py \
    --vrs vrs-files/Carona1-001.vrs \
    --out /path/aria_euroc
```
- Default outputs the two **SLAM** cameras (`camera-slam-left/right`, 640×480
  **global-shutter** fisheye) rectified to a **pinhole** model (Kimera needs
  pinhole; use `--no-rectify` for raw fisheye if you switch to ORB-SLAM3).
- Default IMU is `imu-right` (1000 Hz); add `--second-imu imu-left` for the 800 Hz.
- Writes EuRoC layout (`mav0/cam0|cam1/...`, `mav0/imu0/data.csv`) + calibration
  (`sensor.yaml`, `imucal.yaml`, `orb_slam3_stereo_inertial.yaml`,
  `device_calibration.json`).
- Time base is device-clock nanoseconds (what Aria and VIO ingest natively).

### 2. Run Kimera (external, not shipped here)
Run Kimera-VIO (+ **Kimera-RPGO** for loop closure + **Kimera-Mesher** for the
mesh) on the `mav0` dataset, then export the odometry to a CSV and the mesh to a
`.ply`. Verify the extrinsic sign/scale with your build.

### 3. Adapt back to MPS format (new) — `scripts/gaze/semantic/kimera_to_mps.py`
```bash
python scripts/gaze/semantic/kimera_to_mps.py \
    --pose-csv kimera_odometry.csv \
    --mesh-ply kimera_mesh.ply \
    --gps /path/Carona_02_gps.csv \
    --out /path/mps_kimera
```
- Writes `closed_loop_trajectory.csv` (world-frame pose + optional ECEF) and
  `semidense_points.csv.gz` (`px_world/py_world/pz_world` + `dist_std`).
- `--gps` fits a least-squares **Sim(3)** from the Kimera world frame to **ECEF**
  so `geo_available=1` and `export_trajectory_latlon.py` / baking work as-is.
  Without `--gps`, `geo_available=0` (no geo-reference yet).
- Column names/orientation are configurable (`--t-col`, `--pos-cols`,
  `--quat-cols`, `--quat-order`) because Kimera/ROS dump quaternions as
  **x,y,z,w** by default.

### 4. Consume unchanged
Point the existing pipeline's MPS root at `/path/mps_kimera`:
```bash
python scripts/gaze/semantic/run_narrative_pipeline.py --vrs ... --mps /path/mps_kimera ...
```

---

## What you lose vs. MPS (scoped strictly to SLAM)

| # | Element you lose | Why | Mitigation |
|---|---|---|---|
| 1 | **Geo-referenced ECEF trajectory** (`geo_available`, `tx/ty/tz_ecef_device`) | MPS bakes GPS+gravity into ECEF; Kimera gives a gravity-aligned, metric frame with arbitrary yaw/origin | Use `--gps` to fit a Sim(3) → ECEF (done in `kimera_to_mps.py`) |
| 2 | **Loop closure** | Kimera-VIO is open-loop VIO; `closed_loop` comes from MPS | Run **Kimera-RPGO** and feed its optimized pose graph |
| 3 | **Multi-SLAM / shared world frame across recordings** | MPS merges `0/` + `1/` halves into one frame; Kimera anchors each run at its own origin | Realign per recording externally (the `README_SHARE.md` approach) |
| 4 | **Per-point uncertainty** (`dist_std`/`inv_dist_std`) used for quality filtering | Kimera gives a mesh without per-point confidence | Write a constant `dist_std` (`--dist-std`) or keep using the MPS cloud for raycasting |
| 5 | **Out-of-the-box Aria tuning** | MPS is tuned for the device | Refine Kimera params (pinhole FOV, IMU noise) |

**What you do NOT lose:** metric scale, gravity alignment, per-timestamp pose,
and the CPF gaze signal (your summarizer uses gaze *yaw/pitch*, which is
head-relative and independent of the SLAM frame).

**What you gain:** BSD license, offline processing, no data upload, and a denser,
watertight mesh (optionally semantic via Kimera-Semantics).

---

## Caveats / follow-ups

- The `sensor.yaml`/orb configs are generated; **verify the stereo extrinsic
  sign** against your Kimera/ORB-SLAM3 build before trusting an absolute metric map.
- Kimera consumes data via its ROS/data-provider layer; wiring the `mav0` folder
  into your specific build (ROS bag vs standalone dataset reader) is the one
  remaining integration step.
- Only **SLAM** is swapped here. Eye-gaze and hand-tracking remain on MPS.

## Files added (all additive; no existing file modified)
- `scripts/gaze/semantic/vrs_to_euroc.py`
- `scripts/gaze/semantic/kimera_to_mps.py`
- This document.
