#!/usr/bin/env python3
"""
Offline TTS generation script — ElevenLabs API.

This script is a MANUAL DEV TOOL. It is NEVER invoked from the web app.
Default mode is dry-run (no API calls, no files written, no cost incurred).
You must explicitly pass --no-dry-run to generate audio.

Two tracks are generated per anchor, in the same voice:
  narrative   — narrative_description (the node's synthesis)  → audio/anchor_NNN.mp3            → audioUrl
  transcript  — transcript_slice, de-duplicated and cleaned   → audio/anchor_NNN.transcript.mp3 → audioTranscriptUrl

Anchors with source_recording/source_anchor_id (combined multi-SLAM experiences) point at the
source recording's MP3s (e.g. "../collin_gilbert/audio/anchor_000.mp3") when the text is
identical — no API call, no duplicate files, and each person keeps their own voice.

Usage examples:
  # Preview what would be generated (safe, default):
  python3 scripts/generate_anchor_audio.py --recording riva1

  # Actually generate (reads ELEVENLABS_API_KEY / ELEVENLABS_VOICE_ID from .env):
  python3 scripts/generate_anchor_audio.py --recording riva1 --no-dry-run

  # Per-recording voice, narrative track only:
  python3 scripts/generate_anchor_audio.py --recording collin_gilbert --voice-id jPQzmtcBdv1Qv2g39nqC --track narrative

  # Regenerate all anchors even if MP3 already exists:
  python3 scripts/generate_anchor_audio.py --recording riva1 --no-dry-run --force

See documentation/audio_generation.md for full guide.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# Cost estimate: ElevenLabs Creator tier, ~$0.30 per 1 000 characters
COST_PER_1K_CHARS = 0.30

# Default voice ID — a warm, measured narration voice
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel (ElevenLabs default)
DEFAULT_MODEL_ID = "eleven_multilingual_v2"

# Per-request character cap (eleven_multilingual_v2 allows 10 000)
MAX_CHARS = 10_000

# track name → (anchor field, MP3 filename suffix)
TRACKS = {
    "narrative": ("audioUrl", ""),
    "transcript": ("audioTranscriptUrl", ".transcript"),
}


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


def _norm(word: str) -> str:
    return re.sub(r"[^\w']", "", word.lower())


def clean_transcript(raw: str) -> str:
    """
    transcript_slice is a series of overlapping windows joined by "[...]". Merge them into one
    continuous passage: each window's words are aligned against the text so far and only the
    new tail is appended. Also drops "(silence)" markers and speaker labels, and trims a
    dangling half-sentence at the end.
    """
    raw = re.sub(r"\(silence\)", " ", raw)
    raw = re.sub(r"\b(Guide|Expert|Speaker \d+):\s*", " ", raw)
    acc: list[str] = []
    for seg in raw.split("[...]"):
        words = seg.split()
        if not words:
            continue
        if not acc:
            acc = words
            continue
        acc_n = [_norm(w) for w in acc]
        seg_n = [_norm(w) for w in words]
        min_match = min(6, len(seg_n))
        overlap = None  # words of seg already present at the end of acc; -1 = seg fully contained
        for p in range(len(acc_n)):
            i = 0
            while p + i < len(acc_n) and i < len(seg_n) and acc_n[p + i] == seg_n[i]:
                i += 1
            if i >= min_match and i == len(seg_n):
                overlap = -1
                break
            if i >= min_match and p + i == len(acc_n):
                overlap = i
                break
        if overlap == -1:
            continue
        acc += words[overlap:] if overlap is not None else words
    text = " ".join(acc)
    m = re.search(r"^(.*[.?!])[^.?!]*$", text, re.S)
    if m and len(m.group(1)) > 0.6 * len(text):
        text = m.group(1)
    return text.strip()


def build_tts_text(anchor: dict, track: str) -> str:
    """Compose the text to synthesise for a track."""
    if track == "transcript":
        return clean_transcript(anchor.get("transcript_slice") or "")
    return (anchor.get("narrative_description") or "").strip()


def synthesize(text: str, output_path: Path, voice_id: str, model_id: str, api_key: str) -> bool:
    """
    Calls ElevenLabs text-to-speech API and writes MP3 to output_path.
    Returns True on success, False on error.
    """
    import urllib.request
    import urllib.error

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128"
    payload = json.dumps({
        "text": text,
        "model_id": model_id,
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
        with urllib.request.urlopen(req, timeout=120) as resp:
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


def find_source_audio(anchor: dict, track: str, recordings_dir: Path, cache: dict) -> Path | None:
    """
    For a combined-experience anchor, return the source recording's MP3 for this track if the
    source anchor has identical text and the file exists.
    """
    src_rec = anchor.get("source_recording")
    src_id = anchor.get("source_anchor_id")
    if not src_rec or src_id is None:
        return None
    if src_rec not in cache:
        path = recordings_dir / src_rec / "narrative_anchors.json"
        cache[src_rec] = json.loads(path.read_text()) if path.exists() else []
    field, _ = TRACKS[track]
    for src in cache[src_rec]:
        if src.get("id") != src_id:
            continue
        if build_tts_text(src, track) != build_tts_text(anchor, track) or not src.get(field):
            return None
        mp3 = recordings_dir / src_rec / src[field]
        return mp3 if mp3.exists() else None
    return None


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
    parser.add_argument(
        "--track",
        choices=["narrative", "transcript", "both"],
        default="both",
        help="Which text to synthesise (default: both, same voice)",
    )
    parser.add_argument("--voice-id", help="ElevenLabs voice ID (overrides .env ELEVENLABS_VOICE_ID; default Rachel)")
    parser.add_argument(
        "--speaker",
        help="Only process anchors whose source_speaker matches (combined experiences, one voice per speaker)",
    )
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID, help=f"ElevenLabs model (default {DEFAULT_MODEL_ID})")
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
    parser.add_argument(
        "--print-text",
        action="store_true",
        help="In dry-run, print the full text that would be spoken",
    )
    args = parser.parse_args()

    # Locate project root (two levels up from this script)
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    recordings_dir = project_root / "web-viewer" / "public" / "recordings"

    # Resolve paths
    anchors_path = Path(args.anchors_json) if args.anchors_json else (
        recordings_dir / args.recording / "narrative_anchors.json"
    )
    output_dir = Path(args.output_dir) if args.output_dir else (
        recordings_dir / args.recording / "audio"
    )

    if not anchors_path.exists():
        print(f"ERROR: anchors file not found: {anchors_path}", file=sys.stderr)
        sys.exit(1)

    anchors = json.loads(anchors_path.read_text())
    selected = [a for a in anchors if not args.speaker or a.get("source_speaker") == args.speaker]
    if args.speaker and not selected:
        print(f"ERROR: no anchors with source_speaker {args.speaker!r}", file=sys.stderr)
        sys.exit(1)
    tracks = list(TRACKS) if args.track == "both" else [args.track]

    env = load_env(project_root)
    voice_id = args.voice_id or env.get("ELEVENLABS_VOICE_ID") or os.environ.get("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE_ID

    # Load API key (only needed for real runs)
    api_key: str | None = args.api_key
    if not api_key and not args.dry_run:
        api_key = env.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVENLABS_API_KEY")
        if not api_key:
            print(
                "ERROR: ELEVENLABS_API_KEY not set.\n"
                "  Add it to .env at the project root, or pass --api-key.",
                file=sys.stderr,
            )
            sys.exit(1)

    print(f"Recording {args.recording}  voice {voice_id}  model {args.model_id}  tracks {', '.join(tracks)}")
    if args.dry_run:
        print("DRY-RUN — no API calls, no files written\n")

    # ── Main loop ─────────────────────────────────────────────────────────────
    total_chars = 0
    would_generate = 0
    generated_ok = 0
    reused = 0
    skipped = 0
    failed = 0
    changed = False
    source_cache: dict = {}

    for anchor in selected:
        anchor_id = anchor.get("id", anchor.get("cluster_id", "?"))
        title = anchor.get("narrative_title", f"anchor_{anchor_id}")

        for track in tracks:
            field, suffix = TRACKS[track]
            text = build_tts_text(anchor, track)
            mp3_filename = f"anchor_{str(anchor_id).zfill(3)}{suffix}.mp3"
            mp3_path = output_dir / mp3_filename
            audio_url = f"{output_dir.name}/{mp3_filename}"
            label = f"[{anchor_id}:{track}] {title}"

            # Skip if already generated and not forcing
            if anchor.get(field) and not args.force:
                print(f"  SKIP {label} — already has {field}")
                skipped += 1
                continue

            if not text:
                print(f"  SKIP {label} — no text")
                skipped += 1
                continue

            if len(text) > MAX_CHARS:
                print(f"  SKIP {label} — {len(text)} chars exceeds {MAX_CHARS} per request", file=sys.stderr)
                failed += 1
                continue

            # Combined experiences: point at the source recording's MP3 instead of paying again
            src_mp3 = find_source_audio(anchor, track, recordings_dir, source_cache)
            if src_mp3:
                src_url = Path(os.path.relpath(src_mp3, anchors_path.parent)).as_posix()
                print(f"  REUSE {label} → {src_url}")
                if not args.dry_run:
                    anchor[field] = src_url
                    changed = True
                reused += 1
                continue

            # MP3 left over from an interrupted run — link it rather than pay again
            if mp3_path.exists() and not args.force:
                print(f"  LINK {label} — {mp3_filename} already on disk")
                if not args.dry_run:
                    anchor[field] = audio_url
                    changed = True
                reused += 1
                continue

            total_chars += len(text)

            if args.dry_run:
                print(f"  DRY-RUN {label}\n    {len(text)} chars → {mp3_filename}  (est. ${estimate_cost(len(text)):.4f})")
                if args.print_text:
                    print(f"    \"{text}\"")
                would_generate += 1
                continue

            print(f"  GENERATING {label} ({len(text)} chars)...")
            if synthesize(text, mp3_path, voice_id, args.model_id, api_key):  # type: ignore[arg-type]
                anchor[field] = audio_url
                if track == "narrative" and not anchor.get("audioCaption"):
                    anchor["audioCaption"] = text
                changed = True
                generated_ok += 1
                print(f"    ✓ saved {mp3_path}")
                # Write after every file so an interruption never loses paid-for audio
                anchors_path.write_text(json.dumps(anchors, indent=2, ensure_ascii=False) + "\n")
                # Be polite to the API
                time.sleep(0.5)
            else:
                failed += 1
                print(f"    ✗ failed — anchor NOT updated in JSON")

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    if args.dry_run:
        print(
            f"DRY-RUN SUMMARY: would generate {would_generate} files  "
            f"({total_chars} chars  est. ${estimate_cost(total_chars):.4f}), reuse {reused}, skip {skipped}"
        )
        print("Re-run with --no-dry-run to actually generate audio.")
    else:
        print(f"DONE: generated {generated_ok}  reused {reused}  skipped {skipped}  failed {failed}")
        if changed:
            anchors_path.write_text(json.dumps(anchors, indent=2, ensure_ascii=False) + "\n")
            print(f"Updated {anchors_path}")
        print(f"Total chars processed: {total_chars}  est. cost: ${estimate_cost(total_chars):.4f}")


if __name__ == "__main__":
    main()
