"""
ULTIMATE 3D NARRATIVE VIEWER
----------------------------
Visualizes the PLY point cloud and overlays LARGE RED SPHERES for anchors.
"""

import json
import argparse
import open3d as o3d
import numpy as np
import os

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ply", required=True)
    parser.add_argument("--anchors", required=True)
    args = parser.parse_args()

    print("☁️ Loading Point Cloud...")
    pcd = o3d.io.read_point_cloud(args.ply)
    
    # Check Point Cloud Bounds
    pcd_center = pcd.get_center()
    print(f"   PC Center: {pcd_center}")

    print("📍 Loading Narrative Anchors...")
    with open(args.anchors, 'r') as f:
        data = json.load(f)
        anchors = [a for a in data if 'gx' in a]

    geometries = [pcd]
    
    print(f"🧠 Processing {len(anchors)} anchors...")
    for i, a in enumerate(anchors):
        pos = np.array([a['gx'], a['gy'], a['gz']])
        
        # Create a LARGE sphere (0.3m radius) to ensure visibility
        sphere = o3d.geometry.TriangleMesh.create_sphere(radius=0.3)
        sphere.paint_uniform_color([1, 0, 0]) # Bright Red
        sphere.translate(pos)
        geometries.append(sphere)
        
        # Print distance to PC center to check for coordinate mismatches
        dist = np.linalg.norm(pos - pcd_center)
        print(f"   [{i}] {a.get('narrative_title', 'Anchor')[:30]}... (Dist from center: {dist:.2f}m)")

    print("\n🖱️  Launching Viewer...")
    print("Controls:")
    print(" - Left Click + Drag: Rotate")
    print(" - Ctrl + Left Click + Drag: Translate")
    print(" - Mouse Wheel: Zoom")
    
    o3d.visualization.draw_geometries(geometries, 
                                      window_name="Aria Ultimate Viewer",
                                      width=1280, height=720,
                                      mesh_show_back_face=True)

if __name__ == "__main__":
    main()
