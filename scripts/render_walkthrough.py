#!/usr/bin/env python3
"""
render_walkthrough.py — scripted fly-through of a recording's point cloud along
its SLAM trajectory, rendered offscreen with Open3D.

Research-demo companion to the web viewer's browser flythrough
(web-viewer/scripts/record-walkthrough.mjs + NarrativeViewer TrajectoryFlyThrough).
This version renders at full resolution with a deterministic, constant-speed
camera path and can optionally dwell on the route's narrative anchors (POIs).

Data contract (same files the web viewer consumes, see
scripts/bake_geo_aligned_recording.py):
  pointcloud.ply         — ENU/Three.js aligned cloud (X=east, Y=up, Z=-north)
  trajectory_latlon.json — trajectory; wx/wy/wz are Three.js world coords (device path)
  anchors_route.json     — candidates[] with gx/gy/gz (same frame) + node_id/title

Camera conventions
------------------
Open3D follows the computer-vision convention (camera looks along +Z, X right,
Y down).  World is the baked Three.js frame (Y up).  The device trajectory is
used directly as the camera eye path (head height, real expert walk).

Usage examples
--------------
  # contact-sheet previews (fast) to choose a route segment
  python scripts/render_walkthrough.py --preview-only --end-m 300

  # full renders: both look modes
  python scripts/render_walkthrough.py --look-mode path    --overlay --annotated
  python scripts/render_walkthrough.py --look-mode anchors --overlay --annotated

  # change segment / pacing (--speed-mult 1 = real walking pace)
  python scripts/render_walkthrough.py --start-m 150 --end-m 450 --duration 120

Outputs land in pipeline_results/walkthrough/<recording>/ (gitignored):
  <recording>_walkthrough_<mode>.mp4   — final video (H.264, yuv420p)
  preview_<mode>.png                   — contact sheet of the segment
  settings.json                        — full parameter/stats record (reproducibility)
"""

from __future__ import annotations

import argparse
import colorsys
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_VIEWER_RECORDINGS = REPO_ROOT / "web-viewer" / "public" / "recordings"
DEFAULT_OUT_ROOT = REPO_ROOT / "pipeline_results" / "walkthrough"

POINT_CLOUD_FILE = "pointcloud.ply"
TRAJECTORY_FILE = "trajectory_latlon.json"
ANCHORS_FILE = "anchors_route.json"

UP = np.array([0.0, 1.0, 0.0])  # Three.js/ENU baked frame: Y is up
UP_MAP = np.array([0.0, 0.0, -1.0])  # "north up" for top-down / birds-eye views (Z = -north)


# ── small helpers ─────────────────────────────────────────────────────────────

def load_json(path: Path):
    with open(path) as f:
        return json.load(f)


def moving_average(P: np.ndarray, window: int = 3) -> np.ndarray:
    """Box-filter each axis of P (N,3) along the path using nearest edge handling."""
    if window < 2:
        return P
    from scipy.ndimage import uniform_filter1d
    return uniform_filter1d(P, size=window, axis=0, mode="nearest")


# ── data loading ───────────────────────────────────────────────────────────────

def load_trajectory(rec_dir: Path) -> tuple[np.ndarray, np.ndarray, dict]:
    """Return ((N,3) device-path positions, (N,) device timestamps µs, raw JSON)."""
    data = load_json(rec_dir / TRAJECTORY_FILE)
    pts, ts = [], []
    for p in data["path"]:
        if "wx" in p and "wy" in p and "wz" in p:
            pts.append([p["wx"], p["wy"], p["wz"]])
            ts.append(p.get("t", 0))
    if len(pts) < 4:
        raise RuntimeError(f"trajectory in {rec_dir / TRAJECTORY_FILE} has too few points")
    if not data.get("baked"):
        print("  [!] warning: trajectory is not 'baked' — wx/wy/wz may not be in the point-cloud frame")
    return np.asarray(pts, dtype=np.float64), np.asarray(ts, dtype=np.int64), data


def load_anchors(rec_dir: Path) -> list[dict]:
    """Return anchors with a 3D position in the point-cloud frame."""
    data = load_json(rec_dir / ANCHORS_FILE)
    candidates = data.get("candidates", data if isinstance(data, list) else [])
    anchors = []
    for c in candidates:
        if c.get("gx") is None or c.get("gy") is None or c.get("gz") is None:
            continue
        anchors.append({
            "node_id": c.get("node_id"),
            "title": c.get("title") or f"node {c.get('node_id')}",
            "pos": np.array([c["gx"], c["gy"], c["gz"]], dtype=np.float64),
        })
    return anchors


