"""
SEMANTIC ANALYSIS PIPELINE (MODULAR VERSION)
-------------------------------------------
This version is designed to be imported as a module or called by other programs.
It focuses on the core logic of associating spatial hotspots with verbal transcripts.

Example Usage (Python):
    from semantic_analysis_pipeline import SemanticHotspotPipeline
    
    pipeline = SemanticHotspotPipeline(vrs_path="data.vrs") # Auto-discovers others
    results = pipeline.run_full_analysis()
    print(results[0]['ai_summary'])
"""

import os
import re
import requests
import json
import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN
from scipy.spatial.transform import Rotation as R
from projectaria_tools.core import data_provider
from projectaria_tools.core.sensor_data import TimeDomain, TimeQueryOptions
from PIL import Image, ImageDraw
import moviepy.editor as mpy

class SemanticHotspotPipeline:
    def __init__(self, vrs_path, mps_root=None, transcript_path=None, output_dir=None):
        self.vrs_path = vrs_path
        self.vrs_dir = os.path.dirname(vrs_path)
        self.base_name = os.path.basename(vrs_path).replace(".vrs", "")
        
        # Auto-discovery logic
        self.mps_root = mps_root or self._find_mps_root()
        self.transcript_path = transcript_path or self._find_transcript()
        self.output_dir = output_dir or os.path.join(self.vrs_dir, f"{self.base_name}_semantic_results")
        
        # Load Secrets
        secrets_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "secrets.json")
        if os.path.exists(secrets_path):
            with open(secrets_path, "r") as f:
                secrets = json.load(f)
                self.service_url = secrets.get("SERVICE_URL")
                self.auth_token = secrets.get("RESEARCH_PASSWORD")
        else:
            self.service_url = None
            self.auth_token = None
            print(f"⚠️ Warning: secrets.json not found at {secrets_path}")
        
        os.makedirs(self.output_dir, exist_ok=True)
        self.provider = data_provider.create_vrs_data_provider(self.vrs_path)
        self.rgb_stream = self.provider.get_stream_id_from_label("camera-rgb")
        self.vrs_start_ns = self.provider.get_first_time_ns(self.rgb_stream, TimeDomain.DEVICE_TIME)

    def _find_mps_root(self):
        candidate = os.path.join(self.vrs_dir, f"mps_{self.base_name}_vrs")
        if os.path.exists(candidate): return candidate
        return None

    def _find_transcript(self):
        candidate = os.path.join(self.vrs_dir, f"{self.base_name}_transcript.txt")
        if os.path.exists(candidate): return candidate
        return None

    # --- Core Logic ---

    def load_and_cluster(self, eps=0.25, min_samples=30):
        """Loads gaze/traj and identifies hotspots."""
        gaze_csv = os.path.join(self.mps_root, "eye_gaze", "general_eye_gaze.csv")
        traj_csv = os.path.join(self.mps_root, "closed_loop_trajectory.csv")
        if not os.path.exists(traj_csv):
            traj_csv = os.path.join(self.mps_root, "slam", "closed_loop_trajectory.csv")

        gaze_df = pd.read_csv(gaze_csv, comment='#')
        traj_df = pd.read_csv(traj_csv, comment='#')
        merged = pd.merge_asof(
            gaze_df.sort_values('tracking_timestamp_us'), 
            traj_df.sort_values('tracking_timestamp_us'), 
            on='tracking_timestamp_us', direction='nearest', tolerance=100000
        ).dropna()

        # Simple 3D projection
        depth = 2.0
        yaw = merged.get('yaw_rads_cpf', (merged.get('left_yaw_rads_cpf', 0) + merged.get('right_yaw_rads_cpf', 0)) / 2)
        pitch = merged.get('pitch_rads_cpf', 0)
        
        r = R.from_quat(merged[['qx_device_world', 'qy_device_world', 'qz_device_world', 'qw_device_world']].to_numpy() if 'qx_device_world' in merged.columns else merged[['qx_world_device', 'qy_world_device', 'qz_world_device', 'qw_world_device']].to_numpy())
        pos = merged[['tx_device_world', 'ty_device_world', 'tz_device_world']].to_numpy() if 'tx_device_world' in merged.columns else merged[['tx_world_device', 'ty_world_device', 'tz_world_device']].to_numpy()
        
        local_vecs = np.vstack((depth * np.tan(yaw), depth * np.tan(pitch), np.full(len(merged), depth))).T
        targets = pos + r.apply(local_vecs)
        merged['gx'], merged['gy'], merged['gz'] = targets[:, 0], targets[:, 1], targets[:, 2]
        merged['yaw'], merged['pitch'] = yaw, pitch

        clustering = DBSCAN(eps=eps, min_samples=min_samples).fit(merged[['gx', 'gy', 'gz']].to_numpy())
        merged['cluster_id'] = clustering.labels_
        
        return self._extract_events(merged)

    def _extract_events(self, df):
        events = []
        curr = None
        for _, row in df.iterrows():
            cid, ts = row['cluster_id'], row['tracking_timestamp_us']
            if cid == -1:
                if curr and (ts - curr['end_ts'] > 1500000):
                    events.append(curr); curr = None
                continue
            if curr and curr['cluster_id'] == cid:
                curr['end_ts'] = ts; curr['samples'].append(row)
            else:
                if curr: events.append(curr)
                curr = {'cluster_id': cid, 'start_ts': ts, 'end_ts': ts, 'samples': [row]}
        if curr: events.append(curr)
        return [e for e in events if (e['end_ts'] - e['start_ts']) > 800000]

    def parse_transcript(self):
        if not self.transcript_path: return []
        data = []
        pattern = re.compile(r"\[(\d+)s - (\d+)s\]: (.*)")
        with open(self.transcript_path, 'r') as f:
            for line in f:
                m = pattern.match(line)
                if m: data.append({'start': int(m.group(1)), 'end': int(m.group(2)), 'text': m.group(3)})
        return data

    def get_ai_summary(self, transcript, start_sec, end_sec):
        context = 10
        relevant = [t['text'] for t in transcript if not (t['end'] < (start_sec-context) or t['start'] > (end_sec+context))]
        text = " ".join(relevant)
        if not text: return "No verbal context."

        prompt = f"Summarize the user's architectural intent at {start_sec:.1f}s based on this transcript: \"{text}\". Keep it to 2 sentences."
        try:
            res = requests.post(self.service_url, headers={"Authorization": self.auth_token}, json={"prompt": prompt}, timeout=10)
            return res.json().get("response", "AI error") if res.status_code == 200 else "AI unavailable"
        except: return "Connection failed"

    def run_full_analysis(self, extract_video=True):
        """Main entry point for other programs."""
        print(f"🚀 Starting Semantic Analysis for {self.base_name}...")
        events = self.load_and_cluster()
        transcript = self.parse_transcript()
        
        results = []
        for i, event in enumerate(events):
            rel_start = (event['start_ts'] * 1000 - self.vrs_start_ns) / 1e9
            rel_end = (event['end_ts'] * 1000 - self.vrs_start_ns) / 1e9
            
            summary = self.get_ai_summary(transcript, rel_start, rel_end)
            
            event_data = {
                'id': i,
                'cluster_id': int(event['cluster_id']),
                'start_sec': round(rel_start, 2),
                'duration': round(rel_end - rel_start, 2),
                'ai_summary': summary
            }
            
            if extract_video:
                self._save_clip(event, i)
                event_data['clip_path'] = f"cluster_{event['cluster_id']:02d}/event_{i:03d}.mp4"
            
            results.append(event_data)
        
        # Save structured JSON for other programs
        with open(os.path.join(self.output_dir, "analysis_results.json"), "w") as f:
            json.dump(results, f, indent=4)
            
        print(f"✅ Analysis complete. Results saved to {self.output_dir}")
        return results

    def _save_clip(self, event, idx):
        c_dir = os.path.join(self.output_dir, f"cluster_{event['cluster_id']:02d}")
        os.makedirs(c_dir, exist_ok=True)
        frames = []
        for row in event['samples'][::max(1, len(event['samples']) // 12)]:
            v_idx = self.provider.get_index_by_time_ns(self.rgb_stream, int(row['tracking_timestamp_us']*1000), TimeDomain.DEVICE_TIME, TimeQueryOptions.CLOSEST)
            f_data = self.provider.get_image_data_by_index(self.rgb_stream, v_idx)
            if f_data:
                img = Image.fromarray(f_data[0].to_numpy_array())
                # Add simple marker
                draw = ImageDraw.Draw(img); w, h = img.size
                px = (w/2) + np.tan(row['yaw']) * (w/1.5); py = (h/2) + np.tan(row['pitch']) * (h/1.5)
                draw.ellipse([px-10, py-10, px+10, py+10], outline="red", width=3)
                frames.append(np.array(img))
        
        if frames:
            clip = mpy.ImageSequenceClip(frames, fps=8)
            clip.write_videofile(os.path.join(c_dir, f"event_{idx:03d}.mp4"), codec="libx264", audio=False, logger=None)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--vrs", required=True)
    args = parser.parse_args()
    
    pipeline = SemanticHotspotPipeline(vrs_path=args.vrs)
    pipeline.run_full_analysis()
