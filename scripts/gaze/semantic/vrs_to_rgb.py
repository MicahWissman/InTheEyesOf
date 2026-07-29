"""
Extract RGB camera frames from a Project Aria .vrs file at full resolution.
Outputs either individual PNG frames or a video MP4.

Usage:
    # Individual frames (one PNG per RGB frame):
    python scripts/gaze/semantic/vrs_to_rgb.py \
        --vrs /path/to/recording.vrs \
        --output /path/to/frame_dir/ \
        --format frames

    # Full MP4 video:
    python scripts/gaze/semantic/vrs_to_rgb.py \
        --vrs /path/to/recording.vrs \
        --output /path/to/recording.mp4 \
        --format video
"""

import argparse
import os
import sys

try:
    import numpy as np
    from PIL import Image
except ImportError:
    print("ERROR: numpy/PIL not available.")
    sys.exit(1)

try:
    from projectaria_tools.tools.vrs_to_mp4.vrs_to_mp4_utils import (
        Vrs2Mp4Converter,
        convert_vrs_to_mp4,
    )
except ImportError:
    print("ERROR: 'projectaria_tools' not found. Activate the aria_tools environment.")
    sys.exit(1)


def extract_frames(vrs_path: str, output_dir: str, down_factor: int = 1) -> int:
    """Extract every RGB frame as a PNG in output_dir."""
    print(f"Opening {vrs_path}...")
    converter = Vrs2Mp4Converter(vrs_path, down_sampling_factor=down_factor)

    os.makedirs(output_dir, exist_ok=True)
    duration_s = converter.duration_ns() / 1e9
    fps = converter.video_fps
    total = int(duration_s * fps)

    count = 0
    for i in range(total):
        frame = converter.make_frame(i / fps)  # HxWx3 uint8
        ts_ns = converter.mp4_to_vrs_time_ns(i / fps)
        fname = f"frame_{i:06d}_{ts_ns}.png"
        Image.fromarray(frame).save(os.path.join(output_dir, fname))
        count += 1
        if (i + 1) % 500 == 0:
            print(f"  {i+1}/{total} frames ...")

    print(f"Saved {count} frames to {output_dir}")
    return count


def extract_video(vrs_path: str, output_mp4: str) -> str:
    """Extract RGB frames as an MP4 video (full resolution, no audio)."""
    print(f"Opening {vrs_path}...")

    # Use the existing convert_vrs_to_mp4 which handles encoding
    # We'll pass an empty audio path so it only encodes video
    temp_dir = os.path.dirname(output_mp4) or "."
    convert_vrs_to_mp4(
        vrs_file=vrs_path,
        output_video=output_mp4,
        log_folder=temp_dir,
        down_sample_factor=1,  # full resolution
    )

    duration_s = _mp4_duration(output_mp4)
    print(f"Video saved to {output_mp4} ({duration_s:.1f}s)")
    return output_mp4


def _mp4_duration(path: str) -> float:
    import subprocess
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True
    )
    return float(result.stdout.strip()) if result.stdout.strip() else 0.0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract RGB frames/video from a VRS file")
    parser.add_argument("--vrs", required=True, help="Path to the .vrs file")
    parser.add_argument("--output", required=True, help="Output directory (frames) or MP4 file path")
    parser.add_argument("--format", choices=["frames", "video"], default="frames")
    parser.add_argument("--down-factor", type=int, default=1,
                        help="Down-sampling factor (1=full resolution). Default: 1")
    args = parser.parse_args()

    if not os.path.exists(args.vrs):
        print(f"ERROR: VRS file not found: {args.vrs}")
        sys.exit(1)

    if args.format == "frames":
        extract_frames(args.vrs, args.output, down_factor=args.down_factor)
    else:
        extract_video(args.vrs, args.output)
