"""
HAND INTERACTION EXTRACTOR
--------------------------
1. Parses Aria MPS hand tracking data.
2. Aligns wrist and palm positions with the world-space trajectory.
3. Identifies "Interaction Events" based on proximity to gaze targets or specific gestures.
"""

import os
import pandas as pd
import numpy as np
from scipy.spatial.transform import Rotation as R

class HandInteractionExtractor:
    def __init__(self, mps_root):
        self.mps_root = mps_root
        self.hand_csv = os.path.join(mps_root, "hand_tracking", "hand_tracking_results.csv")
        self.traj_csv = os.path.join(mps_root, "closed_loop_trajectory.csv")
        if not os.path.exists(self.traj_csv):
            self.traj_csv = os.path.join(mps_root, "slam", "closed_loop_trajectory.csv")

    def load_data(self):
        if not os.path.exists(self.hand_csv):
            print(f"⚠️ Hand tracking data not found at {self.hand_csv}")
            return None
        
        hand_df = pd.read_csv(self.hand_csv, comment='#')
        traj_df = pd.read_csv(self.traj_csv, comment='#')
        
        # Merge hand tracking with trajectory to ensure world-space alignment
        # Note: Aria MPS hand tracking is often already in world space if 'world' is in column name
        merged = pd.merge_asof(
            hand_df.sort_values('tracking_timestamp_us'),
            traj_df.sort_values('tracking_timestamp_us'),
            on='tracking_timestamp_us',
            direction='nearest',
            tolerance=100000
        ).dropna()
        
        return merged

    def detect_interactions(self, merged_df, gaze_df=None):
        """
        Detects significant hand interactions.
        For now, we look for 'Hand Raised' and 'Hand Dwell' events.
        """
        interactions = []
        # Simple heuristic: Hand is 'active' if it's within a certain range of the device
        # or if it's dwelling in a specific world-space location.
        
        # Example logic for 'Hand Presence'
        active_left = merged_df[merged_df['left_tracking_confidence'] > 0.8]
        active_right = merged_df[merged_df['right_tracking_confidence'] > 0.8]
        
        # Further logic would involve checking if the hand is near the gaze target
        # (requiring alignment with gaze_df)
        
        return {
            "left_active_count": len(active_left),
            "right_active_count": len(active_right),
            "total_samples": len(merged_df)
        }

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mps_root", required=True)
    args = parser.parse_args()
    
    extractor = HandInteractionExtractor(args.mps_root)
    data = extractor.load_data()
    if data is not None:
        report = extractor.detect_interactions(data)
        print(f"✅ Hand Tracking Analysis: {report}")
