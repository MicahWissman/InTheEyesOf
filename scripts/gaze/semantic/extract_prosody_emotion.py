#!/usr/bin/env python3
"""
Per-segment speech EMOTION + PROSODY from the raw WAV, keyed by seg_idx — the
tonal/affective layer to sit beside transcript, discourse level, and gaze.

Two layers, both LOCAL (no VLM service):

  Layer A - dimensional SER (learned emotion from audio, language-agnostic):
    audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim ->
      ser_arousal, ser_dominance, ser_valence   (~0..1; calm/excited,
      submissive/assertive, negative/positive)

  Layer B - interpretable prosody (the literal tonal curve / intonation), librosa:
      f0_mean_hz, f0_std_hz, f0_range_hz   (pitch; std/range = intonation spread)
      energy_mean, energy_std              (loudness / emphasis dynamics)
      voiced_frac, pause_frac, seg_dur_s
    (--egemaps additionally writes the full openSMILE eGeMAPSv02 set to a sidecar.)

Slices the WAV by each segment's t_start_s/t_end_s (WAV-relative, the same the
transcript uses), so it joins the fusion table on seg_idx. Runs on --device
{mps,cuda,cpu}; the SER model is the only GPU-relevant part (prosody is CPU).

Deps (base env): torch, transformers, librosa, soundfile, numpy  (+ opensmile for --egemaps).
First run downloads the SER model (~1.2 GB) once, then it's offline.

Usage:
  python extract_prosody_emotion.py --wav CaronaAdine1_forJavi.wav \
      --segments CaronaAdine1_fusion_m8.csv --out CaronaAdine1_fusion_m8_emo.csv \
      --device mps
"""
import os
import csv
import argparse
import numpy as np

SER_MODEL = "audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim"
SR = 16000


# ---- Layer A: dimensional SER (wav2vec2 with a regression head) -------------
def build_ser(model_name, device):
    import torch
    import torch.nn as nn
    from transformers import Wav2Vec2Processor
    from transformers.models.wav2vec2.modeling_wav2vec2 import (
        Wav2Vec2Model, Wav2Vec2PreTrainedModel)

    class RegressionHead(nn.Module):
        def __init__(self, config):
            super().__init__()
            self.dense = nn.Linear(config.hidden_size, config.hidden_size)
            self.dropout = nn.Dropout(config.final_dropout)
            self.out_proj = nn.Linear(config.hidden_size, config.num_labels)

        def forward(self, x):
            x = self.dropout(x)
            x = torch.tanh(self.dense(x))
            x = self.dropout(x)
            return self.out_proj(x)

    class EmotionModel(Wav2Vec2PreTrainedModel):
        def __init__(self, config):
            super().__init__(config)
            self.wav2vec2 = Wav2Vec2Model(config)
            self.classifier = RegressionHead(config)
            self.init_weights()

        def forward(self, input_values):
            hidden = self.wav2vec2(input_values)[0]
            hidden = torch.mean(hidden, dim=1)
            return self.classifier(hidden)

    proc = Wav2Vec2Processor.from_pretrained(model_name)
    model = EmotionModel.from_pretrained(model_name).to(device).eval()

    def predict(signal):
        import torch
        x = proc(signal, sampling_rate=SR)["input_values"][0]
        x = torch.tensor(np.array([x]), dtype=torch.float32, device=device)
        with torch.no_grad():
            out = model(x)[0].cpu().numpy()
        # model output order: arousal, dominance, valence
        return float(out[0]), float(out[1]), float(out[2])

    return predict


