import os
import argparse
import tempfile
import shutil

# Attempt to import projectaria_tools
try:
    from projectaria_tools.tools.vrs_to_mp4.vrs_to_mp4_utils import convert_vrs_to_mp4
except ImportError:
    print("❌ Error: 'projectaria_tools' not found. Please ensure you're in the 'aria_tools' environment.")
    exit(1)

# Attempt to import Whisper
try:
    import whisper
except ImportError:
    print("❌ Error: 'openai-whisper' not found. Please run: pip install openai-whisper")
    exit(1)

from transcript_format import write_transcript  # shared canonical multi-line format

def extract_vrs_audio(vrs_path, temp_dir):
    """
    Extracts audio.wav from VRS file using projectaria_tools.
    """
    print(f"⚙️ Extracting audio from {os.path.basename(vrs_path)}...")

    dummy_video = os.path.join(temp_dir, "dummy.mp4")

    try:
        convert_vrs_to_mp4(
            vrs_file=vrs_path,
            output_video=dummy_video,
            log_folder=temp_dir,
            down_sample_factor=100
        )

        for filename in ["audio.wav", "audio.mp3"]:
            p = os.path.join(temp_dir, filename)
            if os.path.exists(p):
                print(f"✅ Found audio file: {filename}")
                return p

        for root, dirs, files in os.walk(temp_dir):
            for f in files:
                if f.endswith((".wav", ".mp3", ".m4a")):
                    print(f"✅ Found audio file: {f}")
                    return os.path.join(root, f)

        if os.path.exists(dummy_video):
            print("✅ Using dummy video as audio source.")
            return dummy_video

        return None
    except Exception as e:
        print(f"❌ Extraction failed: {e}")
        return None

def transcribe_and_chunk(audio_path, output_path, interval=10.0):
    """
    Transcribes audio using Whisper and groups text into fixed-interval chunks.
    """
    print(f"🧠 Loading Whisper model ('base')...")
    model = whisper.load_model("base")

    print(f"🎙️ Transcribing {os.path.basename(audio_path)} (This may take a while)...")
    result = model.transcribe(audio_path, verbose=False, fp16=False)

    segments = result.get('segments', [])
    if not segments:
        print("⚠️ No speech detected in audio.")
        return

    print(f"📝 Formatting transcript into {interval}s chunks...")

    # Use the shared canonical multi-line format so load_transcript() can read it
    # (the old single-line output was silently dropped by the pipeline parser).
    items = [(s['start'], s.get('end', s['start']), s['text'].strip(), None, None)
             for s in segments]
    n = write_transcript(items, output_path, interval=interval, tag_lang=False)

    print(f"✅ Transcript saved to: {output_path} ({n} chunks)")

def main():
    parser = argparse.ArgumentParser(description="Extract and transcribe audio from a Project Aria VRS file")
    parser.add_argument("--vrs", required=True, help="Path to the .vrs file")
    parser.add_argument("--output", required=True, help="Path to save the transcript .txt file")
    parser.add_argument("--interval", type=float, default=10.0,
                        help="Chunk interval in seconds (default: 10.0)")
    args = parser.parse_args()

    if not os.path.exists(args.vrs):
        print(f"❌ VRS file not found: {args.vrs}")
        exit(1)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

    temp_dir = tempfile.mkdtemp()
    try:
        audio_wav = extract_vrs_audio(args.vrs, temp_dir)
        if audio_wav:
            transcribe_and_chunk(audio_wav, args.output, interval=args.interval)
        else:
            print("❌ Could not extract audio from VRS.")
            exit(1)
    finally:
        shutil.rmtree(temp_dir)
        print("🧹 Cleaned up temporary files.")

if __name__ == "__main__":
    main()
