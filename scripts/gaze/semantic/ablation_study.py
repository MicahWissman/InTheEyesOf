#!/usr/bin/env python3
"""
ABLATION STUDY: Edge count vs parameter combinations.
Runs semantic_network_builder.py in --count-only mode across a grid of
tau_spatial, tau_referential, tau_thematic, and lam values.
This sweeps the ACTUAL edge-controlling parameters in the typed-edge system.
"""

import os
import sys
import json
import subprocess
import itertools
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))

ANCHORS_PATH = os.path.join(
    REPO_ROOT,
    "pipeline_results_Irchel_30_enriched_v3.6",
    "narrative_anchors.json"
)

BUILDER_SCRIPT = os.path.join(SCRIPT_DIR, "semantic_network_builder.py")


def count_edges(alpha, beta, gamma, lam, threshold,
                tau_spatial=0.4, tau_referential=0.25, tau_thematic=0.7):
    """Run semantic_network_builder --count-only and return edge count."""
    cmd = [
        sys.executable, BUILDER_SCRIPT,
        "--anchors", ANCHORS_PATH,
        "--alpha", str(alpha),
        "--beta", str(beta),
        "--gamma", str(gamma),
        "--lam", str(lam),
        "--threshold", str(threshold),
        "--tau-spatial", str(tau_spatial),
        "--tau-referential", str(tau_referential),
        "--tau-thematic", str(tau_thematic),
        "--count-only",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    for line in result.stdout.splitlines():
        if line.startswith("EDGE_COUNT:"):
            return int(line.split(":")[1])
    return None


def main():
    if not os.path.exists(ANCHORS_PATH):
        print(f"Error: anchors not found at {ANCHORS_PATH}")
        sys.exit(1)

    # Parameter grids — new typed-edge system: tau_* values are the actual edge controllers
    tau_spatial_values = [0.3, 0.4, 0.5, 0.6]
    tau_referential_values = [0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75]
    tau_thematic_values = [0.5, 0.6, 0.7, 0.8]
    lams = [0.05, 0.15, 0.3]      # spatial decay rate (1/m)

    combos = list(itertools.product(tau_spatial_values, tau_referential_values, tau_thematic_values, lams))
    print(f"Testing {len(combos)} parameter combinations...")
    print()

    results = []
    start = time.time()
    for tau_spatial, tau_referential, tau_thematic, lam in combos:
        edge_count = count_edges(0.5, 0.5, 0.5, lam, 0.5,
            tau_spatial, tau_referential, tau_thematic)
        if edge_count is not None:
            results.append((tau_spatial, tau_referential, tau_thematic, lam, edge_count))
        elapsed = time.time() - start
        sys.stderr.write(f"\r  [{len(results)}/{len(combos)}] tau_s={tau_spatial}, tau_r={tau_referential}, tau_t={tau_thematic}, lam={lam} => {edge_count} edges  ({elapsed:.0f}s)")
        sys.stderr.flush()

    total = time.time() - start
    print(f"\n\nDone ({total:.1f}s)\n")

    # Print as markdown table
    print("| tau_spatial | tau_referential | tau_thematic | lam | edges |")
    print("|--|-|-|-|--|")
    for tau_spatial, tau_referential, tau_thematic, lam, edges in results:
        print(f"| {tau_spatial} | {tau_referential} | {tau_thematic} | {lam} | {edges} |")

    # Also save as JSON for easy parsing
    out_path = os.path.join(REPO_ROOT, "ablation_edges.json")
    with open(out_path, "w") as f:
        json.dump({"results": results, "anchor_count": 68}, f, indent=2)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
