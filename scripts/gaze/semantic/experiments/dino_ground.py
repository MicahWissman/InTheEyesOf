#!/usr/bin/env python3
"""
VISUAL-GROUNDING PILOT — STAGE B: Grounding DINO on gaze crops.
Runs in the `base` conda env (needs transformers + torch).

Reads manifest.json from Stage A, runs zero-shot Grounding DINO on each
gaze-centered crop with a FIXED scene vocabulary, then compares the
gaze-grounded VISUAL objects against the existing TRANSCRIPT objects.

SYMMETRIC canonicalization: BOTH visual labels and transcript objects are
snapped to the same controlled vocabulary (bge-m3 nearest term, gated by a
minimum similarity) before comparison, so we measure modality independence
rather than string-formatting artifacts.

Decision-gate metrics (no human labels):
  - mean Jaccard(visual_canon, transcript_canon)  -> low = independent signal
  - %% anchors whose top visual (foveated) object is absent from transcript

Usage:
  conda run -n base python dino_ground.py \
    --pilot scripts/gaze/semantic/experiments/pilot_out \
    --model IDEA-Research/grounding-dino-tiny
"""

import os
import json
import argparse
import torch
from PIL import Image
from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

# Controlled vocabulary covering the Steger tour (outdoor town + indoor campus).
VOCAB = [
    # outdoor / urban
    "person", "hand", "mobile phone", "cobblestone pavement", "stone wall",
    "building", "window", "door", "tree", "plant", "grass", "path", "road",
    "sky", "car", "bench", "stairs", "street lamp", "sign", "fence", "bush",
    "roof", "bicycle", "backpack", "railing", "water", "bridge", "mountain",
    "manhole cover", "utility pole", "tower",
    # indoor / campus
    "corridor", "ceiling", "floor", "table", "chair", "display screen",
    "fire extinguisher", "bookshelf", "glass wall", "pillar", "light fixture",
]
PROMPT = " . ".join(VOCAB) + " ."
SNAP_GATE = 0.50   # min bge-m3 cosine to assign a term to the controlled vocab


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", required=True, help="Stage A output dir (has manifest.json)")
    ap.add_argument("--model", default="IDEA-Research/grounding-dino-tiny")
    ap.add_argument("--box-threshold", type=float, default=0.30)
    ap.add_argument("--text-threshold", type=float, default=0.20)
    args = ap.parse_args()

    manifest = json.load(open(os.path.join(args.pilot, "manifest.json")))
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"Loading {args.model} on {device} ...")
    processor = AutoProcessor.from_pretrained(args.model)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(args.model).to(device)

    print("Loading BAAI/bge-m3 for canonicalization ...")
    bge = SentenceTransformer("BAAI/bge-m3")
    vocab_emb = bge.encode(VOCAB)

    def snap(label):
        """Nearest controlled-vocab term, or None if below the similarity gate."""
        sims = cosine_similarity(bge.encode([label]), vocab_emb)[0]
        k = int(sims.argmax())
        return VOCAB[k] if sims[k] >= SNAP_GATE else None

    def canon_set(labels):
        out = {}
        for lab in labels:
            c = snap(str(lab).strip())
            if c:
                out.setdefault(c, True)
        return set(out)

    def detect(img):
        inputs = processor(images=img, text=PROMPT, return_tensors="pt").to(device)
        with torch.no_grad():
            outputs = model(**inputs)
        try:
            res = processor.post_process_grounded_object_detection(
                outputs, inputs.input_ids, threshold=args.box_threshold,
                text_threshold=args.text_threshold, target_sizes=[img.size[::-1]])[0]
        except TypeError:
            res = processor.post_process_grounded_object_detection(
                outputs, inputs.input_ids, box_threshold=args.box_threshold,
                text_threshold=args.text_threshold, target_sizes=[img.size[::-1]])[0]
        labels = res.get("text_labels", res.get("labels", []))
        scores = [float(s) for s in res["scores"]]
        best = {}   # canon term -> best score
        for lab, sc in zip(labels, scores):
            c = snap(str(lab).strip())
            if c and (c not in best or sc > best[c]):
                best[c] = sc
        return sorted(best.items(), key=lambda kv: -kv[1])

    results, overlaps, top_absent, n_top = [], [], 0, 0
    for m in manifest:
        img = Image.open(os.path.join(args.pilot, m["crop_path"])).convert("RGB")
        dets = detect(img)                      # [(canon_term, score)] visual side
        V = set(t for t, _ in dets)
        T = canon_set(m["transcript_objects"])  # transcript side, same vocab space

        inter, union = len(V & T), len(V | T)
        ov = inter / union if union else 0.0
        overlaps.append(ov)

        top = dets[0][0] if dets else None
        if top is not None:
            n_top += 1
            top_in_t = top in T
            if not top_in_t:
                top_absent += 1
        else:
            top_in_t = False

        results.append({
            "anchor_id": m["anchor_id"], "title": m.get("narrative_title"),
            "visual_canon": [{"label": t, "score": round(s, 3)} for t, s in dets],
            "transcript_canon": sorted(T),
            "top_visual": top, "top_in_transcript": top_in_t,
            "shared": sorted(V & T), "visual_only": sorted(V - T),
            "jaccard": round(ov, 3),
            "transcript_objects_raw": m["transcript_objects"],
        })
        tflag = "in" if top_in_t else "NEW"
        print(f"\nanchor {m['anchor_id']:>3} | {m.get('narrative_title')}")
        print(f"  visual_canon : {[f'{t}:{s:.2f}' for t, s in dets]}")
        print(f"  transcript   : {sorted(T)}")
        print(f"  shared={sorted(V & T)}  visual_only={sorted(V - T)}")
        print(f"  top={top} [{tflag}]  jaccard={ov:.2f}")

    n = len(results)
    summary = {
        "n_anchors": n,
        "mean_jaccard_visual_vs_transcript": round(sum(overlaps) / n, 3) if n else 0,
        "pct_top_visual_absent_from_transcript": round(100 * top_absent / n_top, 1) if n_top else 0,
        "n_with_detection": n_top,
        "snap_gate": SNAP_GATE, "box_threshold": args.box_threshold,
        "model": args.model, "vocab_size": len(VOCAB),
    }
    out = {"summary": summary, "per_anchor": results}
    outpath = os.path.join(args.pilot, "dino_grounding.json")
    json.dump(out, open(outpath, "w"), indent=2)

    print("\n" + "=" * 60 + "\nSUMMARY")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"\nSaved -> {outpath}")


if __name__ == "__main__":
    main()
