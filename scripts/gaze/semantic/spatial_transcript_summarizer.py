"""
SPATIAL TRANSCRIPT SUMMARIZER
-----------------------------
1. Clusters high-density gaze points into 'Hotspot Zones'.
2. Aligns these zones with the verbal transcript (Whisper output).
3. Uses Gemini 2.5 Flash to summarize the semantic intent at each hotspot.
4. Generates an enhanced HTML report with video clips, transcripts, and AI insights.

Usage:
python spatial_transcript_summarizer.py --mps_root [path] --vrs_path [path] --transcript [path] --output [path]
"""

import os
import re
import argparse
import gzip
import sys
import requests
import numpy as np
import pandas as pd
import open3d as o3d
from sklearn.cluster import DBSCAN
from scipy.spatial.transform import Rotation as R
from tqdm import tqdm
from projectaria_tools.core import data_provider
from projectaria_tools.core.sensor_data import TimeDomain, TimeQueryOptions
from PIL import Image, ImageDraw
import moviepy.editor as mpy
from datetime import datetime
import json

# Maximum points to keep for raycasting (performance limit)
MAX_RAYCAST_POINTS = 500_000

# Semidense CSV.gz column name variations
SEMIDENSE_COLUMNS = {
    'px_world': None, 'py_world': None, 'pz_world': None, 'dist_std': None,
}
SEMIDENSE_CSV_CANDIDATES = ['px_world', 'x', 'px', 'x_coord']
SEMIDENSE_STD_CANDIDATES = ['dist_std', 'std', 'distance_std', 'distance_std_dev']

# --- CONFIGURATION ---
GAP_TOLERANCE_US = 1500000  # 1.5s gap allowed within an event
MIN_EVENT_DURATION_US = 800000  # 0.8s minimum duration
TRANSCRIPT_CONTEXT_SEC = 5.0  # Seconds of transcript context before/after event

# Load Secrets
SECRETS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "secrets.json")
if os.path.exists(SECRETS_PATH):
    with open(SECRETS_PATH, "r") as f:
        secrets = json.load(f)
        SERVICE_URL = secrets.get("SERVICE_URL")
        PASSWORD = secrets.get("RESEARCH_PASSWORD")
else:
    SERVICE_URL = None
    PASSWORD = None
    print(f"⚠️ Warning: secrets.json not found at {SECRETS_PATH}")

# ==========================================
# 0. SEMIDENSE POINT CLOUD LOADER
# ==========================================

SEMIDENSE_CSV_GZ_CANDIDATES = [
    "semidense_points.csv.gz",
    "semidense_points.csv",
    "semi_dense_points.csv.gz",
    "global_points.csv.gz",
]

