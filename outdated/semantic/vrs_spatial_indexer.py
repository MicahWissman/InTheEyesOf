"""
VRS SPATIAL EVENT INDEXER
-------------------------
1. Clusters high-density gaze points into 'Hotspot Zones' (DBSCAN).
2. Maps these zones back to temporal 'Viewing Events' in the VRS.
3. Extracts MP4 clips with a gaze crosshair overlay.
4. Generates an interactive HTML report.

Requirements:
pip install pandas numpy scipy sklearn projectaria-tools Pillow moviepy
"""

import os
import gzip
import argparse
import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN
from scipy.spatial.transform import Rotation as R
from tqdm import tqdm
from projectaria_tools.core import data_provider
from projectaria_tools.core.sensor_data import TimeDomain, TimeQueryOptions
from PIL import Image, ImageDraw
import moviepy.editor as mpy
from datetime import datetime

# ==========================================
# 1. DATA LOADING & PRE-PROCESSING
# ==========================================

def load_data(mps_root):
    print("📐 Loading Gaze and Trajectory...")
    gaze_csv = os.path.join(mps_root, "eye_gaze", "general_eye_gaze.csv")
    traj_candidates = [
        os.path.join(mps_root, "closed_loop_trajectory.csv"),
        os.path.join(mps_root, "slam", "closed_loop_trajectory.csv")
    ]
    traj_csv = next((p for p in traj_candidates if os.path.exists(p)), None)

    if not os.path.exists(gaze_csv) or not traj_csv:
        raise FileNotFoundError("Gaze or trajectory files missing.")

    gaze_df = pd.read_csv(gaze_csv, comment='#')
    traj_df = pd.read_csv(traj_csv, comment='#')

    # Merge gaze with trajectory
    gaze_df = gaze_df.sort_values('tracking_timestamp_us')
    traj_df = traj_df.sort_values('tracking_timestamp_us')
    merged = pd.merge_asof(gaze_df, traj_df, on='tracking_timestamp_us', direction='nearest', tolerance=100000).dropna()

    # Calculate 3D Gaze Targets in World Space
    depth = 2.0 # Assume 2m depth for projection if not provided
    if 'yaw_rads_cpf' not in merged.columns:
        yaw = (merged['left_yaw_rads_cpf'] + merged['right_yaw_rads_cpf']) / 2
        pitch = merged['pitch_rads_cpf']
    else:
        yaw, pitch = merged['yaw_rads_cpf'], merged['pitch_rads_cpf']

    lx, ly, lz = depth * np.tan(yaw), depth * np.tan(pitch), np.full(len(merged), depth)
    local_vecs = np.vstack((lx, ly, lz)).T

    if 'qx_device_world' in merged.columns:
        quats = merged[['qx_device_world', 'qy_device_world', 'qz_device_world', 'qw_device_world']].to_numpy()
        pos = merged[['tx_device_world', 'ty_device_world', 'tz_device_world']].to_numpy()
    else:
        quats = merged[['qx_world_device', 'qy_world_device', 'qz_world_device', 'qw_world_device']].to_numpy()
        pos = merged[['tx_world_device', 'ty_world_device', 'tz_world_device']].to_numpy()

    r = R.from_quat(quats)
    world_targets = pos + r.apply(local_vecs)
    merged['gx'], merged['gy'], merged['gz'] = world_targets[:, 0], world_targets[:, 1], world_targets[:, 2]
    merged['yaw'], merged['pitch'] = yaw, pitch

    return merged

# ==========================================
# 2. CLUSTERING & EVENT MAPPING
# ==========================================

def run_indexing(merged_df, eps=0.25, min_samples=30):
    print("📍 Clustering gaze hotspots...")
    coords = merged_df[['gx', 'gy', 'gz']].to_numpy()
    clustering = DBSCAN(eps=eps, min_samples=min_samples).fit(coords)
    merged_df['cluster_id'] = clustering.labels_

    events = []
    current_event = None
    gap_tolerance_us = 1500000 # 1.5s gap allowed within an event

    for _, row in merged_df.iterrows():
        cid = row['cluster_id']
        ts = row['tracking_timestamp_us']
        
        if cid == -1:
            if current_event and (ts - current_event['end_ts'] > gap_tolerance_us):
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
    
    # Filter: Events must be > 0.8s
    valid_events = [e for e in events if (e['end_ts'] - e['start_ts']) > 800000]
    print(f"   Found {len(valid_events)} significant viewing events.")
    return valid_events