# ── path preparation ───────────────────────────────────────────────────────────

def build_path(P: np.ndarray, start_m: float, end_m: float,
               margin_m: float = 25.0, min_spacing: float = 0.3,
               smooth: int = 3) -> dict:
    """Select trajectory points in [start_m, end_m] (arc length), dedupe, smooth,
    and build a cubic spline parameterised by arc length.

    Returns a dict with:
      pts        (M,3) processed points (margin included)
      arc        (M,) cumulative arc length of pts (arc[0] == 0)
      spline     CubicSpline(s) -> (3,)
      start_m/end_m/lo/hi  arc bookkeeping (lo = arc[0] of the included range)
    """
    from scipy.interpolate import CubicSpline

    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1])

    start_m = max(0.0, min(float(start_m), total))
    end_m = max(start_m + 1.0, min(float(end_m), total))

    lo = max(0.0, start_m - margin_m)
    hi = min(total, end_m + margin_m)

    sel = np.flatnonzero((cum >= lo) & (cum <= hi))
    if len(sel) < 4:
        raise RuntimeError(f"segment [{start_m:.0f}, {end_m:.0f}] m too short")
    if sel[0] > 0:
        sel = np.concatenate([[sel[0] - 1], sel])
    if sel[-1] < len(P) - 1:
        sel = np.concatenate([sel, [sel[-1] + 1]])

    Q = P[sel]

    # drop near-duplicate samples (same rule as the web viewer flythrough)
    keep = [0]
    for i in range(1, len(Q)):
        if np.linalg.norm(Q[i] - Q[keep[-1]]) >= min_spacing:
            keep.append(i)
    Q = Q[keep]
    if len(Q) < 4:
        raise RuntimeError("too few distinct trajectory points in segment")

    Q = moving_average(Q, smooth)

    s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(Q, axis=0), axis=1))])
    cs = CubicSpline(s, Q, axis=0, bc_type="natural")

    return {"pts": Q, "arc": s, "spline": cs, "total": total,
            "start_m": start_m, "end_m": end_m, "lo": lo, "hi": hi}


def map_anchors_to_path(anchors: list[dict], path: dict,
                        max_dist_m: float = 40.0) -> list[dict]:
    """Attach each anchor's nearest arc position on the processed path."""
    from scipy.spatial import cKDTree
    if not anchors:
        return []
    tree = cKDTree(path["pts"])
    arc = path["arc"]
    s_begin = path["start_m"] - path["lo"]
    s_end = path["end_m"] - path["lo"]
    mapped = []
    for a in anchors:
        d, i = tree.query(a["pos"])
        if d > max_dist_m:
            continue
        sa = float(arc[i])
        if s_begin - 5.0 <= sa <= s_end + 5.0:
            mapped.append({**a, "arc": sa, "dist": float(d)})
    mapped.sort(key=lambda a: a["arc"])
    return mapped


# ── camera ─────────────────────────────────────────────────────────────────────

