#!/usr/bin/env python3
"""
SPATIAL-NARRATIVE ANCHOR PIPELINE (Generalized)
----------------------------------------------
Orchestrates the extraction, analysis, and AI synthesis of 3D narratives
for any Meta Project Aria recording.

Usage:
python run_narrative_pipeline.py --vrs [path] --mps [path] --transcript [path] --output [path]
"""

import os
import subprocess
import sys
import json
import argparse
import datetime
import importlib.metadata

# Find the correct Python executable for subprocesses.
# When conda envs are active, sys.executable may point to the base env
# which lacks the env-specific packages (e.g. open3d, projectaria_tools).
_BASE_PYTHON = sys.executable
if "miniconda" in _BASE_PYTHON or "anaconda" in _BASE_PYTHON:
    _conda_home = os.path.dirname(os.path.dirname(_BASE_PYTHON))
    _envs_dir = os.path.join(_conda_home, "envs")
    for _env_name in ["aria_tools", "aria"]:
        _candidate = os.path.join(_envs_dir, _env_name, "bin", "python")
        if os.path.isfile(_candidate):
            PYTHON_BIN = _candidate
            break
    else:
        PYTHON_BIN = _BASE_PYTHON
else:
    PYTHON_BIN = _BASE_PYTHON

def run_command(cmd, description):
    print(f"\n--- 🚀 {description} ---")
    print(f"Executing: {' '.join(cmd)}")
    try:
        # Use subprocess.run to allow output to flow to the console in real-time
        result = subprocess.run(cmd, check=True)
        print(f"✅ {description} completed successfully.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Error during {description}: {e}")
        return False

def _find_mps_for_vrs(vrs_path):
    """Auto-detect MPS directory next to the .vrs file (reccordings_aria/mps_<name>_vrs)."""
    vrs_dir = os.path.dirname(os.path.abspath(vrs_path))
    base = os.path.splitext(os.path.basename(vrs_path))[0]  # e.g. "Irchel_30"
    candidates = [
        os.path.join(vrs_dir, f"mps_{base}_vrs"),
        os.path.join(vrs_dir, f"mps_{base}"),
    ]
    for mps_path in candidates:
        if os.path.isdir(mps_path):
            return mps_path
    # Fallback: search parent dir for any mps_<name>_vrs
    parent = os.path.dirname(vrs_dir)
    for entry in sorted(os.listdir(parent)):
        if entry.startswith("mps_") and entry.endswith("_vrs"):
            full = os.path.abspath(os.path.join(parent, entry))
            slam = os.path.join(full, "slam")
            eye = os.path.join(full, "eye_gaze")
            if os.path.isabs(slam) and os.path.isdir(slam) and os.path.isabs(eye) and os.path.isdir(eye):
                return full
    return None


