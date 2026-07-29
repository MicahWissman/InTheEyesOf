"""
Aligns gaze significance from Project Aria MPS data onto the SLAM point cloud.
Outputs a color-coded .PLY file for 3D visualization.

Usage:
python align_gaze_to_pc.py --mps_root <path_to_mps_folder> --output <output_path.ply>
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
import matplotlib.cm as cm

def load_slam_points(mps_root, slam_filter_threshold=0.005):
    """Loads and filters SLAM points from MPS folder."""
    print("☁️ Loading SLAM points...")
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

    # Filter by confidence
    df = df[df['dist_std'] <= slam_filter_threshold]
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
    return merged

def calculate_gaze_rays(merged_df):
    """Calculates gaze origins and unit vectors in world space."""
    # Handle column names (Project Aria MPS versions vary)
    if 'qx_device_world' in merged_df.columns:
        quats = merged_df[['qx_device_world', 'qy_device_world', 'qz_device_world', 'qw_device_world']].to_numpy()
        pos = merged_df[['tx_device_world', 'ty_device_world', 'tz_device_world']].to_numpy()
    else:
        quats = merged_df[['qx_world_device', 'qy_world_device', 'qz_world_device', 'qw_world_device']].to_numpy()
        pos = merged_df[['tx_world_device', 'ty_world_device', 'tz_world_device']].to_numpy()

    # Calculate average yaw/pitch
    if 'yaw_rads_cpf' in merged_df.columns:
        yaw = merged_df['yaw_rads_cpf'].to_numpy()
        pitch = merged_df['pitch_rads_cpf'].to_numpy()
    else:
        yaw = (merged_df['left_yaw_rads_cpf'] + merged_df['right_yaw_rads_cpf']).to_numpy() / 2
        pitch = merged_df['pitch_rads_cpf'].to_numpy()

    # Create local gaze vectors (assuming CPF forward is +Z)
    lx = np.tan(yaw)
    ly = np.tan(pitch)
    lz = np.ones_like(lx)
    local_vecs = np.vstack((lx, ly, lz)).T
    # Normalize
    local_vecs /= np.linalg.norm(local_vecs, axis=1)[:, np.newaxis]

    # Rotate to world space
    r = R.from_quat(quats)
    world_vecs = r.apply(local_vecs)

    return pos, world_vecs

def apply_heat(slam_points, gaze_origins, gaze_dirs, radius=0.15, max_dist=5.0):
    """Applies heat to SLAM points based on gaze rays with depth filtering."""
    print("🔥 Accumulating gaze heat...")
    tree = cKDTree(slam_points)
    heat = np.zeros(len(slam_points))

    for origin, direction in tqdm(zip(gaze_origins, gaze_dirs), total=len(gaze_origins)):
        # 1. Broad phase: Find points near the ray (within max_dist and a search radius)
        # We query points near a set of samples along the ray
        samples = origin + direction * np.linspace(0.2, max_dist, 20)[:, np.newaxis]
        indices = tree.query_ball_point(samples, r=radius * 2)
        flat_indices = list(set([item for sublist in indices for item in sublist]))
        
        if not flat_indices:
            continue

        nearby_points = slam_points[flat_indices]
        
        # 2. Narrow phase: Ray-point distance calculation
        # Vector from origin to points
        vec_op = nearby_points - origin
        # Projection of vec_op onto ray
        proj_dist = np.dot(vec_op, direction)
        
        # Filter points behind origin or too far
        mask = (proj_dist > 0.1) & (proj_dist < max_dist)
        if not np.any(mask):
            continue
            
        proj_vec = proj_dist[mask, np.newaxis] * direction
        # Perpendicular distance to ray
        perp_dist = np.linalg.norm(vec_op[mask] - proj_vec, axis=1)
        
        # 3. Apply Heat with Depth Filtering
        # Only points within the specific radius of the ray get heat
        within_radius = perp_dist < radius
        if not np.any(within_radius):
            continue
            
        # Depth filter: Find the closest hit
        valid_indices = np.array(flat_indices)[mask][within_radius]
        valid_proj_dist = proj_dist[mask][within_radius]
        
        # Find the distance of the closest point to the user
        min_d = np.min(valid_proj_dist)
        
        # Only apply heat to points within 0.3m of the closest hit (prevents bleeding)
        depth_mask = valid_proj_dist < (min_d + 0.3)
        final_indices = valid_indices[depth_mask]
        
        # Weighted heat (Gaussian falloff)
        final_perp_dist = perp_dist[within_radius][depth_mask]
        weight = np.exp(-0.5 * (final_perp_dist / (radius/2))**2)
        
        heat[final_indices] += weight

    return heat

def export_ply(points, heat, output_path, voxel_size=0.03):
    """Voxelizes and exports the heat-mapped point cloud."""
    print(f"📦 Processing for export (Voxel size: {voxel_size}m)...")
    
    # Create Open3D PointCloud
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(points)
    
    # Normalize heat and map to colors
    if np.max(heat) > 0:
        norm_heat = heat / np.max(heat)
    else:
        norm_heat = heat
        
    colormap = plt.get_cmap('plasma')
    colors = colormap(norm_heat)[:, :3] # Get RGB
    pcd.colors = o3d.utility.Vector3dVector(colors)
    
    # Voxel Downsampling (Tip #3)
    pcd_down = pcd.voxel_down_sample(voxel_size=voxel_size)
    print(f"   Downsampled: {len(points)} -> {len(pcd_down.points)} points")
    
    # Save
    o3d.io.write_point_cloud(output_path, pcd_down)
    print(f"✅ Saved to {output_path}")

def main():
    parser = argparse.ArgumentParser(description="Aria Gaze-to-PC Alignment")
    parser.add_argument("--mps_root", required=True, help="Path to the MPS folder")
    parser.add_argument("--output", required=True, help="Path to save the .ply file")
    parser.add_argument("--subsample", type=int, default=10, help="Gaze subsampling rate")
    parser.add_argument("--radius", type=float, default=0.15, help="Gaze ray influence radius (m)")
    parser.add_argument("--voxel", type=float, default=0.03, help="Output voxel size (m)")
    
    args = parser.parse_args()
    
    # If output is a directory, append a default filename
    output_path = args.output
    if os.path.isdir(output_path):
        output_path = os.path.join(output_path, "gaze_aligned_pc.ply")
    
    try:
        slam_points = load_slam_points(args.mps_root)
        merged_df = load_gaze_and_trajectory(args.mps_root, subsample_rate=args.subsample)
        origins, dirs = calculate_gaze_rays(merged_df)
        
        heat = apply_heat(slam_points, origins, dirs, radius=args.radius)
        
        export_ply(slam_points, heat, output_path, voxel_size=args.voxel)
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
