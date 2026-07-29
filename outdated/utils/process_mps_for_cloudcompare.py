"""
MPS to CloudCompare Converter & Cleaner
---------------------------------------
1. Copies and cleans semidense point clouds (Outlier removal via dist_std).
2. Converts trajectory to a simple X,Y,Z format for CloudCompare.
3. Requires passing the MPS root folder as an argument.
"""

import os
import pandas as pd
import gzip
import argparse

# ==========================================
# 1. CONFIGURATION
# ==========================================
SLAM_FILTER_THRESHOLD = 0.005 # The "MPS Cleaner" logic from xyzTest.py

def find_mps_files(root_path):
    """Recursively finds trajectory and point cloud files in the given root."""
    data = {
        "trajectory": None,
        "points": None
    }
    
    # Common filenames
    traj_names = ["closed_loop_trajectory.csv"]
    point_names = ["semidense_points.csv", "semidense_points.csv.gz"]
    
    for root, dirs, files in os.walk(root_path):
        for f in files:
            if f in traj_names and not data["trajectory"]:
                data["trajectory"] = os.path.join(root, f)
            if f in point_names and not data["points"]:
                data["points"] = os.path.join(root, f)
                
    return data

def process_mps(root_path):
    # Expand ~ to full path if provided
    root_path = os.path.expanduser(root_path)

    if not os.path.exists(root_path):
        print(f"❌ Error: Path not found: {root_path}")
        return

    print(f"🚀 Searching for MPS data in: {root_path}")
    mps_files = find_mps_files(root_path)

    # --- 1. Process Trajectory ---
    if mps_files["trajectory"]:
        print(f"📍 Processing trajectory: {mps_files['trajectory']}")
        try:
            df_traj = pd.read_csv(mps_files["trajectory"], comment='#')
            cc_traj = pd.DataFrame()
            
            # Map Aria world columns to simple X,Y,Z
            if 'tx_world_device' in df_traj.columns:
                cc_traj['x'] = df_traj['tx_world_device']
                cc_traj['y'] = df_traj['ty_world_device']
                cc_traj['z'] = df_traj['tz_world_device']
            elif 'tx_device_world' in df_traj.columns:
                cc_traj['x'] = df_traj['tx_device_world']
                cc_traj['y'] = df_traj['ty_device_world']
                cc_traj['z'] = df_traj['tz_device_world']
            
            if 'tracking_timestamp_us' in df_traj.columns:
                cc_traj['timestamp_us'] = df_traj['tracking_timestamp_us']

            output_traj = os.path.join(os.path.dirname(mps_files["trajectory"]), "cloudcompare_trajectory.csv")
            cc_traj.to_csv(output_traj, index=False)
            print(f"   ✅ Saved: {output_traj}")
        except Exception as e:
            print(f"   ❌ Error processing trajectory: {e}")
    else:
        print("   ⚠️ No closed_loop_trajectory.csv found.")

    # --- 2. Process Point Cloud (The Cleaner) ---
    if mps_files["points"]:
        print(f"☁️ Cleaning point cloud: {mps_files['points']}")
        try:
            p_path = mps_files["points"]
            if p_path.endswith('.gz'):
                with gzip.open(p_path, 'rt') as f:
                    df_points = pd.read_csv(f, comment='#')
            else:
                df_points = pd.read_csv(p_path, comment='#')

            initial_count = len(df_points)
            
            if 'dist_std' in df_points.columns:
                df_points = df_points[df_points['dist_std'] <= SLAM_FILTER_THRESHOLD]
                print(f"   Filtered: {initial_count} -> {len(df_points)} points (Confidence Threshold: {SLAM_FILTER_THRESHOLD})")
            
            cc_points = pd.DataFrame({
                'x': df_points['px_world'],
                'y': df_points['py_world'],
                'z': df_points['pz_world']
            })
            
            if 'dist_std' in df_points.columns:
                cc_points['confidence'] = 1.0 / (df_points['dist_std'] + 1e-6)

            output_points = os.path.join(os.path.dirname(p_path), "cloudcompare_cleaned_points.csv")
            cc_points.to_csv(output_points, index=False)
            print(f"   ✅ Saved: {output_points}")
        except Exception as e:
            print(f"   ❌ Error cleaning points: {e}")
    else:
        print("   ⚠️ No semidense_points found.")

    print("\n🎉 Done! The 'cloudcompare_*.csv' files are located in their respective MPS folders.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert Aria MPS data to CloudCompare format.")
    parser.add_argument("mps_path", help="Path to the MPS root folder or 'slam' folder.")
    
    args = parser.parse_args()
    process_mps(args.mps_path)

"""

notes about data points

  3. Professional Visualization Tips
  Once both files are loaded, you can make the data much more readable:


  A. Color the Trajectory by Time
   1. Select the cloudcompare_trajectory in the DB Tree (left panel).
   2. In the Properties panel (bottom left), find the Color section and change it from RGB to Scalar Field.
   3. Change the Color Ramp to something like Blue-Green-Yellow-Red. This will show you the "start" of your walk in blue and the "end" in red.
   4. Increase the Point Size (e.g., to 5 or 10) to make the path clearly visible through the walls.


  B. Visualizing SLAM Confidence
   1. Select the cloudcompare_cleaned_points in the DB Tree.
   2. Change the Color to Scalar Field.
   3. This will color your environment based on the SLAM quality. High-confidence areas (areas with more structural detail) will stand out.

  C. Navigation
   * Left Click: Rotate.
   * Right Click: Pan.
   * Scroll: Zoom.
   * Press 'G': To reset the view to the center of the selected object.

"""