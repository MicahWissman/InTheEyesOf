"""
EXTRACT HOTSPOT FRAMES
---------------------
Identifies high-density gaze areas (hotspots) and extracts representative 
RGB frames from the VRS file to visualize what the user was looking at.

Requirements:
pip install pandas numpy scipy projectaria-tools Pillow
"""

import os
import gzip
from datetime import datetime
import tkinter as tk
from tkinter import filedialog
import pandas as pd
import numpy as np
from scipy.spatial.transform import Rotation as R
from scipy.stats import gaussian_kde
from projectaria_tools.core import data_provider
from projectaria_tools.core.sensor_data import TimeDomain, TimeQueryOptions
from PIL import Image

# ==========================================
# CONFIGURATION
# ==========================================
DENSITY_PERCENTILE = 95  # Top 5% of gaze density are considered "hotspots"
TIME_WINDOW_MS = 1000    # Minimum time (ms) between extracted frames to avoid redundancy
KDE_MAX_SAMPLES = 2000   # Max points for KDE calculation (performance optimization)
SLAM_FILTER_THRESHOLD = 0.005

# ==========================================
# 1. DATA LOADING (Adapted from gaze_heatmap.py)
# ==========================================

def load_slam_exact(mps_root):
    print("☁️ Loading SLAM...")
    candidates = [
        os.path.join(mps_root, "semidense_points.csv"),
        os.path.join(mps_root, "slam", "semidense_points.csv"),
        os.path.join(mps_root, "semidense_points.csv.gz"),
        os.path.join(mps_root, "slam", "semidense_points.csv.gz")
    ]
    path = next((p for p in candidates if os.path.exists(p)), None)
    if not path:
        return None, "SLAM file not found."

    try:
        if path.endswith('.gz'):
            with gzip.open(path, 'rt') as f:
                df = pd.read_csv(f, comment='#')
        else:
            df = pd.read_csv(path, comment='#')
        
        df = df[df['dist_std'] <= SLAM_FILTER_THRESHOLD]
        return df, "Success"
    except Exception as e:
        return None, str(e)

def calculate_gaze_world(mps_root):
    print("\n📐 Calculating Situated Gaze...")
    gaze_csv = os.path.join(mps_root, "eye_gaze", "general_eye_gaze.csv")
    traj_candidates = [
        os.path.join(mps_root, "closed_loop_trajectory.csv"),
        os.path.join(mps_root, "slam", "closed_loop_trajectory.csv")
    ]
    traj_csv = next((p for p in traj_candidates if os.path.exists(p)), None)

    if not os.path.exists(gaze_csv) or not traj_csv:
        return None, "Gaze or trajectory files missing."

    gaze_df = pd.read_csv(gaze_csv, comment='#')
    traj_df = pd.read_csv(traj_csv, comment='#')

    if 'yaw_rads_cpf' not in gaze_df.columns:
        gaze_df['yaw'] = (gaze_df['left_yaw_rads_cpf'] + gaze_df['right_yaw_rads_cpf']) / 2
        gaze_df['pitch'] = gaze_df['pitch_rads_cpf']
    else:
        gaze_df['yaw'] = gaze_df['yaw_rads_cpf']
        gaze_df['pitch'] = gaze_df['pitch_rads_cpf']

    gaze_df = gaze_df.sort_values('tracking_timestamp_us')
    traj_df = traj_df.sort_values('tracking_timestamp_us')
    merged = pd.merge_asof(gaze_df, traj_df, on='tracking_timestamp_us', direction='nearest', tolerance=100000).dropna()

    depth = merged.get('depth_m', 2.0)
    lx = depth * np.tan(merged['yaw'])
    ly = depth * np.tan(merged['pitch'])
    lz = np.full(len(merged), 2.0) if isinstance(depth, float) else depth
    local_vecs = np.vstack((lx, ly, lz)).T

    if 'qx_device_world' in merged.columns:
        quats = merged[['qx_device_world', 'qy_device_world', 'qz_device_world', 'qw_device_world']].to_numpy()
        pos = merged[['tx_device_world', 'ty_device_world', 'tz_device_world']].to_numpy()
    else:
        quats = merged[['qx_world_device', 'qy_world_device', 'qz_world_device', 'qw_world_device']].to_numpy()
        pos = merged[['tx_world_device', 'ty_world_device', 'tz_world_device']].to_numpy()

    r = R.from_quat(quats)
    world_vecs = r.apply(local_vecs)
    targets = pos + world_vecs

    merged['gx'] = targets[:, 0]
    merged['gy'] = targets[:, 1]
    merged['gz'] = targets[:, 2]

    return merged, "Success"