def _detect_package_versions():
    """Detect installed versions of key pipeline packages."""
    deps = ["sentence-transformers", "open3d", "sklearn", "scipy", "numpy"]
    versions = {}
    for pkg in deps:
        try:
            versions[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            pass
    return versions


def _save_pipeline_params(output_dir, args, graph_file, package_versions):
    """Write pipeline_params.json to the output directory."""
    # Count results from output files
    event_count = 0
    fallback_mean = 0.0
    mean_quality = 0.0
    semantic_file = os.path.join(output_dir, "semantic_results.json")
    if os.path.exists(semantic_file):
        with open(semantic_file) as f:
            events = json.load(f)
        if isinstance(events, list):
            event_count = len(events)
            quality_vals = [e.get("mean_quality") for e in events if e.get("mean_quality") is not None]
            fallback_vals = [e.get("fallback_ratio", 0) for e in events]
            if quality_vals:
                mean_quality = sum(quality_vals) / len(quality_vals)
            fallback_mean = sum(fallback_vals) / len(events) if events else 0

            # Aggregate quality-tier counts across all events
            tier_total = {"strong": 0, "weak": 0, "uncertain": 0, "fallback": 0}
            for ev in events:
                tiers = ev.get("quality_tiers")
                if tiers:
                    for key in tier_total:
                        tier_total[key] += tiers.get(key, 0)
            tier_total["total_samples"] = sum(tier_total.values())

    anchor_count = 0
    has_vlm_objects = False
    anchors_file = os.path.join(output_dir, "narrative_anchors.json")
    if os.path.exists(anchors_file):
        with open(anchors_file) as f:
            anchors = json.load(f)
        if isinstance(anchors, list):
            anchor_count = len(anchors)
            if anchors and "objects" in anchors[0]:
                has_vlm_objects = True

    edge_count = 0
    node_count = 0
    graph_meta = {}
    if graph_file and os.path.exists(graph_file):
        with open(graph_file) as f:
            graph = json.load(f)
        graph_meta = graph.get("metadata", {})
        edge_count = len(graph.get("links", []))
        node_count = len(graph.get("nodes", []))

    # Point cloud size
    ply_size_mb = None
    ply_path = os.path.join(output_dir, "pointcloud.ply")
    if os.path.exists(ply_path):
        ply_size_mb = round(os.path.getsize(ply_path) / (1024*1024), 1)

    params = {
        "generated_at": datetime.datetime.now().isoformat(),
        "pipeline": "InTheEyesOf Semantic Pipeline",
        "vrs_source": os.path.basename(args.vrs) if args.vrs else None,
        "mps_source": os.path.basename(args.mps) if args.mps else None,
        "stage": {
            "summarizer": {
                "cluster_eps": args.cluster_eps,
                "cluster_min_samples": args.cluster_min_samples,
                "quality_tiers": {
                    "STRONG": "< 0.5m perpendicular",
                    "WEAK": "0.5-1.0m perpendicular",
                    "UNCERTAIN": "1.0-1.5m perpendicular",
                    "FALLBACK": "> 1.5m, uses 2.0m depth"
                }
            },
            "synthesizer": {
                "group_radius": args.group_radius,
                "vlm_synthesis": not args.skip_synthesis
            },
            "graph_builder": graph_meta,
            "results": {
                "event_count": event_count,
                "anchor_count": anchor_count,
                "edge_count": edge_count,
                "node_count": node_count,
                "mean_quality": round(mean_quality, 3),
                "fallback_ratio_mean": round(fallback_mean, 3),
                "has_vlm_objects": has_vlm_objects,
                "quality_tier_counts": tier_total
            },
            "pointcloud": {"size_mb": ply_size_mb} if ply_size_mb else None,
            "trajectory_exported": os.path.exists(os.path.join(output_dir, "trajectory_latlon.json"))
        },
        "package_versions": package_versions
    }

    log_path = os.path.join(output_dir, "pipeline_params.json")
    with open(log_path, "w") as f:
        json.dump(params, f, indent=2)
    print(f"💾 Pipeline params logged to: {log_path}")


def main():
    parser = argparse.ArgumentParser(description="Run the Spatial-Narrative Anchor Pipeline")
    parser.add_argument("--vrs", help="Path to the .vrs file (auto-detects MPS if --mps omitted)")
    parser.add_argument("--mps", help="Path to the MPS results directory (containing slam/ and eye_gaze/). Auto-detected from --vrs if omitted.")
    parser.add_argument("--transcript", required=True, help="Path to the transcript text file")
    parser.add_argument("--output", required=True, help="Directory to save all results")
    parser.add_argument("--skip_synthesis", action="store_true", help="Skip the AI VLM synthesis step")
    parser.add_argument("--group_radius", type=float, default=2.0,
                        help="Merge hotspots within this 3D distance (metres) before synthesis. Default: 2.0")
    parser.add_argument("--cluster-eps", type=float, default=0.25,
                        help="DBSCAN eps for clustering gaze hotspots (meters). Default: 0.25")
    parser.add_argument("--cluster-min-samples", type=int, default=10,
                        help="DBSCAN min_samples for clustering. Default: 10")

    args = parser.parse_args()

    # Auto-detect MPS directory from VRS path if --mps is missing or invalid
    if args.vrs:
        if not args.mps or not os.path.isdir(args.mps):
            args.mps = _find_mps_for_vrs(args.vrs)
            if args.mps:
                print(f"  Auto-detected MPS: {args.mps}")

    if not args.vrs:
        parser.error("--vrs is required (or provide --mps with a known MPS directory)")

    # Paths to the specialized scripts
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    summarizer_script = os.path.join(scripts_dir, "spatial_transcript_summarizer.py")
    hand_extractor_script = os.path.join(scripts_dir, "hand_interaction_extractor.py")
    synthesizer_script = os.path.join(scripts_dir, "narrative_synthesizer.py")

    # Ensure output directory exists
    os.makedirs(args.output, exist_ok=True)

    # 1. EVENT EXTRACTION & GAZE HOTSPOTTING
    # This generates: clips, semantic_report.html, and semantic_results.json
    summarizer_cmd = [
        PYTHON_BIN, summarizer_script,
        "--mps_root", args.mps,
        "--vrs_path", args.vrs,
        "--transcript", args.transcript,
        "--output", args.output,
        "--eps", str(args.cluster_eps),
        "--min-samples", str(args.cluster_min_samples),
    ]
    if not run_command(summarizer_cmd, "Stage 1: Event & Gaze Extraction"):
        sys.exit(1)

    # 2. HAND INTERACTION ANALYSIS
    # (Optional/Informational step in the current implementation)
    hand_cmd = [
        PYTHON_BIN, hand_extractor_script,
        "--mps_root", args.mps
    ]
    if not run_command(hand_cmd, "Stage 2: Hand Interaction Analysis"):
        print("⚠️ Stage 2 failed, but this is optional. Continuing...")

    # 3. SPATIAL-NARRATIVE SYNTHESIS (AI VLM)
    if args.skip_synthesis:
        print("\n⏭️  Skipping Stage 3: Narrative Synthesis as requested.")
    else:
        results_json = os.path.join(args.output, "semantic_results.json")
        synth_output = os.path.join(args.output, "narrative_anchors.json")
        
        # Check if secrets.json exists for the synthesizer
        secrets_path = os.path.join(scripts_dir, "..", "..", "..", "secrets.json")
        if not os.path.exists(secrets_path):
            print(f"\n⚠️  Warning: secrets.json not found at {secrets_path}")
            print("   AI synthesis will likely fail. Please ensure your VLM credentials are set up.")

        synth_cmd = [
            PYTHON_BIN, synthesizer_script,
            "--results_json", results_json,
            "--mps_root", args.mps,
            "--output", synth_output,
            "--group_radius", str(args.group_radius)
        ]
        if not run_command(synth_cmd, "Stage 3: Spatial-Narrative Synthesis"):
            print("💡 Intermediate results are still available in the output directory.")

    # Save pipeline parameters log
    graph_file = os.path.join(args.output, "semantic_graph.json")
    _save_pipeline_params(args.output, args, graph_file, _detect_package_versions())

    print(f"\n🎉 Pipeline run finished for: {os.path.basename(args.vrs)}")
    print(f"📂 Results saved to: {args.output}")

if __name__ == "__main__":
    main()