def sample_camera_path(path: dict, duration: float, fps: float,
                       look_ahead_m: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Constant-speed sampling of eye positions and path look-targets.

    Returns (eyes (n,3), path_targets (n,3), s_vals (n,) in segment-local arc m).
    """
    spline = path["spline"]
    s_begin = path["start_m"] - path["lo"]
    s_end = path["end_m"] - path["lo"]
    n = max(2, int(round(duration * fps)))
    s_vals = np.linspace(s_begin, s_end, n)
    eyes = spline(s_vals)
    targets = spline(np.minimum(s_vals + look_ahead_m, s_end))
    return eyes, targets, s_vals


def compute_anchor_look(eyes: np.ndarray, targets: np.ndarray,
                        anchors: list[dict], sigma_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Blend look-targets toward the nearest anchor (Gaussian by 3D distance).

    Returns (blended_targets, engagement_weights); weight 0 = pure path look.
    """
    weights = np.zeros(len(eyes))
    if not anchors:
        return targets, weights
    anchor_pos = np.array([a["pos"] for a in anchors])
    for k in range(len(eyes)):
        d = np.linalg.norm(anchor_pos - eyes[k], axis=1)
        i = int(np.argmin(d))
        w = float(np.exp(-(d[i] / sigma_m) ** 2))
        if w > 0.05:
            targets[k] = (1.0 - w) * targets[k] + w * anchor_pos[i]
        weights[k] = w
    return targets, weights


def segment_frame(path: dict) -> tuple[np.ndarray, float]:
    """Centre and horizontal extent of the segment (for birds-eye framing)."""
    pts = path["pts"]
    cx = float(pts[:, 0].min() + pts[:, 0].max()) * 0.5
    cz = float(pts[:, 2].min() + pts[:, 2].max()) * 0.5
    cy = float(pts[:, 1].min() + pts[:, 1].max()) * 0.5
    extent = float(max(pts[:, 0].max() - pts[:, 0].min(),
                       pts[:, 2].max() - pts[:, 2].min()))
    return np.array([cx, cy, cz]), extent


def birds_camera_path(path: dict, args) -> tuple[np.ndarray, np.ndarray, np.ndarray, str, np.ndarray]:
    """Zoomed-out birds-eye camera path over the segment.

    Returns (eyes, targets, up, tag, walker) where walker is the (n,3) position
    of the recording subject (the "original point") as it travels the route; this
    is used to draw a moving marker so its location is obvious from above.
      up   is the world "up" handed to look_at_extrinsic: the map-style north-up
           vector so the view is a stable overhead map rather than rolling.
    """
    spline = path["spline"]
    s_begin = path["start_m"] - path["lo"]
    s_end = path["end_m"] - path["lo"]
    n = max(2, int(round(args.duration * args.fps)))
    frac = np.linspace(0.0, 1.0, n)
    s_vals = s_begin + frac * (s_end - s_begin)
    ground = spline(s_vals)                      # (n,3) along the path

    if args.view == "topdown":
        # follow the walker from directly above, looking down-and-ahead
        H = args.topdown_height
        eyes = ground + np.array([0.0, H, 0.0])
        ahead = spline(np.minimum(s_vals + args.look_ahead_m, s_end))
        return eyes, ahead, UP_MAP, "topdown-follow", ground

    # overview: frame the whole segment from above, gentle dolly across it
    centre, extent = segment_frame(path)
    H = (args.birds_height if args.birds_height and args.birds_height > 0
         else max(60.0, (extent * 0.5) / math.tan(math.radians(args.vfov) * 0.5) * 1.15))
    dx = float(path["pts"][:, 0].max() - path["pts"][:, 0].min())
    dz = float(path["pts"][:, 2].max() - path["pts"][:, 2].min())
    axis = np.array([1.0, 0.0, 0.0]) if dx >= dz else np.array([0.0, 0.0, 1.0])
    half = axis * max(extent, 1.0) * 0.12             # sweep a fraction of the extent
    offset = (frac[:, None] * 2.0 - 1.0) * half       # (n,3)
    eyes = centre + np.array([0.0, H, 0.0]) + offset
    targets = np.tile(centre, (n, 1))
    return eyes, targets, UP_MAP, "birds-eye-overview", ground


def _translate_matrix(p: np.ndarray) -> np.ndarray:
    T = np.eye(4)
    T[:3, 3] = p
    return T


def make_progress_marker(radius: float, beacon_height: float = 50.0):
    """Bright-red sphere plus a vertical beacon marking the walker's position."""
    import open3d as o3d
    sphere = o3d.geometry.TriangleMesh.create_sphere(radius=radius)
    sphere.compute_vertex_normals()
    beacon = o3d.geometry.LineSet()
    beacon.points = o3d.utility.Vector3dVector(
        np.array([[0.0, 0.0, 0.0], [0.0, beacon_height, 0.0]]))
    beacon.lines = o3d.utility.Vector2iVector([[0, 1]])
    beacon.colors = o3d.utility.Vector3dVector(np.array([[1.0, 0.0, 0.0]]))
    return sphere, beacon


def add_progress_marker(renderer, radius: float) -> list[str]:
    """Add the moving marker to the scene; returns the geometry names to move."""
    import open3d as o3d
    sphere, beacon = make_progress_marker(radius)
    ms = o3d.visualization.rendering.MaterialRecord()
    ms.shader = "unlitSolidColor"      # stays bright regardless of scene lighting
    ms.base_color = [1.0, 0.0, 0.0, 1.0]
    renderer.scene.add_geometry("marker", sphere, ms)
    bl = o3d.visualization.rendering.MaterialRecord()
    bl.shader = "unlitLine"
    bl.line_width = 6.0
    renderer.scene.add_geometry("marker_beacon", beacon, bl)
    return ["marker", "marker_beacon"]


def look_at_extrinsic(eye: np.ndarray, target: np.ndarray, up: np.ndarray = UP) -> np.ndarray:
    """World-to-camera extrinsic for an OpenCV/Open3D camera looking along +Z.

    Camera axes: X right, Y down, Z forward.  World is the baked Three.js frame
    (X east, Y up, Z -north) so world up is +Y.
    """
    f = target - eye
    fn = np.linalg.norm(f)
    if fn < 1e-9:
        return np.eye(4)
    f = f / fn

    right = np.cross(f, up)
    rn = np.linalg.norm(right)
    if rn < 1e-6:  # degenerate: looking straight up/down — pick an arbitrary right
        alt = np.array([0.0, 0.0, 1.0]) if abs(up[1]) > 0.9 else np.array([0.0, 1.0, 0.0])
        right = np.cross(f, alt)
        rn = np.linalg.norm(right)
    right = right / rn
    down = np.cross(f, right)

    R = np.stack([right, down, f])          # rows = camera axes in world coords
    t = -R @ eye
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = t
    return M


# ── point cloud ────────────────────────────────────────────────────────────────

def load_point_cloud(rec_dir: Path, voxel: float, max_points: int):
    """Load and downsample the recording point cloud.  Returns an Open3D point cloud."""
    import open3d as o3d

    path = rec_dir / POINT_CLOUD_FILE
    if not path.exists():
        raise RuntimeError(f"point cloud not found: {path}")
    t0 = time.time()
    print(f"  loading {path.name} …")
    pcd = o3d.io.read_point_cloud(str(path))
    n0 = len(pcd.points)
    if voxel and voxel > 0:
        pcd = pcd.voxel_down_sample(voxel)
        print(f"  voxel {voxel:g} m: {n0:,} → {len(pcd.points):,} points")
    if len(pcd.points) > max_points:
        step = math.ceil(len(pcd.points) / max_points)
        pcd = pcd.uniform_down_sample(step)
        print(f"  stride {step}: {len(pcd.points):,} points (≤ {max_points:,})")
    # defaultLit needs per-vertex normals or the cloud renders nearly black
    if not pcd.has_normals():
        pcd.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=0.5, max_nn=30))
        print(f"  estimated normals for {len(pcd.points):,} points")
    print(f"  point cloud ready: {len(pcd.points):,} points ({time.time() - t0:.1f}s)")
    return pcd


