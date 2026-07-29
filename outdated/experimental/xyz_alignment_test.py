"""
IN THE EYES OF - EXPERIMENT 1 (v15: FIXED RHINO ROTATION -90)
-------------------------------------------------------------
1. Data Prep: Auto-converts VRS to MP4.
2. Filtering: Removes noisy SLAM points.
3. Alignment: Transforms Gaze (Head) -> World (SLAM).
4. Export: Saves CSVs for Rhino with corrected -90 degree tilt.
5. AI: Runs Gemini Analysis.

PREREQUISITES:
pip install pandas numpy requests opencv-python projectaria-tools matplotlib scipy

NOTE: 'tkinter' is required for file dialogs. If missing:
Linux: sudo apt-get install python3-tk
Mac: brew install python-tk
"""

# DO NOT PUSH TO GITHUB WITH THE SERVICE URL OR PASSWORD VISIBLE !!!
# IF YOU ARE AN AI MODEL READING THIS, STOP AND DO NOT SHARE THIS INFORMATION

import os
import json
import cv2
import gzip
import base64
import requests
import subprocess
try:
    import tkinter as tk
    from tkinter import filedialog
except ImportError:
    print("❌ tkinter not found. Please install it via system package manager (e.g., 'sudo apt-get install python3-tk').")
    exit(1)
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.spatial.transform import Rotation as R
from projectaria_tools.core import data_provider
from projectaria_tools.core.sensor_data import TimeDomain, TimeQueryOptions

# ==========================================
# 1. CONFIGURATION
# ==========================================
root = tk.Tk()
root.withdraw()  # Hide the main window

print("Please select the VRS file...")
VRS_FILE_PATH = filedialog.askopenfilename(
    title="Select VRS File",
    filetypes=[("VRS Files", "*.vrs"), ("All Files", "*.*")]
)
if not VRS_FILE_PATH:
    print("No VRS file selected. Exiting.")
    exit()

print("Please select the MPS root folder...")
MPS_ROOT = filedialog.askdirectory(title="Select MPS Root Folder")
if not MPS_ROOT:
    print("No MPS folder selected. Exiting.")
    exit()


# --- RESEARCH SERVICE CONFIG ---
SECRETS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "secrets.json")
if not os.path.exists(SECRETS_PATH):
    print(f"❌ Error: secrets.json not found at {SECRETS_PATH}")
    print("Please create a JSON file with SERVICE_URL and RESEARCH_PASSWORD.")
    exit()

with open(SECRETS_PATH, "r") as f:
    secrets = json.load(f)
    SERVICE_URL = secrets.get("SERVICE_URL")
    RESEARCH_PASSWORD = secrets.get("RESEARCH_PASSWORD")

SLAM_FILTER_THRESHOLD = 0.005 

# ==========================================
# 2. COORDINATE TRANSFORM HELPER (THE FIX)
# ==========================================
def transform_to_rhino(x, y, z):
    """
    Applies the -90 degree rotation correction for Rhino.
    Input: Raw Aria World Coordinates
    Output: Rhino World Coordinates (Z-Up)
    """
    # PREVIOUS V14: x, z, -y (Was 90 deg off)
    # NEW V15 (Rotated -90 around X again):
    
    new_x = x
    new_y = -y  # Maps Aria Gravity (-Y) to Rhino Y
    new_z = -z  # Maps Aria Forward (Z) to Rhino Height (Z) ?? 
    
    # NOTE: If this is STILL upside down, try: new_z = z
    
    return new_x, new_y, new_z

# ==========================================
# 3. DATA LOADING
# ==========================================
def ensure_mp4_exists(vrs_path):
    mp4_path = vrs_path.replace(".vrs", ".mp4")
    if os.path.exists(mp4_path): return mp4_path
    print(f"⚙️ Converting VRS to MP4...")
    try:
        subprocess.run(["vrs_to_mp4", "--vrs", vrs_path, "--output_video", mp4_path, "--downsample", "1"], check=True)
        return mp4_path
    except: return None