def _find_semipcd_csv(mps_root):
    """Search for semidense point cloud CSV.gz in mps_root and mps_root/slam/."""
    candidates = [
        os.path.join(mps_root, "slam", f) for f in SEMIDENSE_CSV_GZ_CANDIDATES
    ] + [os.path.join(mps_root, f) for f in SEMIDENSE_CSV_GZ_CANDIDATES]
    # Also try .ply as a fallback
    ply_candidates = [
        os.path.join(mps_root, "slam", "semi_dense_points.ply"),
        os.path.join(mps_root, "slam", "semidense_points.ply"),
        os.path.join(mps_root, "semi_dense_points.ply"),
        os.path.join(mps_root, "slam", "pointcloud.ply"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c, "csv_gz"
    for c in ply_candidates:
        if os.path.exists(c):
            return c, "ply"
    return None, None


def _read_csv_gz_fast(path, columns):
    """Column-selective read of a gzipped CSV via pyarrow (pandas fallback)."""
    try:
        import pyarrow as pa
        import pyarrow.csv as pacsv
        src = pa.CompressedInputStream(pa.OSFile(path, 'rb'), 'gzip')
        opts = pacsv.ConvertOptions(include_columns=columns) if columns else None
        return pacsv.read_csv(src, convert_options=opts).to_pandas()
    except Exception as e:
        print(f"    (pyarrow gz read failed: {e}; pandas fallback)")
        with gzip.open(path, 'rt') as f:
            return pd.read_csv(f, comment='#', usecols=columns)


def _parse_semipcd_csv_gz(path):
    """Load semidense CSV.gz manually: columns px_world, py_world, pz_world, dist_std."""
    # Fast path: read only the coordinate + confidence columns (pyarrow) when the
    # standard names are present; else fall back to a full read for the heuristic.
    with gzip.open(path, 'rt') as f:
        header = f.readline().strip().split(',')
    std_hdr = next((c for c in SEMIDENSE_STD_CANDIDATES if c in header), None)
    if all(c in header for c in ('px_world', 'py_world', 'pz_world')):
        want = ['px_world', 'py_world', 'pz_world'] + ([std_hdr] if std_hdr else [])
        df = _read_csv_gz_fast(path, want)
    else:
        with gzip.open(path, 'rt') as f:
            df = pd.read_csv(f, comment='#')

    # Prefer exact column names first, then fall back to heuristic search
    x_col = 'px_world' if 'px_world' in df.columns else next((c for c in SEMIDENSE_CSV_CANDIDATES if c in df.columns), df.columns[0])
    y_col = 'py_world' if 'py_world' in df.columns else next((c for c in SEMIDENSE_CSV_CANDIDATES if c in df.columns and c != x_col), df.columns[1] if len(df.columns) > 1 else None)
    z_col = 'pz_world' if 'pz_world' in df.columns else next((c for c in SEMIDENSE_CSV_CANDIDATES if c in df.columns and c not in (x_col, y_col or '')), df.columns[2] if len(df.columns) > 2 else None)

    # Validate: must be numeric columns
    for col in (x_col, y_col, z_col):
        if col not in df.columns or not pd.api.types.is_numeric_dtype(df[col]):
            raise ValueError(f"Expected coordinate column '{col}' not found or not numeric in {path}")

    std_col = None
    for candidate in SEMIDENSE_STD_CANDIDATES:
        if candidate in df.columns and pd.api.types.is_numeric_dtype(df[candidate]):
            std_col = candidate
            break

    # Filter by confidence: MPS recommended threshold is 0.15 for dist_std
    if std_col is not None:
        mask = df[std_col] <= 0.15
        print(f"    Confidence filter (dist_std <= 0.15): {len(df)} -> {mask.sum()} points")
    else:
        mask = np.ones(len(df), dtype=bool)

    points = df[[x_col, y_col, z_col]].to_numpy()[mask].astype(np.float32)

    # Subsample for raycasting performance
    if len(points) > MAX_RAYCAST_POINTS:
        idx = np.random.choice(len(points), MAX_RAYCAST_POINTS, replace=False)
        points = points[idx]

    return points


def load_semipcd_from_mps(mps_root):
    """
    Load semidense point cloud from MPS output, apply confidence filtering,
    and return an Open3D PointCloud suitable for raycasting.

    Uses projectaria_tools.core.mps.read_global_point_cloud() if available
    (official API), falling back to raw CSV parsing.
    """
    path, fmt = _find_semipcd_csv(mps_root)

    if not path:
        return None, None

    if fmt == "ply":
        print(f"  Found .ply point cloud: {path}")
        pcd = o3d.io.read_point_cloud(path)
        if len(pcd.points) > MAX_RAYCAST_POINTS:
            indices = np.random.choice(len(pcd.points), MAX_RAYCAST_POINTS, replace=False)
            pcd = pcd.select_by_index(indices)
        return pcd, path

    print(f"  Loading semidense point cloud from CSV.gz: {path}")

    # Column-selective vectorized read. NB: the MPS binary read_global_point_cloud
    # returns millions of Python objects whose per-point position extraction is
    # far slower than this path, so we read the .csv.gz directly (pyarrow).
    positions = _parse_semipcd_csv_gz(path)
    print(f"  Loaded {len(positions)} points via CSV fallback")

    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(positions.astype(np.float32))
    colors = np.zeros_like(positions, dtype=np.float32)
    pcd.colors = o3d.utility.Vector3dVector(colors)
    return pcd, path


# ==========================================
# 0. RAYCASTING HELPERS
# ==========================================

def get_refined_gaze_points(pcd, origins, directions, fallback_depth=2.0):
    """
    Refines gaze targets by finding the nearest point in the PCD to the gaze ray.
    Returns (refined_points, quality_flags) with four tiers:
      1.0 = STRONG (perp < 0.5m), 0.5 = WEAK (0.5m-1.0m),
      0.25 = UNCERTAIN (1.0m-1.5m), 0.0 = FALLBACK (no surface within 1.5m)
    """
    print(f"Refining {len(origins)} gaze points via KDTree raycasting...")
    from scipy.spatial import cKDTree
    points_pcd = np.asarray(pcd.points)
    tree = cKDTree(points_pcd)

    origins = np.asarray(origins, dtype=np.float64)
    dirs = np.asarray(directions, dtype=np.float64)
    dirs = dirs / np.linalg.norm(dirs, axis=1, keepdims=True)
    guess = origins + dirs * fallback_depth

    # One batched, multithreaded radius search for all rays (replaces the
    # per-point open3d query loop). Same algorithm per ray afterwards.
    neighbor_lists = tree.query_ball_point(guess, 1.5, workers=-1)

    refined = guess.copy()                       # default = 2.0m fallback point
    quality_flags = np.zeros(len(origins))
    for i, idxs in enumerate(neighbor_lists):
        if not idxs:
            continue
        pts = points_pcd[idxs]
        vecs = pts - origins[i]
        proj_dist = vecs @ dirs[i]
        mask = (proj_dist > 0.1) & (proj_dist < 10.0)
        if not np.any(mask):
            continue
        perp_dist = np.linalg.norm(vecs[mask] - np.outer(proj_dist[mask], dirs[i]), axis=1)
        best = np.argmin(perp_dist)
        pd_best = perp_dist[best]
        refined[i] = pts[mask][best]
        quality_flags[i] = 1.0 if pd_best < 0.5 else (0.5 if pd_best < 1.0 else 0.25)

    return refined, quality_flags

# ==========================================
# 1. DATA LOADING & PRE-PROCESSING
# ==========================================

def _header_cols(path):
    """Column names of a CSV (or its .parquet sibling), read cheaply."""
    parq = path[:-4] + ".parquet" if path.endswith(".csv") else None
    if parq and os.path.exists(parq):
        import pyarrow.parquet as pq
        return list(pq.read_schema(parq).names)
    with open(path) as f:
        return f.readline().strip().split(',')


def _read_csv_fast(path, columns):
    """Read `columns` from an MPS CSV (or its .parquet sibling) into a pandas
    DataFrame. Tiers for speed: parquet sibling > pyarrow CSV > pandas. Output is
    identical to pandas read_csv on those columns -- it just reads fewer columns
    with a faster parser (the multi-GB trajectory is the bottleneck)."""
    parq = path[:-4] + ".parquet" if path.endswith(".csv") else None
    if parq and os.path.exists(parq):
        try:
            import pyarrow.parquet as pq
            return pq.read_table(parq, columns=columns).to_pandas()
        except Exception:
            pass
    try:
        import pyarrow.csv as pacsv
        opts = pacsv.ConvertOptions(include_columns=columns)
        return pacsv.read_csv(path, convert_options=opts).to_pandas()
    except Exception as e:
        print(f"  (pyarrow read failed: {e}; pandas fallback)")
        return pd.read_csv(path, comment='#', usecols=columns)


def load_data(mps_root, pcd_path=None):
    print("📐 Loading Gaze and Trajectory...")
    gaze_csv = os.path.join(mps_root, "eye_gaze", "general_eye_gaze.csv")
    traj_candidates = [
        os.path.join(mps_root, "closed_loop_trajectory.csv"),
        os.path.join(mps_root, "slam", "closed_loop_trajectory.csv")
    ]
    traj_csv = next((p for p in traj_candidates if os.path.exists(p)), None)

    if not os.path.exists(gaze_csv) or not traj_csv:
        raise FileNotFoundError("Gaze or trajectory files missing.")

    # Read only the columns used downstream, with a fast parser (parquet sibling
    # or pyarrow). Preserves the same conditional logic by selecting whichever
    # column variant the file actually has.
    gcols = _header_cols(gaze_csv)
    want_g = ['tracking_timestamp_us', 'pitch_rads_cpf']
    want_g += ['yaw_rads_cpf'] if 'yaw_rads_cpf' in gcols else ['left_yaw_rads_cpf', 'right_yaw_rads_cpf']
    gaze_df = _read_csv_fast(gaze_csv, [c for c in want_g if c in gcols])

    tcols = _header_cols(traj_csv)
    pose = (['tx_device_world', 'ty_device_world', 'tz_device_world',
             'qx_device_world', 'qy_device_world', 'qz_device_world', 'qw_device_world']
            if 'qx_device_world' in tcols else
            ['tx_world_device', 'ty_world_device', 'tz_world_device',
             'qx_world_device', 'qy_world_device', 'qz_world_device', 'qw_world_device'])
    traj_df = _read_csv_fast(traj_csv, ['tracking_timestamp_us'] + [c for c in pose if c in tcols])

    # Merge gaze with trajectory
    gaze_df = gaze_df.sort_values('tracking_timestamp_us')
    traj_df = traj_df.sort_values('tracking_timestamp_us')
    merged = pd.merge_asof(gaze_df, traj_df, on='tracking_timestamp_us', direction='nearest', tolerance=100000).dropna()

    # Calculate 3D Gaze Targets in World Space
    if 'yaw_rads_cpf' not in merged.columns:
        yaw = (merged['left_yaw_rads_cpf'] + merged['right_yaw_rads_cpf']) / 2
        pitch = merged['pitch_rads_cpf']
    else:
        yaw, pitch = merged['yaw_rads_cpf'], merged['pitch_rads_cpf']

    # Local unit vectors (normalized)
    lx, ly, lz = np.tan(yaw), np.tan(pitch), np.ones(len(merged))
    local_vecs = np.vstack((lx, ly, lz)).T

    if 'qx_device_world' in merged.columns:
        quats = merged[['qx_device_world', 'qy_device_world', 'qz_device_world', 'qw_device_world']].to_numpy()
        pos = merged[['tx_device_world', 'ty_device_world', 'tz_device_world']].to_numpy()
    else:
        quats = merged[['qx_world_device', 'qy_world_device', 'qz_world_device', 'qw_world_device']].to_numpy()
        pos = merged[['tx_world_device', 'ty_world_device', 'tz_world_device']].to_numpy()

    r = R.from_quat(quats)
    world_dirs = r.apply(local_vecs)

    pcd = None
    pcd_source = None

    if pcd_path and os.path.exists(pcd_path):
        # Explicitly provided point cloud
        pcd = o3d.io.read_point_cloud(pcd_path)
        pcd_source = pcd_path
    else:
        # Auto-detect semidense point cloud from MPS
        pcd, pcd_source = load_semipcd_from_mps(mps_root)

    # Initialize gaze_quality (1.0 = default, will be overwritten for real raycast points)
    merged['gaze_quality'] = 0.0

    if pcd is not None and len(pcd.points) > 0:
        world_targets, quality_flags = get_refined_gaze_points(pcd, pos, world_dirs)
        # Force writable copy (pandas .values can return read-only views)
        merged['gaze_quality'] = quality_flags.astype(np.float64)
    else:
        print("⚠️ No Point Cloud provided. Using fixed 2.0m depth.")
        world_targets = pos + (world_dirs * 2.0)

    merged['gx'], merged['gy'], merged['gz'] = world_targets[:, 0], world_targets[:, 1], world_targets[:, 2]
    merged['yaw'], merged['pitch'] = yaw, pitch

    return merged, pcd

# ==========================================
# 2. CLUSTERING & EVENT MAPPING
# ==========================================

def run_indexing(merged_df, eps=0.25, min_samples=10, quality_col=None):
    print("📍 Clustering gaze hotspots...")
    coords = merged_df[['gx', 'gy', 'gz']].to_numpy()
    if quality_col:
        low_quality_mask = merged_df[quality_col] < 0.5
        coords[low_quality_mask] = np.full(3, -1e6)  # Push low-quality points far away so they don't cluster
    clustering = DBSCAN(eps=eps, min_samples=min_samples).fit(coords)
    merged_df['cluster_id'] = clustering.labels_

    events = []
    current_event = None

    for _, row in merged_df.iterrows():
        # iterrows() returns each row as a single-dtype Series; with an all-numeric
        # frame that upcasts these ints to float, so cast back explicitly.
        cid = int(row['cluster_id'])
        ts = int(row['tracking_timestamp_us'])

        if cid == -1:
            if current_event and (ts - current_event['end_ts'] > GAP_TOLERANCE_US):
                events.append(current_event)
                current_event = None
            continue
            
        if current_event and current_event['cluster_id'] == cid:
            current_event['end_ts'] = ts
            current_event['samples'].append(row)
        else:
            if current_event: events.append(current_event)
            current_event = {'cluster_id': cid, 'start_ts': ts, 'end_ts': ts, 'samples': [row]}
    
    if current_event: events.append(current_event)
    
    valid_events = [e for e in events if (e['end_ts'] - e['start_ts']) > MIN_EVENT_DURATION_US]
    print(f"   Found {len(valid_events)} significant viewing events.")
    return valid_events

# ==========================================
# 3. TRANSCRIPT ALIGNMENT & AI SUMMARY
# ==========================================

def load_transcript(path):
    """Parses [0000s - 0010s]: Text format (single-line or multi-line).

    Supports both formats:
      [0000s - 0010s]: Text on same line
      [0000s - 0010s]:

      ORIGINAL: Multi-line content...
      VISUALS:  ...
    """
    if not os.path.exists(path):
        print(f"⚠️ Warning: Transcript not found at {path}")
        return None

    transcript_data = []
    pattern = re.compile(r"\[(\d+)s - (\d+)s\]")
    text_lines = []
    prev_start = None

    with open(path, 'r') as f:
        for line in f:
            match = pattern.search(line)
            if match:
                # Save previous block
                if prev_start is not None:
                    text = ' '.join(l.strip() for l in text_lines if l.strip())
                    transcript_data.append({'start': prev_start, 'end': int(match.group(1)), 'text': text})
                prev_start = int(match.group(1))
                text_lines = []
                # Single-line format: capture text after the marker on the same
                # line, e.g. "[0000s - 0010s] (it): hola" -> "hola" (the optional
                # (lang)/speaker tag before the colon is dropped).
                after = line[match.end():]
                if ':' in after:
                    same = after.split(':', 1)[1].strip()
                    if same:
                        text_lines.append(same)
            else:
                text_lines.append(line.rstrip('\n\r'))

    # Save last block (extend by 10s from its start)
    if prev_start is not None:
        text = ' '.join(l.strip() for l in text_lines if l.strip())
        transcript_data.append({'start': prev_start, 'end': prev_start + 10, 'text': text})

    return transcript_data

def get_transcript_slice(transcript, start_sec, end_sec):
    if not transcript: return "No transcript available."
    
    # Expand window for context
    w_start = max(0, start_sec - TRANSCRIPT_CONTEXT_SEC)
    w_end = end_sec + TRANSCRIPT_CONTEXT_SEC
    
    relevant = [t['text'] for t in transcript if not (t['end'] < w_start or t['start'] > w_end)]
    return " ".join(relevant)

def summarize_with_gemini(transcript_slice):
    if "No transcript available" in transcript_slice: return "No verbal context."
    
    prompt = f"""
    I am analyzing an egocentric recording where a user is looking at an architectural model or spatial structure.
    Based on the following transcript slice, summarize the user's intent or the specific features they are describing 
    at this moment. Keep it to 2 concise sentences. Focus on architectural or technical details mentioned.
    
    TRANSCRIPT:
    "{transcript_slice}"
    
    SUMMARY:
    """
    
    headers = {"Content-Type": "application/json", "Authorization": PASSWORD}
    payload = {"prompt": prompt}
    
    try:
        response = requests.post(SERVICE_URL, headers=headers, json=payload, timeout=60)
        if response.status_code == 200:
            return response.json().get("response", "AI summary unavailable.").strip()
    except Exception as e:
        print(f"   ❌ Gemini Error: {e}")
    return "AI processing failed."

# ==========================================
# 4. VIDEO EXTRACTION & REPORTING
# ==========================================

def save_semantic_results(events, output_path):
    serializable_events = []
    for i, e in enumerate(events):
        se = e.copy()
        if 'samples' in se:
            del se['samples']
        se['id'] = i  # Add ID for Stage 3 synthesis
        serializable_events.append(se)
    
    with open(output_path, "w") as f:
        json.dump(serializable_events, f, indent=4)
    print(f"💾 Saved {len(serializable_events)} events to {output_path}")

def process_events(vrs_path, transcript_path, events, output_root):
    print(f"🎬 Processing {len(events)} events (Clips + Transcripts + AI)...")
    provider = data_provider.create_vrs_data_provider(vrs_path)
    rgb_stream = provider.get_stream_id_from_label("camera-rgb")
    vrs_start_ns = provider.get_first_time_ns(rgb_stream, TimeDomain.DEVICE_TIME)
    
    transcript = load_transcript(transcript_path)

    for i, event in enumerate(tqdm(events)):
        cluster_id = event['cluster_id']
        cluster_dir = os.path.join(output_root, f"cluster_{cluster_id:02d}")
        os.makedirs(cluster_dir, exist_ok=True)
        
        # 1. Calculate Relative Timestamps for Transcript
        event_start_sec = (event['start_ts'] * 1000 - vrs_start_ns) / 1e9
        event_end_sec = (event['end_ts'] * 1000 - vrs_start_ns) / 1e9
        
        # 2. Extract Transcript Slice & AI Summary
        t_slice = get_transcript_slice(transcript, event_start_sec, event_end_sec)
        event['transcript_slice'] = t_slice
        event['ai_summary'] = summarize_with_gemini(t_slice)
        event['relative_time'] = f"{event_start_sec:.1f}s - {event_end_sec:.1f}s"
        event['start_sec'] = event_start_sec
        event['duration'] = event_end_sec - event_start_sec
        
        # Calculate mean gaze position for 3D anchor
        samples_df = pd.DataFrame(event['samples'])
        event['gx'] = float(samples_df['gx'].mean())
        event['gy'] = float(samples_df['gy'].mean())
        event['gz'] = float(samples_df['gz'].mean())
        event['mean_quality'] = float(samples_df['gaze_quality'].mean())
        event['sample_count'] = len(samples_df)
        event['fallback_ratio'] = float((samples_df['gaze_quality'] == 0.0).mean())
        q = samples_df['gaze_quality'].values
        event['quality_tiers'] = {
            "strong": int((q == 1.0).sum()),
            "weak": int((q == 0.5).sum()),
            "uncertain": int((q == 0.25).sum()),
            "fallback": int((q == 0.0).sum()),
        }

        # 3. Extract Video Clip with Overlay
        frames = []
        step = max(1, len(event['samples']) // 15) 
        for row in event['samples'][::step]:
            ts_ns = int(row['tracking_timestamp_us'] * 1000)
            try:
                vrs_idx = provider.get_index_by_time_ns(rgb_stream, ts_ns, TimeDomain.DEVICE_TIME, TimeQueryOptions.CLOSEST)
                frame_data = provider.get_image_data_by_index(rgb_stream, vrs_idx)
                if frame_data:
                    img = Image.fromarray(frame_data[0].to_numpy_array())
                    w, h = img.size
                    cx, cy = w/2, h/2
                    px = cx + np.tan(row['yaw']) * (w / 1.5) 
                    py = cy + np.tan(row['pitch']) * (h / 1.5)
                    draw = ImageDraw.Draw(img)
                    r = 15
                    draw.ellipse([px-r, py-r, px+r, py+r], outline="red", width=4)
                    frames.append(np.array(img))
            except: continue

        if frames:
            clip_name = f"event_{i:03d}_cluster_{cluster_id}.mp4"
            clip_path = os.path.join(cluster_dir, clip_name)
            clip = mpy.ImageSequenceClip(frames, fps=10)
            clip.write_videofile(clip_path, codec="libx264", audio=False, logger=None)
            event['clip_rel_path'] = f"cluster_{cluster_id:02d}/{clip_name}"

def generate_html_report(events, output_root):
    print("🌐 Generating Enhanced Semantic Report...")
    html_content = f"""
    <html>
    <head>
        <title>Aria Semantic Hotspot Report</title>
        <style>
            body {{ font-family: -apple-system, system-ui, sans-serif; background: #0f0f0f; color: #eee; padding: 40px; }}
            h1 {{ color: #fff; border-bottom: 2px solid #333; }}
            .hotspot {{ border: 1px solid #333; margin-bottom: 50px; padding: 30px; border-radius: 15px; background: #1a1a1a; }}
            .event-card {{ background: #242424; padding: 20px; border-radius: 10px; margin-top: 20px; display: flex; gap: 20px; }}
            .video-side {{ flex: 1; min-width: 400px; }}
            .text-side {{ flex: 1.5; }}
            video {{ width: 100%; border-radius: 8px; background: #000; }}
            h2 {{ color: #ff5252; margin-top: 0; }}
            .ai-box {{ background: #2d3436; padding: 15px; border-left: 4px solid #00cec9; margin-top: 15px; font-style: italic; color: #00cec9; }}
            .transcript-box {{ font-size: 0.9em; color: #aaa; margin-top: 10px; height: 100px; overflow-y: auto; background: #111; padding: 10px; border-radius: 5px; }}
            .meta {{ color: #777; font-size: 0.8em; margin-bottom: 5px; }}
        </style>
    </head>
    <body>
        <h1>Aria Research: Semantic Hotspot Report</h1>
        <p>Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
    """
    
    clusters = sorted(list(set([e['cluster_id'] for e in events])))
    for cid in clusters:
        if cid == -1: continue
        c_events = [e for e in events if e['cluster_id'] == cid]
        html_content += f"""
        <div class="hotspot">
            <h2>📍 Hotspot Zone {cid:02d}</h2>
            <p>Observed {len(c_events)} times</p>
        """
        for e in c_events:
            html_content += f"""
            <div class="event-card">
                <div class="video-side">
                    <video controls>
                        <source src="{e.get('clip_rel_path', '')}" type="video/mp4">
                    </video>
                    <div class="meta">Relative Time: {e['relative_time']} | Duration: {((e['end_ts'] - e['start_ts'])/1e6):.2f}s</div>
                </div>
                <div class="text-side">
                    <strong>🤖 AI Semantic Insight:</strong>
                    <div class="ai-box">{e.get('ai_summary', 'Processing failed.')}</div>
                    <div style="margin-top:20px;"><strong>🎙️ Transcript Slice:</strong></div>
                    <div class="transcript-box">{e.get('transcript_slice', 'No transcript context.')}</div>
                </div>
            </div>
            """
        html_content += "</div>"

    html_content += "</body></html>"
    with open(os.path.join(output_root, "semantic_report.html"), "w") as f:
        f.write(html_content)

# ==========================================
# MAIN
# ==========================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mps_root", required=True)
    parser.add_argument("--vrs_path", required=True)
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--pcd", help="Path to point cloud (.ply), or unset to auto-detect semidense from MPS")
    parser.add_argument("--eps", type=float, default=0.25, help="DBSCAN eps (meters). Default: 0.25")
    parser.add_argument("--min-samples", type=int, default=10, help="DBSCAN min_samples. Default: 10")
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)

    try:
        data, loaded_pcd = load_data(args.mps_root, args.pcd)
        events = run_indexing(data, eps=args.eps, min_samples=args.min_samples, quality_col='gaze_quality')
        process_events(args.vrs_path, args.transcript, events, args.output)
        generate_html_report(events, args.output)

        # Save results for next stage (narrative synthesis)
        results_json_path = os.path.join(args.output, "semantic_results.json")
        save_semantic_results(events, results_json_path)

        # Export point cloud PLY for web-viewer compatibility
        if loaded_pcd is not None and len(loaded_pcd.points) > 0:
            ply_path = os.path.join(args.output, "pointcloud.ply")
            o3d.io.write_point_cloud(ply_path, loaded_pcd)
            print(f"  Exported point cloud ({len(loaded_pcd.points)} pts): {ply_path}")
        elif args.pcd is None:
            print("  Skipped point cloud export (no point cloud loaded).")

        print(f"\n🎉 Success! Semantic report: {os.path.join(args.output, 'semantic_report.html')}")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