# ── scene geometry (annotated variant) ─────────────────────────────────────────

def make_trajectory_lines(Q: np.ndarray, arc: np.ndarray):
    """LineSet of the smoothed trajectory, hue-coloured by arc position."""
    import open3d as o3d

    lines = [[i, i + 1] for i in range(len(Q) - 1)]
    ls = o3d.geometry.LineSet()
    ls.points = o3d.utility.Vector3dVector(Q)
    ls.lines = o3d.utility.Vector2iVector(lines)
    if len(Q) > 1 and arc[-1] > 0:
        t = arc / arc[-1]
        cols = []
        for tt in t:
            r, g, b = colorsys.hsv_to_rgb(0.55 - 0.5 * tt, 0.85, 1.0)  # cyan → magenta
            cols.append([r, g, b])
        ls.colors = o3d.utility.Vector3dVector(np.asarray(cols, dtype=np.float64)[:-1])
    return ls


def make_anchor_markers(anchors: list[dict], radius: float = 0.5):
    """Orange spheres at each anchor's 3D position."""
    import open3d as o3d

    spheres = []
    for a in anchors:
        s = o3d.geometry.TriangleMesh.create_sphere(radius=radius)
        s.compute_vertex_normals()
        s.translate(a["pos"], relative=False)
        spheres.append(s)
    return spheres


def build_scene(renderer, pcd, args, traj_lines=None, anchor_spheres=None,
                bg: float | None = None):
    """Add point cloud and (optionally) trajectory line + anchor markers."""
    import open3d as o3d

    if bg is None:
        bg = getattr(args, "background", 0.05)
    renderer.scene.set_background([bg, bg, bg, 1.0])
    mat = o3d.visualization.rendering.MaterialRecord()
    mat.shader = args.shader
    mat.base_color = [1.0, 1.0, 1.0, 1.0]  # white: show the point cloud's own colors
    mat.point_size = args.point_size
    renderer.scene.add_geometry("pcd", pcd, mat)

    if traj_lines is not None:
        lm = o3d.visualization.rendering.MaterialRecord()
        lm.shader = "unlitLine"
        lm.line_width = 2.0
        try:
            renderer.scene.add_geometry("traj", traj_lines, lm)
        except Exception:
            lm.shader = "unlit"
            renderer.scene.add_geometry("traj", traj_lines, lm)

    if anchor_spheres:
        sm = o3d.visualization.rendering.MaterialRecord()
        sm.shader = "defaultLit"
        sm.base_color = [1.0, 0.55, 0.1, 1.0]
        for i, sp in enumerate(anchor_spheres):
            renderer.scene.add_geometry(f"anchor_{i}", sp, sm)


# ── rendering ──────────────────────────────────────────────────────────────────