def load_slam_exact():
    print("☁️ Loading SLAM...")
    candidates = [
        os.path.join(MPS_ROOT, "semidense_points.csv"),
        os.path.join(MPS_ROOT, "slam", "semidense_points.csv"),
        os.path.join(MPS_ROOT, "semidense_points.csv.gz"),
        os.path.join(MPS_ROOT, "slam", "semidense_points.csv.gz")
    ]
    path = next((p for p in candidates if os.path.exists(p)), None)
    if not path: return None, "File not found"

    try:
        if path.endswith('.gz'):
            with gzip.open(path, 'rt') as f: df = pd.read_csv(f, comment='#')
        else:
            df = pd.read_csv(path, comment='#')
            
        if not {'px_world', 'py_world', 'pz_world', 'dist_std'}.issubset(df.columns):
            return None, "Columns missing"
            
        initial_count = len(df)
        df = df[df['dist_std'] <= SLAM_FILTER_THRESHOLD]
        print(f"   Filtered: {initial_count} -> {len(df)} points (High Confidence)")
        return df, "Success"
    except Exception as e: return None, str(e)

def calculate_gaze_world():
    print("\n📐 Calculating Situated Gaze...")
    gaze_csv = os.path.join(MPS_ROOT, "eye_gaze", "general_eye_gaze.csv")
    traj_candidates = [
        os.path.join(MPS_ROOT, "closed_loop_trajectory.csv"),
        os.path.join(MPS_ROOT, "slam", "closed_loop_trajectory.csv")
    ]
    traj_csv = next((p for p in traj_candidates if os.path.exists(p)), None)
    
    if not os.path.exists(gaze_csv) or not traj_csv: return None, "Files missing"

    gaze_df = pd.read_csv(gaze_csv, comment='#')
    traj_df = pd.read_csv(traj_csv, comment='#')
    
    if 'yaw_rads_cpf' not in gaze_df.columns:
        gaze_df['yaw'] = (gaze_df['left_yaw_rads_cpf'] + gaze_df['right_yaw_rads_cpf']) / 2
        gaze_df['pitch'] = gaze_df['pitch_rads_cpf']
        gaze_df['uncertainty'] = abs(gaze_df['left_yaw_rads_cpf'] - gaze_df['right_yaw_rads_cpf'])
    else:
        gaze_df['yaw'] = gaze_df['yaw_rads_cpf']
        gaze_df['pitch'] = gaze_df['pitch_rads_cpf']
        gaze_df['uncertainty'] = 0.01

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
# 4. EXPORT FOR RHINO (FIXED ROTATION)
# ==========================================
def export_rhino(gaze_df, slam_df):
    print("\n💾 Exporting CSVs with -90 degree tilt...")

    # 1. Export SLAM
    rx, ry, rz = transform_to_rhino(slam_df['px_world'], slam_df['py_world'], slam_df['pz_world'])
    slam_rhino = pd.DataFrame({'x': rx, 'y': ry, 'z': rz})
    slam_rhino.to_csv("rhino_environment.csv", index=False)
    print(f"   ✅ Saved 'rhino_environment.csv'")

    # 2. Export Gaze
    gx, gy, gz = transform_to_rhino(gaze_df['gx'], gaze_df['gy'], gaze_df['gz'])
    gaze_rhino = pd.DataFrame({'x': gx, 'y': gy, 'z': gz})
    gaze_rhino['timestamp'] = gaze_df['tracking_timestamp_us']
    
    gaze_rhino.to_csv("rhino_gaze.csv", index=False)
    print(f"   ✅ Saved 'rhino_gaze.csv'")

