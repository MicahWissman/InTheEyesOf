#!/usr/bin/env python3
"""
Tag each companion anchor with a DISCOURSE PROFILE — the share of its speech that
is L1 concrete / L2 contextual / L3 aside — by rolling up the time-mapped
transcript segments (which carry discourse_level, via apply_device_timemap) that
overlap the anchor's gaze-time window. Duration-weighted. Adds per anchor:

  discourse_profile   {l1, l2, l3}   duration-weighted fractions
  dominant_discourse  concrete|contextual|aside|None
  intent_strength     = frac L1      (the convergence referential gate; 0 if no speech)

Post-hoc (no new VLM calls): high intent_strength = the expert was on-topic,
object-referential while the wearer fixated here — the target intent signal.

Usage:
  python enrich_anchors_discourse.py \
      --anchors  web-viewer/public/recordings/Carona_02_companion/narrative_anchors.json \
      --segments /path/Carona_02_fromAdine_m8.csv
"""
import csv
import json
import argparse
import statistics
from collections import Counter

LABELS = {"1": "concrete", "2": "contextual", "3": "aside"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anchors", required=True)
    ap.add_argument("--segments", required=True,
                    help="fromAdine CSV with t_start_s,t_end_s,discourse_level")
    ap.add_argument("--out", help="default: overwrite --anchors")
    args = ap.parse_args()

    segs = []
    for r in csv.DictReader(open(args.segments)):
        lvl = (r.get("discourse_level") or "").strip()
        if lvl in ("1", "2", "3"):
            segs.append((float(r["t_start_s"]), float(r["t_end_s"]), lvl))
    segs.sort()

    raw = json.load(open(args.anchors))
    anchors = raw if isinstance(raw, list) else raw.get("anchors", raw.get("narrative_anchors", []))

    n_tagged = 0
    for a in anchors:
        a0 = a.get("start_sec", 0.0)
        a1 = a0 + a.get("duration", 0.0)
        w = {"1": 0.0, "2": 0.0, "3": 0.0}
        for s0, s1, lvl in segs:
            if s0 >= a1:
                break
            ov = min(a1, s1) - max(a0, s0)
            if ov > 0:
                w[lvl] += ov
        total = sum(w.values())
        if total > 0:
            prof = {f"l{k}": round(w[k] / total, 3) for k in ("1", "2", "3")}
            dom = max(("1", "2", "3"), key=lambda k: w[k])
            a["discourse_profile"] = prof
            a["dominant_discourse"] = LABELS[dom]
            a["intent_strength"] = prof["l1"]
            n_tagged += 1
        else:
            a["discourse_profile"] = {"l1": 0.0, "l2": 0.0, "l3": 0.0}
            a["dominant_discourse"] = None
            a["intent_strength"] = 0.0

    out = args.out or args.anchors
    json.dump(raw, open(out, "w"), indent=2, ensure_ascii=False)

    iss = [a["intent_strength"] for a in anchors]
    dc = Counter(a["dominant_discourse"] for a in anchors)
    print(f"tagged {n_tagged}/{len(anchors)} anchors  (rest had no overlapping speech)")
    print(f"intent_strength (frac L1): mean={statistics.mean(iss):.2f} "
          f"median={statistics.median(iss):.2f}")
    print(f"dominant discourse: {dict(dc)}")
    print(f"high-intent anchors (L1>=0.6): {sum(1 for x in iss if x >= 0.6)} | "
          f"aside-dominated (to down-weight): {dc.get('aside', 0)}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