def make_intrinsic(width: int, height: int, vfov_deg: float):
    import open3d as o3d

    fy = (height / 2.0) / math.tan(math.radians(vfov_deg) / 2.0)
    fx = fy
    return o3d.camera.PinholeCameraIntrinsic(width, height, fx, fy,
                                            width / 2.0, height / 2.0)


def render_frame(renderer, intrinsic, extrinsic, width: int, height: int,
                 brightness: float = 1.0, gamma: float = 1.0) -> np.ndarray:
    """Render one frame; returns HxWx3 RGB uint8 (with optional gain/gamma lift)."""
    renderer.setup_camera(intrinsic, extrinsic)
    img = renderer.render_to_image()
    arr = np.asarray(img)
    if arr.ndim == 3 and arr.shape[2] == 4:
        arr = arr[:, :, :3]
    if brightness != 1.0 or gamma != 1.0:
        f = arr.astype(np.float32) * brightness / 255.0
        if gamma != 1.0:
            f = np.power(np.clip(f, 0.0, 1.0), 1.0 / gamma)
        arr = np.clip(f * 255.0, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(arr)


def _load_font(size: int):
    from PIL import ImageFont
    candidates = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    ]
    for p in candidates:
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                pass
    return ImageFont.load_default()


def draw_overlay(frame: np.ndarray, ctx: dict) -> np.ndarray:
    """Composite text/bars onto an RGB frame with PIL (returns new frame)."""
    from PIL import Image, ImageDraw

    img = Image.fromarray(frame)
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    font = _load_font(22)
    small = _load_font(16)

    # top bar: title + mode
    draw.rectangle([0, 0, w, 46], fill=(0, 0, 0, 150))
    draw.text((16, 10), ctx["title"], font=font, fill=(255, 255, 255, 255))
    mode_label = ctx["mode"]
    tw = draw.textlength(mode_label, font=font)
    draw.text((w - 16 - tw, 10), mode_label, font=font, fill=(200, 230, 255, 255))

    # bottom bar: progress + arc
    draw.rectangle([0, h - 52, w, h], fill=(0, 0, 0, 150))
    frac = ctx["frac"]
    bar_x, bar_y, bar_w, bar_h = 16, h - 30, int((w - 32) * 0.55), 6
    draw.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], fill=(255, 255, 255, 60))
    draw.rectangle([bar_x, bar_y, bar_x + int(bar_w * frac), bar_y + bar_h],
                   fill=(120, 200, 255, 220))
    prog = (f"route {ctx['arc_m']:>5.0f} / {ctx['seg_m']:>5.0f} m · "
            f"{ctx['t']:>5.1f} / {ctx['dur']:>5.1f} s")
    draw.text((bar_x, h - 44), prog, font=small, fill=(230, 230, 230, 255))

    # center: engaged anchor title
    if ctx.get("anchor_title"):
        at = f"◈ {ctx['anchor_title']}"
        aw = draw.textlength(at, font=font)
        draw.rectangle([w / 2 - aw / 2 - 14, h - 100, w / 2 + aw / 2 + 14, h - 66],
                       fill=(0, 0, 0, 160))
        draw.text((w / 2 - aw / 2, h - 96), at, font=font, fill=(255, 200, 120, 255))

    return np.asarray(img)[:, :, :3].copy()


# ── preview contact sheet ──────────────────────────────────────────────────────

