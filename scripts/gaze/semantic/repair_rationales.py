#!/usr/bin/env python3
"""
Repair only the FAILED rationales in a semantic graph (idempotent, re-runnable).

VLM rationale generation leaves fallback placeholders when the connection blips
(common on an unstable local network). This regenerates ONLY the edges whose
rationale is a known fallback, leaves good ones untouched, writes back in place,
and reports how many remain — so on a flaky link you just re-run until 0 remain.
Self-contained (no model load); uses a higher retry count than the live build.

Usage:
  python repair_rationales.py --graph .../semantic_graph.json
  # re-run until it prints "0 still failed"
"""
import os
import json
import time
import argparse
import requests

FALLBACKS = {
    "Connection identified by semantic clustering.",
    "Similarity in technical or spatial context.",
    "Rationale unavailable (no API config).",
    "High semantic similarity detected.",
    "Calculating...",
    "",
}


def _post_retry(url, headers, payload, timeout=30, retries=3, backoff=2.0):
    last = None
    for k in range(retries):
        try:
            return requests.post(url, headers=headers, json=payload, timeout=timeout)
        except Exception as e:
            last = e
            if k < retries - 1:
                time.sleep(backoff * (k + 1))
    raise last


def rationale(url, auth, desc_a, desc_b):
    prompt = f"""
        Analyze these two expert observations from an egocentric recording:
        Observation A: "{desc_a}"
        Observation B: "{desc_b}"

        These have been mathematically flagged as semantically related.
        In 2-3 descriptive sentences, explain the specific shared theme,
        functional purpose, or expert intent that connects these two moments.
        Focus on identifying specific objects, technical challenges (like SLAM or data capture),
        or navigational goals they share.
        Do not use filler like "The connection is..." or "Both observations..."
        just provide a direct analytical comparison.
        """
    try:
        r = _post_retry(url, {"Authorization": auth}, {"prompt": prompt})
        if r.status_code == 200:
            return r.json().get("response", "").strip().strip('"')
    except Exception as e:
        print(f"  edge failed: {str(e)[:60]}")
    return None  # leave as-is (still failed) -> picked up on the next run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", required=True)
    ap.add_argument("--secrets", default="secrets.json")
    ap.add_argument("--min-degree", type=int, default=0,
                    help="only repair edges with convergence_degree >= N (skip the rest)")
    ap.add_argument("--referential-only", action="store_true",
                    help="only repair edges whose types include 'referential'")
    args = ap.parse_args()

    s = json.load(open(args.secrets))
    url, auth = s["SERVICE_URL"], s.get("RESEARCH_PASSWORD", "")

    g = json.load(open(args.graph))
    links = g.get("links", [])
    desc = {n["id"]: (n.get("narrative_description") or n.get("title", "")) for n in g.get("nodes", [])}

    todo = [l for l in links if l.get("rationale", "").strip() in FALLBACKS]
    if args.min_degree:
        todo = [l for l in todo if (l.get("convergence_degree") or 0) >= args.min_degree]
    if args.referential_only:
        todo = [l for l in todo if "referential" in (l.get("types") or [])]
    sel = []
    if args.min_degree:
        sel.append(f"degree>={args.min_degree}")
    if args.referential_only:
        sel.append("referential")
    scope = f" [{', '.join(sel)}]" if sel else ""
    print(f"{len(todo)} rationales to repair{scope} (of {len(links)} edges)...")

    fixed = 0
    consec_fail = 0
    for i, l in enumerate(todo, 1):
        rat = rationale(url, auth, desc.get(l.get("source"), ""), desc.get(l.get("target"), ""))
        if rat and rat.strip() not in FALLBACKS:
            l["rationale"] = rat
            fixed += 1
            consec_fail = 0
        else:
            consec_fail += 1
            if consec_fail >= 8:
                print(f"  ⚠️  {consec_fail} consecutive failures — connection looks down. "
                      f"Stopping early and saving progress; re-run when stable.")
                break
        if i % 50 == 0:
            print(f"  {i}/{len(todo)} attempted, {fixed} fixed so far")

    json.dump(g, open(args.graph, "w"), indent=2, ensure_ascii=False)
    remaining = sum(1 for l in todo if l.get("rationale", "").strip() in FALLBACKS)  # within the selected scope
    print(f"repaired {fixed}; {remaining} still failed."
          + ("  ✅ COMPLETE" if remaining == 0 else "  -> re-run to fix more"))


if __name__ == "__main__":
    main()
