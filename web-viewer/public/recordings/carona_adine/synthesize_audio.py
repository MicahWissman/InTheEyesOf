#!/usr/bin/env python3
"""Batch-synthesize audio for all carona_adine anchors via ElevenLabs API.

Reads elevenlabs_manifest.json, generates MP3 files into audio_route/.
Skips files that already exist (safe to re-run).

Voice mapping:
  George (JBFqnCBsd6RMkjVDRZzb) → en.m, it.m
  Carla  (litDcG1avVppv4R90BLu) → en.f, it.f
"""
import json, os, sys, time
from pathlib import Path
from dotenv import load_dotenv

# Load API key from project .env
for env_path in [
    Path(__file__).parent / '.env',
    Path(__file__).resolve().parents[4] / '.env',  # InTheEyesOf/.env
]:
    if env_path.exists():
        load_dotenv(env_path)
        break

API_KEY = os.environ.get('ELEVENLABS_API_KEY')
if not API_KEY:
    sys.exit("ELEVENLABS_API_KEY not found in environment")

from elevenlabs import ElevenLabs

client = ElevenLabs(api_key=API_KEY)

VOICES = {
    'en.m': 'JBFqnCBsd6RMkjVDRZzb',  # George
    'en.f': 'litDcG1avVppv4R90BLu',  # Carla
    'it.m': 'JBFqnCBsd6RMkjVDRZzb',  # George
    'it.f': 'litDcG1avVppv4R90BLu',  # Carla
}

MODEL = 'eleven_v3'

with open('elevenlabs_manifest.json') as f:
    manifest = json.load(f)

os.makedirs('audio_route', exist_ok=True)

total = len(manifest['anchors']) * 4
done = 0
skipped = 0
errors = []

for anchor in manifest['anchors']:
    nid = anchor['node_id']
    title = anchor['title'][:50]
    texts = anchor['text']

    for variant, voice_id in VOICES.items():
        lang = variant.split('.')[0]  # 'en' or 'it'
        text = texts.get(lang, '')
        if not text:
            skipped += 1
            continue

        out_path = anchor['files'][variant]
        if os.path.exists(out_path):
            done += 1
            skipped += 1
            print(f"  SKIP {out_path} (exists)")
            continue

        try:
            print(f"  [{done+1}/{total}] {out_path} ({len(text)} chars)...", end=' ', flush=True)
            audio = client.text_to_speech.convert(
                voice_id=voice_id,
                text=text,
                model_id=MODEL,
                output_format='mp3_44100_128',
            )
            with open(out_path, 'wb') as f:
                for chunk in audio:
                    f.write(chunk)
            size_kb = os.path.getsize(out_path) / 1024
            print(f"OK ({size_kb:.0f} KB)")
            done += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"ERROR: {e}")
            errors.append({'file': out_path, 'error': str(e)})
            done += 1

print(f"\nDone: {done} processed, {skipped} skipped, {len(errors)} errors")
if errors:
    print("Errors:")
    for e in errors:
        print(f"  {e['file']}: {e['error']}")