def render_preview(renderer, intrinsic, path, eyes, targets, anchors, weights, args,
                   out_path: Path, up: np.ndarray = UP,
                   marker_pos: np.ndarray | None = None, marker_names: list[str] | None = None):
    """Render a contact sheet along the segment to inspect the route.

    Frames are rendered at full renderer resolution and downscaled to
    (preview_width × preview_height) cells.
    """
    from PIL import Image, ImageDraw

    pw, ph = args.preview_width, args.preview_height
    n = min(args.preview_frames, len(eyes))
    idx = np.linspace(0, len(eyes) - 1, n).astype(int)
    font = _load_font(14)
    cells = []
    for k in idx:
        if marker_pos is not None and marker_names:
            T = _translate_matrix(marker_pos[k])
            for name in marker_names:
                renderer.scene.set_geometry_transform(name, T)
        ext = look_at_extrinsic(eyes[k], targets[k], up)
        cell = render_frame(renderer, intrinsic, ext, args.width, args.height,
                            args.brightness, args.gamma)
        img = Image.fromarray(cell).resize((pw, ph), Image.LANCZOS)
        d = ImageDraw.Draw(img, "RGBA")
        d.rectangle([0, 0, pw, 20], fill=(0, 0, 0, 140))
        s_begin = path["start_m"] - path["lo"]
        arc_m = s_begin + (k / max(len(eyes) - 1, 1)) * (path["end_m"] - path["start_m"])
        d.text((6, 4), f"{arc_m:5.0f} m", font=font, fill=(255, 255, 255, 255))
        if weights is not None and len(anchors) and weights[k] > 0.2:
            d_i = int(np.argmin([np.linalg.norm(a["pos"] - eyes[k]) for a in anchors]))
            d.text((6, ph - 20), f"◈ {anchors[d_i]['title'][:34]}", font=font,
                   fill=(255, 200, 120, 255))
        cells.append(np.asarray(img))

    cols = 4
    rows = math.ceil(n / cols)
    canvas = Image.new("RGB", (cols * pw, rows * ph), (10, 10, 10))
    for i, c in enumerate(cells):
        canvas.paste(Image.fromarray(c), ((i % cols) * pw, (i // cols) * ph))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(str(out_path))
    print(f"  preview → {out_path}")


# ── video writer ───────────────────────────────────────────────────────────────

def write_video(renderer, intrinsic, eyes, targets, weights, anchors, args, path,
                mode: str, out_path: Path, settings: dict, up: np.ndarray = UP,
                marker_pos: np.ndarray | None = None, marker_names: list[str] | None = None):
    import imageio.v2 as imageio

    n = len(eyes)
    seg_m = path["end_m"] - path["start_m"]
    s_begin = path["start_m"] - path["lo"]
    duration = n / args.fps
    mode_label = {"anchors": "anchor-aware", "path": "path-ahead"}.get(mode, mode)
    writer = imageio.get_writer(
        str(out_path), fps=args.fps, codec="libx264",
        output_params=["-crf", "20", "-preset", "medium"],
        pixelformat="yuv420p", macro_block_size=1,
    )
    t0 = time.time()
    try:
        for k in range(n):
            if marker_pos is not None and marker_names:
                T = _translate_matrix(marker_pos[k])
                for name in marker_names:
                    renderer.scene.set_geometry_transform(name, T)
            ext = look_at_extrinsic(eyes[k], targets[k], up)
            frame = render_frame(renderer, intrinsic, ext, args.width, args.height,
                                 args.brightness, args.gamma)
            if args.overlay:
                anchor_title = None
                if mode == "anchors" and weights is not None and weights[k] > 0.35 and len(anchors):
                    d_i = int(np.argmin([np.linalg.norm(a["pos"] - eyes[k]) for a in anchors]))
                    anchor_title = anchors[d_i]["title"]
                ctx = {
                    "title": args.title,
                    "mode": mode_label,
                    "frac": k / max(n - 1, 1),
                    "arc_m": s_begin + (k / max(n - 1, 1)) * seg_m,
                    "seg_m": seg_m,
                    "t": k / args.fps,
                    "dur": duration,
                    "anchor_title": anchor_title,
                }
                frame = draw_overlay(frame, ctx)
            writer.append_data(frame)
            if (k + 1) % max(1, n // 10) == 0 or k == n - 1:
                el = time.time() - t0
                eta = el / (k + 1) * (n - k - 1)
                print(f"    frame {k + 1:,}/{n:,}  ({el:.0f}s elapsed, ~{eta:.0f}s left)")
    finally:
        writer.close()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    settings["video_path"] = str(out_path)
    settings["frames"] = n
    settings["duration_s"] = duration
    print(f"  video → {out_path}")


# ── CLI / main ─────────────────────────────────────────────────────────────────

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--recording", default="carona_adine",
                   help="recording id under web-viewer/public/recordings/")
    p.add_argument("--recording-dir", type=Path, default=None,
                   help="override the recording directory entirely")
    p.add_argument("--start-m", type=float, default=0.0,
                   help="segment start along the route, metres of arc length")
    p.add_argument("--end-m", type=float, default=300.0,
                   help="segment end along the route, metres of arc length")
    p.add_argument("--duration", type=float, default=90.0,
                   help="video duration in seconds")
    p.add_argument("--speed-mult", type=float, default=None,
                   help="if set, duration = real segment time / speed-mult (1 = walking pace)")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--vfov", type=float, default=55.0,
                   help="vertical field of view, degrees")
    p.add_argument("--point-size", type=float, default=4.0)
    p.add_argument("--background", type=float, default=0.12,
                   help="scene background grey level (0 = black, 1 = white)")
    p.add_argument("--shader", choices=["defaultLit"], default="defaultLit",
                   help="material shader for the point cloud (0.19 has no 'unlit' for colored points)")
    p.add_argument("--voxel", type=float, default=0.05,
                   help="voxel downsample size in metres (0 disables)")
    p.add_argument("--max-points", type=int, default=1_200_000)
    p.add_argument("--smooth", type=int, default=3, help="path smoothing window")
    p.add_argument("--look-mode", choices=["path", "anchors"], default="anchors",
                   help="path = look ahead along the route; anchors = dwell on POIs")
    p.add_argument("--view", choices=["walkthrough", "topdown", "overview"],
                   default="walkthrough",
                   help="walkthrough = first-person along the path; "
                        "topdown = follow the walker from straight above; "
                        "overview = zoom out to frame the whole segment from above")
    p.add_argument("--topdown-height", type=float, default=120.0,
                   help="camera height above the walker for --view topdown (metres)")
    p.add_argument("--birds-height", type=float, default=0.0,
                   help="camera height for --view overview (0 = auto from segment size)")
    p.add_argument("--marker-radius", type=float, default=6.0,
                   help="radius (metres) of the beacon marking the walker's position in aerial views")
    p.add_argument("--no-marker", action="store_true",
                   help="disable the moving position marker in aerial views")
    p.add_argument("--look-ahead-m", type=float, default=8.0,
                   help="look-ahead distance for path mode")
    p.add_argument("--anchor-sigma-m", type=float, default=10.0,
                   help="anchor engagement radius (Gaussian sigma)")
    p.add_argument("--max-anchor-dist", type=float, default=40.0,
                   help="ignore anchors farther than this from the path")
    p.add_argument("--brightness", type=float, default=1.6,
                   help="post-render brightness multiplier (dark baked height-colors)")
    p.add_argument("--gamma", type=float, default=1.0,
                   help="post-render gamma correction (1.0 = none)")
    p.add_argument("--overlay", action="store_true",
                   help="draw a text/progress overlay on the video")
    p.add_argument("--annotated", action="store_true",
                   help="draw the trajectory polyline + anchor markers in 3D")
    p.add_argument("--out", type=Path, default=None,
                   help="output directory (default pipeline_results/walkthrough/<recording>)")
    p.add_argument("--preview-only", action="store_true")
    p.add_argument("--preview-frames", type=int, default=12)
    p.add_argument("--preview-width", type=int, default=480)
    p.add_argument("--preview-height", type=int, default=270)
    p.add_argument("--title", default=None)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    rec_dir = args.recording_dir or (WEB_VIEWER_RECORDINGS / args.recording)
    if not rec_dir.exists():
        sys.exit(f"recording dir not found: {rec_dir}")

    print(f"== Walkthrough renderer · {args.recording} ==")
    P, ts, _meta = load_trajectory(rec_dir)
    anchors_all = load_anchors(rec_dir)
    print(f"  trajectory: {len(P):,} samples · anchors with 3D pos: {len(anchors_all)}")

    path = build_path(P, args.start_m, args.end_m, smooth=args.smooth)
    seg_len = path["end_m"] - path["start_m"]
    print(f"  segment {path['start_m']:.0f}–{path['end_m']:.0f} m "
          f"(len {seg_len:.0f} m, route total {path['total']:.0f} m)")

    # real recorded duration of the segment (for --speed-mult diagnostics)
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    sel_t = np.flatnonzero((cum >= path["start_m"]) & (cum <= path["end_m"]))
    real_dur = 0.0
    if len(sel_t) >= 2 and ts[sel_t[0]] != ts[sel_t[-1]]:
        real_dur = (ts[sel_t[-1]] - ts[sel_t[0]]) / 1e6
    duration = (real_dur / args.speed_mult) if (args.speed_mult and real_dur > 0) else args.duration
    speed = seg_len / duration
    n_frames = int(round(duration * args.fps))
    pace = f" (real walk {real_dur:.0f} s, ×{real_dur / duration:.1f})" if real_dur > 0 else ""
    print(f"  duration {duration:.1f} s @ {args.fps} fps → {n_frames:,} frames · "
          f"camera speed {speed:.2f} m/s{pace}")

    anchors = map_anchors_to_path(anchors_all, path, max_dist_m=args.max_anchor_dist)
    print(f"  anchors in segment: {len(anchors)}")
    for a in anchors:
        print(f"    - arc {a['arc'] + path['lo']:7.1f} m  d={a['dist']:4.1f} m  {a['title'][:60]}")

    eyes, targets, _s_vals = sample_camera_path(path, duration, args.fps, args.look_ahead_m)
    up = UP
    cam_label = args.look_mode
    walker = None
    if args.view != "walkthrough":
        eyes, targets, up, cam_label, walker = birds_camera_path(path, args)
        weights = np.zeros(len(eyes))
        print(f"  view: {cam_label} ({len(eyes):,} frames)")
    elif args.look_mode == "anchors":
        targets, weights = compute_anchor_look(eyes, targets, anchors, args.anchor_sigma_m)
    else:
        weights = np.zeros(len(eyes))
    print(f"  frames with an engaged anchor (w > 0.35): {(weights > 0.35).sum()}")

    pcd = load_point_cloud(rec_dir, args.voxel, args.max_points)

    import open3d as o3d
    print("  building offscreen renderer …")
    show_path = args.annotated or args.view != "walkthrough"   # highlight the route in aerial views
    traj_lines = make_trajectory_lines(path["pts"], path["arc"]) if show_path else None
    anchor_spheres = make_anchor_markers(anchors) if args.annotated else None

    renderer = o3d.visualization.rendering.OffscreenRenderer(args.width, args.height)
    build_scene(renderer, pcd, args, traj_lines=traj_lines, anchor_spheres=anchor_spheres)
    intrinsic = make_intrinsic(args.width, args.height, args.vfov)

    # moving marker at the walker's ground position (in aerial views) so the
    # "original point" is easy to spot from the drone/birds-eye camera
    marker_pos = walker
    marker_names = None
    if marker_pos is not None and not args.no_marker:
        marker_names = add_progress_marker(renderer, args.marker_radius)
        print("  progress marker: ON (bright red beacon follows the route)")

    out_dir = args.out or (DEFAULT_OUT_ROOT / args.recording)
    out_dir.mkdir(parents=True, exist_ok=True)
    args.title = args.title or f"{args.recording} · SLAM walkthrough"

    # distinct output names per render flavour (so annotated/overlay runs never
    # clobber the clean comparison videos)
    base = f"walkthrough_{args.look_mode}" if args.view == "walkthrough" else cam_label
    flavour = "_".join([f for f in ("annotated", "overlay") if getattr(args, f, False)])
    suffix = f"_{flavour}" if flavour else ""

    # preview contact sheet (cheap; useful even in full-render runs)
    render_preview(renderer, intrinsic, path, eyes, targets, anchors,
                   weights if (args.look_mode == "anchors" and args.view == "walkthrough") else None,
                   args, out_dir / f"preview_{base}{suffix}.png", up=up,
                   marker_pos=marker_pos, marker_names=marker_names)

    if args.preview_only:
        print("preview-only run finished.")
        return

    video_path = out_dir / f"{args.recording}_{base}{suffix}.mp4"
    settings = {
        "recording": args.recording,
        "view": args.view,
        "look_mode": args.look_mode,
        "camera": cam_label,
        "topdown_height": getattr(args, "topdown_height", None),
        "birds_height": getattr(args, "birds_height", None),
        "marker_radius": getattr(args, "marker_radius", None),
        "no_marker": getattr(args, "no_marker", False),
        "segment_m": [path["start_m"], path["end_m"]],
        "segment_len_m": seg_len,
        "route_total_m": path["total"],
        "duration_s": duration,
        "camera_speed_mps": speed,
        "real_duration_s": real_dur or None,
        "fps": args.fps,
        "width": args.width,
        "height": args.height,
        "vfov_deg": args.vfov,
        "point_size": args.point_size,
        "background": args.background,
        "shader": args.shader,
        "brightness": args.brightness,
        "gamma": args.gamma,
        "voxel_m": args.voxel,
        "cloud_points": len(pcd.points),
        "path_points": len(path["pts"]),
        "anchors_in_segment": [
            {"node_id": a["node_id"], "arc_m": float(a["arc"] + path["lo"]),
             "dist_m": a["dist"], "title": a["title"]} for a in anchors
        ],
        "overlay": args.overlay,
        "annotated": args.annotated,
    }
    write_video(renderer, intrinsic, eyes, targets, weights, anchors, args, path,
                cam_label, video_path, settings, up=up,
                marker_pos=marker_pos, marker_names=marker_names)

    settings["video_path"] = str(video_path)
    with open(out_dir / "settings.json", "w") as f:
        json.dump(settings, f, indent=2)
    flavoured = out_dir / f"settings{('_' + flavour) if flavour else ''}.json"
    if flavoured != out_dir / "settings.json":
        with open(flavoured, "w") as f:
            json.dump(settings, f, indent=2)
        print(f"  settings → {out_dir / 'settings.json'} (+ {flavoured.name})")
    else:
        print(f"  settings → {out_dir / 'settings.json'}")
    print("Done.")


if __name__ == "__main__":
    main()
