#!/usr/bin/env python3
"""
Apply the cross-device time map (timemap.json from fit_device_timemap.py) to put
device-1 (Adine) native-segment transcripts onto each device-2 (Carona) spatial
timeline. The Adine mic is cleaner/more complete, so its transcript becomes the
authoritative speech for Carona's spatial pipeline.

  Carona_02  <- Adine1
  Carona_03  <- Adine2 (early part) + Adine3 (late part), merged on Carona time

For each Carona target it writes:
  *_fromAdine_m3.csv  native segments in Carona time (+ source column)
  *_fromAdine_m3.txt  binned multi-line (the pipeline --transcript format)

Usage:
  python apply_device_timemap.py --base-dir /path/to/Carona --timemap timemap.json
"""

import os
import csv
import json
import argparse
from transcript_format import write_transcript

# Carona target -> [(source_name_in_timemap, source_csv)] for a given transcript suffix
def targets_for(suffix):
    return {
        "Carona_02": [("Adine1", f"CaronaAdine1_forJavi_{suffix}.csv")],
        "Carona_03": [("Adine2", f"CaronaAdine2_forJavi_{suffix}.csv"),
                      ("Adine3", f"CaronaAdine3_forJavi_{suffix}.csv")],
    }


def load_segments(path):
    """Native segments, with discourse_level joined from a <name>_discourse.csv
    sidecar (by seg_idx) if present, so the level rides through the time-map."""
    disc = {}
    disc_path = path[:-4] + "_discourse.csv"
    if os.path.exists(disc_path):
        disc = {int(r["seg_idx"]): r.get("level", "") for r in csv.DictReader(open(disc_path))}
    out = []
    for r in csv.DictReader(open(path)):
        out.append((float(r["t_start_s"]), float(r["t_end_s"]), r["transcript"],
                    r.get("lang", ""), r.get("speaker", ""), disc.get(int(r["seg_idx"]), "")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-dir", default=".")
    ap.add_argument("--timemap", default="timemap.json")
    ap.add_argument("--suffix", default="m3", help="transcript suffix (e.g. m3, m8)")
    args = ap.parse_args()

    tm = json.load(open(os.path.join(args.base_dir, args.timemap)))

    for target, sources in targets_for(args.suffix).items():
        merged = []  # (carona_start, carona_end, text, lang, speaker, source, discourse_level)
        for name, csv_name in sources:
            m = tm[name]
            for s, e, text, lang, spk, dlvl in load_segments(os.path.join(args.base_dir, csv_name)):
                cs = m["slope"] * s + m["offset_s"]
                ce = m["slope"] * e + m["offset_s"]
                merged.append((cs, ce, text, lang, spk, name, dlvl))
        merged.sort(key=lambda x: x[0])

        # diagnostics: coverage + overlap between sources
        if merged:
            span = (merged[0][0], merged[-1][1])
            overlaps = sum(1 for i in range(1, len(merged)) if merged[i][0] < merged[i - 1][1] - 0.5)
        else:
            span, overlaps = (0, 0), 0

        # native CSV (Carona time, with source)
        csv_out = os.path.join(args.base_dir, f"{target}_fromAdine_{args.suffix}.csv")
        with open(csv_out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["seg_idx", "t_start_s", "t_end_s", "lang", "speaker", "source",
                        "discourse_level", "transcript"])
            for i, (cs, ce, text, lang, spk, src, dlvl) in enumerate(merged):
                w.writerow([i, round(cs, 3), round(ce, 3), lang, spk, src, dlvl, text])

        # binned multi-line .txt for the pipeline --transcript
        items = [(cs, ce, text, lang, spk) for cs, ce, text, lang, spk, _src, _dlvl in merged]
        txt_out = os.path.join(args.base_dir, f"{target}_fromAdine_{args.suffix}.txt")
        n = write_transcript(items, txt_out, interval=10.0, tag_lang=True)

        print(f"{target}: {len(merged)} segments from {[s[0] for s in sources]} | "
              f"Carona span {span[0]:.0f}-{span[1]:.0f}s | overlaps={overlaps} | "
              f"{n} binned chunks")
        print(f"  -> {os.path.basename(csv_out)}, {os.path.basename(txt_out)}")


if __name__ == "__main__":
    main()
