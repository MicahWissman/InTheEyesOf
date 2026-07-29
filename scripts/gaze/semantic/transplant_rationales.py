#!/usr/bin/env python3
"""
Transplant edge rationales from source (part) graphs into a merged graph, matching
by the anchor description-pair (undirected). Within-part edges are the SAME anchor
pairs as in their source graph, so their rationales copy over for free; cross-part
edges are new pairs (not in any source) and stay as placeholders — to be computed
fresh, e.g. `repair_rationales.py --min-degree 2 --referential-only`.

Usage:
  python transplant_rationales.py --merged <merged_graph.json> \
      --source <partA_graph.json> --source <partB_graph.json>
"""
import json
import argparse

FALLBACKS = {
    "Connection identified by semantic clustering.",
    "Similarity in technical or spatial context.",
    "Rationale unavailable (no API config).",
    "High semantic similarity detected.",
    "Calculating...",
    "",
}


def pair_key(nodes, link):
    a = (nodes[link["source"]].get("narrative_description") or "").strip()
    b = (nodes[link["target"]].get("narrative_description") or "").strip()
    return frozenset({a, b})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merged", required=True)
    ap.add_argument("--source", action="append", required=True, help="part graph (repeatable)")
    args = ap.parse_args()

    lookup = {}
    for sp in args.source:
        g = json.load(open(sp))
        nodes = g["nodes"]
        n = 0
        for l in g["links"]:
            r = (l.get("rationale") or "").strip()
            if r and r not in FALLBACKS:
                lookup[pair_key(nodes, l)] = l["rationale"]
                n += 1
        print(f"  {sp}: {n} real rationales available")

    g = json.load(open(args.merged))
    nodes = g["nodes"]
    transplanted = 0
    for l in g["links"]:
        if (l.get("rationale") or "").strip() in FALLBACKS:
            r = lookup.get(pair_key(nodes, l))
            if r:
                l["rationale"] = r
                transplanted += 1
    json.dump(g, open(args.merged, "w"), indent=2, ensure_ascii=False)

    remaining = sum(1 for l in g["links"] if (l.get("rationale") or "").strip() in FALLBACKS)
    print(f"transplanted {transplanted} rationales into {args.merged}")
    print(f"{remaining} edges still placeholder (cross-part / weak within-part not in sources)")


if __name__ == "__main__":
    main()
