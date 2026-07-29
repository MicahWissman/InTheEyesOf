"""
HOTSPOT GOLD STANDARD: Voxel-First Raycasting & Top-K Extraction
--------------------------------------------------------------
Implements the hybrid "Golden Standard" approach:
1. Voxelizes the 3D environment for efficient ray-grid accumulation.
2. Filters gaze by fixation duration (Step 2b).
3. Aggregates true Dwell Time (Step 3).
4. Extracts Top-K ROIs (Step 4) for Semantic Analysis.
5. Back-projects heat to SLAM points for high-fidelity PLY visualization.

Usage:
python hotspot_gold_standard.py --mps_root <path> --output_ply <path.ply> --k 5
"""

import os
import gzip
import json
import argparse
import numpy as np
import pandas as pd
import open3d as o3d
from scipy.spatial.transform import Rotation as R
from tqdm import tqdm
import matplotlib.pyplot as plt

class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super(NpEncoder, self).default(obj)

# ==========================================
# 1. DATA LOADING (Inherited from align_gaze_to_pc)
# ==========================================

def load_slam_points(mps_root, slam_filter_threshold=0.005):
    print("☁️ Loading SLAM points...")
    candidates = [
        os.path.join(mps_root, "semidense_points.csv"),
        os.path.join(mps_root, "slam", "semidense_points.csv"),
        os.path.join(mps_root, "semidense_points.csv.gz"),
        os.path.join(mps_root, "slam", "semidense_points.csv.gz")
    ]
    path = next((p for p in candidates if os.path.exists(p)), None)
    if not path: raise FileNotFoundError("SLAM file not found.")

    if path.endswith('.gz'):
        with gzip.open(path, 'rt') as f: df = pd.read_csv(f, comment='#')
    else:
        df = pd.read_csv(path, comment='#')
    
    df = df[df['dist_std'] <= slam_filter_threshold]
    return df[['px_world', 'py_world', 'pz_world']].to_numpy()

def load_gaze_data(mps_root):
    print("📐 Loading Gaze and Trajectory...")
    gaze_csv = os.path.join(mps_root, "eye_gaze", "general_eye_gaze.csv")
    traj_candidates = [
        os.path.join(mps_root, "closed_loop_trajectory.csv"),
        os.path.join(mps_root, "slam", "closed_loop_trajectory.csv")
    ]
    traj_csv = next((p for p in traj_candidates if os.path.exists(p)), None)
    
    gaze_df = pd.read_csv(gaze_csv, comment='#')
    traj_df = pd.read_csv(traj_csv, comment='#')
    
    merged = pd.merge_asof(
        gaze_df.sort_values('tracking_timestamp_us'), 
        traj_df.sort_values('tracking_timestamp_us'), 
        on='tracking_timestamp_us', direction='nearest', tolerance=100000
    ).dropna()
    
    return merged

# ==========================================
# 2. GAZE FILTERING (Step 2b: Gaze longer than X)
# ==========================================

def filter_fixations(merged_df, min_duration_s=0.2, velocity_threshold=0.5):
    """
    Filters for stable gaze periods (fixations) using angular velocity.
    """
    print(f"👁️ Filtering fixations (min_duration: {min_duration_s}s)...")
    
    # Calculate yaw/pitch
    if 'yaw_rads_cpf' in merged_df.columns:
        yaw = merged_df['yaw_rads_cpf'].to_numpy()
        pitch = merged_df['pitch_rads_cpf'].to_numpy()
    else:
        yaw = (merged_df['left_yaw_rads_cpf'] + merged_df['right_yaw_rads_cpf']).to_numpy() / 2
        pitch = merged_df['pitch_rads_cpf'].to_numpy()
        
    ts = merged_df['tracking_timestamp_us'].to_numpy() / 1e6 # seconds
    
    # Simple angular velocity (rad/s)
    dy = np.diff(yaw) / np.diff(ts)
    dp = np.diff(pitch) / np.diff(ts)
    vel = np.sqrt(dy**2 + dp**2)
    vel = np.insert(vel, 0, 0) # align with length
    
    # Identify samples where velocity is low (fixation)
    is_fixation = vel < velocity_threshold
    
    # Group consecutive fixation samples
    fixations = []
    if len(is_fixation) == 0: return []
    
    start_idx = 0
    for i in range(1, len(is_fixation)):
        if is_fixation[i] != is_fixation[i-1]:
            if is_fixation[i-1]: # End of a fixation block
                duration = ts[i-1] - ts[start_idx]
                if duration >= min_duration_s:
                    fixations.append(merged_df.iloc[start_idx:i])
            start_idx = i
            
    print(f"   Found {len(fixations)} stable fixations.")
    return fixations

