#!/usr/bin/env python3
"""
REFERENTIAL CHANNEL DIAGNOSTIC (no human labels required)
---------------------------------------------------------
The ablation showed tau_referential is inert. This script tests *why*,
automatically, on one or more anchor sets.

For every anchor pair it computes the three convergence channels and
compares the referential (object-overlap) channel under three definitions:
  - exact   : current production Jaccard on raw object strings
  - soft    : normalized + embedding cosine match (tag ~ tag if cos > THR)
  - soft_idf: soft overlap, each shared object weighted by rarity (IDF)

It then reports the metrics that decide whether a knowledge graph is worth
building, WITHOUT any golden set:
  1. distribution + %>0 of each referential variant   (is the channel dead?)
  2. correlation referential vs thematic              (is it redundant?)
  3. "referential-only" edge count at default taus    (does it add links the
     bge-m3 thematic baseline would miss?)

Usage:
  python referential_diagnostic.py anchors_A.json [anchors_B.json ...]
"""

import sys
import json
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from scipy.stats import pearsonr, spearmanr

# Production defaults (mirror semantic_network_builder.py)
TAU_SPATIAL = 0.4
TAU_REFERENTIAL = 0.25
TAU_THEMATIC = 0.7
LAM = 0.05
SOFT_THR = 0.80   # tag~tag cosine threshold for soft matching


def normalize(tag):
    return str(tag).lower().strip().rstrip("s")  # cheap lemmatize: drop trailing plural


def exact_jaccard(a, b):
    A, B = set(a or []), set(b or [])
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def soft_overlap(a, b, sim_lookup, idf=None):
    """Symmetric soft Jaccard. If idf given, weight matched tags by rarity."""
    A = [normalize(t) for t in (a or [])]
    B = [normalize(t) for t in (b or [])]
    if not A or not B:
        return 0.0

    def matched(src, dst):
        out = []
        for s in src:
            best = max((sim_lookup.get((s, d), 0.0) for d in dst), default=0.0)
            if best >= SOFT_THR:
                out.append(s)
        return out

    mA, mB = matched(A, B), matched(B, A)
    if idf is None:
        inter = (len(mA) + len(mB)) / 2.0
        union = len(A) + len(B) - inter
        return inter / union if union > 0 else 0.0
    # IDF-weighted: rare shared objects count more
    wA = sum(idf.get(t, 1.0) for t in mA)
    wB = sum(idf.get(t, 1.0) for t in mB)
    inter = (wA + wB) / 2.0
    union = sum(idf.get(t, 1.0) for t in A) + sum(idf.get(t, 1.0) for t in B) - inter
    return inter / union if union > 0 else 0.0


def dist(vals, label):
    v = np.array(vals)
    nz = float((v > 0).mean())
    return (f"  {label:9s} | %>0={nz*100:5.1f}%  mean={v.mean():.3f}  "
            f"p90={np.percentile(v,90):.3f}  max={v.max():.3f}")


def analyze(path, model):
    anchors = json.load(open(path))
    n = len(anchors)
    print(f"\n{'='*72}\n{path}\n  anchors={n}")

    # --- thematic (bge-m3 on descriptions) ---
    descs = [a.get("narrative_description", "") or "" for a in anchors]
    sem = cosine_similarity(model.encode(descs))

    # --- spatial ---
    pos = np.array([[a["gx"], a["gy"], a["gz"]] for a in anchors])
    spat = np.exp(-LAM * np.linalg.norm(pos[:, None] - pos[None, :], axis=-1))

    # --- tag vocabulary + IDF + soft similarity lookup ---
    norm_objs = [[normalize(t) for t in (a.get("objects", []) or [])] for a in anchors]
    vocab = sorted({t for o in norm_objs for t in o})
    print(f"  unique normalized object tags={len(vocab)} "
          f"(raw was the per-dataset string count)")
    df = {t: sum(1 for o in norm_objs if t in set(o)) for t in vocab}
    idf = {t: np.log(n / (1 + df[t])) for t in vocab}
    sim_lookup = {}
    if vocab:
        tag_emb = model.encode(vocab)
        tag_sim = cosine_similarity(tag_emb)
        for i, ti in enumerate(vocab):
            for j, tj in enumerate(vocab):
                if tag_sim[i, j] >= SOFT_THR:
                    sim_lookup[(ti, tj)] = float(tag_sim[i, j])

    # --- pairwise channels ---
    ex, sf, sfi, th, sp = [], [], [], [], []
    for i in range(n):
        for j in range(i + 1, n):
            ex.append(exact_jaccard(anchors[i].get("objects"), anchors[j].get("objects")))
            sf.append(soft_overlap(anchors[i].get("objects"), anchors[j].get("objects"), sim_lookup))
            sfi.append(soft_overlap(anchors[i].get("objects"), anchors[j].get("objects"), sim_lookup, idf))
            th.append(sem[i, j]); sp.append(spat[i, j])
    ex, sf, sfi, th, sp = map(np.array, (ex, sf, sfi, th, sp))

    print("\n  [1] channel distributions (all pairs):")
    print(dist(ex,  "ref_exact")); print(dist(sf,  "ref_soft"))
    print(dist(sfi, "ref_idf"));   print(dist(th,  "thematic")); print(dist(sp, "spatial"))

    print("\n  [2] redundancy — corr(referential, thematic):")
    for name, arr in [("ref_soft", sf), ("ref_idf", sfi)]:
        if arr.std() > 0:
            pr = pearsonr(arr, th)[0]; sprho = spearmanr(arr, th)[0]
            print(f"      {name:9s} pearson={pr:+.3f}  spearman={sprho:+.3f}")
        else:
            print(f"      {name:9s} no variance (channel still dead)")

    print("\n  [3] referential-ONLY edges at default taus "
          f"(ref>={TAU_REFERENTIAL}, NOT thematic>={TAU_THEMATIC}, NOT spatial>={TAU_SPATIAL}):")
    th_fire = th >= TAU_THEMATIC
    sp_fire = sp >= TAU_SPATIAL
    for name, arr in [("ref_exact", ex), ("ref_soft", sf), ("ref_idf", sfi)]:
        rf = arr >= TAU_REFERENTIAL
        only = int((rf & ~th_fire & ~sp_fire).sum())
        total = int(rf.sum())
        print(f"      {name:9s} fires={total:5d}  referential-only(new links)={only:5d}")
    print(f"      (baseline: thematic fires={int(th_fire.sum())}, spatial fires={int(sp_fire.sum())})")


def main():
    paths = sys.argv[1:]
    if not paths:
        print("usage: referential_diagnostic.py anchors_A.json [anchors_B.json ...]")
        sys.exit(1)
    print("Loading BAAI/bge-m3 ...")
    model = SentenceTransformer("BAAI/bge-m3")
    for p in paths:
        analyze(p, model)


if __name__ == "__main__":
    main()
