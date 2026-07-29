"""
Integrated MPS to CloudCompare + Gaze Alignment Tool
----------------------------------------------------
1. Cleans SLAM point clouds based on confidence.
2. Aligns gaze significance (heat) onto the point cloud.
3. Processes device trajectory for 3D visualization.
4. Outputs a unified .PLY file for CloudCompare.

Usage:
python process_mps_for_gaze_cc.py --mps_root <path_to_mps_folder> --output <output_dir_or_file>
"""

import os
import gzip
import argparse
import numpy as np
import pandas as pd
import open3d as o3d
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation as R
from tqdm import tqdm
import matplotlib.pyplot as plt

# ==========================================
# 1. DATA LOADING & CLEANING
# ==========================================

def load_and_clean_slam_points(mps_root, threshold=0.005):
    """Loads and filters SLAM points from MPS folder."""
    print("☁️ Loading and cleaning SLAM points...")
    candidates = [
        os.path.join(mps_root, "semidense_points.csv"),
        os.path.join(mps_root, "slam", "semidense_points.csv"),
        os.path.join(mps_root, "semidense_points.csv.gz"),
        os.path.join(mps_root, "slam", "semidense_points.csv.gz")
    ]
    path = next((p for p in candidates if os.path.exists(p)), None)
    if not path:
        raise FileNotFoundError("SLAM file (semidense_points.csv[.gz]) not found.")

    if path.endswith('.gz'):
        with gzip.open(path, 'rt') as f:
            df = pd.read_csv(f, comment='#')
    else:
        df = pd.read_csv(path, comment='#')

    initial_count = len(df)
    # Filter by confidence (dist_std)
    if 'dist_std' in df.columns:
        df = df[df['dist_std'] <= threshold]
        print(f"   Filtered: {initial_count} -> {len(df)} points (Threshold: {threshold})")
    
    return df[['px_world', 'py_world', 'pz_world']].to_numpy()

def load_gaze_and_trajectory(mps_root, subsample_rate=10):
    """Loads gaze and trajectory, merges them, and subsamples."""
    print("📐 Loading Gaze and Trajectory...")
    gaze_csv = os.path.join(mps_root, "eye_gaze", "general_eye_gaze.csv")
    traj_candidates = [
        os.path.join(mps_root, "closed_loop_trajectory.csv"),
        os.path.join(mps_root, "slam", "closed_loop_trajectory.csv")
    ]
    traj_csv = next((p for p in traj_candidates if os.path.exists(p)), None)

    if not os.path.exists(gaze_csv) or not traj_csv:
        raise FileNotFoundError("Gaze or trajectory files not found.")

    gaze_df = pd.read_csv(gaze_csv, comment='#')
    traj_df = pd.read_csv(traj_csv, comment='#')

    # Sort for merge_asof
    gaze_df = gaze_df.sort_values('tracking_timestamp_us')
    traj_df = traj_df.sort_values('tracking_timestamp_us')

    # Merge gaze with trajectory to get pose for each gaze sample
    merged = pd.merge_asof(
        gaze_df, traj_df, 
        on='tracking_timestamp_us', 
        direction='nearest', 
        tolerance=100000
    ).dropna()

    # Subsample for performance
    merged = merged.iloc[::subsample_rate]
    print(f"   Processing {len(merged)} gaze samples (Subsampled by {subsample_rate}x)")
    return merged, traj_df

# ==========================================
# 2. GAZE CALCULATION
# ==========================================

def calculate_gaze_rays(merged_df):
    """Calculates gaze origins and unit vectors in world space."""
    if 'qx_device_world' in merged_df.columns:
        quats = merged_df[['qx_device_world', 'qy_device_world', 'qz_device_world', 'qw_device_world']].to_numpy()
        pos = merged_df[['tx_device_world', 'ty_device_world', 'tz_device_world']].to_numpy()
    else:
        quats = merged_df[['qx_world_device', 'qy_world_device', 'qz_world_device', 'qw_world_device']].to_numpy()
        pos = merged_df[['tx_world_device', 'ty_world_device', 'tz_world_device']].to_numpy()

    if 'yaw_rads_cpf' in merged_df.columns:
        yaw = merged_df['yaw_rads_cpf'].to_numpy()
        pitch = merged_df['pitch_rads_cpf'].to_numpy()
    else:
        yaw = (merged_df['left_yaw_rads_cpf'] + merged_df['right_yaw_rads_cpf']).to_numpy() / 2
        pitch = merged_df['pitch_rads_cpf'].to_numpy()

    lx, ly, lz = np.tan(yaw), np.tan(pitch), np.ones_like(yaw)
    local_vecs = np.vstack((lx, ly, lz)).T
    local_vecs /= np.linalg.norm(local_vecs, axis=1)[:, np.newaxis]

    r = R.from_quat(quats)
    world_vecs = r.apply(local_vecs)
    return pos, world_vecs

