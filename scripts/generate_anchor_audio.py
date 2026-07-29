#!/usr/bin/env python3
"""
Offline TTS generation script — ElevenLabs API.

This script is a MANUAL DEV TOOL. It is NEVER invoked from the web app.
Default mode is dry-run (no API calls, no files written, no cost incurred).
You must explicitly pass --no-dry-run to generate audio.

Usage examples:
  # Preview what would be generated (safe, default):
  python3 scripts/generate_anchor_audio.py --recording riva1

  # Actually generate (reads ELEVENLABS_API_KEY from .env):
  python3 scripts/generate_anchor_audio.py --recording riva1 --no-dry-run

  # Regenerate all anchors even if MP3 already exists:
  python3 scripts/generate_anchor_audio.py --recording riva1 --no-dry-run --force

See documentation/audio_generation.md for full guide.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Cost estimate: ElevenLabs Creator tier, ~$0.30 per 1 000 characters
COST_PER_1K_CHARS = 0.30

# Default voice ID — a warm, measured narration voice
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel (ElevenLabs default)

def load_env(project_root: Path) -> dict:
    """Load .env file from project root if it exists. Does not override real env vars."""
    env_path = project_root / ".env"
    env = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def estimate_cost(chars: int) -> float:
    return (chars / 1000) * COST_PER_1K_CHARS


def build_tts_text(anchor: dict) -> str:
    """Compose the text to synthesise. Uses narrative_description as the primary source."""
    return anchor.get("narrative_description", "").strip()


def generate_audio_for_anchor(
    anchor: dict,
    output_path: Path,
    voice_id: str,
    api_key: str,
) -> bool:
    """
    Calls ElevenLabs text-to-speech API and writes MP3 to output_path.
    Returns True on success, False on error.
    """
    try:
        import urllib.request
        import urllib.error
    except ImportError:
        print("  ERROR: urllib not available", file=sys.stderr)
        return False

    text = build_tts_text(anchor)
    if not text:
        print(f"  SKIP anchor {anchor.get('id')}: no narrative text")
        return False

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    payload = json.dumps({
        "text": text,
        "model_id": "eleven_turbo_v2",
        "voice_settings": {
            "stability": 0.55,
            "similarity_boost": 0.80,
            "style": 0.1,
            "use_speaker_boost": True,
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(resp.read())
        return True
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  ERROR HTTP {e.code} from ElevenLabs: {body[:200]}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate MP3 audio for narrative anchors using ElevenLabs TTS. "
                    "ALWAYS runs in dry-run mode by default — pass --no-dry-run to write files.",
    )
    parser.add_argument("--recording", required=True, help="Recording ID (e.g. riva1)")
    parser.add_argument(
        "--anchors-json",
        help="Path to narrative_anchors.json. Defaults to web-viewer/public/recordings/<id>/narrative_anchors.json",
    )
    parser.add_argument(
        "--output-dir",
        help="Directory for generated MP3s. Defaults to web-viewer/public/recordings/<id>/audio/",
    )
    parser.add_argument("--voice-id", default=DEFAULT_VOICE_ID, help="ElevenLabs voice ID")
    parser.add_argument("--api-key", help="ElevenLabs API key (overrides .env ELEVENLABS_API_KEY)")
    parser.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        default=True,
        help="Actually call the API and write MP3 files (cost is incurred)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate audio even if MP3 already exists",
    )
    args = parser.parse_args()

    # Locate project root (two levels up from this script)
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent

    # Resolve paths
    anchors_path = Path(args.anchors_json) if args.anchors_json else (
        project_root / "web-viewer" / "public" / "recordings" / args.recording / "narrative_anchors.json"
    )
    output_dir = Path(args.output_dir) if args.output_dir else (
        project_root / "web-viewer" / "public" / "recordings" / args.recording / "audio"
    )

    if not anchors_path.exists():
        print(f"ERROR: anchors file not found: {anchors_path}", file=sys.stderr)
        sys.exit(1)

    anchors = json.loads(anchors_path.read_text())

    # Load API key (only needed for real runs)
    api_key: str | None = args.api_key
    if not api_key and not args.dry_run:
        env = load_env(project_root)
        api_key = env.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVENLABS_API_KEY")
        if not api_key:
            print(
                "ERROR: ELEVENLABS_API_KEY not set.\n"
                "  Add it to .env at the project root, or pass --api-key.",
                file=sys.stderr,
            )
            sys.exit(1)

    # ── Main loop ─────────────────────────────────────────────────────────────
    total_chars = 0
    would_generate: list[dict] = []
    generated_ok: list[int] = []
    skipped: list[int] = []

    for anchor in anchors:
        anchor_id = anchor.get("id", anchor.get("cluster_id", "?"))
        title = anchor.get("narrative_title", f"anchor_{anchor_id}")
        text = build_tts_text(anchor)
        char_count = len(text)

        mp3_filename = f"anchor_{str(anchor_id).zfill(3)}.mp3"
        mp3_path = output_dir / mp3_filename
        audio_url = f"audio/{mp3_filename}"

        # Skip if already generated and not forcing
        if anchor.get("audioUrl") and not args.force:
            print(f"  SKIP [{anchor_id}] {title} — already has audioUrl")
            skipped.append(anchor_id)
            continue

        if not text:
            print(f"  SKIP [{anchor_id}] {title} — no narrative text")
            skipped.append(anchor_id)
            continue

        total_chars += char_count
        cost = estimate_cost(char_count)

        if args.dry_run:
            print(
                f"  DRY-RUN [{anchor_id}] {title}\n"
                f"    {char_count} chars → {mp3_filename}  (est. ${cost:.4f})"
            )
            would_generate.append({"id": anchor_id, "title": title, "chars": char_count})
        else:
            print(f"  GENERATING [{anchor_id}] {title} ({char_count} chars)...")
            ok = generate_audio_for_anchor(anchor, mp3_path, args.voice_id, api_key)  # type: ignore[arg-type]
            if ok:
                anchor["audioUrl"] = audio_url
                if not anchor.get("audioCaption"):
                    anchor["audioCaption"] = text
                generated_ok.append(anchor_id)
                print(f"    ✓ saved {mp3_path}")
                # Be polite to the API
                time.sleep(0.5)
            else:
                print(f"    ✗ failed — anchor NOT updated in JSON")

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    if args.dry_run:
        print(
            f"DRY-RUN SUMMARY: would process {len(would_generate)} anchors  "
            f"({total_chars} chars  est. ${estimate_cost(total_chars):.4f})"
        )
        print("Re-run with --no-dry-run to actually generate audio.")
    else:
        print(f"DONE: generated {len(generated_ok)}  skipped {len(skipped)}")
        if generated_ok:
            # Write updated JSON back to disk
            anchors_path.write_text(json.dumps(anchors, indent=2, ensure_ascii=False) + "\n")
            print(f"Updated {anchors_path}")
        print(f"Total chars processed: {total_chars}  est. cost: ${estimate_cost(total_chars):.4f}")


if __name__ == "__main__":
    main()