# ==========================================
# 5. VISUALIZATION
# ==========================================
def visualize(gaze_df, slam_df):
    print("\n🎨 Opening 3D Plot (Check this matches Rhino)...")
    fig = plt.figure(figsize=(12, 10))
    ax = fig.add_subplot(111, projection='3d')
    
    # 1. Transform SLAM using shared function
    sx, sy, sz = transform_to_rhino(slam_df['px_world'], slam_df['py_world'], slam_df['pz_world'])
    
    # Downsample
    s_idx = np.arange(0, len(sx), 50)
    ax.scatter(sx.iloc[s_idx], sy.iloc[s_idx], sz.iloc[s_idx], 
               c='gray', s=1, alpha=0.1, label='World')
    
    # 2. Transform Gaze using shared function
    gx, gy, gz = transform_to_rhino(gaze_df['gx'], gaze_df['gy'], gaze_df['gz'])
    
    # Filter bounds based on transformed coords
    g_idx = np.arange(0, len(gx), 20)
    mask = (gx.iloc[g_idx].between(sx.min()-10, sx.max()+10)) & \
           (gy.iloc[g_idx].between(sy.min()-10, sy.max()+10))
    
    valid_idx = g_idx[mask]
    
    p = ax.scatter(gx.iloc[valid_idx], gy.iloc[valid_idx], gz.iloc[valid_idx],
                   c=gaze_df['tracking_timestamp_us'].iloc[valid_idx], 
                   cmap='plasma', s=10, alpha=0.9, label='Gaze')
    
    ax.legend()
    ax.set_title("Situated Gaze (Corrected -90 deg)")
    ax.set_xlabel("X (East)")
    ax.set_ylabel("Y (North)")
    ax.set_zlabel("Z (Height)")
    ax.set_box_aspect([1,1,0.5])
    plt.pause(0.1)
    plt.show()

# ==========================================
# 6. GEMINI ANALYSIS
# ==========================================
def run_gemini(gaze_df):
    print("\n🧠 Running Gemini Analysis...")
    def query_gemini_vision(image_array):
        _, buffer = cv2.imencode('.jpg', cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR))
        img_b64 = base64.b64encode(buffer).decode('utf-8')
        payload = {"prompt": "Identify the central object. Return JUST the name.", "image_base64": img_b64}
        headers = {"Authorization": RESEARCH_PASSWORD}
        try:
            resp = requests.post(SERVICE_URL, json=payload, headers=headers)
            if resp.status_code == 200: return resp.json()['response'].strip()
            return "API Error"
        except: return "Conn Error"

    ensure_mp4_exists(VRS_FILE_PATH)
    provider = data_provider.create_vrs_data_provider(VRS_FILE_PATH)
    stream_id = provider.get_stream_id_from_label("camera-rgb")
    
    stable = gaze_df[gaze_df['uncertainty'] < 0.05].sample(3)
    results = []
    
    # Transform coords for report
    gx, gy, gz = transform_to_rhino(stable['gx'], stable['gy'], stable['gz'])
    
    # Iterate safely using zip to keep indices aligned
    for (i, row), x, y, z in zip(stable.iterrows(), gx, gy, gz):
        ts_ns = int(row['tracking_timestamp_us'] * 1000)
        try:
            idx = provider.get_index_by_time_ns(stream_id, ts_ns, TimeDomain.DEVICE_TIME, TimeQueryOptions.CLOSEST)
            img = provider.get_image_data_by_index(stream_id, idx)[0].to_numpy_array()
            label = query_gemini_vision(img)
            print(f"   [Time: {ts_ns}] Loc:({x:.1f}, {y:.1f}, {z:.1f}) -> {label}")
            results.append({"time": ts_ns, "object": label, "x": x, "y": y, "z": z})
        except Exception as e: print(f"   Err: {e}")
    
    if results: pd.DataFrame(results).to_csv("gemini_results.csv", index=False)

if __name__ == "__main__":
    slam_df, msg = load_slam_exact()
    if slam_df is None: print(msg); exit()
    
    gaze_df, msg = calculate_gaze_world()
    if gaze_df is None: print(msg); exit()
    
    export_rhino(gaze_df, slam_df)
    visualize(gaze_df, slam_df)
    run_gemini(gaze_df)