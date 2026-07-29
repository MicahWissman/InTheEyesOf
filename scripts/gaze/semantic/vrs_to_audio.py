"""
Extract raw microphone audio from a Project Aria .vrs file.
Uses the same convert_vrs_to_mp4 utility as vrs_to_transcript.py,
but extracts the audio stream directly as a WAV file instead of
passing it through Whisper.

Usage:
    python scripts/gaze/semantic/vrs_to_audio.py \
        --vrs /path/to/recording.vrs \
        --output /path/to/recording.wav
"""

import argparse
import os
import subprocess
import tempfile

try:
    from projectaria_tools.tools.vrs_to_mp4.vrs_to_mp4_utils import convert_vrs_to_mp4
except ImportError:
    print("ERROR: 'projectaria_tools' not found. Activate the aria_tools environment.")
    exit(1)


def extract_audio(vrs_path: str, output_wav: str) -> str:
    print(f"Opening {os.path.basename(vrs_path)}...")
    temp_dir = tempfile.mkdtemp()
    dummy_mp4 = os.path.join(temp_dir, "dummy.mp4")

    try:
        convert_vrs_to_mp4(
            vrs_file=vrs_path,
            output_video=dummy_mp4,
            log_folder=temp_dir,
            down_sample_factor=100,
        )

        wav_temp = os.path.join(temp_dir, "audio_extracted.wav")
        result = subprocess.run(
            [
                "ffmpeg",
                "-i", dummy_mp4,
                "-vn",
                "-acodec", "pcm_s16le",
                "-y",
                wav_temp,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"ERROR: ffmpeg failed\n{result.stderr}")
            return None

        os.makedirs(os.path.dirname(os.path.abspath(output_wav)), exist_ok=True)
        subprocess.run(["mv", wav_temp, output_wav], check=True)
        print(f"Audio saved to {output_wav}")
        return output_wav

    finally:
        import shutil
        shutil.rmtree(temp_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract microphone audio from a VRS file")
    parser.add_argument("--vrs", required=True, help="Path to the .vrs file")
    parser.add_argument("--output", required=True, help="Path for the output WAV file")
    args = parser.parse_args()

    if not os.path.exists(args.vrs):
        print(f"ERROR: VRS file not found: {args.vrs}")
        exit(1)

    wav_path = extract_audio(args.vrs, args.output)
    if wav_path:
        import wave
        with wave.open(wav_path, "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            print(f"  {frames} frames, {rate} Hz, {frames/rate:.1f}s duration")
    else:
        exit(1)
