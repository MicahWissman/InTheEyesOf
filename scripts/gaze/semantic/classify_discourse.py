#!/usr/bin/env python3
"""
Classify each transcript segment by DISCOURSE LEVEL — the content layer that the
convergence model needs to separate interpretive intent from salience/noise:

  1 = concrete   : tangible, object-referential knowledge (THE target signal —
                   the expert names/explains the actual feature/object/space)
  2 = contextual : ancillary/background elaboration (RAG-like scaffolding)
  3 = aside      : side comments, jokes, procedural, self-correction, filler, or
                   metalinguistic remarks (about the language/recording) — noise

Input : a native-segment transcript CSV (seg_idx,t_start_s,t_end_s,lang,speaker,transcript)
Output: a sidecar <name>_discourse.csv keyed by seg_idx (self-contained, carries
        the text so it can be hand-validated). The label is a property of the
        TRANSCRIPT, so it lives next to it and propagates downstream:
          build_fusion --discourse  (per-segment column)  and the anchor synthesis.

Classifier: the project LLM service (secrets.json), batched with local context so
the model sees the surrounding discourse flow.

Usage:
  python classify_discourse.py --transcript CaronaAdine1_forJavi_m8.csv
"""
import os
import csv
import json
import time
import argparse
import requests

LEVELS = {1: "concrete", 2: "contextual", 3: "aside"}

RUBRIC = """You label segments of an expert's spoken discourse during a guided walk
through a physical space, by their CONTENT LEVEL. Use the surrounding segments as
context — a short segment's level often depends on what is around it.

LEVEL 1 — concrete: tangible, object-referential knowledge. The expert names or
explains the actual feature/object/space: what it is, how it works, its parts.
The core substantive content the walk is about.
  e.g. "Empezamos por la forma de la montaña" / "el agua va moldeando el terreno"

LEVEL 2 — contextual: ancillary/background elaboration that supports but is not the
concrete fact itself — generalisations, framing, history, tangential domain context.
  e.g. "antes de la vida, la geomorfologia lo determina todo"

LEVEL 3 — aside: side comments, jokes, procedural talk ("can I start?"), self-
correction, filler, or metalinguistic remarks (about the language or the recording
itself), and off-topic chatter.
  e.g. "Posso iniziare?" / "e la mia lingua materna" / "No, la temperatura e cambiata"

Return STRICT JSON ONLY: a list with one object per segment given, SAME order,
{"seg_idx": <int>, "level": 1|2|3, "confidence": <0.0-1.0>, "rationale": "<=8 words"}.
No prose, no markdown."""


def classify_batch(service_url, auth, batch):
    listing = "\n".join(f'[{s["seg_idx"]}] ({s.get("lang","")}) {s["transcript"]}' for s in batch)
    prompt = f"{RUBRIC}\n\nSEGMENTS:\n{listing}\n\nJSON:"
    r = requests.post(service_url, headers={"Authorization": auth},
                      json={"prompt": prompt}, timeout=90)
    r.raise_for_status()
    txt = r.json().get("response", "").strip()
    if txt.startswith("```"):
        txt = txt.split("```", 2)[1].removeprefix("json").strip().removesuffix("```").strip()
    i, j = txt.find("["), txt.rfind("]")
    arr = json.loads(txt[i:j + 1])
    return {int(x["seg_idx"]): x for x in arr if "seg_idx" in x}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcript", required=True, help="native-segment CSV")
    ap.add_argument("--out", help="default: <transcript>_discourse.csv")
    ap.add_argument("--batch", type=int, default=15, help="segments per LLM call")
    ap.add_argument("--limit", type=int, help="only classify the first N segments (smoke test)")
    ap.add_argument("--secrets", default="secrets.json")
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.transcript)))
    if args.limit:
        rows = rows[:args.limit]
    s = json.load(open(args.secrets))
    url, auth = s["SERVICE_URL"], s.get("RESEARCH_PASSWORD", "")

    labels = {}
    for k in range(0, len(rows), args.batch):
        batch = rows[k:k + args.batch]
        for attempt in range(2):
            try:
                labels.update(classify_batch(url, auth, batch))
                break
            except Exception as e:
                if attempt:
                    print(f"  batch @{k}: failed ({str(e)[:60]}); left unlabeled")
                else:
                    time.sleep(2)
        print(f"  {min(k + args.batch, len(rows))}/{len(rows)} classified")

    out = args.out or (args.transcript[:-4] + "_discourse.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["seg_idx", "t_start_s", "t_end_s", "lang", "level", "label",
                    "confidence", "rationale", "transcript"])
        for r in rows:
            si = int(r["seg_idx"])
            lab = labels.get(si, {})
            lvl = lab.get("level")
            w.writerow([si, r["t_start_s"], r["t_end_s"], r.get("lang", ""), lvl or "",
                        LEVELS.get(lvl, ""), lab.get("confidence", ""),
                        lab.get("rationale", ""), r["transcript"]])

    from collections import Counter
    dist = Counter(lab.get("level") for lab in labels.values())
    pct = {LEVELS.get(k, k): f"{v} ({100*v/max(len(labels),1):.0f}%)" for k, v in sorted(dist.items(), key=lambda x: (x[0] is None, x[0]))}
    print(f"wrote {out}  |  {len(labels)}/{len(rows)} labeled  |  levels: {pct}")


if __name__ == "__main__":
    main()