# ==========================================
# 3. VOXEL ACCUMULATION (Step 1-3)
# ==========================================

class VoxelAccumulator:
    def __init__(self, voxel_size=0.05):
        self.voxel_size = voxel_size
        self.grid = {} # (ix, iy, iz) -> dwell_time_seconds
        
    def world_to_grid(self, pos):
        return tuple(np.floor(pos / self.voxel_size).astype(int))
    
    def grid_to_world(self, idx):
        return (np.array(idx) + 0.5) * self.voxel_size

    def add_ray(self, origin, direction, duration, max_dist=5.0):
        # Sample points along the ray every half-voxel
        step = self.voxel_size / 2.0
        n_samples = int(max_dist / step)
        
        # We assume the ray hits 'something' at max_dist or where we have points
        # For simplicity in this grid-first approach, we increment all voxels along ray 
        # but we'll focus on the 'end' of the ray if we had a mesh. 
        # Since we have a point cloud, we'll use a slightly different approach:
        # We only count the 'endpoint' which we define as the first voxel that contains SLAM points.
        pass

def calculate_rays(df):
    if 'qx_device_world' in df.columns:
        quats = df[['qx_device_world', 'qy_device_world', 'qz_device_world', 'qw_device_world']].to_numpy()
        pos = df[['tx_device_world', 'ty_device_world', 'tz_device_world']].to_numpy()
    else:
        quats = df[['qx_world_device', 'qy_world_device', 'qz_world_device', 'qw_world_device']].to_numpy()
        pos = df[['tx_world_device', 'ty_world_device', 'tz_world_device']].to_numpy()

    if 'yaw_rads_cpf' in df.columns:
        yaw = df['yaw_rads_cpf'].to_numpy()
        pitch = df['pitch_rads_cpf'].to_numpy()
    else:
        yaw = (df['left_yaw_rads_cpf'] + df['right_yaw_rads_cpf']).to_numpy() / 2
        pitch = df['pitch_rads_cpf'].to_numpy()

    lx, ly = np.tan(yaw), np.tan(pitch)
    local_vecs = np.vstack((lx, ly, np.ones_like(lx))).T
    local_vecs /= np.linalg.norm(local_vecs, axis=1)[:, np.newaxis]
    
    world_vecs = R.from_quat(quats).apply(local_vecs)
    return pos, world_vecs

def accumulate_dwell_time(fixations, slam_points, voxel_size=0.05, max_dist=5.0):
    print("🧱 Building Voxel Grid and casting rays...")
    from scipy.spatial import cKDTree
    tree = cKDTree(slam_points)
    
    voxel_heat = {} # (ix, iy, iz) -> total_seconds
    voxel_times = {} # (ix, iy, iz) -> list of (start_ts, end_ts)
    
    for fix_df in tqdm(fixations):
        origins, dirs = calculate_rays(fix_df)
        ts = fix_df['tracking_timestamp_us'].to_numpy()
        # Duration per sample in seconds
        durs = np.diff(ts, append=ts[-1] + (ts[-1]-ts[-2] if len(ts)>1 else 100000)) / 1e6
        
        fix_start = ts[0]
        fix_end = ts[-1]
        
        # Track which voxels this specific fixation hit
        hit_voxels_in_fixation = set()
        
        for o, d, dur in zip(origins, dirs, durs):
            samples = o + d * np.linspace(0.2, max_dist, 50)[:, np.newaxis]
            dist, idx = tree.query(samples, k=1)
            
            hit_mask = dist < 0.2
            if np.any(hit_mask):
                hit_idx = np.where(hit_mask)[0][0]
                hit_pos = samples[hit_idx]
                
                v_idx = tuple(np.floor(hit_pos / voxel_size).astype(int))
                voxel_heat[v_idx] = voxel_heat.get(v_idx, 0) + dur
                hit_voxels_in_fixation.add(v_idx)
        
        # Associate this fixation's time range with all voxels it hit
        for v_idx in hit_voxels_in_fixation:
            if v_idx not in voxel_times: voxel_times[v_idx] = []
            voxel_times[v_idx].append((int(fix_start), int(fix_end)))

    return voxel_heat, voxel_times

