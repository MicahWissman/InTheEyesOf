"""
Generates a heatmap of the most viewed areas of the point cloud from Aria Glasses VRS/MPS files.

tkinter needs to be installed for folder selection dialog.

requirements: 
pip install pandas numpy matplotlib scipy projectaria-tools
"""

import os
import gzip
import tkinter as tk
from tkinter import filedialog
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.spatial.transform import Rotation as R
from projectaria_tools.core import data_provider
from projectaria_tools.core.sensor_data import TimeDomain, TimeQueryOptions

# ==========================================
# 1. DATA LOADING (Adapted from xyzTest.py)
# ==========================================

def load_slam_exact(mps_root, slam_filter_threshold=0.005):
    """
    Loads and filters the SLAM point cloud from the MPS root folder.
    """
    print("☁️ Loading SLAM...")
    candidates = [
        os.path.join(mps_root, "semidense_points.csv"),
        os.path.join(mps_root, "slam", "semidense_points.csv"),
        os.path.join(mps_root, "semidense_points.csv.gz"),
        os.path.join(mps_root, "slam", "semidense_points.csv.gz")
    ]
    path = next((p for p in candidates if os.path.exists(p)), None)
    if not path:
        return None, "SLAM file (semidense_points.csv[.gz]) not found in MPS folder."

    try:
        if path.endswith('.gz'):
            with gzip.open(path, 'rt') as f:
                df = pd.read_csv(f, comment='#')
        else:
            df = pd.read_csv(path, comment='#')

        if not {'px_world', 'py_world', 'pz_world', 'dist_std'}.issubset(df.columns):
            return None, "SLAM file is missing required columns."

        initial_count = len(df)
        df = df[df['dist_std'] <= slam_filter_threshold]
        print(f"   Filtered: {initial_count} -> {len(df)} points (High Confidence)")
        return df, "Success"
    except Exception as e:
        return None, f"Error loading SLAM data: {e}"

def calculate_gaze_world(mps_root):
    """
    Calculates situated gaze by aligning gaze data with the device's trajectory.
    """
    print("\n📐 Calculating Situated Gaze...")
    gaze_csv = os.path.join(mps_root, "eye_gaze", "general_eye_gaze.csv")
    traj_candidates = [
        os.path.join(mps_root, "closed_loop_trajectory.csv"),
        os.path.join(mps_root, "slam", "closed_loop_trajectory.csv")
    ]
    traj_csv = next((p for p in traj_candidates if os.path.exists(p)), None)

    if not os.path.exists(gaze_csv) or not traj_csv:
        return None, "Gaze or trajectory files not found in MPS folder."

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
# 2. HEATMAP GENERATION
# ==========================================
def generate_heatmap(gaze_df, slam_df, output_path="gaze_heatmap.png"):
    """
    Generates and saves a 2D heatmap of gaze points on the SLAM point cloud.
    """
    print("\n🎨 Generating Heatmap...")

    # Project SLAM and gaze points onto the X-Y plane
    slam_x = slam_df['px_world']
    slam_y = slam_df['py_world']
    gaze_x = gaze_df['gx']
    gaze_y = gaze_df['gy']

    # Create the plot
    fig, ax = plt.subplots(figsize=(12, 10))

    # Plot SLAM points as a background
    ax.scatter(slam_x, slam_y, c='gray', s=1, alpha=0.1, label='SLAM Points')

    # Create the 2D heatmap of gaze points
    # The `bins` parameter controls the number of cells in the heatmap.
    # The `cmap` parameter sets the color map.
    heatmap, xedges, yedges = np.histogram2d(gaze_x, gaze_y, bins=100)
    extent = [xedges[0], xedges[-1], yedges[0], yedges[-1]]

    # Plot the heatmap
    im = ax.imshow(heatmap.T, extent=extent, origin='lower', cmap='plasma', alpha=0.7)
    fig.colorbar(im, ax=ax, label='Gaze Density')

    ax.set_title("Gaze Heatmap on SLAM Point Cloud")
    ax.set_xlabel("X World Coordinate")
    ax.set_ylabel("Y World Coordinate")
    ax.legend()
    ax.set_aspect('equal', adjustable='box')

    # Save the figure
    plt.savefig(output_path)
    print(f"   ✅ Saved heatmap to '{output_path}'")
    plt.show()

# ==========================================
# 3. MAIN EXECUTION
# ==========================================
def main():
    """
    Main function to run the script.
    """
    root = tk.Tk()
    root.withdraw()  # Hide the main window

    print("Please select the MPS root folder...")
    mps_root = filedialog.askdirectory(title="Select MPS Root Folder")
    if not mps_root:
        print("No MPS folder selected. Exiting.")
        return

    # Load data
    slam_df, msg = load_slam_exact(mps_root)
    if slam_df is None:
        print(f"❌ {msg}")
        return

    gaze_df, msg = calculate_gaze_world(mps_root)
    if gaze_df is None:
        print(f"❌ {msg}")
        return

    # Generate heatmap
    output_filename = os.path.join(os.path.dirname(mps_root), "gaze_heatmap.png")
    generate_heatmap(gaze_df, slam_df, output_path=output_filename)

if __name__ == "__main__":
    main()
