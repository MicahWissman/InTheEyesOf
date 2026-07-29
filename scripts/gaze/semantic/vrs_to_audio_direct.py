#!/usr/bin/env python3
"""
Extract the FULL microphone stream from an Aria .vrs directly into a
16 kHz mono WAV (what Whisper expects).

Why not vrs_to_audio.py? That path routes through convert_vrs_to_mp4 with
down_sample_factor, which decimates the video timeline and TRUNCATES the
audio (a 48-min recording came out as ~5 min). This reads the mic stream
records directly, so the full duration is preserved.

Usage:
  python vrs_to_audio_direct.py --vrs rec.vrs --output rec.wav [--channel 0]
"""

import argparse
import os
import sys
import numpy as np
from scipy.signal import decimate
from scipy.io import wavfile

from projectaria_tools.core import data_provider

TARGET_SR = 16000


def resolve_mix(mix, ch, provider, mic, n):
    """Return (channel_list, mode). mode in {'single','mean'}."""
    if mix == "mean":
        return list(range(ch)), "mean"
    if mix.startswith("mean:"):
        return [int(x) for x in mix[5:].split(",")], "mean"
    if mix == "best":
        ss = np.zeros(ch)
        cnt = 0
        for i in range(0, n, 60):
            m = np.asarray(provider.get_audio_data_by_index(mic, i)[0].data,
                           dtype=np.float64).reshape(-1, ch)
            ss += (m ** 2).sum(axis=0); cnt += m.shape[0]
        best = int(np.sqrt(ss / cnt).argmax())
        print(f"  best channel by energy: ch{best}")
        return [best], "single"
    return [int(mix)], "single"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vrs", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--mix", default="0",
                    help="channel index | 'best' | 'mean' | 'mean:0,4,2' (subset average)")
    ap.add_argument("--start-sec", type=float, default=0.0, help="slice start (for A/B testing)")
    ap.add_argument("--dur-sec", type=float, default=0.0, help="slice duration (0 = whole file)")
    args = ap.parse_args()

    provider = data_provider.create_vrs_data_provider(args.vrs)
    mic = provider.get_stream_id_from_label("mic")
    cfg = provider.get_audio_configuration(mic)
    sr, ch = int(cfg.sample_rate), int(cfg.num_channels)
    n = provider.get_num_data(mic)
    channels, mode = resolve_mix(args.mix, ch, provider, mic, n)
    print(f"mic: {sr} Hz, {ch} ch, {n} records — mix={args.mix} ({mode} of {channels})")

    start_smp = int(args.start_sec * sr)
    end_smp = int((args.start_sec + args.dur_sec) * sr) if args.dur_sec > 0 else None

    blocks = []
    elapsed = 0
    for i in range(n):
        ad = provider.get_audio_data_by_index(mic, i)[0]
        m = np.asarray(ad.data, dtype=np.float32).reshape(-1, ch)   # frames x channels
        nf = m.shape[0]
        if end_smp is not None and elapsed >= end_smp:
            break
        if elapsed + nf > start_smp:
            sel = m[:, channels]
            mono = sel.mean(axis=1) if mode == "mean" else sel[:, 0]
            lo = max(0, start_smp - elapsed)
            hi = nf if end_smp is None else min(nf, end_smp - elapsed)
            blocks.append(mono[lo:hi])
        elapsed += nf
        if i % 20000 == 0:
            sys.stderr.write(f"\r  read {i}/{n} records")
            sys.stderr.flush()
    sys.stderr.write("\n")

    sig = np.concatenate(blocks).astype(np.float32)
    print(f"raw samples: {len(sig)} ({len(sig)/sr:.1f}s)")

    # normalize to full-scale, then anti-aliased downsample 48k -> 16k (factor 3)
    peak = np.abs(sig).max()
    if peak > 0:
        sig /= peak
    if sr % TARGET_SR == 0:
        sig = decimate(sig, sr // TARGET_SR, ftype="fir")
    else:
        from scipy.signal import resample_poly
        sig = resample_poly(sig, TARGET_SR, sr)

    pcm = np.clip(sig, -1.0, 1.0)
    pcm = (pcm * 32767).astype(np.int16)
    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
    wavfile.write(args.output, TARGET_SR, pcm)
    print(f"saved {args.output} — {len(pcm)/TARGET_SR:.1f}s @ {TARGET_SR} Hz mono")


if __name__ == "__main__":
    main()