# ==========================================
# 4. OUTPUT & EXPORT (Step 4)
# ==========================================

def extract_top_k(voxel_heat, voxel_times, k=5, voxel_size=0.05):
    sorted_voxels = sorted(voxel_heat.items(), key=lambda x: x[1], reverse=True)
    top_k = sorted_voxels[:k]
    
    results = []
    for i, (v_idx, dwell) in enumerate(top_k):
        centroid = (np.array(v_idx) + 0.5) * voxel_size
        results.append({
            "rank": i + 1,
            "centroid_world": centroid.tolist(),
            "dwell_time": float(dwell),
            "voxel_idx": v_idx,
            "intervals": voxel_times.get(v_idx, [])
        })
    return results

def export_results(slam_points, voxel_heat, top_k, output_ply, voxel_size=0.05):
    print(f"📦 Exporting PLY to {output_ply}...")
    
    # Ensure output directory exists
    output_dir = os.path.dirname(output_ply)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    
    # Map heat back to SLAM points
    point_heat = np.zeros(len(slam_points))
    for i, pt in enumerate(slam_points):
        v_idx = tuple(np.floor(pt / voxel_size).astype(int))
        point_heat[i] = voxel_heat.get(v_idx, 0)
        
    # Create Open3D PointCloud
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(slam_points)
    
    if np.max(point_heat) > 0:
        norm_heat = point_heat / np.max(point_heat)
        colormap = plt.get_cmap('plasma')
        colors = colormap(norm_heat)[:, :3]
        pcd.colors = o3d.utility.Vector3dVector(colors)
        
    o3d.io.write_point_cloud(output_ply, pcd)
    
    # Save ROIs to JSON
    roi_path = output_ply.replace(".ply", "_rois.json")
    with open(roi_path, "w") as f:
        json.dump(top_k, f, indent=4, cls=NpEncoder)
    print(f"✅ Top-K ROIs saved to {roi_path}")

# ==========================================
# MAIN
# ==========================================

def main():
    parser = argparse.ArgumentParser(description="Aria Hotspot Gold Standard")
    parser.add_argument("--mps_root", required=True)
    parser.add_argument("--output_ply", required=True)
    parser.add_argument("--k", type=int, default=5, help="Number of ROIs to extract")
    parser.add_argument("--voxel", type=float, default=0.05, help="Voxel size (m)")
    parser.add_argument("--min_dwell", type=float, default=0.2, help="Min fixation duration (s)")
    
    args = parser.parse_args()
    
    try:
        slam_points = load_slam_points(args.mps_root)
        gaze_df = load_gaze_data(args.mps_root)
        
        # Phase 1: Filter
        fixations = filter_fixations(gaze_df, min_duration_s=args.min_dwell)
        
        # Phase 2 & 3: Voxel Accumulation
        voxel_heat, voxel_times = accumulate_dwell_time(fixations, slam_points, voxel_size=args.voxel)
        
        # Phase 4: Extraction
        top_k = extract_top_k(voxel_heat, voxel_times, k=args.k, voxel_size=args.voxel)
        
        print("\n🏆 Top Predicted ROIs:")
        for roi in top_k:
            print(f"  #{roi['rank']}: Pos {roi['centroid_world']} | Dwell: {roi['dwell_time']:.2f}s")
            
        # Phase 5: Export
        export_results(slam_points, voxel_heat, top_k, args.output_ply, voxel_size=args.voxel)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
