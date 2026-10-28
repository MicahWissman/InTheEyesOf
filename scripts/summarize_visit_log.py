#!/usr/bin/env python3
"""Summarise the anonymous web-viewer visit log into per-visitor and per-perspective tables.

The log is written by server/ask-proxy.js (deployed) or the vite dev/preview server (local)
from web-viewer/src/utils/visitLog.ts: one JSON event per line.

Usage:
    python scripts/summarize_visit_log.py [server/logs/visits.jsonl] [--recording ID] [--csv OUT]
"""
import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict


def load(path, recording=None):
    events = []
    with open(path) as f:
        for line in f:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if recording and e.get("rec") != recording:
                continue
            events.append(e)
    # batches can arrive out of order (beacon vs fetch) — seq is per visitor and monotonic
    events.sort(key=lambda e: (e["v"], e.get("seq", 0)))
    return events


def short(p):
    return "".join(w[0] for w in p.split()).upper() if p else "?"


def visitor_rows(events):
    by = defaultdict(list)
    for e in events:
        by[(e["v"], e.get("rec"))].append(e)
    rows = []
    for (v, rec), ev in by.items():
        if rec is None:
            continue
        starts = [e for e in ev if e["type"] == "listen_start"]
        ends = [e for e in ev if e["type"] == "listen_end"]
        skips = [e for e in ends if e["outcome"] == "skipped"]
        views = [e for e in ev if e["type"] == "view_start"]
        dwell = [e["dwell_s"] for e in ev if e["type"] == "view_end"]
        first = next((e for e in ev if e["type"] == "session_start"), {})
        # perspective choice = anchors opened (works with or without audio)
        persp = Counter(short(e.get("perspective")) for e in views if e.get("perspective"))
        rows.append({
            "visitor": v[:6],
            "recording": rec,
            "device": first.get("device", "?"),
            "minutes": round((max(e["t"] for e in ev) - min(e["t"] for e in ev)) / 60, 1),
            "opened": len(views),
            "perspectives": " ".join(f"{k}:{n}" for k, n in persp.most_common()),
            "first_perspective": short(views[0].get("perspective")) if views else "",
            "median_dwell_s": round(statistics.median(dwell)) if dwell else "",
            "revisits": sum(bool(e.get("revisit")) for e in views),
            "clips": len(starts),
            "completed": sum(e["outcome"] == "completed" for e in ends),
            "skipped": len(skips),
            "skip_at_pct": round(100 * statistics.median(e["fraction"] for e in skips if e.get("fraction") is not None))
                           if any(e.get("fraction") is not None for e in skips) else "",
            "listen_min": round(sum(e.get("position_s") or 0 for e in ends) / 60, 1),
            "replays": sum(bool(e.get("replay")) for e in starts),
            "rewinds": sum(e["type"] == "seek" and e.get("to_s", 0) < e.get("from_s", 0) for e in ev),
            "pauses": sum(e["type"] == "pause" for e in ev),
            "expert_audio": sum(e.get("track") == "transcript" for e in starts),
            "proximity": sum(e.get("trigger") == "proximity" for e in starts),
        })
    return sorted(rows, key=lambda r: (r["recording"], -r["opened"]))


def perspective_rows(events):
    views, ends = defaultdict(list), defaultdict(list)
    for e in events:
        if e.get("perspective") and e["type"] == "view_end":
            views[e["perspective"]].append(e)
        if e.get("perspective") and e["type"] == "listen_end":
            ends[e["perspective"]].append(e)
    rows = []
    for p in sorted(set(views) | set(ends)):
        v, l = views[p], ends[p]
        fr = [e["fraction"] for e in l if e.get("fraction") is not None]
        rows.append({
            "perspective": f"{p} ({short(p)})",
            "visitors": len({e["v"] for e in v + l}),
            "opens": len(v),
            "median_dwell_s": round(statistics.median(e["dwell_s"] for e in v)) if v else "",
            "listens": len(l),
            "completed_pct": round(100 * sum(e["outcome"] == "completed" for e in l) / len(l)) if l else "",
            "mean_heard_pct": round(100 * statistics.mean(fr)) if fr else "",
        })
    return rows


def markdown(rows):
    if not rows:
        return "(no rows)"
    cols = list(rows[0])
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    out += ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", nargs="?", default="server/logs/visits.jsonl")
    ap.add_argument("--recording", help="only this recording id (e.g. robotics_lab_combined)")
    ap.add_argument("--csv", help="also write the per-visitor table to this CSV")
    a = ap.parse_args()

    events = load(a.log, a.recording)
    vis = visitor_rows(events)
    print(f"{len(events)} events, {len({r['visitor'] for r in vis})} visitors\n")
    print("Per visitor (perspective codes = initials; skip_at_pct = median % of a clip heard before skipping)\n")
    print(markdown(vis))
    print("\nPer perspective\n")
    print(markdown(perspective_rows(events)))
    if a.csv and vis:
        with open(a.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(vis[0]))
            w.writeheader()
            w.writerows(vis)


if __name__ == "__main__":
    main()
