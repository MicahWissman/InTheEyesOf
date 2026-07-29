#!/usr/bin/env python3
"""
A/B test microphone mixing strategies on a short slice, scored by Whisper's
own avg_logprob (higher = the model is more confident => cleaner audio).
Reads the slice once, builds each variant, transcribes with large-v3.

Usage:
  python mic_ab.py --vrs rec.vrs --start-sec 600 --dur-sec 180
"""
import argparse
import numpy as np
from scipy.signal import decimate
from projectaria_tools.core import data_provider
from faster_whisper import WhisperModel

TARGET_SR = 16000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vrs", required=True)
    ap.add_argument("--start-sec", type=float, default=600.0)
    ap.add_argument("--dur-sec", type=float, default=180.0)
    ap.add_argument("--all-channels", action="store_true",
                    help="test each channel individually (+ means) instead of the default mix set")
    args = ap.parse_args()

    p = data_provider.create_vrs_data_provider(args.vrs)
    mic = p.get_stream_id_from_label("mic")
    cfg = p.get_audio_configuration(mic)
    sr, ch = int(cfg.sample_rate), int(cfg.num_channels)
    n = p.get_num_data(mic)
    a, b = int(args.start_sec * sr), int((args.start_sec + args.dur_sec) * sr)

    # read the slice once, keep all channels
    blocks, elapsed = [], 0
    for i in range(n):
        m = np.asarray(p.get_audio_data_by_index(mic, i)[0].data, dtype=np.float32).reshape(-1, ch)
        nf = m.shape[0]
        if elapsed >= b:
            break
        if elapsed + nf > a:
            lo, hi = max(0, a - elapsed), min(nf, b - elapsed)
            blocks.append(m[lo:hi])
        elapsed += nf
    seg = np.concatenate(blocks)  # frames x ch
    print(f"slice {args.start_sec:.0f}-{args.start_sec+args.dur_sec:.0f}s, {seg.shape[0]} frames x {ch} ch\n")

    if args.all_channels:
        variants = {f"ch{c}": [c] for c in range(ch)}
        variants["mean_all"] = "all"
        variants["mean_top3"] = [0, 4, 2]
    else:
        variants = {"ch0": [0], "ch4(best)": [4], "mean_all": "all", "mean_top3": [0, 4, 2]}

    # Global per-channel reference levels (99.5th pct over a sampled scan of the
    # WHOLE recording) so quiet sections stay quiet -> VAD filters silence instead
    # of the model hallucinating on an over-amplified noise floor.
    print("Scanning global reference levels ...")
    samp = []
    for i in range(0, n, 90):
        samp.append(np.abs(np.asarray(p.get_audio_data_by_index(mic, i)[0].data,
                                      dtype=np.float32).reshape(-1, ch)))
    global_ref = np.percentile(np.concatenate(samp), 99.5, axis=0)  # per-channel
    print("  per-channel ref (99.5pct):", np.round(global_ref).astype(int).tolist())

    print("Loading large-v3 ...")
    model = WhisperModel("large-v3", device="cpu", compute_type="int8")

    def score(mono, ref):
        mono = mono / (ref + 1e-9)                     # fixed global gain, not slice peak
        mono = np.clip(mono, -1.0, 1.0)
        mono16 = decimate(mono.astype(np.float32), sr // TARGET_SR, ftype="fir")
        segs, info = model.transcribe(mono16.astype(np.float32), task="transcribe",
                                      language=None, vad_filter=True, beam_size=5)
        segs = list(segs)
        if not segs:
            return info.language, info.language_probability, None, 0, 0.0
        dur = sum(s.end - s.start for s in segs)
        wlp = sum(s.avg_logprob * (s.end - s.start) for s in segs) / max(dur, 1e-6)
        return info.language, info.language_probability, wlp, len(segs), dur

    print(f"{'variant':12s} {'lang':5s} {'p_lang':>7s} {'avg_logprob':>12s} {'#seg':>5s} {'speech_s':>9s}")
    results = {}
    for name, sel in variants.items():
        cols = list(range(ch)) if sel == "all" else sel
        mono = seg[:, cols].mean(axis=1)
        ref = float(np.mean([global_ref[c] for c in cols]))  # matching gain for the mix
        lang, plang, wlp, nseg, dur = score(mono, ref)
        results[name] = wlp
        wlp_s = f"{wlp:+.3f}" if wlp is not None else "n/a"
        print(f"{name:12s} {lang:5s} {plang:7.2f} {wlp_s:>12s} {nseg:5d} {dur:9.1f}")

    best = max((k for k in results if results[k] is not None), key=lambda k: results[k])
    print(f"\n=> best by avg_logprob: {best}")


if __name__ == "__main__":
    main()