# ==========================================
# 3. VIDEO EXTRACTION WITH OVERLAY
# ==========================================

def extract_clips_with_overlay(vrs_path, events, output_root):
    print(f"🎬 Extracting video clips with gaze overlays...")
    provider = data_provider.create_vrs_data_provider(vrs_path)
    rgb_stream = provider.get_stream_id_from_label("camera-rgb")

    for i, event in enumerate(tqdm(events)):
        cluster_id = event['cluster_id']
        cluster_dir = os.path.join(output_root, f"cluster_{cluster_id:02d}")
        os.makedirs(cluster_dir, exist_ok=True)
        
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
                    draw.line([px-20, py, px+20, py], fill="red", width=2)
                    draw.line([px, py-20, px, py+20], fill="red", width=2)
                    frames.append(np.array(img))
            except Exception:
                continue

        if frames:
            clip_name = f"event_{i:03d}_cluster_{cluster_id}.mp4"
            clip_path = os.path.join(cluster_dir, clip_name)
            clip = mpy.ImageSequenceClip(frames, fps=10)
            clip.write_videofile(clip_path, codec="libx264", audio=False, logger=None)
            # Use forward slashes for HTML compatibility
            event['clip_rel_path'] = f"cluster_{cluster_id:02d}/{clip_name}"
        else:
            print(f"   ⚠️ Warning: No frames captured for event {i}")

# ==========================================
# 4. HTML REPORT GENERATION
# ==========================================

def generate_html_report(events, output_root):
    print("🌐 Generating HTML report...")
    html_content = f"""
    <html>
    <head>
        <title>Aria Spatial Event Report</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #121212; color: #e0e0e0; padding: 40px; line-height: 1.6; }}
            h1 {{ color: #ffffff; border-bottom: 2px solid #333; padding-bottom: 10px; }}
            .hotspot {{ border: 1px solid #333; margin-bottom: 40px; padding: 25px; border-radius: 12px; background: #1e1e1e; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }}
            .clip-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 20px; margin-top: 20px; }}
            .event-card {{ background: #252525; padding: 10px; border-radius: 8px; text-align: center; }}
            video {{ border-radius: 6px; width: 100%; background: #000; display: block; }}
            h2 {{ color: #ff5252; margin-top: 0; }}
            .meta {{ color: #aaa; font-size: 0.9em; margin-top: 8px; }}
            .no-video {{ background: #333; padding: 40px; border-radius: 6px; color: #888; }}
        </style>
    </head>
    <body>
        <h1>Project Aria: Gaze Hotspot Report</h1>
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
            <div class="clip-grid">
        """
        for e in c_events:
            html_content += '<div class="event-card">'
            if 'clip_rel_path' in e:
                html_content += f"""
                    <video controls preload="metadata">
                        <source src="{e['clip_rel_path']}" type="video/mp4">
                        Your browser does not support the video tag.
                    </video>
                """
            else:
                html_content += '<div class="no-video">Video missing or failed to generate</div>'
            
            html_content += f"""
                    <div class="meta">
                        <strong>Duration:</strong> {((e['end_ts'] - e['start_ts'])/1e6):.2f}s<br>
                        <strong>Time:</strong> {e['start_ts']}
                    </div>
                </div>
            """
        html_content += "</div></div>"

    html_content += "</body></html>"
    with open(os.path.join(output_root, "report.html"), "w") as f:
        f.write(html_content)

# ==========================================
# MAIN
# ==========================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mps_root", required=True)
    parser.add_argument("--vrs_path", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)
    
    try:
        data = load_data(args.mps_root)
        events = run_indexing(data)
        extract_clips_with_overlay(args.vrs_path, events, args.output)
        generate_html_report(events, args.output)
        print(f"\n🎉 Success! View your report at: {os.path.join(args.output, 'report.html')}")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