def apply_heat(slam_points, gaze_origins, gaze_dirs, radius=0.15, max_dist=5.0):
    """Applies heat to SLAM points based on gaze rays with depth filtering."""
    print("🔥 Accumulating gaze heat...")
    tree = cKDTree(slam_points)
    heat = np.zeros(len(slam_points))

    for origin, direction in tqdm(zip(gaze_origins, gaze_dirs), total=len(gaze_origins)):
        samples = origin + direction * np.linspace(0.2, max_dist, 20)[:, np.newaxis]
        indices = tree.query_ball_point(samples, r=radius * 2)
        flat_indices = list(set([item for sublist in indices for item in sublist]))
        
        if not flat_indices: continue

        nearby_points = slam_points[flat_indices]
        vec_op = nearby_points - origin
        proj_dist = np.dot(vec_op, direction)
        
        mask = (proj_dist > 0.1) & (proj_dist < max_dist)
        if not np.any(mask): continue
            
        proj_vec = proj_dist[mask, np.newaxis] * direction
        perp_dist = np.linalg.norm(vec_op[mask] - proj_vec, axis=1)
        
        within_radius = perp_dist < radius
        if not np.any(within_radius): continue
            
        valid_indices = np.array(flat_indices)[mask][within_radius]
        valid_proj_dist = proj_dist[mask][within_radius]
        
        min_d = np.min(valid_proj_dist)
        depth_mask = valid_proj_dist < (min_d + 0.3)
        final_indices = valid_indices[depth_mask]
        
        final_perp_dist = perp_dist[within_radius][depth_mask]
        weight = np.exp(-0.5 * (final_perp_dist / (radius/2))**2)
        heat[final_indices] += weight

    return heat

# ==========================================
# 3. EXPORT
# ==========================================

def export_results(points, heat, traj_df, output_path, voxel_size=0.03):
    """Exports both gaze-aligned point cloud and clean trajectory."""
    print(f"📦 Exporting results to {output_path}...")
    
    if os.path.isdir(output_path):
        pc_out = os.path.join(output_path, "gaze_aligned_cleaned.ply")
        traj_out = os.path.join(output_path, "trajectory_cleaned.csv")
    else:
        pc_out = output_path
        traj_out = output_path.replace(".ply", "_trajectory.csv")

    # 1. Point Cloud Export
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(points)
    
    if np.max(heat) > 0:
        norm_heat = heat / np.max(heat)
    else:
        norm_heat = heat
        
    colormap = plt.get_cmap('plasma')
    colors = colormap(norm_heat)[:, :3]
    pcd.colors = o3d.utility.Vector3dVector(colors)
    
    pcd_down = pcd.voxel_down_sample(voxel_size=voxel_size)
    o3d.io.write_point_cloud(pc_out, pcd_down)
    print(f"   ✅ Point Cloud Saved: {pc_out} ({len(pcd_down.points)} points)")

    # 2. Trajectory Export
    cc_traj = pd.DataFrame()
    if 'tx_world_device' in traj_df.columns:
        cc_traj['x'], cc_traj['y'], cc_traj['z'] = traj_df['tx_world_device'], traj_df['ty_world_device'], traj_df['tz_world_device']
    else:
        cc_traj['x'], cc_traj['y'], cc_traj['z'] = traj_df['tx_world_device'], traj_df['ty_world_device'], traj_df['tz_world_device']
    
    if 'tracking_timestamp_us' in traj_df.columns:
        cc_traj['timestamp_us'] = traj_df['tracking_timestamp_us']
    
    cc_traj.to_csv(traj_out, index=False)
    print(f"   ✅ Trajectory Saved: {traj_out}")

def main():
    parser = argparse.ArgumentParser(description="Integrated Aria MPS Gaze + CC Tool")
    parser.add_argument("--mps_root", required=True, help="Path to the MPS folder")
    parser.add_argument("--output", required=True, help="Output directory or .ply file path")
    parser.add_argument("--threshold", type=float, default=0.005, help="SLAM confidence threshold")
    parser.add_argument("--subsample", type=int, default=10, help="Gaze subsampling rate")
    parser.add_argument("--radius", type=float, default=0.15, help="Gaze ray influence radius (m)")
    parser.add_argument("--voxel", type=float, default=0.03, help="Output voxel size (m)")
    
    args = parser.parse_args()
    
    try:
        slam_points = load_and_clean_slam_points(args.mps_root, threshold=args.threshold)
        merged_df, traj_df = load_gaze_and_trajectory(args.mps_root, subsample_rate=args.subsample)
        origins, dirs = calculate_gaze_rays(merged_df)
        
        heat = apply_heat(slam_points, origins, dirs, radius=args.radius)
        
        export_results(slam_points, heat, traj_df, args.output, voxel_size=args.voxel)
        print("🎉 All set! Open these in CloudCompare and remember to click 'Yes' to the Global Shift.")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
