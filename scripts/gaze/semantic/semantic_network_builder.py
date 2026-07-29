"""
SEMANTIC NETWORK BUILDER (Convergence Graph Engine)
----------------------------------------------------
This script analyzes the semantic and spatial relationships between hotspots
to build a graphic network of expert intent.

Logic:
1. Semantic Similarity (S): Cosine similarity of multilingual embeddings (BAAI/bge-m3).
2. Tag Overlap (T): Jaccard similarity of object tags from VLM output.
3. Spatial Proximity (P): Exponential decay of 3D Euclidean distance.
Edges are typed by independently thresholding each channel and recording
how many agree (convergence degree 0-3).
"""

import os
import json
import datetime
import numpy as np
import requests
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity


def _post_retry(url, headers, payload, timeout, retries=4, backoff=3.0):
    """POST with retry/backoff so a transient DNS/timeout blip doesn't poison a
    whole stage. Raises the last exception only after all retries are exhausted."""
    import time
    last = None
    for k in range(retries):
        try:
            return requests.post(url, headers=headers, json=payload, timeout=timeout)
        except Exception as e:
            last = e
            if k < retries - 1:
                time.sleep(backoff * (k + 1))
    raise last


class SemanticNetworkBuilder:
    def __init__(self, model_name='BAAI/bge-m3'):
        print(f"Loading embedding model: {model_name}...")
        self.model = SentenceTransformer(model_name)

        # Load Secrets for AI Rationale
        secrets_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "secrets.json")
        if os.path.exists(secrets_path):
            with open(secrets_path, "r") as f:
                secrets = json.load(f)
                self.service_url = secrets.get("SERVICE_URL")
                self.auth_token = secrets.get("RESEARCH_PASSWORD")
        else:
            self.service_url = None
            self.auth_token = None

    def _get_ai_rationale(self, desc_a, desc_b):
        """Ask Gemini to explain the semantic link between two descriptions."""
        if not self.service_url:
            return "Rationale unavailable (no API config)."

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
            res = _post_retry(self.service_url, {"Authorization": self.auth_token},
                              {"prompt": prompt}, 30)
            if res.status_code == 200:
                ai_response = res.json().get("response", "High semantic similarity detected.")
                return ai_response.strip().strip('"')
            return "Similarity in technical or spatial context."
        except Exception as e:
            print(f"   Rationale Error: {e}")
            return "Connection identified by semantic clustering."

    def build_graph(self, anchors, alpha=0.5, beta=0.5, gamma=0.5, lam=0.05, threshold=0.6,
                    tau_spatial=0.4, tau_referential=0.25, tau_thematic=0.7,
                    generate_rationales=True, count_only=False, intent_gate=True):
        """
        Builds the semantic-spatial network.

        Parameters
        ----------
        alpha : float
            Weight for semantic similarity (cosine of bge-m3 embeddings).
        beta : float
            Weight for tag overlap (Jaccard of VLM object tags).
        gamma : float
            Weight for spatial proximity.
        lam : float
            Spatial decay rate (1/m). Separated from gamma so the
            proximity weight and its distance-decay are independent.
            P = exp(-lam * d), then weighted by gamma.
        """
        print(f"Building network for {len(anchors)} hotspots...")

        # intent_strength per node (fraction of L1/concrete speech). Gates the
        # REFERENTIAL channel only: an object-overlap edge counts as referential
        # convergence only when BOTH endpoints were genuinely object-referential
        # (not aside/contextual). Spatial/thematic channels are untouched.
        # Defaults to 1.0 when absent, so un-enriched anchors behave as before.
        intents = np.array([float(a.get('intent_strength', 1.0)) for a in anchors])
        if intent_gate and any('intent_strength' in a for a in anchors):
            print(f"  Referential channel gated by intent_strength (mean={intents.mean():.2f}).")

        # 1. Generate Semantic Embeddings
        descriptions = [a.get('narrative_description', '') for a in anchors]
        embeddings = self.model.encode(descriptions)

        # 2. Compute Semantic Similarity Matrix
        semantic_sim = cosine_similarity(embeddings)

        # 3. Compute Tag Overlap Matrix (Jaccard similarity on objects lists)
        num_nodes = len(anchors)
        tag_overlap = np.zeros((num_nodes, num_nodes))
        for i in range(num_nodes):
            objs_i = set(anchors[i].get('objects', []) or [])
            for j in range(i + 1, num_nodes):
                objs_j = set(anchors[j].get('objects', []) or [])
                if objs_i and objs_j:
                    intersection = len(objs_i & objs_j)
                    union = len(objs_i | objs_j)
                    tag_overlap[i, j] = intersection / union if union > 0 else 0
                    tag_overlap[j, i] = tag_overlap[i, j]

        # 4. Compute Spatial Proximity Matrix
        positions = np.array([[a['gx'], a['gy'], a['gz']] for a in anchors])
        spatial_prox = np.zeros((num_nodes, num_nodes))

        for i in range(num_nodes):
            for j in range(num_nodes):
                dist = np.linalg.norm(positions[i] - positions[j])
                spatial_prox[i, j] = np.exp(-lam * dist)

        # ---- Edge types: independent thresholds, convergence degree ----
        # Each channel is thresholded on its own; a pair gets 0-3 types
        # and a convergence_degree = number of channels that fire.

        # For edges that fire, compute degree + types
        if not count_only:
            nodes = []
            links = []
        all_components = []  # (3) full pairwise component store
        edge_count = 0

        for i, anchor in enumerate(anchors):
            if not count_only:
                nodes.append({
                    "id": i,
                    "cluster_id": anchor.get('cluster_id'),
                    "title": anchor.get('narrative_title', f"Point {i}"),
                    "pos": [anchor['gx'], anchor['gy'], anchor['gz']],
                    "time": anchor.get('relative_time'),
                    "narrative_description": descriptions[i] if i < len(descriptions) else "",
                    "objects": anchor.get('objects', [])
                })

            for j in range(i + 1, num_nodes):
                s_sim = semantic_sim[i, j]
                p_prox = spatial_prox[i, j]
                t_ov_raw = tag_overlap[i, j]
                # Intent gate on the referential channel: discount object overlap
                # by the geometric mean of the two endpoints' intent_strength.
                r_gate = float(np.sqrt(intents[i] * intents[j])) if intent_gate else 1.0
                t_ov = t_ov_raw * r_gate

                # Record all-pairs components (for reviewer/human-rating)
                if not count_only:
                    all_components.append({
                        "source": i, "target": j,
                        "semantic_sim": float(s_sim),
                        "tag_overlap": float(t_ov),
                        "tag_overlap_raw": float(t_ov_raw),
                        "intent_gate": r_gate,
                        "spatial_prox": float(p_prox)
                    })

                # Type set
                types = []
                if p_prox >= tau_spatial: types.append("spatial")
                if t_ov   >= tau_referential: types.append("referential")
                if s_sim  >= tau_thematic: types.append("thematic")

                degree = len(types)
                if degree == 0:
                    continue

                edge_count += 1
                if count_only:
                    continue

                rationale = "Calculating..."
                if generate_rationales:
                    print(f"   Explaining link {i} <-> {j} ({degree} channel{'s' if degree > 1 else ''})...")
                    rationale = self._get_ai_rationale(descriptions[i], descriptions[j])

                # Deprecated fallback weight for viewer compatibility
                weight = (alpha * s_sim) + (beta * t_ov) + (gamma * p_prox)

                links.append({
                    "source": i,
                    "target": j,
                    "weight": float(weight),          # deprecated; use types/degree
                    "types": types,
                    "convergence_degree": degree,
                    "semantic_sim": float(s_sim),
                    "tag_overlap": float(t_ov),
                    "tag_overlap_raw": float(t_ov_raw),
                    "intent_gate": r_gate,
                    "spatial_prox": float(p_prox),
                    "rationale": rationale,
                    "type": "convergence"             # kept for backward compat
                })

        if count_only:
            return edge_count

        print(f"Generated {len(links)} semantic-spatial edges.")
        # Count edges by convergence degree
        deg_counts = {d: 0 for d in range(1, 4)}
        for l in links:
            deg_counts[l["convergence_degree"]] = deg_counts.get(l["convergence_degree"], 0) + 1

        return {
            "metadata": {
                "alpha": float(alpha),
                "beta": float(beta),
                "gamma": float(gamma),
                "lam": float(lam),
                "threshold": threshold,
                "tau_spatial": tau_spatial,
                "tau_referential": tau_referential,
                "tau_thematic": tau_thematic,
                "edge_method": "typed_edges_with_convergence_degree",
                "model": "BAAI/bge-m3",
                "weights": {
                    "semantic": alpha,
                    "tag_overlap": beta,
                    "spatial_weight": gamma,
                    "spatial_decay": float(lam)
                },
                "total_pairs_evaluated": num_nodes * (num_nodes - 1) // 2,
                "edges_by_degree": deg_counts
            },
            "nodes": nodes,
            "links": links,
            "components": all_components  # (3) all-pairs; for reviewer/rating
        }

    def save_graph(self, graph_data, output_path):
        with open(output_path, "w") as f:
            json.dump(graph_data, f, indent=4)
        print(f"Graph saved to: {output_path}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchors", required=True, help="Path to narrative_anchors.json")
    parser.add_argument("--output", help="Path to save semantic_graph.json")
    parser.add_argument("--alpha", type=float, default=0.5)
    parser.add_argument("--beta", type=float, default=0.5)
    parser.add_argument("--gamma", type=float, default=0.5, help="Spatial proximity weight.")
    parser.add_argument("--lam", type=float, default=0.05, help="Spatial proximity decay rate (1/m). Independent of --gamma.")
    parser.add_argument("--threshold", type=float, default=0.6,
                        help="DEPRECATED fallback; use --tau-* for per-channel thresholds.")
    parser.add_argument("--tau-spatial", type=float, default=0.4,
                        help="Spatial proximity threshold. P >= tau_spatial fires spatial type. Default: 0.4.")
    parser.add_argument("--tau-referential", type=float, default=0.25,
                        help="Tag overlap (Jaccard) threshold. Default: 0.25.")
    parser.add_argument("--tau-thematic", type=float, default=0.7,
                        help="Semantic similarity (cosine) threshold. Default: 0.7.")
    parser.add_argument("--no-intent-gate", action="store_true",
                        help="Disable gating the referential channel by anchor intent_strength "
                             "(default: gate on when anchors carry intent_strength).")
    parser.add_argument("--no-rationale", action="store_true", help="Skip AI rationale generation to save time/cost.")
    parser.add_argument("--count-only", action="store_true",
                        help="Count edges only -- no saving, no VLM calls, no logging.")
    # components CSV is always emitted alongside the graph
    parser.add_argument("--model", default="BAAI/bge-m3", help="SentenceTransformer model for embeddings. Default: BAAI/bge-m3")

    args = parser.parse_args()

    if not os.path.exists(args.anchors):
        print(f"Error: File not found {args.anchors}")
        exit(1)

    with open(args.anchors, "r") as f:
        anchors_data = json.load(f)

    builder = SemanticNetworkBuilder(model_name=args.model)
    graph = builder.build_graph(
        anchors_data,
        alpha=args.alpha,
        beta=args.beta,
        gamma=args.gamma,
        lam=args.lam,
        threshold=args.threshold,
        tau_spatial=args.tau_spatial,
        tau_referential=args.tau_referential,
        tau_thematic=args.tau_thematic,
        generate_rationales=not args.no_rationale,
        count_only=args.count_only,
        intent_gate=not args.no_intent_gate
    )

    if args.count_only:
        print(f"EDGE_COUNT:{graph}")
    else:
        builder.save_graph(graph, args.output)

        # (3) Save all-pairs components CSV for reviewer/human-rating
        comp_path = args.output.replace(".json", "_components.csv")
        with open(comp_path, "w") as f:
            f.write("source,target,semantic_sim,tag_overlap,spatial_prox\n")
            for c in graph.get("components", []):
                f.write(f"{c['source']},{c['target']},{c['semantic_sim']:.6f},{c['tag_overlap']:.6f},{c['spatial_prox']:.6f}\n")
        print(f"  All-pairs components saved to: {comp_path}")

        # Log graph builder parameters
        output_dir = os.path.dirname(os.path.abspath(args.output))
        params_path = os.path.join(output_dir, "pipeline_params.json")

        # Read existing params if present (from orchestrator), otherwise create new
        existing = {}
        if os.path.exists(params_path):
            with open(params_path, "r") as f:
                existing = json.load(f)

        params = {
            "generated_at": existing.get("generated_at", datetime.datetime.now().isoformat()),
            "pipeline": "InTheEyesOf Semantic Pipeline",
            "stage": existing.get("stage", {})
        }
        params["stage"]["graph_builder"] = {
            "alpha": args.alpha,
            "beta": args.beta,
            "gamma": args.gamma,
            "lam": args.lam,
            "threshold": args.threshold,
            "tau_spatial": args.tau_spatial,
            "tau_referential": args.tau_referential,
            "tau_thematic": args.tau_thematic,
            "edge_method": "typed_edges_with_convergence_degree",
            "model": args.model,
            "edge_count": len(graph.get("links", [])),
            "node_count": len(graph.get("nodes", []))
        }

        with open(params_path, "w") as f:
            json.dump(params, f, indent=2)
        print(f"Graph params logged to: {params_path}")
