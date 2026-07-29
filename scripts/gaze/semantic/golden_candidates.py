#!/usr/bin/env python3
"""
Rank and shortlist companion anchors for human intent-labeling (the golden set).

Uses intent_strength (fraction of L1/concrete, object-referential speech in the
anchor's gaze window; from enrich_anchors_discourse.py) to nominate candidate
interpretive-intent moments — the expert was fixated AND speaking concretely about
an object — and to separate them from salience/noise:

  candidate   : intent_strength >= threshold and dominant_discourse == concrete
  low_intent  : has speech but below threshold (review for recall)
  aside       : dominant_discourse == aside        (excluded — chatter/meta)
  silence     : no speech in the window             (visual salience only — the
                                                      dwell-time / Model-1 baseline)

Emits a CSV ranked by intent_strength (desc) with an empty `human_intent` column,
so the costly human pass starts with the highest-yield anchors. Does not delete
anything — silence/aside anchors are tagged, not dropped, so they remain available
for the salience-vs-intent comparison.

Usage:
  python golden_candidates.py \
      --anchors web-viewer/public/recordings/Carona_02_companion/narrative_anchors.json \
      --threshold 0.6
"""
import os
import csv
import json
import argparse
from collections import Counter


def tier(a, thr):
    dom = a.get("dominant_discourse")
    if dom is None:
        return "silence"
    if dom == "aside":
        return "aside"
    if a.get("intent_strength", 0.0) >= thr and dom == "concrete":
        return "candidate"
    return "low_intent"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anchors", required=True)
    ap.add_argument("--threshold", type=float, default=0.6,
                    help="intent_strength cutoff for a candidate (default 0.6)")
    ap.add_argument("--out", help="default: <anchors dir>/golden_candidates.csv")
    args = ap.parse_args()

    raw = json.load(open(args.anchors))
    anchors = raw if isinstance(raw, list) else raw.get("anchors", raw.get("narrative_anchors", []))
    for i, a in enumerate(anchors):
        a["_idx"] = i  # graph node id

    ranked = sorted(anchors, key=lambda a: a.get("intent_strength", 0.0), reverse=True)

    out = args.out or os.path.join(os.path.dirname(args.anchors), "golden_candidates.csv")
    cols = ["rank", "anchor_id", "cluster_id", "tier", "intent_strength", "dominant_discourse",
            "l1", "l2", "l3", "mean_quality", "narrative_title", "objects",
            "start_sec", "duration", "gx", "gy", "gz", "clip_rel_path",
            "transcript_slice", "human_intent"]

    tc = Counter()
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for rank, a in enumerate(ranked, 1):
            t = tier(a, args.threshold)
            tc[t] += 1
            prof = a.get("discourse_profile", {})
            mq = a.get("mean_quality")
            w.writerow([
                rank, a["_idx"], a.get("cluster_id", ""), t,
                round(a.get("intent_strength", 0.0), 3), a.get("dominant_discourse"),
                prof.get("l1", ""), prof.get("l2", ""), prof.get("l3", ""),
                round(mq, 3) if isinstance(mq, (int, float)) else "",
                a.get("narrative_title", ""), "; ".join(a.get("objects", []) or []),
                round(a.get("start_sec", 0.0), 1), round(a.get("duration", 0.0), 1),
                round(a.get("gx", 0.0), 2), round(a.get("gy", 0.0), 2), round(a.get("gz", 0.0), 2),
                a.get("clip_rel_path", ""),
                (a.get("transcript_slice", "") or "").replace("\n", " ").strip(),
                "",  # human_intent — to be filled in annotation
            ])

    print(f"wrote {out}  ({len(ranked)} anchors ranked by intent_strength)")
    print(f"tiers (threshold={args.threshold}): {dict(tc)}")
    print(f"-> {tc['candidate']} candidate intent moments to annotate first; "
          f"{tc['low_intent']} low-intent for recall; "
          f"{tc['aside']} aside + {tc['silence']} silence excluded (kept for the salience baseline)")


if __name__ == "__main__":
    main()
