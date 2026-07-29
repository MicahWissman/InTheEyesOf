"""
use align_gaze_to_pc.py --mps_root /path/to/your/mps_folder
     --output output_heatmap.ply --subsample 10 --radius 0.15 --voxel 0.03

     as an example run
"""

import argparse
import os
import shutil
import subprocess
import sys

# Try to import projectaria_tools, provide clear error if missing
try:
    from projectaria_tools.core import data_provider
    from projectaria_tools.core.stream_id import StreamId
    from projectaria_tools.core.sensor_data import TimeDomain
except ImportError:
    print("❌ Error: 'projectaria-tools' is not installed.")
    print("   Please install it using: pip install projectaria-tools")
    sys.exit(1)

def split_vrs_file(vrs_path, chunk_minutes, output_dir, vrs_bin="vrs"):
    """
    Splits a VRS file into time-based chunks using the 'vrs' CLI tool.
    """
    
    # Expand paths
    vrs_path = os.path.abspath(os.path.expanduser(vrs_path))
    output_dir = os.path.abspath(os.path.expanduser(output_dir))
    vrs_bin_expanded = os.path.expanduser(vrs_bin)

    # 1. Verify vrs binary
    vrs_exec = shutil.which(vrs_bin_expanded)
    if vrs_exec is None:
        # Check if it's a direct path that exists but isn't in PATH
        if os.path.isfile(vrs_bin_expanded) and os.access(vrs_bin_expanded, os.X_OK):
            vrs_exec = vrs_bin_expanded
        else:
            if os.path.isdir(vrs_bin_expanded):
                print(f"❌ Error: '{vrs_bin}' is a directory, not the executable binary.")

            print(f"❌ Error: The 'vrs' executable was not found at '{vrs_bin}'.")
            print("   This script requires the Meta VRS command-line tool.")
            print("   If you built it from source, provide the path to the 'vrs' binary using --vrs_bin")
            return

    if not os.path.exists(vrs_path):
        print(f"❌ Error: Input file not found: {vrs_path}")
        return

    print(f"📂 Opening {vrs_path}...")
    try:
        provider = data_provider.create_vrs_data_provider(vrs_path)
    except Exception as e:
        print(f"❌ Failed to open VRS file: {e}")
        return

    # 2. Determine time range using the Left SLAM Camera (1201-1) as reference
    stream_id = StreamId("1201-1")
    if not provider.check_stream_is_active(stream_id):
        print("⚠️ SLAM Camera (1201-1) not found. Trying RGB Camera (214-1)...")
        stream_id = StreamId("214-1") # RGB
        if not provider.check_stream_is_active(stream_id):
             print("❌ No suitable camera stream found to determine time range.")
             return

    # Get timestamps in Device Time (nanoseconds)
    start_ns = provider.get_first_time_ns(stream_id, TimeDomain.DEVICE_TIME)
    end_ns = provider.get_last_time_ns(stream_id, TimeDomain.DEVICE_TIME)
    
    if start_ns == -1 or end_ns == -1:
        print("❌ Error: Could not retrieve valid timestamps from the VRS stream.")
        return

    duration_ns = end_ns - start_ns
    duration_min = (duration_ns / 1e9) / 60
    print(f"⏱️  Duration: {duration_min:.2f} minutes (Start: {start_ns}, End: {end_ns})")

    # 3. Calculate Chunks
    chunk_ns = int(chunk_minutes * 60 * 1e9)
    os.makedirs(output_dir, exist_ok=True)
    
    base_name = os.path.splitext(os.path.basename(vrs_path))[0]
    
    current_start = start_ns
    part_num = 1
    
    # 4. Execute Splits
    while current_start < end_ns:
        current_end = min(current_start + chunk_ns, end_ns)
        
        output_filename = f"{base_name}_part{part_num:02d}.vrs"
        output_path = os.path.join(output_dir, output_filename)
        
        print(f"✂️  Creating Part {part_num}: {output_filename}")
        # Use seconds for vrs CLI
        min_ts = current_start / 1e9
        max_ts = current_end / 1e9
        print(f"    Range: {min_ts:.3f}s - {max_ts:.3f}s")

        # Construct vrs copy command
        cmd = [
            vrs_exec, "copy",
            vrs_path,
            "--to", output_path,
            "--after", str(min_ts),
            "--before", str(max_ts)
        ]
        
        try:
            # Run vrs copy
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            print(f"    ✅ Success")
        except subprocess.CalledProcessError as e:
            print(f"    ❌ Failed to create chunk. Return code: {e.returncode}")
            print(f"    VRS Tool Output:\n{e.stderr}")
            return

        current_start = current_end
        part_num += 1

    print(f"\n🎉 Done! Split into {part_num - 1} files in '{output_dir}/'")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Split Aria VRS files into chunks for Multi-SLAM.")
    parser.add_argument("--vrs_path", required=True, help="Path to the input .vrs file")
    parser.add_argument("--chunk_min", type=float, default=5.0, help="Chunk size in minutes (default: 5.0)")
    parser.add_argument("--output_dir", default="vrs_chunks", help="Output directory")
    parser.add_argument("--vrs_bin", default="vrs", help="Path to 'vrs' executable if not in PATH")
    
    args = parser.parse_args()
    split_vrs_file(args.vrs_path, args.chunk_min, args.output_dir, args.vrs_bin)