# ==========================================
# 2. HOTSPOT IDENTIFICATION
# ==========================================

def identify_hotspots(gaze_df):
    print(f"\n🔥 Identifying hotspots (Top {100-DENSITY_PERCENTILE}% density)...")
    
    data = np.vstack([gaze_df['gx'], gaze_df['gy'], gaze_df['gz']])
    if len(gaze_df) > KDE_MAX_SAMPLES:
        idx = np.random.choice(len(gaze_df), KDE_MAX_SAMPLES, replace=False)
        kde = gaussian_kde(data[:, idx])
    else:
        kde = gaussian_kde(data)
    
    print(f"   Calculating density for {len(gaze_df)} points...")
    density = kde(data)
    gaze_df['density'] = density
    
    threshold = np.percentile(density, DENSITY_PERCENTILE)
    hotspots = gaze_df[gaze_df['density'] >= threshold].sort_values('tracking_timestamp_us')
    print(f"   Found {len(hotspots)} hotspot points above threshold.")
    
    selected_timestamps = []
    last_ts = -float('inf')
    
    for ts in hotspots['tracking_timestamp_us']:
        if ts - last_ts >= TIME_WINDOW_MS * 1000:
            selected_timestamps.append(ts)
            last_ts = ts
            
    print(f"   Identified {len(selected_timestamps)} unique moments for frame extraction.")
    return selected_timestamps

# ==========================================
# 3. FRAME EXTRACTION
# ==========================================

def extract_frames(vrs_path, timestamps, output_dir):
    print(f"\n📸 Extracting frames from {os.path.basename(vrs_path)}...")
    if not os.path.exists(output_dir): os.makedirs(output_dir)
        
    provider = data_provider.create_vrs_data_provider(vrs_path) # initialize VRS data provider
    stream_id = provider.get_stream_id_from_label("camera-rgb") # grab RBG camera stream
    
    count = 0
    for ts_us in timestamps:
        ts_ns = int(ts_us * 1000) # nanoseconds is standard for Project Aria SDK
        try:
            idx = provider.get_index_by_time_ns(stream_id, ts_ns, TimeDomain.DEVICE_TIME, TimeQueryOptions.CLOSEST)
            frame_data = provider.get_image_data_by_index(stream_id, idx)
            if frame_data:
                img_array = frame_data[0].to_numpy_array() # get image as numpy array
                img = Image.fromarray(img_array) # convert to PIL Image
                filename = f"hotspot_frame_{ts_us}.jpg"
                img.save(os.path.join(output_dir, filename))
                count += 1
                print(f"   [{count}/{len(timestamps)}] Saved: {filename}")
        except Exception as e:
            print(f"   ❌ Error extracting frame at {ts_us}: {e}")
    print(f"\n✅ Finished! Extracted {count} frames to: {output_dir}")

if __name__ == "__main__":
    root = tk.Tk(); root.withdraw()
    mps_root = filedialog.askdirectory(title="Select MPS Root Folder")
    vrs_path = filedialog.askopenfilename(title="Select VRS File", filetypes=[("VRS Files", "*.vrs")])
    
    if mps_root and vrs_path:
        slam_df, _ = load_slam_exact(mps_root)
        gaze_df, _ = calculate_gaze_world(mps_root)
        if gaze_df is not None:
            hotspot_ts = identify_hotspots(gaze_df)
            # Create a unique folder for each run using a timestamp
            run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = os.path.join(os.path.dirname(vrs_path), f"hotspot_frames_{run_id}")
            extract_frames(vrs_path, hotspot_ts, output_dir)