# ---- Layer B: interpretable prosody (librosa) -------------------------------
def prosody(signal, sr):
    import librosa
    out = {"seg_dur_s": round(len(signal) / sr, 3)}
    if len(signal) < int(0.1 * sr):
        return out
    try:
        f0, voiced, _ = librosa.pyin(signal, fmin=65, fmax=400, sr=sr)
        vf = f0[~np.isnan(f0)]
        out["f0_mean_hz"] = round(float(np.mean(vf)), 1) if vf.size else ""
        out["f0_std_hz"] = round(float(np.std(vf)), 1) if vf.size else ""
        out["f0_range_hz"] = round(float(np.ptp(vf)), 1) if vf.size else ""
        out["voiced_frac"] = round(float(np.mean(voiced)), 3)
    except Exception:
        pass
    rms = librosa.feature.rms(y=signal)[0]
    out["energy_mean"] = round(float(np.mean(rms)), 5)
    out["energy_std"] = round(float(np.std(rms)), 5)
    # pause fraction: frames below 10% of the segment's peak RMS
    if rms.size:
        thr = 0.1 * np.max(rms)
        out["pause_frac"] = round(float(np.mean(rms < thr)), 3)
    return out


def get_device(name):
    import torch
    if name == "cuda" and torch.cuda.is_available():
        return torch.device("cuda")
    if name == "mps" and getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    if name in ("cuda", "mps"):
        print(f"  ({name} unavailable, falling back to cpu)")
    return torch.device("cpu")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", required=True, help="the WAV the transcript/segments came from (16k mono ok)")
    ap.add_argument("--segments", required=True, help="CSV with seg_idx, t_start_s, t_end_s")
    ap.add_argument("--out", help="default: <segments>_emo.csv")
    ap.add_argument("--device", default="mps", choices=["mps", "cuda", "cpu"])
    ap.add_argument("--model", default=SER_MODEL)
    ap.add_argument("--no-ser", action="store_true", help="prosody only (skip the wav2vec2 SER model)")
    ap.add_argument("--egemaps", action="store_true", help="also write full openSMILE eGeMAPSv02 sidecar")
    ap.add_argument("--min-dur", type=float, default=0.4, help="segments shorter than this skip SER (noisy)")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    import librosa
    print(f"loading WAV {args.wav} ...")
    y, sr = librosa.load(args.wav, sr=SR, mono=True)
    print(f"  {len(y)/sr:.1f}s @ {sr} Hz")

    predict = None
    if not args.no_ser:
        device = get_device(args.device)
        print(f"loading SER model on {device} ...")
        predict = build_ser(args.model, device)

    smile = None
    if args.egemaps:
        import opensmile
        smile = opensmile.Smile(feature_set=opensmile.FeatureSet.eGeMAPSv02,
                                feature_level=opensmile.FeatureLevel.Functionals)

    rows = list(csv.DictReader(open(args.segments)))
    if args.limit:
        rows = rows[:args.limit]

    egemaps_rows = []
    for i, r in enumerate(rows, 1):
        t0 = float(r["t_start_s"]); t1 = float(r["t_end_s"])
        seg = y[int(t0 * sr):int(t1 * sr)]
        r.update(prosody(seg, sr))
        if predict is not None:
            if (t1 - t0) >= args.min_dur and seg.size:
                try:
                    a, d, v = predict(seg)
                    r["ser_arousal"], r["ser_dominance"], r["ser_valence"] = round(a, 4), round(d, 4), round(v, 4)
                except Exception as e:
                    r["ser_arousal"] = r["ser_dominance"] = r["ser_valence"] = ""
                    print(f"  seg {r['seg_idx']}: SER failed ({str(e)[:40]})")
            else:
                r["ser_arousal"] = r["ser_dominance"] = r["ser_valence"] = ""  # too short
        if smile is not None and seg.size:
            try:
                f = smile.process_signal(seg, sr).iloc[0].to_dict()
                f = {"seg_idx": r["seg_idx"], **{k: round(float(v), 5) for k, v in f.items()}}
                egemaps_rows.append(f)
            except Exception:
                pass
        if i % 100 == 0:
            print(f"  {i}/{len(rows)} segments")

    out = args.out or (args.segments[:-4] + "_emo.csv")
    cols = list(rows[0].keys())
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out}  ({len(rows)} rows)")

    if egemaps_rows:
        eg_out = (args.out or args.segments)[:-4] + "_egemaps.csv"
        with open(eg_out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(egemaps_rows[0].keys()))
            w.writeheader()
            w.writerows(egemaps_rows)
        print(f"wrote {eg_out}  (full eGeMAPSv02, {len(egemaps_rows)} rows)")


if __name__ == "__main__":
    main()
